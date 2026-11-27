"""Font family choice for the few UI glyphs Segoe UI does not contain.

On Windows, Qt's DirectWrite font engine reacts to a character that the widget's
font (Segoe UI) lacks by loading its whole fallback chain of fonts - roughly
40 MB of resident memory, for the life of the process. The chevrons and
symbols on the main widget's small buttons (and a few labels elsewhere) hit
that path on every launch. Giving *only* those widgets a single family that does
contain the glyphs (Segoe UI Symbol; Segoe UI Emoji for the gear, to keep it
looking the same) avoids the fallback.

Notes on how this was chosen:

* A single family only works: ``setFamilies([...])``, font substitutions and a
  QSS ``font-family`` list do not prevent the fallback.
* The set of affected characters is listed explicitly instead of asked from Qt
  at run time. ``QFontMetrics.inFontUcs4`` answers True for any character that
  the fallback chain can render, and the offscreen platform used by the tests
  has no fonts at all. ``tests/test_ui_fonts.py`` checks this list against the
  real Segoe UI font file and fails when a new symbol is added to the sources
  without being listed here.
* Everything is a no-op outside Windows: macOS and Linux fonts are untouched.
"""

from __future__ import annotations

import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget

#: Family used for the symbols below, except the gear.
SYMBOL_FAMILY = "Segoe UI Symbol"

#: The gear is the one glyph whose fallback is the colour emoji font: with the
#: fallback chain, Qt draws it in Segoe UI Emoji, and a widget set to that
#: single family draws it pixel-for-pixel the same for about 1 MB. Segoe UI
#: Symbol would swap it for an outline gear.
EMOJI_FAMILY = "Segoe UI Emoji"

#: Characters used in widget text that Segoe UI lacks, and the family each is
#: set in (verified against the font files by the tests):
#: U+25B4 small up triangle, U+25B8 small right triangle, U+25BE small down
#: triangle, U+2715 multiplication X, U+24D8 circled i, U+2699 gear.
FAMILY_FOR_CHAR: dict[str, str] = {
    "\u25b4": SYMBOL_FAMILY,
    "\u25b8": SYMBOL_FAMILY,
    "\u25be": SYMBOL_FAMILY,
    "\u2715": SYMBOL_FAMILY,
    "\u24d8": SYMBOL_FAMILY,
    "\u2699": EMOJI_FAMILY,
}
SYMBOL_CHARS = frozenset(FAMILY_FOR_CHAR)


def symbol_family_for(text: str) -> str | None:
    """Family to set for ``text``, or None when Segoe UI covers all of it.

    Text mixing characters that need different families gets the first one's;
    the widgets here never do (the test suite would show it).
    """
    for ch in text:
        family = FAMILY_FOR_CHAR.get(ch)
        if family is not None:
            return family
    return None


def needs_symbol_font(text: str) -> bool:
    """True when ``text`` has a character in :data:`SYMBOL_CHARS`."""
    return symbol_family_for(text) is not None


def apply_symbol_font(widget: QWidget, text: str | None = None) -> None:
    """Switch ``widget`` to the symbol family its text needs, if any.

    Only the family changes; size, weight and the rest of the font are kept.
    ``text`` defaults to ``widget.text()``. Safe to call repeatedly, and a
    no-op on every platform except Windows.
    """
    if sys.platform != "win32":
        return
    if text is None:
        text = widget.text()  # type: ignore[attr-defined]
    family = symbol_family_for(text)
    if family is None:
        return
    font = QFont(widget.font())
    if font.family() == family:
        return
    font.setFamily(family)
    widget.setFont(font)


def set_symbol_text(widget: QWidget, text: str) -> None:
    """``widget.setText(text)`` plus :func:`apply_symbol_font` for that text."""
    widget.setText(text)  # type: ignore[attr-defined]
    apply_symbol_font(widget, text)
