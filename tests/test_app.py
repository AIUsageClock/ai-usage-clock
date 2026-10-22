from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from aiusageclock import app as app_module
from aiusageclock.app import (
    App,
    _acquire_instance_lock,
    _adaptive_refresh_minutes,
    _enabled_providers,
    _preserve_error_metrics,
    _refresh_provider_order,
    _raw_summary,
    _tray_tooltip,
    _truncate_utf16,
)
from aiusageclock.config import BrowserAccount, Config
from aiusageclock.models import SnapshotStatus, UsageMetric, UsageSnapshot
from aiusageclock.widget import UsageWidget, _compact_metric_code, tray_metric_code


class _Timer:
    def __init__(self):
        self.stopped = False
        self.started_ms: int | None = None
        self.active = False
        self.remaining_ms = 0

    def stop(self):
        self.stopped = True
        self.active = False

    def start(self, ms: int):
        self.started_ms = ms
        self.remaining_ms = ms
        self.active = True

    def isActive(self):
        return self.active

    def remainingTime(self):
        return self.remaining_ms


class _Widget:
    def __init__(self):
        self.loading_calls = []
        self.refreshing = []
        self.refresh_state_calls = []
        self.visible = True

    def set_refreshing(self, refreshing):
        self.refreshing.append(refreshing)

    def mark_loading(self, providers):
        self.loading_calls.append(providers)

    def set_refresh_state(self, *, active, minutes, next_at=None):
        self.refresh_state_calls.append(
            {"active": active, "minutes": minutes, "next_at": next_at}
        )

    def isVisible(self):
        return self.visible


class _Dialog:
    def __init__(self):
        self.calls = []

    def isMinimized(self):
        return False

    def show(self):
        self.calls.append("show")

    def showNormal(self):
        self.calls.append("showNormal")

    def raise_(self):
        self.calls.append("raise")

    def activateWindow(self):
        self.calls.append("activate")


def _refresh_app_stub() -> App:
    app = App.__new__(App)
    app._providers = {"claude": object(), "codex": object()}  # noqa: SLF001
    app._inflight = set()  # noqa: SLF001
    app._refresh_queue = []  # noqa: SLF001
    app._active_until = datetime.now() - timedelta(minutes=1)  # noqa: SLF001
    app._unchanged_cycles = 3  # noqa: SLF001
    app._timer = _Timer()  # noqa: SLF001
    app._current_refresh_manual = False  # noqa: SLF001
    app._cycle_signatures = {"old": ()}  # noqa: SLF001
    app._widget = _Widget()  # noqa: SLF001
    app._start_next_refresh = lambda: None  # noqa: SLF001
    app._config = SimpleNamespace()  # noqa: SLF001
    return app


def test_adaptive_refresh_uses_active_interval_when_active():
    assert _adaptive_refresh_minutes(
        active=True,
        active_minutes=5,
        unchanged_cycles=10,
        max_minutes=15,
    ) == 5


def test_adaptive_refresh_backs_off_when_unchanged():
    assert _adaptive_refresh_minutes(
        active=False,
        active_minutes=5,
        unchanged_cycles=0,
        max_minutes=60,
    ) == 5
    assert _adaptive_refresh_minutes(
        active=False,
        active_minutes=5,
        unchanged_cycles=1,
        max_minutes=60,
    ) == 10
    assert _adaptive_refresh_minutes(
        active=False,
        active_minutes=5,
        unchanged_cycles=3,
        max_minutes=60,
    ) == 40


def test_adaptive_refresh_caps_at_configured_max():
    assert _adaptive_refresh_minutes(
        active=False,
        active_minutes=5,
        unchanged_cycles=8,
        max_minutes=15,
    ) == 15


def test_adaptive_refresh_respects_short_user_interval():
    assert _adaptive_refresh_minutes(
        active=True,
        active_minutes=5,
        unchanged_cycles=0,
        max_minutes=2,
    ) == 2


def test_adaptive_refresh_uses_configured_active_rate():
    assert _adaptive_refresh_minutes(
        active=True,
        active_minutes=1,
        unchanged_cycles=0,
        max_minutes=60,
    ) == 1
    assert _adaptive_refresh_minutes(
        active=False,
        active_minutes=15,
        unchanged_cycles=1,
        max_minutes=120,
    ) == 30


