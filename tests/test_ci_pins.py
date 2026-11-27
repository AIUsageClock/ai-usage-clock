"""The CI workflows must only use pinned, exact versions.

Supply-chain rule: nothing a workflow downloads or selects may change because
an upstream published a new release (which could be a compromised one).
Floating references that this test rejects:

* a ``uses:`` that is not a 40-character commit SHA,
* a ``-latest`` runner label,
* a ``python-version``, ``node-version`` or setup-uv ``version`` that is not an
  exact ``X.Y.Z`` (also ``python-version-file``, which hides the version),
* an installation that bypasses ``uv.lock`` (pip, npm install, brew, uvx, ...),
* a ``uv sync`` / ``uv run`` without ``--frozen``.

The workflows are read as text, line by line, so that the test needs no YAML
library. How to upgrade the pinned versions: docs/build.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

_USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)")
_SHA_REF = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
_EXACT = re.compile(r"^\d+\.\d+\.\d+$")
_VERSION_KEY = re.compile(
    r"^\s*(?P<key>python-version|node-version|version):\s*(?P<value>.+?)\s*$"
)
_FLOATING_INSTALL = re.compile(
    r"\b(pip3?\s+install|-m\s+pip\b|uv\s+pip\b|uv\s+tool\b|uvx\b|npm\s+(install|i)\b"
    r"|npx\b|yarn\s+(add|install)\b|pnpm\s+(add|install)\b|brew\s+(install|upgrade)\b"
    r"|choco\s+install\b|winget\s+install\b|curl\b|wget\b|Invoke-WebRequest\b"
    r"|docker\s+(pull|run)\b)"
)
_UV_COMMAND = re.compile(r"\buv\s+(sync|run)\b")


def _code_lines(text: str) -> list[tuple[int, str]]:
    """(line number, line) without full-line comments and trailing comments."""
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = re.sub(r"\s+#.*$", "", line)
        if stripped.strip() and not stripped.lstrip().startswith("#"):
            out.append((number, stripped))
    return out


def _unquote(value: str) -> str:
    return value.strip().strip("\"'")


def _matrix_items(value: str) -> list[str]:
    """``["3.14.10", "3.11.18"]`` -> the items; a plain scalar -> itself."""
    value = value.strip()
    if value.startswith("["):
        return [_unquote(item) for item in value.strip("[]").split(",") if item.strip()]
    return [_unquote(value)]


def find_violations(text: str) -> list[str]:
    problems: list[str] = []
    lines = _code_lines(text)
    for index, (number, line) in enumerate(lines):
        match = _USES.match(line)
        if match:
            ref = match.group("ref")
            if not ref.startswith("./") and not _SHA_REF.match(ref):
                problems.append(f"line {number}: uses {ref!r} is not a 40-hex commit SHA")
            if ref.startswith("astral-sh/setup-uv@"):
                # The step's with: block follows; version: must be an exact one.
                found = None
                for _, nxt in lines[index + 1 : index + 6]:
                    if _USES.match(nxt) or re.match(r"^\s*-\s", nxt):
                        break
                    key = _VERSION_KEY.match(nxt)
                    if key and key.group("key") == "version":
                        found = _unquote(key.group("value"))
                if found is None or not _EXACT.match(found):
                    problems.append(f"line {number}: setup-uv needs an exact version: X.Y.Z")
        if "-latest" in line:
            problems.append(f"line {number}: floating runner label (-latest): {line.strip()}")
        if re.match(r"^\s*python-version-file:", line):
            problems.append(f"line {number}: python-version-file hides the exact version")
        key = _VERSION_KEY.match(line)
        if key and key.group("key") in ("python-version", "node-version"):
            for item in _matrix_items(key.group("value")):
                if item.startswith("${{"):
                    continue  # taken from a matrix that is checked on its own line
                if not _EXACT.match(item):
                    problems.append(
                        f"line {number}: {key.group('key')} {item!r} is not an exact X.Y.Z"
                    )
        if _FLOATING_INSTALL.search(line):
            problems.append(f"line {number}: install outside uv.lock: {line.strip()}")
        if _UV_COMMAND.search(line) and "--frozen" not in line:
            problems.append(f"line {number}: uv sync/run without --frozen: {line.strip()}")
    return problems


def test_workflows_found():
    names = {path.name for path in WORKFLOWS}
    assert {"test.yml", "release.yml"} <= names


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_pinned(path: Path):
    problems = find_violations(path.read_text(encoding="utf-8"))
    assert not problems, f"{path.name}:\n" + "\n".join(problems)


@pytest.mark.parametrize(
    "bad",
    [
        "      - uses: actions/checkout@v4",
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677",
        "    runs-on: ubuntu-latest",
        "        os: [windows-latest, ubuntu-22.04]",
        '          python-version: "3.14"',
        "        python-version: [3.14.10, 3.11]",
        '        include:\n          - os: macos-26\n            python-version: "3.11"',
        "          node-version: 24",
        "          python-version-file: .python-version",
        "        run: pip install pyyaml",
        "        run: python -m pip install -U pip",
        "        run: npm install",
        "        run: curl -sSL https://example.invalid/x.sh | sh",
        "        run: uv sync --extra dev",
        "        run: uv run pytest",
        "      - uses: astral-sh/setup-uv@" + "0" * 40,
        "      - uses: astral-sh/setup-uv@" + "0" * 40 + '\n        with:\n          version: "0.13"',
    ],
)
def test_detector_rejects_floating_reference(bad: str):
    assert find_violations(bad)


@pytest.mark.parametrize(
    "good",
    [
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0",
        "    runs-on: ubuntu-22.04",
        '          python-version: "3.14.10"',
        "          python-version: ${{ matrix.python-version }}",
        '        python-version: ["3.14.10", "3.11.18"]',
        '        include:\n          - os: macos-26\n            python-series: "3.11"\n            python-version: "3.11.9"',
        "          node-version: 24.22.2",
        "        run: uv sync --frozen --extra dev",
        "      - uses: astral-sh/setup-uv@" + "0" * 40 + '\n        with:\n          version: "0.13.9"',
        "      # pip install is only mentioned in a comment",
    ],
)
def test_detector_accepts_pinned_reference(good: str):
    assert find_violations(good) == []


def test_release_runs_the_packaged_webengine_worker_selftest_on_every_platform():
    """The GUI smoke test turns every provider off, so it never starts the worker.

    Without these steps a trimmed packaged build that lost a WebEngine module
    would ship without any CI step noticing.
    """
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    code = "\n".join(line for _, line in _code_lines(text))

    assert "--webengine-worker" in code and "--selftest" in code
    # Windows: a windowed exe has no console, so wait for it and read its exit code.
    assert re.search(r"Start-Process[^\n]*ai-usage-clock\.exe|Start-Process -FilePath \$exe", code)
    assert "-Wait -PassThru" in code
    assert "ExitCode" in code
    # macOS: the executable inside the .app bundle.
    assert "dist/ai-usage-clock.app/Contents/MacOS/ai-usage-clock --webengine-worker --selftest" in code
    # Linux: no display on the runner, so a virtual one.
    assert "xvfb-run -a dist/ai-usage-clock/ai-usage-clock --webengine-worker --selftest" in code