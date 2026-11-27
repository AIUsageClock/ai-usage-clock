"""Windows-only guards for the "Segoe UI Symbol" rule in aiusageclock/ui_fonts.py.

A character that Segoe UI lacks makes Qt's DirectWrite engine load its whole
fallback font chain (~40 MB resident). Widgets showing such characters must use
the single family "Segoe UI Symbol". These tests fail when a new symbol is added
without being handled. Other platforms never touch fonts, so they skip.

Tooltips are not walked: every tooltip string in the sources is plain ASCII,
which the static scan below enforces together with all other string constants.
"""

from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMenu, QWidget

from aiusageclock import settings_dialog, ui_fonts
from aiusageclock.config import Config
from aiusageclock.error_dialog import ErrorDetailsDialog
from aiusageclock.local_usage.limit_changes_dialog import LimitChangesDialog
from aiusageclock.local_usage.rates import load_rate_table
from aiusageclock.local_usage.service import LocalUsageService
from aiusageclock.local_usage.usage_tab import UsageCostTab
from aiusageclock.models import SnapshotStatus, UsageMetric, UsageSnapshot
from aiusageclock.ratio_dialog import RatioHistoryDialog
from aiusageclock.settings_dialog import SettingsDialog
from aiusageclock.widget import UsageWidget

from tests.symbol_fonts import (
    SYMBOL_FONT_FILES,
    assert_symbol_fonts,
    family_has,
    missing_from_segoe_ui,
    segoe_available,
    segoe_ui_has,
)

pytestmark = pytest.mark.skipif(
    not segoe_available(), reason="needs Windows with Segoe UI and Segoe UI Symbol"
)

SRC = Path(__file__).resolve().parents[1] / "src" / "aiusageclock"
FIXTURES = Path(__file__).parent / "fixtures" / "local_usage"


def test_symbol_chars_are_what_segoe_ui_lacks_and_their_family_has(qapp):
    assert set(ui_fonts.FAMILY_FOR_CHAR.values()) <= set(SYMBOL_FONT_FILES)
    for char, family in ui_fonts.FAMILY_FOR_CHAR.items():
        assert not segoe_ui_has(char), f"U+{ord(char):04X} is in Segoe UI; drop it from FAMILY_FOR_CHAR"
        assert family_has(family, char), f"{family} lacks U+{ord(char):04X}"


