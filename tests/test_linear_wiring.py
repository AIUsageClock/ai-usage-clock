from types import SimpleNamespace

import pytest

from aiusageclock import app as app_module
from aiusageclock import config as config_module
from aiusageclock import settings_dialog
from aiusageclock.app import App, _enabled_providers
from aiusageclock.config import ColorThresholds, Config, display_name_for_account
from aiusageclock.gauge import thresholds_for_provider
from aiusageclock.mcp_server import _configured_account_ids
from aiusageclock.menubar import PROVIDER_LABELS
from aiusageclock.models import SnapshotStatus, UsageMetric, UsageSnapshot
from aiusageclock.settings_dialog import SettingsDialog
from aiusageclock.widget import (
    PROVIDER_ORDER,
    UsageWidget,
    _COMPACT_RESET_WIDTH,
    _CompactMetric,
)

TEST_KEY = "lin_api_TESTKEY_do_not_persist_1234567890"


def _make_dialog(qtbot, monkeypatch, config=None, saved_key=None):
    monkeypatch.setattr(settings_dialog, "resolve_cli", lambda _: None)
    monkeypatch.setattr(settings_dialog, "set_start_at_login", lambda _: None)
    monkeypatch.setattr(settings_dialog, "get_linear_key", lambda: saved_key)
    dialog = SettingsDialog(config or Config())
    qtbot.addWidget(dialog)
    return dialog


def _tab_index(dialog, title):
    return next(
        i for i in range(dialog.tabs.count()) if dialog.tabs.tabText(i) == title
    )


def test_linear_config_defaults_and_legacy_json(tmp_path, monkeypatch):
    config = Config()
    assert config.providers.linear is False
    assert config.linear.issue_limit == 250
    config_file = tmp_path / "config.json"
    config_file.write_text('{"providers": {"claude": false}}', encoding="utf-8")
    monkeypatch.setattr(config_module, "config_path", lambda: config_file)
    legacy = Config.load()
    assert legacy.providers.linear is False
    assert legacy.linear.issue_limit == 250
    assert legacy.linear.colors == ColorThresholds()


def test_linear_threshold_label_name_and_order():
    config = Config()
    config.linear.colors = ColorThresholds(green_color="#123456")
    assert thresholds_for_provider(config, "linear") == config.linear.colors
    assert thresholds_for_provider(config, "linear").green_color == "#123456"
    assert PROVIDER_LABELS["linear"] == "Ln"
    assert PROVIDER_ORDER.index("linear") == PROVIDER_ORDER.index("antigravity") + 1
    assert display_name_for_account(config, "linear") == "Linear"


def test_enabled_providers_follow_linear_toggle():
    config = Config()
    config.providers.linear = True
    assert "linear" in _enabled_providers(config)
    config.providers.linear = False
    assert "linear" not in _enabled_providers(config)


def test_mcp_account_ids_follow_linear_toggle():
    config = Config()
    config.providers.linear = True
    assert "linear" in _configured_account_ids(config)
    config.providers.linear = False
    assert "linear" not in _configured_account_ids(config)


def test_app_builds_linear_provider_and_tile(monkeypatch):
    config = Config()
    config.providers.claude = False
    config.providers.codex = False
    config.providers.copilot = False
    config.providers.linear = True
    created = []
    ensured = []

    def fake_provider(cfg):
        created.append(cfg)
        return object()

    monkeypatch.setattr(app_module, "LinearProvider", fake_provider)
    app = App.__new__(App)
    app._config = config
    app._providers = {}
    app._snapshots = {}
    app._widget = SimpleNamespace(
        _tiles={},
        ensure_tile=lambda account_id, label: ensured.append((account_id, label)),
        remove_tile=lambda account_id: None,
    )

    app._build_providers()

    assert created == [config]
    assert "linear" in app._providers
    assert ensured == [("linear", "Linear")]


def test_app_skips_linear_provider_when_disabled(monkeypatch):
    config = Config()
    config.providers.claude = False
    config.providers.codex = False
    config.providers.copilot = False
    created = []
    monkeypatch.setattr(
        app_module, "LinearProvider", lambda cfg: created.append(cfg) or object()
    )
    app = App.__new__(App)
    app._config = config
    app._providers = {}
    app._snapshots = {}
    app._widget = SimpleNamespace(
        _tiles={},
        ensure_tile=lambda account_id, label: None,
        remove_tile=lambda account_id: None,
    )

    app._build_providers()

    assert created == []
    assert "linear" not in app._providers