def test_manual_refresh_marks_tiles_loading():
    app = _refresh_app_stub()

    app.refresh_now(manual=True)

    assert app._widget.loading_calls == [  # noqa: SLF001
        {"claude": "Claude", "codex": "Codex"}
    ]
    assert app._refresh_queue == ["claude", "codex"]  # noqa: SLF001
    assert app._unchanged_cycles == 0  # noqa: SLF001


def test_scheduled_refresh_keeps_existing_tiles_visible():
    app = _refresh_app_stub()

    app.refresh_now(manual=False)

    assert app._widget.loading_calls == []  # noqa: SLF001
    assert app._refresh_queue == ["claude", "codex"]  # noqa: SLF001
    assert app._unchanged_cycles == 3  # noqa: SLF001


def test_refresh_order_prioritizes_openrouter_without_reordering_tiles():
    providers = {
        "claude": object(),
        "codex": object(),
        "copilot": object(),
        "openrouter": object(),
    }

    assert _refresh_provider_order(providers) == [
        "openrouter",
        "claude",
        "codex",
        "copilot",
    ]


def test_enabled_providers_includes_enabled_browser_accounts():
    config = Config()
    config.browser_accounts.append(
        BrowserAccount(id="claude-team", kind="claude", name="Team", enabled=True)
    )
    config.providers.codex = False

    assert _enabled_providers(config) == (
        "claude",
        "claude-team",
        "copilot",
    )




def test_enabled_providers_respects_explicitly_empty_browser_accounts():
    config = Config(browser_accounts=[])
    config.providers.copilot = False

    assert _enabled_providers(config) == ()


def test_enabled_providers_includes_multiple_opencode_accounts_when_enabled():
    config = Config()
    config.browser_accounts.append(
        BrowserAccount(
            id="opencode_go-work",
            kind="opencode_go",
            name="Work",
        )
    )
    config.providers.opencode_go = True

    assert _enabled_providers(config) == (
        "claude",
        "codex",
        "opencode_go",
        "opencode_go-work",
        "copilot",
    )


def test_build_providers_creates_one_provider_per_opencode_account(monkeypatch):
    config = Config(
        browser_accounts=[
            BrowserAccount(
                id="opencode_go",
                kind="opencode_go",
            ),
            BrowserAccount(
                id="opencode_go-work",
                kind="opencode_go",
                name="Work",
            ),
        ]
    )
    config.providers.claude = False
    config.providers.codex = False
    config.providers.copilot = False
    config.providers.openrouter = False
    config.providers.opencode_go = True
    created = []
    ensured = []

    def fake_opencode_provider(config, parent=None, account_id="opencode_go"):
        created.append((config, parent, account_id))
        return SimpleNamespace(account_id=account_id)

    monkeypatch.setattr(app_module, "OpenCodeGoProvider", fake_opencode_provider)
    app = App.__new__(App)
    app._config = config  # noqa: SLF001
    app._providers = {}  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        _tiles={},
        ensure_tile=lambda account_id, name: ensured.append((account_id, name)),
        remove_tile=lambda account_id: None,
    )

    app._build_providers()  # noqa: SLF001

    assert list(app._providers) == ["opencode_go", "opencode_go-work"]  # noqa: SLF001
    assert [call[2] for call in created] == ["opencode_go", "opencode_go-work"]
    assert ensured == [
        ("opencode_go", "OpenCode"),
        ("opencode_go-work", "OpenCode (Work)"),
    ]


def test_build_providers_passes_per_account_fable_toggle(monkeypatch):
    config = Config(
        browser_accounts=[
            BrowserAccount(id="claude", kind="claude", show_fable=True),
            BrowserAccount(id="claude-b", kind="claude", name="B", show_fable=False),
        ]
    )
    config.providers.claude = True
    config.providers.codex = False
    config.providers.copilot = False
    config.providers.openrouter = False
    config.providers.opencode_go = False
    created = []

    def fake_claude_provider(parent=None, account_id="claude", show_fable=False):
        created.append((account_id, show_fable))
        return SimpleNamespace(account_id=account_id)

    monkeypatch.setattr(app_module, "ClaudeProvider", fake_claude_provider)
    app = App.__new__(App)
    app._config = config  # noqa: SLF001
    app._providers = {}  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        _tiles={},
        ensure_tile=lambda account_id, name: None,
        remove_tile=lambda account_id: None,
    )

    app._build_providers()  # noqa: SLF001

    assert created == [("claude", True), ("claude-b", False)]


