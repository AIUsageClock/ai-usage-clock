"""Lazily imported modules must reach the packaged executables.

``lazy_module("x")`` imports by name at run time, which PyInstaller cannot see.
tools/lazy_modules.txt is the single list the build scripts turn into
``--hidden-import`` flags and tools/check_lazy_modules.py verifies against the
built PYZ archive. These tests keep that list complete and the checker honest.
"""

from __future__ import annotations

import ast
import pprint
import re
from pathlib import Path

import pytest

from tools import check_lazy_modules as check

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"


def lazy_module_names() -> dict[str, list[str]]:
    """Every literal passed to lazy_module() under src/, with where it is called."""
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "lazy_module":
                arg = node.args[0] if node.args else None
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                    f"{path}:{node.lineno}: lazy_module() needs a string literal so the "
                    "build list can be checked against it"
                )
                found.setdefault(arg.value, []).append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


def test_there_are_lazy_modules_to_check():
    assert {"requests", "keyring"} <= set(lazy_module_names())


def test_every_lazy_module_in_src_is_listed_for_the_gui_build():
    listed = set(check.hidden_imports("gui"))
    unlisted = {name: where for name, where in lazy_module_names().items() if name not in listed}
    assert unlisted == {}, (
        "lazy_module() names missing from tools/lazy_modules.txt ('hidden gui <name>'); "
        "the packaged app would raise ModuleNotFoundError: " + repr(unlisted)
    )


def test_no_other_import_by_name_hides_in_src():
    # importlib.import_module / __import__ with a string are as invisible to
    # PyInstaller as lazy_module; only _lazy.py may do it (through the list above).
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "_lazy.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in {"import_module", "__import__"}:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == []


def test_the_manifest_parses_and_every_require_belongs_to_a_target():
    entries = check.parse_manifest()
    assert any(e.kind == "hidden" for e in entries)
    assert {e.target for e in entries} <= set(check.TARGETS)


def _toc(tmp_path: Path, modules: list[str]) -> Path:
    path = tmp_path / "PYZ-00.toc"
    path.write_text(
        pprint.pformat(("PYZ-00.pyz", [(m, f"C:/x/{m}.py", "PYMODULE") for m in modules])),
        encoding="utf-8",
    )
    return path


def _all_gui_modules(platform: str) -> list[str]:
    return [e.module for e in check.parse_manifest() if check.applies(e, "gui", platform)]


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_a_complete_archive_passes(tmp_path, platform):
    toc = _toc(tmp_path, _all_gui_modules(platform))
    assert check.missing_modules("gui", toc, platform) == []


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_an_archive_without_a_lazy_module_is_reported(tmp_path, platform):
    modules = [m for m in _all_gui_modules(platform) if m != "keyring"]
    assert check.missing_modules("gui", _toc(tmp_path, modules), platform) == ["keyring"]


def test_the_platform_backend_is_only_required_on_its_platform(tmp_path):
    modules = [m for m in _all_gui_modules("win32") if m != "keyring.backends.Windows"]
    toc = _toc(tmp_path, modules)
    assert check.missing_modules("gui", toc, "win32") == ["keyring.backends.Windows"]
    assert check.missing_modules("gui", toc, "linux") == [
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
    ]


def test_the_command_line_exits_1_when_something_is_missing(tmp_path, capsys):
    toc = _toc(tmp_path, ["requests"])
    assert check.main(["gui", str(toc)]) == 1
    assert "keyring" in capsys.readouterr().err


def test_the_command_line_refuses_a_file_that_is_not_a_pyz_table(tmp_path, capsys):
    bad = tmp_path / "PYZ-00.toc"
    bad.write_text("not a table", encoding="utf-8")
    assert check.main(["gui", str(bad)]) == 2


def test_list_hidden_prints_the_gui_modules(capsys):
    assert check.main(["--list-hidden", "gui"]) == 0
    assert set(capsys.readouterr().out.split()) == set(check.hidden_imports("gui"))


# --- the build scripts and CI really use the list ---------------------------------


@pytest.mark.parametrize("script", ["build.ps1", "build.sh"])
def test_the_build_scripts_pass_the_list_and_check_the_result(script):
    text = (REPO_ROOT / script).read_text(encoding="utf-8")
    assert "check_lazy_modules.py" in text
    assert "--list-hidden" in text and "--hidden-import" in text
    for target in ("gui", "mcp"):
        assert re.search(rf'Get-LazyHiddenImportArgs "{target}"|lazy_hidden_import_args {target}\)', text), (
            script,
            target,
        )
    # the check runs on both executables' PYZ tables, after both are built
    assert text.index("PYZ-00.toc") > text.index("pyinstaller_mcp_entry.py")
    assert re.search(r'"mcp"|\bmcp "', text[text.index("PYZ-00.toc") - 400 :])


def test_ci_mcp_helper_build_gets_the_same_hidden_imports_as_the_release_build():
    # The helper needs none today. If the manifest ever lists one, the CI smoke
    # build in test.yml must pass the same --hidden-import flags.
    workflow = (REPO_ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    block = re.search(r"--name ai-usage-clock-mcp(.*?)pyinstaller_mcp_entry\.py", workflow, re.DOTALL)
    assert block
    ci = set(re.findall(r"--hidden-import\s+(\S+)", block.group(1)))
    assert ci == set(check.hidden_imports("mcp"))
