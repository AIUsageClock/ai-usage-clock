"""The README capture tool must never write into the real app data folder."""

from __future__ import annotations

import ast
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_readme_screenshots.py"


def _isolates_app_data_before_importing_the_app(source: str) -> bool:
    """True when ``os.environ["APPDATA"]`` is assigned before any app import."""
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
                    and target.slice.value == "APPDATA"
                ):
                    return True
    return False


def test_capture_tool_points_app_data_at_a_temporary_folder_first():
    assert _isolates_app_data_before_importing_the_app(TOOL.read_text(encoding="utf-8"))


def test_check_rejects_an_override_that_comes_after_the_app_import():
    source = (
        "import os\n"
        "from aiusageclock.config import Config\n"
        "os.environ['APPDATA'] = '/tmp/x'\n"
    )
    assert not _isolates_app_data_before_importing_the_app(source)


def test_check_rejects_a_tool_without_any_override():
    assert not _isolates_app_data_before_importing_the_app(
        "import os\nfrom aiusageclock.widget import UsageWidget\n"
    )