def test_opencode_auth_action_opens_account_key_settings():
    draft = BrowserAccount(
        id="opencode_go-work",
        kind="opencode_go",
        name="Work",
    )
    captured = []
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._settings_dialog = SimpleNamespace(  # noqa: SLF001
        draft_browser_account=lambda account_id: (
            draft if account_id == draft.id else None
        ),
        show_provider=lambda kind, account_id: captured.append((kind, account_id)),
    )
    app.open_settings = lambda: None

    app.open_login("opencode_go-work")

    assert captured == [("opencode_go", "opencode_go-work")]


def test_login_refreshes_immediately_when_embedded_session_changed(monkeypatch):
    refreshed = []
    timers = []

    class FakeLoginWindow:
        session_may_have_changed = True

        def __init__(self, *args, **kwargs):
            return None

        def exec(self):
            return False

    monkeypatch.setattr(app_module, "LoginWindow", FakeLoginWindow)
    monkeypatch.setattr(app_module.webengine, "is_available", lambda: True)
    monkeypatch.setattr(
        app_module.QTimer,
        "singleShot",
        lambda delay, callback: timers.append((delay, callback)),
    )
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._settings_dialog = None  # noqa: SLF001
    app._cleared_sessions = {"claude"}  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        suspend_always_on_top=lambda: None,
        restore_always_on_top=lambda: None,
    )
    app.refresh_provider = refreshed.append

    app.open_login("claude")

    assert app._cleared_sessions == set()  # noqa: SLF001
    assert timers[0][0] == 750
    timers[0][1]()
    assert refreshed == ["claude"]

def test_widget_activation_raises_open_settings_dialog():
    app = App.__new__(App)
    dialog = _Dialog()
    app._settings_dialog = dialog  # noqa: SLF001

    app._on_widget_activated()  # noqa: SLF001

    assert dialog.calls == ["show", "raise", "activate"]


def test_app_menu_controls_widget_view_and_is_available_on_widget(qtbot):
    config = Config()
    widget = UsageWidget(config)
    qtbot.addWidget(widget)
    app = App.__new__(App)
    app._config = config  # noqa: SLF001
    app._widget = widget  # noqa: SLF001
    app._ui_mode = "floating_widget"  # noqa: SLF001
    app._toggle_widget = lambda: None  # noqa: SLF001
    app.refresh_now = lambda *, manual: None
    app.open_settings = lambda: None

    menu = app._build_app_menu()  # noqa: SLF001
    qtbot.addWidget(menu)
    app._app_menu = menu  # noqa: SLF001
    app._install_widget_context_menu()  # noqa: SLF001

    assert widget.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert app._compact_view_action.isChecked() is False  # noqa: SLF001
    assert app._show_header_action.isChecked() is True  # noqa: SLF001
    assert app._always_on_top_action.isChecked() is True  # noqa: SLF001
    assert app._snap_to_corners_action.isChecked() is True  # noqa: SLF001

    app._compact_view_action.trigger()  # noqa: SLF001
    app._show_header_action.trigger()  # noqa: SLF001
    app._always_on_top_action.trigger()  # noqa: SLF001
    app._snap_to_corners_action.trigger()  # noqa: SLF001

    assert config.window.collapsed is True
    assert config.window.show_header is False
    assert config.window.always_on_top is False
    assert config.window.snap_to_corners is False

    widget.set_collapsed(False)
    widget.set_header_visible(True)
    app._sync_app_menu_actions()  # noqa: SLF001
    assert app._compact_view_action.isChecked() is False  # noqa: SLF001
    assert app._show_header_action.isChecked() is True  # noqa: SLF001


def test_settings_leaves_widget_topmost_state_unchanged(monkeypatch):
    lifecycle = []

    class _Signal:
        def connect(self, callback):
            self.callback = callback

    class _SettingsDialog(_Dialog):
        def __init__(self, config, parent=None, local_usage_service=None):
            super().__init__()
            self.sign_in_clicked = _Signal()
            self.paste_cookie_clicked = _Signal()
            self.clear_sign_in_clicked = _Signal()
            self.finished = _Signal()

        def setModal(self, modal):
            pass

        def setWindowModality(self, modality):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(app_module, "SettingsDialog", _SettingsDialog)
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._settings_dialog = None  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        suspend_always_on_top=lambda: lifecycle.append("suspend"),
        restore_always_on_top=lambda: lifecycle.append("restore"),
    )

    app.open_settings()

    assert lifecycle == []
    dialog = app._settings_dialog  # noqa: SLF001
    dialog.finished.callback(0)
    assert lifecycle == []
    assert app._settings_dialog is None  # noqa: SLF001


