"""The release build must ship LICENSE and THIRD_PARTY_NOTICES.txt.

The MIT License wants its text to travel with every copy, and the bundled
PyQt6, Qt and the other dependencies carry terms of their own. The build
scripts and the release workflow are shell code that unit tests cannot run, so
this reads their text and checks that each step is still there. Every check has
a deliberately broken counterpart further down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aiusageclock import identity

REPO_ROOT = Path(__file__).resolve().parents[1]
LICENSE_FILES = "LICENSE THIRD_PARTY_NOTICES.txt"

Expectation = tuple[str, re.Pattern[str]]


def _lit(label: str, text: str) -> Expectation:
    return label, re.compile(re.escape(text))


def expectations() -> dict[str, list[Expectation]]:
    slug = identity.SLUG
    mcp = identity.MCP_COMMAND
    return {
        "build.ps1": [
            _lit("notice folder choice", '$noticeDir = if ($OneFile) {'),
            _lit(
                "LICENSE copy",
                'Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LICENSE") '
                '-Destination (Join-Path $noticeDir "LICENSE")',
            ),
            _lit(
                "notices generator call",
                '(Join-Path $PSScriptRoot "tools\\write_third_party_notices.py") '
                '(Join-Path $noticeDir "THIRD_PARTY_NOTICES.txt")',
            ),
            _lit("generator failure check", 'Write-Error "Could not write THIRD_PARTY_NOTICES.txt."'),
            _lit(
                "output existence check",
                'foreach ($noticeFile in @("LICENSE", "THIRD_PARTY_NOTICES.txt"))',
            ),
        ],
        "build.sh": [
            _lit(
                "notice folder choice",
                'if [ "$(uname -s)" = "Darwin" ] || [ "$ONEFILE" -eq 1 ]; then\n'
                '    NOTICE_DIR="dist"\n'
                "else\n"
                f'    NOTICE_DIR="dist/{slug}"\n'
                "fi",
            ),
            _lit("LICENSE copy", 'cp "$SCRIPT_DIR/LICENSE" "$NOTICE_DIR/LICENSE"'),
            _lit(
                "notices generator call",
                '"$VENV_PY" "$SCRIPT_DIR/tools/write_third_party_notices.py" '
                '"$NOTICE_DIR/THIRD_PARTY_NOTICES.txt"',
            ),
            _lit("output existence check", "for NOTICE_FILE in LICENSE THIRD_PARTY_NOTICES.txt; do"),
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


def test_notices_are_written_after_pruning_and_before_the_build_is_declared_done():
    for relative_path, prune, done in (
        ("build.ps1", "prune_bundle.py", 'Write-Host "Build complete."'),
        ("build.sh", "prune_bundle.py", 'echo "Build complete."'),
    ):
        text = _read(relative_path)
        assert text.index(prune) < text.index("write_third_party_notices.py") < text.index(done)


# --- deliberately broken copies must be reported ---------------------------


def test_a_build_ps1_that_forgets_the_license_copy_is_reported():
    text = _read("build.ps1")
    broken = text.replace(
        'Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LICENSE")',
        'Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.md")',
    )
    assert broken != text

    assert missing("build.ps1", broken) == ["LICENSE copy"]


def test_a_build_sh_that_skips_the_generator_is_reported():
    text = _read("build.sh")
    broken = text.replace("write_third_party_notices.py", "something_else.py")
    assert broken != text

    assert missing("build.sh", broken) == ["notices generator call"]


def test_a_build_sh_that_puts_the_files_in_the_wrong_folder_is_reported():
    text = _read("build.sh")
    broken = text.replace(f'NOTICE_DIR="dist/{identity.SLUG}"', 'NOTICE_DIR="build"')
    assert broken != text

    assert missing("build.sh", broken) == ["notice folder choice"]


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
