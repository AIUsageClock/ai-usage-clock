import html

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PyQt6.QtWidgets import QApplication
from aiusageclock.app import App
from aiusageclock.config import Config
from aiusageclock.models import SnapshotStatus, UsageMetric, UsageSnapshot
from aiusageclock.providers._resets_common import ResetEvent, ResetWatch, ResetsFetchError, build_snapshot
from aiusageclock.providers.codex_resets import CodexResetsProvider, _parse_watch
from aiusageclock.widget import UsageWidget, _ProviderTile, _SummaryChip


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


def watch_payload(source=None, **changes):
    payload = {
        "level": "elevated",
        "reset_chance_percent": 37,
        "forecast_window": "later this week",
        "observed_at": "2026-09-27T11:00:00Z",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
        "text": "Synthetic activity suggests a possible reset.",
        "source": source if source is not None else {"type": "observed"},
    }
    payload.update(changes)
    return payload

def event(identifier="one"):
    return ResetEvent(
        "landed", identifier, NOW, "limits refilled", "Synthetic event",
        f"https://example.test/{identifier}",
    )

def ag_snapshot(groups=("Gemini", "Claude+GPT")):
    return UsageSnapshot(
        provider="antigravity", status=SnapshotStatus.OK,
        metrics=[
            UsageMetric(f"{group} {window}", percent, None,
                        reset_label="idle" if window == "5h" else "2.8d")
            for group in groups
            for window, percent in (("5h", 0.0), ("weekly", 14.0))
        ],
    )


ARGON_METRICS = (
    UsageMetric("Gemini 5h", 0.0, None, reset_label="idle"),
    UsageMetric("Gemini weekly", 14.0, None, reset_label="2.8d"),
    UsageMetric("Claude+GPT 5h", 0.0, None, reset_label="idle"),
    UsageMetric("Claude+GPT weekly", 88.5, None, reset_label="1.0d"),
    UsageMetric("Argon weekly", 38.7, None, reset_label="6.0d"),
)


def _slot(tile: _ProviderTile, row_index: int, window: str):
    col_index = 1 if window == "5h" else 2
    return tile._compact_group_rows[row_index].layout().itemAt(col_index).widget()

def test_antigravity_compact_groups_and_saved_state(qtbot, monkeypatch):
    config = Config()
    save = Mock()
    monkeypatch.setattr(Config, "save", save)
    widget = UsageWidget(config)
    qtbot.addWidget(widget)
    widget.update_snapshot(ag_snapshot(), "Antigravity")
    tile = widget._tiles["antigravity"]
    assert not tile.expand_btn.isHidden()
    assert tile._expanded
    app = App.__new__(App)
    app._config = config
    tile.expand_btn.click()
    assert tile.expand_btn.text() == "▸"
    assert tile._compact_below_header
    assert tile._rows == []
    assert [row.layout().itemAt(0).widget().text() for row in tile._compact_group_rows] == [
        "Gemini", "Claude+GPT",
    ]
    assert [item.code.text() for item in tile._compact_metrics] == ["5", "W", "5", "W"]
    tile.set_available_width(320)
    assert all(row.sizeHint().width() <= 320 for row in tile._compact_group_rows)
    assert tile._compact_group_rows[0].layout().itemAt(1).widget().x() == (
        tile._compact_group_rows[1].layout().itemAt(1).widget().x()
    )
    app._on_tile_expanded_changed("antigravity", False)
    assert config.collapsed_tiles == ["antigravity"]
    save.assert_called_once()
    widget.update_snapshot(ag_snapshot(("Claude+GPT",)), "Antigravity")
    assert len(tile._compact_group_rows) == 1
    assert [item.code.text() for item in tile._compact_metrics] == ["5", "W"]
    widget.update_snapshot(ag_snapshot(()), "Antigravity")
    assert tile._compact_summary.isHidden()