def test_clear_sign_in_clears_session_and_updates_tile(monkeypatch):
    cleared = []
    rendered = []
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._settings_dialog = object()  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        update_snapshot=lambda snapshot, name: rendered.append((snapshot, name))
    )
    app._providers = {"claude": object()}  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    app._cleared_sessions = set()  # noqa: SLF001
    app._update_tray = lambda: None  # noqa: SLF001

    monkeypatch.setattr(
        app_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        app_module,
        "clear_browser_session",
        lambda account_id: cleared.append(account_id),
    )

    app.clear_sign_in("claude")

    assert cleared == ["claude"]
    assert app._cleared_sessions == {"claude"}  # noqa: SLF001
    snapshot, display_name = rendered[0]
    assert snapshot.status == SnapshotStatus.AUTH_REQUIRED
    assert snapshot.error == "Sign-in cleared from AI Usage Clock."
    assert display_name == "Claude"


def test_authenticated_refresh_cannot_restore_a_cleared_session():
    rendered = []
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._cleared_sessions = {"claude"}  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    app._cycle_signatures = {}  # noqa: SLF001
    app._inflight = {"claude"}  # noqa: SLF001
    app._history = SimpleNamespace(record_snapshot=lambda snapshot: None)  # noqa: SLF001
    app._ratio = SimpleNamespace(  # noqa: SLF001
        record_snapshot=lambda snapshot: None,
        display_estimate=lambda provider: None,
        current_estimate=lambda provider: None,
    )
    app._ratio_recent = lambda provider: []  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        update_snapshot=lambda snapshot, name: rendered.append(snapshot),
        set_ratio=lambda *args: None,
        set_refreshing=lambda refreshing: None,
    )
    app._refresh_queue = []  # noqa: SLF001
    app._cycle_changed = lambda: False  # noqa: SLF001
    app._current_refresh_manual = True  # noqa: SLF001
    app._last_cycle_signatures = None  # noqa: SLF001
    app._update_tray = lambda: None  # noqa: SLF001
    app._schedule_next_refresh = lambda: None  # noqa: SLF001

    app._on_snapshot(  # noqa: SLF001
        UsageSnapshot(provider="claude", status=SnapshotStatus.OK)
    )

    assert app._snapshots["claude"].status == SnapshotStatus.AUTH_REQUIRED  # noqa: SLF001
    assert rendered[0].status == SnapshotStatus.AUTH_REQUIRED




def test_tile_expanded_changed_persists_browser_tile_collapsed_state():
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001

    app._on_tile_expanded_changed("claude", False)  # noqa: SLF001

    assert app._config.collapsed_tiles == ["claude"]
    assert app._config.expanded_tiles == []

    app._on_tile_expanded_changed("claude", True)  # noqa: SLF001

    assert app._config.collapsed_tiles == []


def test_tile_expanded_changed_persists_linear_tile_collapsed_state():
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001

    app._on_tile_expanded_changed("linear", False)  # noqa: SLF001

    assert app._config.collapsed_tiles == ["linear"]
    assert app._config.expanded_tiles == []

    app._on_tile_expanded_changed("linear", True)  # noqa: SLF001

    assert app._config.collapsed_tiles == []


def _tray_snapshots(pct: float = 12.0) -> dict[str, UsageSnapshot]:
    def snap(provider, labels):
        return UsageSnapshot(
            provider=provider,
            status=SnapshotStatus.OK,
            metrics=[UsageMetric(label, pct, None) for label in labels],
        )

    return {
        "claude": snap("claude", ["Session", "Weekly", "Fable"]),
        "codex": snap("codex", ["Session"]),
        "antigravity": snap(
            "antigravity",
            [
                "Gemini 5h",
                "Gemini weekly",
                "Claude+GPT 5h",
                "Claude+GPT weekly",
                "Argon weekly",
            ],
        ),
        "linear": snap("linear", ["Issues"]),
    }


_TRAY_PROVIDERS = ("claude", "codex", "antigravity", "linear")