def _string_constants(tree: ast.AST):
    """String constants that are not docstrings (those never reach the screen)."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node


def _is_cjk(char: str) -> bool:
    return 0x2E80 <= ord(char) <= 0x9FFF or 0xF900 <= ord(char) <= 0xFAFF


def test_every_symbol_in_the_sources_is_handled(qapp):
    """Fails when a string constant gains a character Segoe UI lacks and
    ``ui_fonts.SYMBOL_CHARS`` does not know it, so the widget showing it would
    quietly bring back the 40 MB fallback. CJK ideographs are exempt: they only
    appear in the Codex page-matching patterns, never in widget text."""
    unhandled: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _string_constants(tree):
            for char in missing_from_segoe_ui(node.value):
                if char in ui_fonts.SYMBOL_CHARS or _is_cjk(char):
                    continue
                unhandled.setdefault(f"U+{ord(char):04X} {char}", []).append(
                    f"{path.relative_to(SRC.parent.parent).as_posix()}:{node.lineno}"
                )
    assert not unhandled, (
        "characters missing from Segoe UI must be added to ui_fonts.SYMBOL_CHARS "
        f"(and their widgets given apply_symbol_font): {unhandled}"
    )


def test_helper_switches_only_the_family_and_only_on_windows(qapp, monkeypatch):
    from PyQt6.QtWidgets import QPushButton

    plain = QPushButton("OK")
    ui_fonts.apply_symbol_font(plain)
    assert plain.font().family() not in SYMBOL_FONT_FILES

    button = QPushButton("▾")
    font = button.font()
    font.setBold(True)
    font.setPixelSize(13)
    button.setFont(font)
    ui_fonts.apply_symbol_font(button)
    assert button.font().family() == ui_fonts.SYMBOL_FAMILY
    assert button.font().bold() and button.font().pixelSize() == 13

    gear = QPushButton("⚙")
    ui_fonts.apply_symbol_font(gear)
    assert gear.font().family() == ui_fonts.EMOJI_FAMILY

    other = QPushButton("⚙")
    before = other.font().family()
    monkeypatch.setattr(sys, "platform", "linux")
    ui_fonts.apply_symbol_font(other)
    assert other.font().family() == before


def test_main_widget_symbols_use_the_symbol_font(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(
        UsageSnapshot(
            provider="claude",
            status=SnapshotStatus.OK,
            metrics=[UsageMetric("Session", 40.0), UsageMetric("Weekly", 20.0)],
        ),
        "Claude",
    )
    tile = widget._tiles["claude"]
    # The three header buttons and the two collapsed-view buttons, plus the tile's
    # chevron and dismiss button.
    checked = assert_symbol_fonts(widget)
    assert checked >= 7, checked
    # The chevron flips between two glyphs; both must keep the symbol font.
    for expanded in (True, False, True):
        tile._expanded = expanded
        tile._update_expand_btn_glyph()
        assert_symbol_fonts(widget)
    widget.set_collapsed(True)
    assert_symbol_fonts(widget)
    widget.set_collapsed(False)
    assert_symbol_fonts(widget)


def test_settings_dialog_and_menus_use_the_symbol_font(qtbot, monkeypatch):
    monkeypatch.setattr(settings_dialog, "resolve_cli", lambda _: None)
    monkeypatch.setattr(settings_dialog, "set_start_at_login", lambda _: None)
    monkeypatch.setattr(settings_dialog, "get_linear_key", lambda: None)
    dialog = SettingsDialog(Config())
    qtbot.addWidget(dialog)
    assert_symbol_fonts(dialog)
    for menu in dialog.findChildren(QMenu):
        assert_symbol_fonts(menu)


def test_small_dialogs_use_the_symbol_font(qtbot):
    snapshot = UsageSnapshot(provider="claude", status=SnapshotStatus.ERROR, error="boom")
    error_dialog = ErrorDetailsDialog("claude", "Claude", snapshot)
    qtbot.addWidget(error_dialog)
    assert_symbol_fonts(error_dialog)

    limits = LimitChangesDialog([], "Claude")
    qtbot.addWidget(limits)
    assert_symbol_fonts(limits)


@pytest.fixture
def usage_service(tmp_path):
    claude = tmp_path / "logs" / "claude" / "projects"
    codex = tmp_path / "logs" / "codex"
    shutil.copytree(FIXTURES / "claude" / "projects", claude)
    shutil.copytree(FIXTURES / "codex" / "sessions", codex / "sessions")
    config = Config()
    config.local_usage.enabled = True
    config.local_usage.claude.account_id = "claude"
    config.local_usage.claude.log_root = str(claude)
    config.local_usage.codex.account_id = "codex"
    config.local_usage.codex.log_root = str(codex)
    service = LocalUsageService(config, base_dir=tmp_path / "data")
    yield service
    service.shutdown()


def test_usage_tab_and_ratio_dialog_use_the_symbol_font(qtbot, usage_service):
    tab = UsageCostTab(
        usage_service,
        "claude",
        "Claude",
        None,
        rate_table=load_rate_table(override_path=Path("does-not-exist.json")),
    )
    qtbot.addWidget(tab)
    for view in ("model", "day", "trend"):
        tab.show_view(view)
        assert_symbol_fonts(tab)
    dialog = RatioHistoryDialog("claude", "Claude", [], current_estimate=None, usage_tab=tab)
    qtbot.addWidget(dialog)
    assert_symbol_fonts(dialog)
    # Dynamic text with symbols (day chip, skipped-windows toggle, trend warning)
    # is asserted in test_local_usage_usage_tab.py and test_local_usage_trend_tab.py,
    # where the data that produces it already exists.


def test_tab_texts_are_walked_too(qtbot):
    """The walker must see tab titles, not only buttons and labels."""
    from PyQt6.QtWidgets import QTabWidget

    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.addTab(QWidget(), "Alerts ⓘ")
    with pytest.raises(AssertionError):
        assert_symbol_fonts(tabs)