def test_antigravity_compact_three_groups_with_argon_weekly(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    snapshot = UsageSnapshot(
        provider="antigravity",
        status=SnapshotStatus.OK,
        metrics=list(ARGON_METRICS),
    )
    widget.update_snapshot(snapshot, "Antigravity")
    tile = widget._tiles["antigravity"]
    tile.expand_btn.click()
    assert [row.layout().itemAt(0).widget().text() for row in tile._compact_group_rows] == [
        "Gemini",
        "Claude+GPT",
        "Argon",
    ]
    assert [item.code.text() for item in tile._compact_metrics] == [
        "5",
        "W",
        "5",
        "W",
        "",
        "W",
    ]
    assert [row.layout().count() for row in tile._compact_group_rows] == [3, 3, 3]
    argon_placeholder = _slot(tile, 2, "5h")
    assert argon_placeholder.code.text() == ""
    assert argon_placeholder.pct.text() == ""
    assert argon_placeholder.reset.text() == ""
    assert argon_placeholder.bar.isHidden()
    assert argon_placeholder.toolTip() == ""
    argon_metric = _slot(tile, 2, "weekly")
    assert argon_metric.code.text() == "W"
    assert argon_metric.pct.text() == "39%"
    assert argon_metric.reset.text() == "6.0d"


def test_antigravity_compact_argon_weekly_geometry_alignment(qtbot):
    tile = _ProviderTile("antigravity", "Antigravity")
    qtbot.addWidget(tile)
    snapshot = UsageSnapshot(
        provider="antigravity",
        status=SnapshotStatus.OK,
        metrics=list(ARGON_METRICS),
    )
    tile.set_snapshot(snapshot)
    tile.expand_btn.click()
    tile.show()
    qtbot.waitExposed(tile)

    gemini_5 = _slot(tile, 0, "5h")
    gemini_w = _slot(tile, 0, "weekly")
    claude_w = _slot(tile, 1, "weekly")
    argon_5 = _slot(tile, 2, "5h")
    argon_w = _slot(tile, 2, "weekly")

    assert argon_5.sizeHint().width() == gemini_5.sizeHint().width()
    assert argon_5.sizeHint().width() == argon_w.sizeHint().width()

    for width in (320, 500):
        target_width = max(width, tile.minimumWidth())
        tile.set_available_width(target_width)
        tile.resize(target_width, tile.sizeHint().height())
        QApplication.processEvents()
        tile.layout().activate()
        assert argon_w.x() == gemini_w.x() == claude_w.x()
        assert argon_w.bar.x() == gemini_w.bar.x() == claude_w.bar.x()
        assert argon_w.pct.x() == gemini_w.pct.x() == claude_w.pct.x()
        assert gemini_w.x() > gemini_5.x()


def test_antigravity_compact_empty_reset_preserves_subwidget_alignment(qtbot):
    tile = _ProviderTile("antigravity", "Antigravity")
    qtbot.addWidget(tile)
    snapshot = UsageSnapshot(
        provider="antigravity",
        status=SnapshotStatus.OK,
        metrics=[
            UsageMetric("Gemini 5h", None, None),
            UsageMetric("Gemini weekly", 14.0, None, reset_label="2.8d"),
            UsageMetric("Claude+GPT 5h", 0.0, None, reset_label="idle"),
            UsageMetric("Claude+GPT weekly", 88.5, None, reset_label="1.0d"),
        ],
    )
    tile.set_snapshot(snapshot)
    tile.expand_btn.click()
    tile.show()
    qtbot.waitExposed(tile)
    QApplication.processEvents()
    tile.layout().activate()

    gemini_5 = _slot(tile, 0, "5h")
    claude_5 = _slot(tile, 1, "5h")
    assert gemini_5.reset.text() == ""
    assert not gemini_5.reset.isHidden()
    assert gemini_5.bar.x() == claude_5.bar.x()
    assert gemini_5.pct.x() == claude_5.pct.x()


def test_antigravity_compact_duplicate_slot_keeps_higher_percent(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    snapshot = UsageSnapshot(
        provider="antigravity",
        status=SnapshotStatus.OK,
        metrics=[
            UsageMetric("Gemini 5h", 90.0, None, reset_label="1.0h"),
            UsageMetric("Gemini 5h", 5.0, None, reset_label="4.9h"),
            UsageMetric("Gemini weekly", 10.0, None, reset_label="6.0d"),
            UsageMetric("Gemini weekly", 70.0, None, reset_label="2.0d"),
            UsageMetric("Claude+GPT 5h", None, None),
            UsageMetric("Claude+GPT 5h", 0.0, None, reset_label="idle"),
        ],
    )
    widget.update_snapshot(snapshot, "Antigravity")
    tile = widget._tiles["antigravity"]
    tile.expand_btn.click()
    assert len(tile._compact_group_rows) == 2
    assert _slot(tile, 0, "5h").pct.text() == "90%"
    assert _slot(tile, 0, "weekly").pct.text() == "70%"
    assert _slot(tile, 1, "5h").pct.text() == "0%"


def test_antigravity_compact_alignment_reset_column_hidden(qtbot):
    # Guards the show_reset=False parameter contract on _set_antigravity_compact_metrics
    # (currently unused by production callers, which keep the default True).
    tile = _ProviderTile("antigravity", "Antigravity")
    qtbot.addWidget(tile)
    tile.set_expanded(False, emit=False)
    tile._set_antigravity_compact_metrics(list(ARGON_METRICS), show_reset=False)
    tile.show()
    qtbot.waitExposed(tile)
    QApplication.processEvents()
    tile.layout().activate()

    gemini_5 = _slot(tile, 0, "5h")
    gemini_w = _slot(tile, 0, "weekly")
    claude_w = _slot(tile, 1, "weekly")
    argon_w = _slot(tile, 2, "weekly")

    assert all(item.reset.isHidden() for item in tile._compact_metrics)
    assert argon_w.x() == gemini_w.x() == claude_w.x()
    assert argon_w.bar.x() == gemini_w.bar.x() == claude_w.bar.x()
    assert argon_w.pct.x() == gemini_w.pct.x() == claude_w.pct.x()
    assert gemini_w.x() > gemini_5.x()

@pytest.mark.parametrize("name,codes", [
    ("claude", ["S", "W"]), ("codex", ["S", "W"]),
    ("opencode_go", ["R", "M"]),
])
def test_other_compact_tiles_keep_header_chips(qtbot, name, codes):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    labels = ("Rolling", "Monthly") if name == "opencode_go" else ("Session", "Weekly")
    widget.update_snapshot(UsageSnapshot(
        provider=name, status=SnapshotStatus.OK,
        metrics=[UsageMetric(label, 20.0, None) for label in labels],
    ), name)
    tile = widget._tiles[name]
    tile.set_expanded(False)
    assert not tile._compact_below_header
    assert tile._rows == []
    assert [item.code.text() for item in tile._compact_metrics] == codes

@pytest.mark.parametrize("name", ["codex_resets", "claude_resets"])
def test_dismissed_tile_hides_on_ok_and_error_then_returns(qtbot, name):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    first = event()
    for error in (None, "HTTP 503"):
        widget.update_snapshot(build_snapshot(name, first, first.key, NOW, error), name)
        assert widget._tiles[name].isHidden()
        assert name in widget._tiles
        widget.set_collapsed(True)
        assert all(
            name.replace("_", " ").lower() not in chip.text().lower()
            for chip in widget._collapsed_widget.findChildren(_SummaryChip)
        )
        widget.set_collapsed(False)
    widget.update_snapshot(build_snapshot(name, event("two"), first.key, NOW), name)
    assert not widget._tiles[name].isHidden()
    widget.update_snapshot(build_snapshot(name, None, None, NOW), name)
    assert not widget._tiles[name].isHidden()
    assert "no new announcements" in widget._tiles[name].status.text()

def test_watch_display_expiry_elision_and_url(qtbot, monkeypatch):
    from aiusageclock import widget as widget_module

    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    forecast = "a very long synthetic forecast window " * 12
    source_url = "https://example.test/watch"
    watch = _parse_watch(watch_payload(
        {"type": "observed", "url": source_url},
        forecast_window=forecast,
        expires_at="2026-09-29T11:00:00Z",
    ))
    snapshot = build_snapshot("codex_resets", None, None, NOW, watch=watch)
    widget.update_snapshot(snapshot, "Codex Resets")
    tile = widget._tiles["codex_resets"]
    tile.set_available_width(320)
    row = tile._rows[0]
    assert row.label.text() == "Watch"
    assert "…" in row.reset.text()
    assert forecast in row.toolTip()
    assert "not an official announcement" in row.toolTip()
    assert not tile.open_btn.isHidden()
    opened = Mock()
    monkeypatch.setattr(widget_module.QDesktopServices, "openUrl", opened)
    tile.open_btn.click()
    assert opened.call_args.args[0].toString() == source_url
    no_url = _parse_watch(watch_payload())
    widget.update_snapshot(build_snapshot("codex_resets", None, None, NOW, watch=no_url), "Codex Resets")
    assert tile.open_btn.isHidden()
    expired = build_snapshot("codex_resets", None, None, NOW + timedelta(days=3), watch=watch)
    widget.update_snapshot(expired, "Codex Resets")
    assert tile._rows == []
    assert not tile.isHidden()
    assert "no new announcements" in tile.status.text()

def test_watch_null_chance_and_event_dismissal(qtbot):
    watch = _parse_watch(watch_payload(reset_chance_percent=None))
    snapshot = build_snapshot("codex_resets", event(), event().key, NOW, watch=watch)
    assert len(snapshot.metrics) == 1
    assert snapshot.metrics[0].label == "Watch · elevated · later this week (AI)"
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(snapshot, "Codex Resets")
    assert widget._tiles["codex_resets"]._rows[0].label.text() == "Watch"

def test_event_row_precedes_watch_and_event_url_wins(qtbot, monkeypatch):
    from aiusageclock import widget as widget_module

    watch = _parse_watch(watch_payload(
        {"type": "observed", "url": "https://example.test/watch"}
    ))
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(build_snapshot("codex_resets", event(), None, NOW, watch=watch),
                           "Codex Resets")
    tile = widget._tiles["codex_resets"]
    assert [row.label.text() for row in tile._rows] == ["Reset", "Watch"]
    opened = Mock()
    monkeypatch.setattr(widget_module.QDesktopServices, "openUrl", opened)
    tile.open_btn.click()
    assert opened.call_args.args[0].toString() == event().url

def test_reset_tile_uses_plain_text_and_escaped_tooltip(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    tile = widget.ensure_tile("codex_resets", "Codex Resets")
    event = ResetEvent("landed", "1", NOW, "<b>x</b>", '<a href="https://e.test">y</a>', None)
    tile.set_snapshot(build_snapshot("codex_resets", event, None, NOW))
    row = tile._rows[0]
    assert row.label.textFormat().name == "PlainText"
    assert row.reset.textFormat().name == "PlainText"
    assert row.reset.text() == "<b>x</b>, just now"
    assert "&lt;a href=&quot;https://e.test&quot;&gt;y&lt;/a&gt;" in row.toolTip()
    assert html.escape(event.detail, quote=True) in row.toolTip()