def test_tray_tooltip_common_setup_fits_and_has_every_provider_code():
    tooltip = _tray_tooltip(Config(), _tray_snapshots(), _TRAY_PROVIDERS)

    assert len(tooltip) <= 127
    assert tooltip.splitlines() == [
        f"{app_module.PRODUCT_NAME} {app_module.__version__}",
        "Claude S12% W12% F12%",
        "Codex S12%",
        "Antigravity G5 12% GW12% C5 12% CW12% AW12%",
        "Linear I12%",
    ]


def test_tray_tooltip_status_lines_are_short():
    snapshots = _tray_snapshots()
    snapshots["claude"] = UsageSnapshot(
        provider="claude", status=SnapshotStatus.AUTH_REQUIRED
    )
    snapshots["codex"] = UsageSnapshot(provider="codex", status=SnapshotStatus.ERROR)

    lines = _tray_tooltip(Config(), snapshots, _TRAY_PROVIDERS).splitlines()

    assert "Claude !setup" in lines
    assert "Codex !error" in lines


def test_tray_tooltip_shows_no_limit_for_paid_linear_plan():
    snapshots = _tray_snapshots()
    snapshots["linear"] = UsageSnapshot(
        provider="linear",
        status=SnapshotStatus.OK,
        metrics=[UsageMetric("Issues", None, None, reset_label="no limit")],
    )

    lines = _tray_tooltip(Config(), snapshots, _TRAY_PROVIDERS).splitlines()

    assert lines[-1] == "Linear no limit"


def test_tray_tooltip_drops_version_before_dropping_providers():
    snapshots = _tray_snapshots(100.0)
    full = _tray_tooltip(Config(), snapshots, _TRAY_PROVIDERS, limit=10_000)
    assert "\n…" not in full
    # Exactly the full text minus the version: only the version has to go.
    limit = len(full) - len(f" {app_module.__version__}")

    tooltip = _tray_tooltip(Config(), snapshots, _TRAY_PROVIDERS, limit=limit)

    assert len(tooltip) <= limit
    assert app_module.__version__ not in tooltip
    assert not tooltip.endswith("…")
    assert tooltip.splitlines()[-1].startswith("Linear")


def test_tray_tooltip_truncates_from_the_end_with_ellipsis():
    snapshots = _tray_snapshots(100.0)

    tooltip = _tray_tooltip(Config(), snapshots, _TRAY_PROVIDERS, limit=60)

    assert len(tooltip) <= 60
    assert tooltip.endswith("…")
    assert tooltip.splitlines()[0] == app_module.PRODUCT_NAME
    assert "Claude S100%" in tooltip
    assert "Linear" not in tooltip


def test_tray_tooltip_very_long_account_name_keeps_later_providers():
    config = Config()
    snapshots = _tray_snapshots()
    config.browser_accounts.append(
        BrowserAccount(id="claude-long", kind="claude", name="X" * 300)
    )
    snapshots["claude-long"] = snapshots["claude"]
    providers = ("claude-long", "codex", "antigravity", "linear")

    tooltip = _tray_tooltip(config, snapshots, providers)

    lines = tooltip.splitlines()
    assert app_module._utf16_len(tooltip) <= 127  # noqa: SLF001
    assert lines[0].startswith(app_module.PRODUCT_NAME)
    assert lines[1].startswith("Claude (XXXXX")
    assert "…" in lines[1].split(" S")[0]
    assert [line.split(" ")[0] for line in lines[2:]] == [
        "Codex",
        "Antigravity",
        "Linear",
    ]
    assert not tooltip.endswith("…")


def test_tray_tooltip_multi_account_setup_keeps_every_provider():
    # Two Claude + two Codex accounts (default name "Account 2") with
    # Antigravity and Linear. Uncapped names ("Claude (Account 2)") push Linear
    # out of 127 units; capped names keep all six.
    config = Config()
    config.browser_accounts += [
        BrowserAccount(id="claude-2", kind="claude", name="Account 2"),
        BrowserAccount(id="codex-2", kind="codex", name="Account 2"),
    ]

    def snap(provider, labels):
        return UsageSnapshot(
            provider=provider,
            status=SnapshotStatus.OK,
            metrics=[UsageMetric(label, 12.0, None) for label in labels],
        )

    snapshots = {
        "claude": snap("claude", ["Session", "Weekly"]),
        "claude-2": snap("claude", ["Session", "Weekly"]),
        "codex": snap("codex", ["Session"]),
        "codex-2": snap("codex", ["Session"]),
        "antigravity": snap("antigravity", ["Gemini 5h", "Gemini weekly"]),
        "linear": snap("linear", ["Issues"]),
    }
    providers = tuple(snapshots)

    tooltip = _tray_tooltip(config, snapshots, providers)

    lines = tooltip.splitlines()
    assert app_module._utf16_len(tooltip) <= 127  # noqa: SLF001
    assert not tooltip.endswith("…")
    assert len(lines) == 1 + len(providers)
    assert [line.split(" ")[0] for line in lines[1:]] == [
        "Claude",
        "Claude",
        "Codex",
        "Codex",
        "Antigravity",
        "Linear",
    ]


