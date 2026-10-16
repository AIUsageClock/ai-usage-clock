"""The release build must ship LICENSE and THIRD_PARTY_NOTICES.txt.

The MIT License wants its text to travel with every copy, and the bundled
PyQt6, Qt and the other dependencies carry terms of their own. The build
scripts and the release workflow are shell code that unit tests cannot run, so
this reads their text and checks that each step is still there: the generator
call, the file names it writes, the folder they land in, and the check that
compares the notices with what PyInstaller really packed. Whitespace, line
continuations and the wording of error messages are not pinned. Every check
has a deliberately broken counterpart further down.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from aiusageclock import identity

REPO_ROOT = Path(__file__).resolve().parents[1]
LICENSE_FILES = "LICENSE THIRD_PARTY_NOTICES.txt"

# Between two tokens of a command: any whitespace, plus the line continuation
# character of PowerShell (backtick) or of a POSIX shell (backslash).
_GAP = r"[\s`\\]*"

Expectation = tuple[str, re.Pattern[str]]


def _lit(label: str, text: str) -> Expectation:
    return label, re.compile(re.escape(text))


def _seq(label: str, *tokens: str) -> Expectation:
    """The tokens in this order, separated by anything that is not code."""
    return label, re.compile(_GAP.join(re.escape(token) for token in tokens))


def expectations() -> dict[str, list[Expectation]]:
    slug = identity.SLUG
    mcp = identity.MCP_COMMAND
    return {
        "build.ps1": [
            _seq(
                "notice folder of a one-file build",
                "$noticeDir = if ($OneFile) {",
                'Join-Path $PSScriptRoot "dist"',
                "}",
            ),
            _seq(
                "notice folder of a folder build",
                "} else {",
                f'Join-Path $PSScriptRoot "dist\\{slug}"',
                "}",
            ),
            _seq(
                "LICENSE copy",
                'Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LICENSE")',
                '-Destination (Join-Path $noticeDir "LICENSE")',
            ),
            _seq(
                "notices generator call",
                'write_third_party_notices.py")',
                '(Join-Path $noticeDir "THIRD_PARTY_NOTICES.txt")',
            ),
            _seq(
                "output file names",
                'foreach ($noticeFile in @("LICENSE",',
                '"THIRD_PARTY_NOTICES.txt"))',
            ),
            _seq(
                "coverage check call",
                'check_bundled_notices.py")',
                '(Join-Path $noticeDir "THIRD_PARTY_NOTICES.txt")',
                f'(Join-Path $PSScriptRoot "build\\{slug}\\Analysis-00.toc")',
                f'(Join-Path $PSScriptRoot "build\\{mcp}\\Analysis-00.toc")',
            ),
        ],
        "build.sh": [
            _seq("notice folder of a one-file or macOS build", 'NOTICE_DIR="dist"'),
            _seq("notice folder of a folder build", f'NOTICE_DIR="dist/{slug}"'),
            _seq("LICENSE copy", 'cp "$SCRIPT_DIR/LICENSE" "$NOTICE_DIR/LICENSE"'),
            _seq(
                "notices generator call",
                'tools/write_third_party_notices.py"',
                '"$NOTICE_DIR/THIRD_PARTY_NOTICES.txt"',
            ),
            _seq(
                # On Linux the generator finds the system libraries PyInstaller
                # copied into the build from these two analyses. build.ps1 does
                # not pass them: the generator ignores them on Windows.
                "notices generator reads the analyses",
                'tools/write_third_party_notices.py"',
                '"$NOTICE_DIR/THIRD_PARTY_NOTICES.txt"',
                f'"$SCRIPT_DIR/build/{slug}/Analysis-00.toc"',
                f'"$SCRIPT_DIR/build/{mcp}/Analysis-00.toc"',
            ),
            _seq("output file names", "for NOTICE_FILE in LICENSE THIRD_PARTY_NOTICES.txt; do"),
            _seq(
                "coverage check call",
                'tools/check_bundled_notices.py"',
                '"$NOTICE_DIR/THIRD_PARTY_NOTICES.txt"',
                f'"$SCRIPT_DIR/build/{slug}/Analysis-00.toc"',
                f'"$SCRIPT_DIR/build/{mcp}/Analysis-00.toc"',
            ),
        ],
        ".github/workflows/release.yml": [
            _lit(
                "macOS archive lists the license files",
                f'tar -C dist -czf "$archive" {slug}.app {mcp} {LICENSE_FILES}',
            ),
            _lit("Linux archive is the whole folder", f'tar -C dist -czf "$archive" {slug}\n'),
            _lit("Windows archive is the whole folder", f"Compress-Archive -Path dist\\{slug} "),
            _lit("Windows archive check: LICENSE", f'"{slug}/LICENSE"'),
            _lit("Windows archive check: notices", f'"{slug}/THIRD_PARTY_NOTICES.txt"'),
            _lit("Unix archive listing", 'listing="$(tar -tzf "$archive")"'),
            _lit("Unix archive check", "for required in LICENSE THIRD_PARTY_NOTICES.txt; do"),
            _lit("Linux archive path prefix", f'prefix="{slug}/"'),
        ],
    }


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def missing(relative_path: str, text: str | None = None) -> list[str]:
    if text is None:
        text = _read(relative_path)
    return [label for label, pattern in expectations()[relative_path] if not pattern.search(text)]


@pytest.mark.parametrize("relative_path", sorted(expectations()))
def test_build_files_ship_the_license_files(relative_path):
    assert missing(relative_path) == []


def test_the_inputs_of_those_steps_exist():
    assert _read("LICENSE").startswith("MIT License")
    assert (REPO_ROOT / "tools" / "write_third_party_notices.py").is_file()
    assert (REPO_ROOT / "tools" / "check_bundled_notices.py").is_file()


def test_the_wheel_and_sdist_metadata_ship_both_license_files():
    # The wheel and the sdist carry the files that pyproject.toml lists under
    # license-files, so the archived upstream notice travels with every copy.
    project = tomllib.loads(_read("pyproject.toml"))["project"]

    assert project["license"] == "MIT"
    patterns = project["license-files"]
    assert {"LICENSE", "docs/legal/UPSTREAM-LICENSE.txt"} <= set(patterns)
    for pattern in patterns:
        assert sorted(REPO_ROOT.glob(pattern)), f"no file matches license-files entry {pattern!r}"


def test_notices_are_written_after_pruning_and_checked_before_the_build_is_declared_done():
    for relative_path, prune, done in (
        ("build.ps1", "prune_bundle.py", 'Write-Host "Build complete."'),
        ("build.sh", "prune_bundle.py", 'echo "Build complete."'),
    ):
        text = _read(relative_path)
        # The check is named in an earlier comment too; the call is the last mention.
        assert (
            text.index(prune)
            < text.index("write_third_party_notices.py")
            < text.rindex("check_bundled_notices.py")
            < text.index(done)
        )


# --- what PyInstaller is told to leave out ---------------------------------------
#
# Optional imports reach development and build-time packages: anyio tries
# _pytest, uvicorn and pydantic-settings try yaml, cffi tries setuptools. The
# executables are not meant to carry them (nor their notices), so each build
# command excludes them; the coverage check above is the net underneath.

LEFT_OUT_OF_BOTH = ("setuptools", "pkg_resources", "_distutils_hack")
LEFT_OUT_OF_THE_HELPER = ("_pytest", "pytest", "yaml")


def command_texts(relative_path: str, text: str | None = None) -> dict[str, str]:
    """The PyInstaller argument list of the GUI build and of the MCP helper build."""
    if text is None:
        text = _read(relative_path)
    if relative_path == "build.ps1":
        patterns = {
            "GUI": r"\$args\s*=\s*@\((.*?)\n\)",
            "helper": r"\$mcpArgs\s*=\s*@\((.*?)\n\)",
        }
    else:
        patterns = {
            "GUI": r"PYINSTALLER_ARGS=\((.*?)\n\)",
            "helper": r"--name\s+" + re.escape(identity.MCP_COMMAND) + r"(.*?)pyinstaller_mcp_entry\.py",
        }
    found = {}
    for label, pattern in patterns.items():
        match = re.search(pattern, text, re.DOTALL)
        assert match, f"no {label} PyInstaller command found in {relative_path}"
        found[label] = match.group(1)
    return found


def excludes(relative_path: str, command: str) -> set[str]:
    if relative_path == "build.ps1":
        pattern = r'"--exclude-module"\s*,\s*"([^"]+)"'
    else:
        pattern = r"--exclude-module\s+(\S+)"
    return set(re.findall(pattern, command))


@pytest.mark.parametrize("relative_path", ["build.ps1", "build.sh"])
def test_the_build_commands_leave_out_the_packages_the_notices_do_not_list(relative_path):
    commands = command_texts(relative_path)

    assert set(LEFT_OUT_OF_BOTH) <= excludes(relative_path, commands["GUI"])
    assert set(LEFT_OUT_OF_BOTH + LEFT_OUT_OF_THE_HELPER) <= excludes(
        relative_path, commands["helper"]
    )


# --- deliberately broken copies must be reported ---------------------------


def test_a_build_ps1_that_forgets_the_license_copy_is_reported():
    text = _read("build.ps1")
    broken = text.replace(
        'Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LICENSE")',
        'Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.md")',
    )
    assert broken != text

    assert missing("build.ps1", broken) == ["LICENSE copy"]


def test_a_build_ps1_that_reflows_the_commands_is_still_accepted():
    text = _read("build.ps1")
    reflowed = re.sub(r"[ \t]*`\r?\n[ \t]*", " ", text)
    reflowed = reflowed.replace('"LICENSE", "THIRD_PARTY_NOTICES.txt"', '"LICENSE",   "THIRD_PARTY_NOTICES.txt"')
    assert reflowed != text

    assert missing("build.ps1", reflowed) == []


def test_a_build_sh_that_skips_the_generator_is_reported():
    text = _read("build.sh")
    broken = text.replace("write_third_party_notices.py", "something_else.py")
    assert broken != text

    assert missing("build.sh", broken) == [
        "notices generator call",
        "notices generator reads the analyses",
    ]


_GENERATOR_CALL = r'(write_third_party_notices\.py" "\$NOTICE_DIR/THIRD_PARTY_NOTICES\.txt")'
_ANALYSIS_ARGUMENT = r' \\\n[ \t]+"\$SCRIPT_DIR/build/%s/Analysis-00\.toc"'


@pytest.mark.parametrize(
    ("pattern", "replacement"),
    [
        # no analysis at all
        (
            _GENERATOR_CALL + 2 * (_ANALYSIS_ARGUMENT % r'[^/"\n]+'),
            r"\1",
        ),
        # only the GUI's: the helper's is dropped
        (
            _GENERATOR_CALL
            + r"(" + _ANALYSIS_ARGUMENT % re.escape(identity.SLUG) + r")"
            + _ANALYSIS_ARGUMENT % re.escape(identity.MCP_COMMAND),
            r"\1\2",
        ),
    ],
    ids=["no analysis", "the helper's analysis"],
)
def test_a_build_sh_whose_generator_is_not_given_the_analyses_is_reported(pattern, replacement):
    text = _read("build.sh")
    broken = re.sub(pattern, replacement, text, count=1)
    assert broken != text

    assert missing("build.sh", broken) == ["notices generator reads the analyses"]


def test_a_build_sh_that_puts_the_files_in_the_wrong_folder_is_reported():
    text = _read("build.sh")
    broken = text.replace(f'NOTICE_DIR="dist/{identity.SLUG}"', 'NOTICE_DIR="build"')
    assert broken != text

    assert missing("build.sh", broken) == ["notice folder of a folder build"]


@pytest.mark.parametrize("relative_path", ["build.ps1", "build.sh"])
def test_a_build_script_that_skips_the_coverage_check_is_reported(relative_path):
    text = _read(relative_path)
    broken = text.replace("check_bundled_notices.py", "something_else.py")
    assert broken != text

    assert "coverage check call" in missing(relative_path, broken)


def test_a_build_sh_that_drops_a_toc_from_the_coverage_check_is_reported():
    text = _read("build.sh")
    # The generator call names the same file earlier; the check call is the last.
    target = f"build/{identity.MCP_COMMAND}/Analysis-00.toc"
    before, found, after = text.rpartition(target)
    assert found
    broken = before + "build/other/Analysis-00.toc" + after

    assert missing("build.sh", broken) == ["coverage check call"]


def test_a_helper_command_that_lets_yaml_back_in_is_reported():
    for relative_path, flag in (
        ("build.ps1", r'\n\s*"--exclude-module",\s*"yaml",'),
        ("build.sh", r"\n\s*--exclude-module yaml [\\]"),
    ):
        text = _read(relative_path)
        broken = re.sub(flag, "", text)
        assert broken != text, relative_path

        helper_excludes = excludes(relative_path, command_texts(relative_path, broken)["helper"])
        assert "yaml" not in helper_excludes
        assert {"_pytest", "pytest"} <= helper_excludes


# The helper smoke test of test.yml builds the helper itself, in a venv with
# the dev extras. Without the exclusions of the release build it would test an
# executable that carries pytest, PyYAML and so on, not the one that ships.

TEST_WORKFLOW = ".github/workflows/test.yml"


def ci_helper_excludes(text: str | None = None) -> set[str]:
    """The --exclude-module values of the PyInstaller command in test.yml's helper smoke job."""
    if text is None:
        text = _read(TEST_WORKFLOW)
    match = re.search(
        r"--name\s+" + re.escape(identity.MCP_COMMAND) + r"(.*?)pyinstaller_mcp_entry\.py",
        text,
        re.DOTALL,
    )
    assert match, f"no PyInstaller command for the MCP helper found in {TEST_WORKFLOW}"
    return excludes("build.sh", match.group(1))