def test_settings_dialog_linear_tab_and_show_provider(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    linear_index = _tab_index(dialog, "Linear")
    assert linear_index == 7
    dialog.show_provider("linear")
    assert dialog.tabs.currentIndex() == linear_index
    # The tab insertion must not break the shifted tabs' show_provider indexes.
    expected = {
        "claude": "Claude",
        "codex": "Codex",
        "opencode_go": "OpenCode",
        "copilot": "GitHub Copilot",
        "openrouter": "OpenRouter",
        "antigravity": "Antigravity",
        "codex_resets": "Reset alerts",
        "claude_resets": "Reset alerts",
    }
    for kind, title in expected.items():
        dialog.show_provider(kind)
        assert dialog.tabs.currentIndex() == _tab_index(dialog, title), kind


def test_settings_dialog_loads_and_applies_linear_options(qtbot, monkeypatch):
    config = Config()
    config.linear.issue_limit = 300
    dialog = _make_dialog(qtbot, monkeypatch, config)
    assert dialog.linear_issue_limit.value() == 300
    assert not dialog.linear_cb.isChecked()

    colors = ColorThresholds(green_color="#abcdef")
    dialog.linear_cb.setChecked(True)
    dialog.linear_issue_limit.setValue(500)
    dialog.linear_colors.colors = colors
    dialog.apply_to(config)

    assert config.providers.linear is True
    assert config.linear.issue_limit == 500
    assert config.linear.colors == colors


def test_settings_dialog_has_no_mcp_pause_policy_for_linear(qtbot, monkeypatch):
    config = Config()
    config.providers.linear = True
    dialog = _make_dialog(qtbot, monkeypatch, config)
    assert "linear" not in dialog.mcp_policy_controls


def test_accept_saves_entered_linear_key(qtbot, monkeypatch):
    calls = []
    stored = {"value": None}

    def setter(value):
        calls.append(value)
        stored["value"] = value

    monkeypatch.setattr(settings_dialog, "set_linear_key", setter)
    dialog = _make_dialog(qtbot, monkeypatch)
    monkeypatch.setattr(settings_dialog, "get_linear_key", lambda: stored["value"])
    dialog.linear_key_edit.setText(f"  {TEST_KEY}  ")

    dialog._accept()  # noqa: SLF001

    assert calls == [TEST_KEY]


def test_blank_linear_key_leaves_saved_key_alone(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(
        settings_dialog, "set_linear_key", lambda value: calls.append(value)
    )
    dialog = _make_dialog(qtbot, monkeypatch, saved_key="saved")
    assert "saved" in dialog.linear_key_edit.placeholderText()

    dialog._accept()  # noqa: SLF001

    assert calls == []


def test_clear_saved_linear_key_checkbox_removes_key(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(
        settings_dialog, "set_linear_key", lambda value: calls.append(value)
    )
    dialog = _make_dialog(qtbot, monkeypatch, saved_key="saved")
    # Once the setter has run, the "keychain" reads back as empty.
    monkeypatch.setattr(
        settings_dialog, "get_linear_key", lambda: None if calls else "saved"
    )
    dialog.clear_linear_key_cb.setChecked(True)

    dialog._accept()  # noqa: SLF001

    assert calls == [None]


def test_saved_config_json_does_not_contain_linear_key(qtbot, monkeypatch):
    stored = {"value": None}

    def setter(value):
        stored["value"] = value

    monkeypatch.setattr(settings_dialog, "set_linear_key", setter)
    config = Config()
    dialog = _make_dialog(qtbot, monkeypatch, config)
    monkeypatch.setattr(settings_dialog, "get_linear_key", lambda: stored["value"])
    dialog.linear_cb.setChecked(True)
    dialog.linear_key_edit.setText(TEST_KEY)

    dialog._accept()  # noqa: SLF001
    dialog.apply_to(config)
    config.save()

    assert stored["value"] == TEST_KEY
    text = config_module.config_path().read_text(encoding="utf-8")
    assert TEST_KEY not in text
    assert "lin_api_" not in text
    assert '"linear"' in text


def _linear_snapshot(metric):
    return UsageSnapshot(
        provider="linear", status=SnapshotStatus.OK, metrics=[metric]
    )


def test_collapsed_chip_shows_no_limit_for_paid_plan(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(_linear_snapshot(_paid_issues_metric()), "Linear")

    chip = widget._summary_chip("linear")  # noqa: SLF001

    assert chip.text() == "Linear no limit"


def test_collapsed_chip_shows_percent_for_free_plan(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    metric = UsageMetric(
        label="Issues",
        percent_used=49.2,
        resets_at=None,
        window=None,
        reset_label="123 / 250",
        note="123 / 250 issues (Free plan)",
    )
    widget.update_snapshot(_linear_snapshot(metric), "Linear")

    assert widget._summary_chip("linear").text() == "Linear 49%"  # noqa: SLF001


def _free_issues_metric():
    return UsageMetric(
        label="Issues",
        percent_used=51.2,
        resets_at=None,
        window=None,
        reset_label="128 / 250",
        note="128 / 250 issues (Free plan)",
    )


def _paid_issues_metric():
    return UsageMetric(
        label="Issues",
        percent_used=None,
        resets_at=None,
        window=None,
        reset_label="no limit",
        note="Paid plan: no issue limit",
    )


def test_linear_tile_supports_compact_collapse(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(_linear_snapshot(_free_issues_metric()), "Linear")

    tile = widget._tiles["linear"]  # noqa: SLF001

    assert tile._supports_compact_collapse()  # noqa: SLF001
    assert not tile.expand_btn.isHidden()
    assert [row.label.text() for row in tile._rows] == ["Issues"]  # noqa: SLF001


def test_linear_free_plan_collapsed_tile_shows_issues_percent(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(_linear_snapshot(_free_issues_metric()), "Linear")
    tile = widget._tiles["linear"]  # noqa: SLF001

    tile.set_expanded(False)

    assert tile._rows == []  # noqa: SLF001
    assert not tile._compact_summary.isHidden()  # noqa: SLF001
    assert [m.code.text() for m in tile._compact_metrics] == ["I"]  # noqa: SLF001
    assert [m.pct.text() for m in tile._compact_metrics] == ["51%"]  # noqa: SLF001
    assert tile._compact_metrics[0].bar.value() == 51  # noqa: SLF001
    assert tile._compact_metrics[0].reset.text() == "128 / 250"  # noqa: SLF001


def test_linear_paid_plan_collapsed_tile_is_not_blank(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(_linear_snapshot(_paid_issues_metric()), "Linear")
    tile = widget._tiles["linear"]  # noqa: SLF001

    assert not tile.expand_btn.isHidden()
    tile.set_expanded(False)

    assert not tile._compact_summary.isHidden()  # noqa: SLF001
    assert len(tile._compact_metrics) == 1  # noqa: SLF001
    item = tile._compact_metrics[0]  # noqa: SLF001
    assert item.code.text() == "I"
    assert item.pct.text() == "--"
    assert item.reset.text() == "no limit"
    assert item.reset.minimumWidth() >= item.reset.fontMetrics().horizontalAdvance("no limit")


def test_compact_metric_fit_reset_widens_then_restores_default_width(qtbot):
    item = _CompactMetric()
    qtbot.addWidget(item)

    item.set_metric(_paid_issues_metric(), fit_reset=True)
    widened = item.reset.minimumWidth()
    item.set_metric(_paid_issues_metric(), fit_reset=False)

    assert widened > _COMPACT_RESET_WIDTH
    assert item.reset.minimumWidth() == item.reset.maximumWidth()
    assert item.reset.minimumWidth() == _COMPACT_RESET_WIDTH


def test_linear_tile_reexpands_to_full_row(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(_linear_snapshot(_free_issues_metric()), "Linear")
    tile = widget._tiles["linear"]  # noqa: SLF001
    tile.set_expanded(False)

    tile.set_expanded(True)

    assert tile._compact_summary.isHidden()  # noqa: SLF001
    assert [row.label.text() for row in tile._rows] == ["Issues"]  # noqa: SLF001


def test_configured_collapsed_linear_tile_starts_compact(qtbot):
    config = Config()
    config.collapsed_tiles = ["linear"]
    widget = UsageWidget(config)
    qtbot.addWidget(widget)

    widget.update_snapshot(_linear_snapshot(_free_issues_metric()), "Linear")

    tile = widget._tiles["linear"]  # noqa: SLF001
    assert tile._rows == []  # noqa: SLF001
    assert not tile._compact_summary.isHidden()  # noqa: SLF001


def test_collapsed_chip_other_providers_still_show_dashes_without_percent(qtbot):
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    metric = UsageMetric(
        label="Session",
        percent_used=None,
        resets_at=None,
        window=None,
        reset_label="whatever",
    )
    widget.update_snapshot(
        UsageSnapshot(provider="copilot", status=SnapshotStatus.OK, metrics=[metric]),
        "Copilot",
    )

    assert widget._summary_chip("copilot").text() == "Copilot --"  # noqa: SLF001