def test_tray_tooltip_drops_whole_lines_down_to_the_minimum_limit():
    # Every line is short, so dropping lines always reaches "name + …".
    tooltip = _tray_tooltip(
        Config(), _tray_snapshots(100.0), _TRAY_PROVIDERS, limit=16
    )

    assert tooltip == f"{app_module.PRODUCT_NAME}\n…"


def test_tray_tooltip_antigravity_duplicate_labels_keep_higher_usage():
    snapshots = _tray_snapshots()
    snapshots["antigravity"] = UsageSnapshot(
        provider="antigravity",
        status=SnapshotStatus.OK,
        metrics=[
            UsageMetric("Gemini weekly", 10.0, None),
            UsageMetric("Gemini weekly", 40.0, None),
            UsageMetric("Gemini weekly", 25.0, None),
        ],
    )

    lines = _tray_tooltip(Config(), snapshots, _TRAY_PROVIDERS).splitlines()

    assert "Antigravity GW40%" in lines


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("Claude", 14, "Claude"),
        ("Claude (Account 2)", 14, "Claude (Accou…"),
        ("X" * 300, 14, "X" * 13 + "…"),
        # An astral character is 2 UTF-16 units and is never split.
        ("a" + "\U0001f600" * 10, 6, "a\U0001f600\U0001f600…"),
    ],
)
def test_truncate_utf16(text, limit, expected):
    result = _truncate_utf16(text, limit)

    assert result == expected
    assert app_module._utf16_len(result) <= limit  # noqa: SLF001


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Session", "S"),
        ("Weekly", "W"),
        ("Fable", "F"),
        ("Rolling", "R"),
        ("Monthly", "M"),
        ("Issues", "I"),
        ("Premium requests", "P"),
        ("", "?"),
        ("Gemini 5h", "G5"),
        ("Gemini weekly", "GW"),
        ("Claude+GPT 5h", "C5"),
        ("Claude+GPT weekly", "CW"),
        ("Argon weekly", "AW"),
    ],
)
def test_tray_metric_code(label, expected):
    assert tray_metric_code(label) == expected


@pytest.mark.parametrize(
    "label", ["Gemini 5h", "Gemini weekly", "Argon weekly", "Plan weekly"]
)
def test_compact_metric_code_stays_single_character(label):
    assert len(_compact_metric_code(label)) == 1


def test_tile_expanded_changed_keeps_openrouter_model_expansion_state():
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001

    app._on_tile_expanded_changed("openrouter", True)  # noqa: SLF001

    assert app._config.expanded_tiles == ["openrouter"]
    assert app._config.collapsed_tiles == []

def test_raw_summary_includes_sanitized_payload_details():
    summary = _raw_summary(
        {
            "session": None,
            "weekly": {
                "raw": "x" * 400,
                "percent": None,
            },
            "items": [{"a": 1}, {"b": 2}, {"c": 3}, {"d": 4}, {"e": 5}, {"f": 6}],
        }
    )

    assert '"session": null' in summary
    assert '"percent": null' in summary
    assert "xxx" in summary
    assert "more" in summary
    assert len(summary) < 700


def test_error_snapshot_preserves_previous_metrics():
    previous = UsageSnapshot(
        provider="claude",
        status=SnapshotStatus.OK,
        metrics=[UsageMetric("Session", 42.0, None)],
    )
    current = UsageSnapshot(
        provider="claude",
        status=SnapshotStatus.ERROR,
        error="extractor retry limit exceeded",
    )

    merged = _preserve_error_metrics(current, previous)

    assert merged.status == SnapshotStatus.ERROR
    assert merged.error == "extractor retry limit exceeded"
    assert [(m.label, m.percent_used) for m in merged.metrics] == [("Session", 42.0)]