def test_the_ci_helper_smoke_build_excludes_what_the_release_builds_exclude():
    release_sh = excludes("build.sh", command_texts("build.sh")["helper"])
    release_ps1 = excludes("build.ps1", command_texts("build.ps1")["helper"])

    assert release_sh == release_ps1
    assert ci_helper_excludes() == release_sh


def test_a_ci_helper_smoke_build_that_lets_an_excluded_package_back_in_is_reported():
    text = _read(TEST_WORKFLOW)
    release = excludes("build.sh", command_texts("build.sh")["helper"])

    broken = re.sub(r"\n\s*--exclude-module yaml(?=\n)", "", text)
    assert broken != text
    assert ci_helper_excludes(broken) == release - {"yaml"}

    unrelated = text.replace("--exclude-module PIL", "--exclude-module PIL --exclude-module extra")
    assert unrelated != text
    assert ci_helper_excludes(unrelated) == release | {"extra"}


def test_a_macos_tar_command_without_the_license_files_is_reported():
    text = _read(".github/workflows/release.yml")
    broken = text.replace(f" {LICENSE_FILES}\n", "\n", 1)
    assert broken != text

    assert missing(".github/workflows/release.yml", broken) == [
        "macOS archive lists the license files"
    ]


def test_a_release_workflow_without_the_archive_check_is_reported():
    text = _read(".github/workflows/release.yml")
    broken = text.replace("for required in LICENSE THIRD_PARTY_NOTICES.txt; do", "true; do")
    assert broken != text

    assert missing(".github/workflows/release.yml", broken) == ["Unix archive check"]


def test_changing_the_product_slug_is_reported(monkeypatch):
    assert missing(".github/workflows/release.yml") == []

    monkeypatch.setattr(identity, "SLUG", "renamed-app")

    assert missing(".github/workflows/release.yml") != []
    assert missing("build.sh") != []
