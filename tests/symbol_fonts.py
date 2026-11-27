"""Test helpers for the Windows symbol-font rule (see aiusageclock/ui_fonts.py).

The coverage of Segoe UI is read from the real font file, not from the
application's own character list, so these checks do not just echo the code
they guard. The offscreen platform has no system fonts, but a font file can
still be registered with ``QFontDatabase.addApplicationFont`` for lookups.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase, QRawFont
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QMenu,
    QTabBar,
    QTableWidget,
    QWidget,
)

#: Families a widget may use for characters Segoe UI lacks, and their font files.
SYMBOL_FONT_FILES = {"Segoe UI Symbol": "seguisym.ttf", "Segoe UI Emoji": "seguiemj.ttf"}
_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def segoe_available() -> bool:
    return sys.platform == "win32" and all(
        (_FONT_DIR / name).is_file() for name in ("segoeui.ttf", *SYMBOL_FONT_FILES.values())
    )


@lru_cache(maxsize=None)
def _raw_font(filename: str) -> QRawFont:
    assert QApplication.instance() is not None, "needs a QApplication"
    font_id = QFontDatabase.addApplicationFont(str(_FONT_DIR / filename))
    assert font_id >= 0, f"cannot load {filename}"
    family = QFontDatabase.applicationFontFamilies(font_id)[0]
    raw = QRawFont.fromFont(QFont(family, 10))
    # Do not leave Segoe UI registered: on the offscreen platform (which has no
    # fonts of its own) it would change text metrics in every later test.
    QFontDatabase.removeApplicationFont(font_id)
    return raw


def segoe_ui_has(char: str) -> bool:
    return _raw_font("segoeui.ttf").supportsCharacter(char)


def family_has(family: str, char: str) -> bool:
    return _raw_font(SYMBOL_FONT_FILES[family]).supportsCharacter(char)


def missing_from_segoe_ui(text: str) -> set[str]:
    return {ch for ch in text if ord(ch) > 127 and not segoe_ui_has(ch)}


def _texts(widget: QWidget) -> list[str]:
    """Every user-visible string a widget draws itself."""
    out: list[str] = []
    if isinstance(widget, (QAbstractButton, QLabel)):
        out.append(widget.text())
    if isinstance(widget, QGroupBox):
        out.append(widget.title())
    if isinstance(widget, QComboBox):
        out.extend(widget.itemText(i) for i in range(widget.count()))
    if isinstance(widget, QTabBar):
        out.extend(widget.tabText(i) for i in range(widget.count()))
    if isinstance(widget, QMenu):
        out.extend(action.text() for action in widget.actions())
    return out


def _assert_font_covers(family: str, chars: set[str], who: str) -> None:
    assert family in SYMBOL_FONT_FILES, (
        f"{who} shows {sorted(f'U+{ord(c):04X}' for c in chars)}, which Segoe UI lacks, "
        f"but uses font {family!r} instead of one of {sorted(SYMBOL_FONT_FILES)}"
    )
    assert all(family_has(family, c) for c in chars), f"{who}: {family!r} lacks one of {chars}"


def assert_symbol_fonts(root: QWidget) -> int:
    """Fail unless every widget showing a Segoe-UI-less character uses the
    Segoe UI Symbol family. Returns how many such widgets were checked.

    No-op (returns 0) when not on Windows or when the fonts are missing.
    """
    if not segoe_available():
        return 0
    checked = 0
    for widget in [root, *root.findChildren(QWidget)]:
        for text in _texts(widget):
            bad = missing_from_segoe_ui(text)
            if bad:
                checked += 1
                _assert_font_covers(widget.font().family(), bad, f"{type(widget).__name__} {widget.objectName()!r} {text!r}")
        if isinstance(widget, QTableWidget):
            for row in range(widget.rowCount()):
                for col in range(widget.columnCount()):
                    item = widget.item(row, col)
                    if item is not None and missing_from_segoe_ui(item.text()):
                        checked += 1
                        _assert_font_covers(item.font().family(), missing_from_segoe_ui(item.text()), f"table item {item.text()!r}")
    return checked