def test_mcp_cache_sync_is_inert_when_disabled(monkeypatch):
    app = App.__new__(App)
    app._config = Config(mcp_enabled=False)  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    calls = []
    monkeypatch.setattr(app_module, "invalidate_usage_cache", lambda: calls.append("remove"))
    monkeypatch.setattr(app_module, "write_usage_cache", lambda snapshots: calls.append("write"))

    app._sync_usage_cache()  # noqa: SLF001

    assert calls == ["remove"]


def test_mcp_cache_sync_publishes_only_when_enabled(monkeypatch):
    app = App.__new__(App)
    app._config = Config(mcp_enabled=True)  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    calls = []
    monkeypatch.setattr(app_module, "invalidate_usage_cache", lambda: calls.append("remove"))
    monkeypatch.setattr(app_module, "write_usage_cache", lambda snapshots: calls.append(snapshots))

    app._sync_usage_cache()  # noqa: SLF001

    assert calls == [{}]


def test_repeated_error_snapshot_keeps_stale_metrics():
    previous = UsageSnapshot(
        provider="claude",
        status=SnapshotStatus.ERROR,
        error="previous failure",
        metrics=[UsageMetric("Session", 42.0, None)],
    )
    current = UsageSnapshot(
        provider="claude",
        status=SnapshotStatus.ERROR,
        error="extractor retry limit exceeded",
    )

    merged = _preserve_error_metrics(current, previous)

    assert [(m.label, m.percent_used) for m in merged.metrics] == [("Session", 42.0)]


def test_codex_error_keeps_work_stale_weekly_and_success_replaces_it():
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._cleared_sessions = set()  # noqa: SLF001
    app._snapshots = {  # noqa: SLF001
        "codex-home": UsageSnapshot(
            provider="codex-home", status=SnapshotStatus.OK,
            metrics=[UsageMetric("Weekly", 11.0)],
        ),
        "codex-work": UsageSnapshot(
            provider="codex-work", status=SnapshotStatus.OK,
            metrics=[UsageMetric("Weekly", 22.0)],
        ),
    }
    app._cycle_signatures = {}  # noqa: SLF001
    app._inflight = set()  # noqa: SLF001
    app._history = SimpleNamespace(record_snapshot=lambda _snapshot: [])  # noqa: SLF001
    app._ratio = SimpleNamespace(  # noqa: SLF001
        record_snapshot=lambda _snapshot: None,
        display_estimate=lambda _provider: None,
        current_estimate=lambda _provider: None,
    )
    app._ratio_recent = lambda _provider: []  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        update_snapshot=lambda *_args: None,
        set_ratio=lambda *_args: None,
        set_refreshing=lambda _refreshing: None,
    )
    app._local_usage_on_snapshot = lambda _snapshot, _closed: None  # noqa: SLF001
    app._refresh_queue = []  # noqa: SLF001
    app._current_refresh_manual = True  # noqa: SLF001
    app._unchanged_cycles = 0  # noqa: SLF001
    app._cycle_changed = lambda: False  # noqa: SLF001
    app._update_tray = lambda: None  # noqa: SLF001
    app._schedule_next_refresh = lambda: None  # noqa: SLF001

    app._on_snapshot(  # noqa: SLF001
        UsageSnapshot(
            provider="codex-work", status=SnapshotStatus.ERROR,
            error="Codex usage page only rendered part of the usage cards; retrying.",
        )
    )
    work = app._snapshots["codex-work"]  # noqa: SLF001
    assert work.status == SnapshotStatus.ERROR
    assert work.error == "Codex usage page only rendered part of the usage cards; retrying."
    assert [(metric.label, metric.percent_used) for metric in work.metrics] == [
        ("Weekly", 22.0)
    ]
    assert app._snapshots["codex-home"].metrics[0].percent_used == 11.0  # noqa: SLF001

    app._current_refresh_manual = True  # noqa: SLF001
    app._on_snapshot(  # noqa: SLF001
        UsageSnapshot(
            provider="codex-work", status=SnapshotStatus.OK,
            metrics=[UsageMetric("Weekly", 37.0)],
        )
    )
    work = app._snapshots["codex-work"]  # noqa: SLF001
    assert work.status == SnapshotStatus.OK
    assert [(metric.label, metric.percent_used) for metric in work.metrics] == [
        ("Weekly", 37.0)
    ]
    assert app._snapshots["codex-home"].metrics[0].percent_used == 11.0  # noqa: SLF001


