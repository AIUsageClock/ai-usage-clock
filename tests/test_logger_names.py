"""Guard the logger namespace.

``setup_logging()`` attaches its handlers to the logger named ``LOGGER_NAME``.
A ``getLogger("<literal>")`` call whose literal is outside that tree (for
example a leftover name from before a rename) would silently bypass the log
file, so every literal name must be ``LOGGER_NAME`` or a dotted child of it.
Calls that pass a non-literal (``__name__``, ``self.__class__.__module__``,
...) are not checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import aiusageclock
from aiusageclock.logging_setup import LOGGER_NAME

SRC_ROOT = Path(aiusageclock.__file__).resolve().parent


def _is_get_logger_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "getLogger"
    if isinstance(func, ast.Name):
        return func.id == "getLogger"
    return False


def literal_logger_names(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """Return (line, name) for every getLogger call that passes a string literal."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call) or not _is_get_logger_call(node):
            continue
        arg = node.args[0] if node.args else None
        if arg is None:
            arg = next((kw.value for kw in node.keywords if kw.arg == "name"), None)
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.append((node.lineno, arg.value))
    return sorted(found)


def is_app_logger_name(name: str) -> bool:
    return name == LOGGER_NAME or name.startswith(LOGGER_NAME + ".")


def test_logger_name_matches_package_name():
    assert LOGGER_NAME == aiusageclock.__name__


def test_literal_logger_names_in_src_use_app_namespace():
    checked = 0
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for lineno, name in literal_logger_names(source, str(path)):
            checked += 1
            if not is_app_logger_name(name):
                offenders.append(f"{path.relative_to(SRC_ROOT).as_posix()}:{lineno}: {name!r}")

    # Guard against a scan that silently finds nothing and passes vacuously.
    assert checked > 0
    assert offenders == [], (
        f"logger names must be {LOGGER_NAME!r} or start with {LOGGER_NAME + '.'!r}: {offenders}"
    )


def test_scan_flags_names_outside_app_namespace():
    source = "\n".join(
        [
            "import logging",
            f'good = logging.getLogger("{LOGGER_NAME}")',
            f'good_child = logging.getLogger("{LOGGER_NAME}.providers.claude")',
            'bad_old = logging.getLogger("oldname.app")',
            f'bad_sibling = logging.getLogger("{LOGGER_NAME}x")',
            "from logging import getLogger",
            'bad_bare = getLogger("other")',
            'bad_keyword = logging.getLogger(name="elsewhere")',
            "dynamic = logging.getLogger(__name__)",
            "dynamic_module = logging.getLogger(self.__class__.__module__)",
            "root = logging.getLogger()",
        ]
    )

    names = literal_logger_names(source)
    offenders = [name for _, name in names if not is_app_logger_name(name)]

    assert offenders == ["oldname.app", f"{LOGGER_NAME}x", "other", "elsewhere"]
    # The non-literal and no-argument calls are not reported at all.
    assert len(names) == 6
