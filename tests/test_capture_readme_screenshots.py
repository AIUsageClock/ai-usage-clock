"""The README capture tool must never write into the real app data folder.

The folder is redirected through the environment variable the app itself honours
for that purpose (``APP_DATA_DIR_OVERRIDE_ENV``). The tool has to spell it out
because it must set the variable before it imports the app, so this test ties
the spelling to the app's constant instead of repeating the literal.
"""

from __future__ import annotations

import ast
from pathlib import Path

from aiusageclock.platforms.base import APP_DATA_DIR_OVERRIDE_ENV

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_readme_screenshots.py"


def _isolates_app_data_before_importing_the_app(
    source: str, variable: str = APP_DATA_DIR_OVERRIDE_ENV
) -> bool:
    """True when ``os.environ[<variable>]`` is assigned before any app import."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aiusageclock"):
            return False
        if isinstance(node, ast.Import) and any(a.name.startswith("aiusageclock") for a in node.names):
            return False
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and ast.unparse(target.value) == "os.environ"
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == variable
                ):
                    return True
    return False


def test_capture_tool_points_app_data_at_a_temporary_folder_first():
    assert _isolates_app_data_before_importing_the_app(TOOL.read_text(encoding="utf-8"))


def test_capture_tool_uses_the_variable_the_app_reads_for_its_data_folder():
    # If the app ever reads another variable, the tool's literal no longer
    # redirects anything and this fails instead of the tool silently writing
    # into the real settings.
    source = TOOL.read_text(encoding="utf-8")

    assert _isolates_app_data_before_importing_the_app(source, APP_DATA_DIR_OVERRIDE_ENV)
    assert not _isolates_app_data_before_importing_the_app(source, "SOME_OTHER_VARIABLE")


def test_check_rejects_an_override_that_comes_after_the_app_import():
    source = (
        "import os\n"
        "from aiusageclock.config import Config\n"
        f"os.environ[{APP_DATA_DIR_OVERRIDE_ENV!r}] = '/tmp/x'\n"
    )
    assert not _isolates_app_data_before_importing_the_app(source)


def test_check_rejects_an_override_of_another_variable():
    source = "import os\nos.environ['HOME'] = '/tmp/x'\nfrom aiusageclock.widget import UsageWidget\n"

    assert not _isolates_app_data_before_importing_the_app(source)


def test_check_rejects_a_tool_without_any_override():
    assert not _isolates_app_data_before_importing_the_app(
        "import os\nfrom aiusageclock.widget import UsageWidget\n"
    )