def test_lifecycle_context_includes_refresh_state():
    app = App.__new__(App)
    app._started_at = datetime.now() - timedelta(seconds=90)  # noqa: SLF001
    app._ui_mode = "floating_widget"  # noqa: SLF001
    app._widget = _Widget()  # noqa: SLF001
    app._config = SimpleNamespace(  # noqa: SLF001
        providers=SimpleNamespace(
            claude=True, codex=False, copilot=True, openrouter=False
        )
    )
    app._inflight = {"claude"}  # noqa: SLF001
    app._refresh_queue = ["copilot"]  # noqa: SLF001
    app._unchanged_cycles = 2  # noqa: SLF001
    app._timer = _Timer()  # noqa: SLF001
    app._timer.start(125_000)  # noqa: SLF001

    context = app._lifecycle_context()  # noqa: SLF001

    assert context["uptime_s"] >= 89
    assert context["ui_mode"] == "floating_widget"
    assert context["widget_visible"] is True
    assert context["providers"] == "claude,copilot"
    assert context["inflight"] == "claude"
    assert context["queue"] == "copilot"
    assert context["next_refresh_s"] == 125
    assert context["unchanged_cycles"] == 2


def test_instance_lock_prevents_second_running_copy(tmp_path, monkeypatch):
    monkeypatch.setattr("aiusageclock.app.app_data_dir", lambda: tmp_path)

    first = _acquire_instance_lock()
    assert first is not None
    try:
        assert _acquire_instance_lock() is None
    finally:
        first.unlock()


def _schedule_app_stub() -> App:
    app = App.__new__(App)
    app._inflight = set()  # noqa: SLF001
    app._refresh_queue = []  # noqa: SLF001
    app._active_until = datetime.now() - timedelta(minutes=1)  # noqa: SLF001
    app._unchanged_cycles = 5  # noqa: SLF001
    app._timer = _Timer()  # noqa: SLF001
    app._widget = _Widget()  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    app._config = SimpleNamespace(
        active_refresh_interval_minutes=5,
        refresh_interval_minutes=60,
    )
    return app


def test_schedule_pulls_refresh_forward_to_known_reset():
    app = _schedule_app_stub()
    soon = datetime.now() + timedelta(minutes=10)
    app._snapshots = {  # noqa: SLF001
        "claude": UsageSnapshot(
            provider="claude",
            status=SnapshotStatus.OK,
            metrics=[
                UsageMetric(label="Session", percent_used=80.0, resets_at=soon),
            ],
        ),
    }

    app._schedule_next_refresh()  # noqa: SLF001

    # Default backoff would be way longer; reset+grace is ~11 minutes.
    assert app._timer.started_ms is not None  # noqa: SLF001
    scheduled_minutes = app._timer.started_ms / 60_000  # noqa: SLF001
    assert 9 <= scheduled_minutes <= 13


def test_schedule_ignores_unused_metric_resets():
    app = _schedule_app_stub()
    soon = datetime.now() + timedelta(minutes=10)
    app._snapshots = {  # noqa: SLF001
        # 0% used — resetting changes nothing visible.
        "claude": UsageSnapshot(
            provider="claude",
            status=SnapshotStatus.OK,
            metrics=[
                UsageMetric(label="Session", percent_used=0.0, resets_at=soon),
            ],
        ),
    }

    app._schedule_next_refresh()  # noqa: SLF001

    assert app._timer.started_ms is not None  # noqa: SLF001
    scheduled_minutes = app._timer.started_ms / 60_000  # noqa: SLF001
    # Falls back to adaptive backoff (5 min × 2^5 = 160, capped at 60).
    assert scheduled_minutes >= 30


def test_schedule_pulls_stale_error_refresh_forward():
    app = _schedule_app_stub()
    app._snapshots = {  # noqa: SLF001
        "claude": UsageSnapshot(
            provider="claude",
            status=SnapshotStatus.ERROR,
            error="Could not read usage from page.",
            metrics=[UsageMetric(label="Session", percent_used=80.0)],
        ),
    }

    app._schedule_next_refresh()  # noqa: SLF001

    assert app._timer.started_ms is not None  # noqa: SLF001
    scheduled_minutes = app._timer.started_ms / 60_000  # noqa: SLF001
    assert 0 < scheduled_minutes <= 1.2
