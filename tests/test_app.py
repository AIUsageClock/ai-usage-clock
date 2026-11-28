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


class _FakeHost:
    def __init__(self):
        self.submitted = []
        self.focused = []

    def submit(self, kind, params, on_result, **kwargs):
        job = SimpleNamespace(kind=kind, params=params, on_result=on_result, kwargs=kwargs)
        self.submitted.append(job)
        return job

    def focus_job(self, kind):
        self.focused.append(kind)
        return True


def _login_app(monkeypatch):
    host = _FakeHost()
    monkeypatch.setattr(app_module, "get_host", lambda: host)
    monkeypatch.setattr(app_module, "existing_host", lambda: host)
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._settings_dialog = None  # noqa: SLF001
    app._cleared_sessions = {"claude"}  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        suspend_always_on_top=lambda: app._calls.append("suspend"),
        restore_always_on_top=lambda: app._calls.append("restore"),
    )
    app._calls = []  # noqa: SLF001
    return app, host


def test_login_runs_in_the_worker_and_refreshes_when_the_session_changed(monkeypatch):
    refreshed = []
    timers = []
    monkeypatch.setattr(
        app_module.QTimer,
        "singleShot",
        lambda delay, callback: timers.append((delay, callback)),
    )
    app, host = _login_app(monkeypatch)
    app.refresh_provider = refreshed.append

    app.open_login("claude")

    job = host.submitted[0]
    assert job.kind == "login"
    assert job.params["kind"] == "claude"
    assert job.params["account_id"] == "claude"
    assert job.params["title"] == "Sign in to Claude"
    assert job.params["browser_preference"] == "ask"
    assert job.kwargs["priority"] is True
    assert app._calls == ["suspend"]  # noqa: SLF001

    job.on_result({"ok": True, "accepted": False, "session_may_have_changed": True})

    assert app._calls == ["suspend", "restore"]  # noqa: SLF001
    assert app._cleared_sessions == set()  # noqa: SLF001
    assert app._login_job is None  # noqa: SLF001
    assert timers[0][0] == 750
    timers[0][1]()
    assert refreshed == ["claude"]


def test_only_one_login_window_at_a_time(monkeypatch):
    app, host = _login_app(monkeypatch)

    app.open_login("claude")
    app.open_login("claude")

    assert len(host.submitted) == 1
    assert host.focused == ["login"]


def test_cancelled_login_does_not_refresh(monkeypatch):
    refreshed = []
    app, host = _login_app(monkeypatch)
    app.refresh_provider = refreshed.append

    app.open_login("claude")
    host.submitted[0].on_result(
        {"ok": True, "accepted": False, "session_may_have_changed": False}
    )

    assert refreshed == []
    assert app._cleared_sessions == {"claude"}  # noqa: SLF001
    assert app._login_job is None  # noqa: SLF001


def test_login_without_gl_shows_the_unavailable_dialog_with_the_reason(qtbot, monkeypatch):
    shown = []
    app, host = _login_app(monkeypatch)
    app._show_webengine_unavailable = lambda name, reason: shown.append((name, reason))  # noqa: SLF001

    app.open_login("claude")
    host.submitted[0].on_result({"ok": False, "error": "no_gl", "reason": "no GLX/EGL"})
    assert shown == [], "the dialog is shown after the callback returns"
    qtbot.waitUntil(lambda: bool(shown), timeout=3000)

    assert shown == [("Claude", "no GLX/EGL")]
    assert app._calls == ["suspend", "restore"]  # noqa: SLF001


def _capture_warnings(monkeypatch):
    shown = []
    monkeypatch.setattr(
        app_module.QMessageBox,
        "warning",
        staticmethod(lambda parent, title, text: shown.append((title, text))),
    )
    return shown


def test_login_worker_failure_is_reported_but_cancel_is_silent(qtbot, monkeypatch):
    # The real dialog methods run; only QMessageBox.warning is intercepted.
    shown = _capture_warnings(monkeypatch)
    app, host = _login_app(monkeypatch)

    app.open_login("claude")
    host.submitted[0].on_result({"ok": False, "error": "worker_crashed", "detail": "exit code 7"})
    qtbot.waitUntil(lambda: bool(shown), timeout=3000)
    app.open_login("claude")
    host.submitted[1].on_result({"ok": False, "error": "cancelled"})
    qtbot.wait(100)

    assert len(shown) == 1
    title, text = shown[0]
    assert title == "Sign-in did not complete"
    assert text == (
        "Signing in to Claude did not finish: the browser helper process "
        "exited unexpectedly (exit code 7)."
    )
    assert "OpenGL" not in text and "FORCE" not in text


def test_login_timeout_says_the_window_was_open_too_long(qtbot, monkeypatch):
    shown = _capture_warnings(monkeypatch)
    app, host = _login_app(monkeypatch)

    app.open_login("claude")
    host.submitted[0].on_result({"ok": False, "error": "worker_timeout"})
    qtbot.waitUntil(lambda: bool(shown), timeout=3000)

    minutes = int(app_module.worker_ipc.LOGIN_TIMEOUT_S // 60)
    assert shown == [
        (
            "Sign-in did not complete",
            f"The sign-in window for Claude was closed because it was open for more "
            f"than {minutes} minutes. Open it again to finish signing in.",
        )
    ]
    assert "OpenGL" not in shown[0][1] and "FORCE" not in shown[0][1]


def test_login_without_gl_still_uses_the_original_dialog_text(qtbot, monkeypatch):
    shown = _capture_warnings(monkeypatch)
    app, host = _login_app(monkeypatch)

    app.open_login("claude")
    host.submitted[0].on_result({"ok": False, "error": "no_gl", "reason": "no GLX/EGL"})
    qtbot.waitUntil(lambda: bool(shown), timeout=3000)

    assert len(shown) == 1
    assert shown[0][0] == "Browser sign-in unavailable"
    assert "OpenGL" in shown[0][1] and "no GLX/EGL" in shown[0][1]


def test_login_failure_reason_ending_in_a_period_is_not_doubled(qtbot, monkeypatch):
    shown = _capture_warnings(monkeypatch)
    app, host = _login_app(monkeypatch)

    app.open_login("claude")
    host.submitted[0].on_result(
        {"ok": False, "error": "profile_locked", "detail": "The file is in use."}
    )
    qtbot.waitUntil(lambda: bool(shown), timeout=3000)

    assert shown == [
        ("Sign-in did not complete", "Signing in to Claude did not finish: The file is in use.")
    ]


def test_login_remembers_the_browser_choice_made_in_the_worker(monkeypatch):
    remembered = []
    app, host = _login_app(monkeypatch)
    app._remember_sign_in_browser = remembered.append  # noqa: SLF001

    app.open_login("claude")
    host.submitted[0].kwargs["on_event"]({"event": "browser_preference", "value": "edge"})

    assert remembered == ["edge"]

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


# ----- a sign-in window holds the browser worker, not the whole refresh round -----


class _CountingProvider:
    def __init__(self):
        self.refreshed = 0

    def refresh(self, emit):
        self.refreshed += 1


def _sign_in_open_app(*, sign_in_open=True):
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._providers = {  # noqa: SLF001
        "claude": _CountingProvider(),
        "copilot": _CountingProvider(),
        "openrouter": _CountingProvider(),
    }
    app._inflight = set()  # noqa: SLF001
    app._refresh_queue = []  # noqa: SLF001
    app._login_job = object() if sign_in_open else None  # noqa: SLF001
    app._cycle_signatures = {}  # noqa: SLF001
    app._last_cycle_signatures = {"claude": ("last reading",)}  # noqa: SLF001
    app._unmarked = []  # noqa: SLF001
    app._cycles_finished = 0  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        unmark_loading=app._unmarked.append,
        set_refreshing=lambda value: None,
        mark_loading=lambda names: None,
        restore_always_on_top=lambda: None,
    )
    app._finish_refresh_cycle = lambda: setattr(  # noqa: SLF001
        app, "_cycles_finished", app._cycles_finished + 1
    )
    return app


def test_providers_without_a_browser_keep_refreshing_while_a_sign_in_window_is_open():
    app = _sign_in_open_app()
    app._refresh_queue = ["claude", "copilot", "openrouter"]  # noqa: SLF001

    app._start_next_refresh()  # noqa: SLF001

    assert app._providers["copilot"].refreshed == 1  # noqa: SLF001
    assert app._providers["claude"].refreshed == 0  # noqa: SLF001
    assert app._inflight == {"copilot"}  # noqa: SLF001
    assert app._refresh_queue == ["openrouter"]  # noqa: SLF001
    assert app._deferred_browser_refresh == ["claude"]  # noqa: SLF001
    assert app._unmarked == ["claude"]  # noqa: SLF001
    assert app._cycle_signatures == {"claude": ("last reading",)}  # noqa: SLF001


def test_a_round_that_only_has_browser_accounts_left_ends_instead_of_stalling():
    app = _sign_in_open_app()
    app._refresh_queue = ["claude"]  # noqa: SLF001

    app._start_next_refresh()  # noqa: SLF001

    assert app._cycles_finished == 1  # noqa: SLF001
    assert app._refresh_queue == []  # noqa: SLF001
    assert app._inflight == set()  # noqa: SLF001


def test_a_browser_scrape_already_queued_behind_the_sign_in_does_not_hold_up_the_rest():
    app = _sign_in_open_app()
    app._inflight = {"claude"}  # noqa: SLF001 - submitted before the window opened
    app._refresh_queue = ["copilot"]  # noqa: SLF001

    app._start_next_refresh()  # noqa: SLF001

    assert app._providers["copilot"].refreshed == 1  # noqa: SLF001


def test_without_a_sign_in_window_the_round_is_still_one_provider_at_a_time():
    app = _sign_in_open_app(sign_in_open=False)
    app._inflight = {"copilot"}  # noqa: SLF001
    app._refresh_queue = ["claude"]  # noqa: SLF001

    app._start_next_refresh()  # noqa: SLF001

    assert app._providers["claude"].refreshed == 0  # noqa: SLF001
    assert app._refresh_queue == ["claude"]  # noqa: SLF001

    app._inflight = set()  # noqa: SLF001
    app._start_next_refresh()  # noqa: SLF001

    assert app._providers["claude"].refreshed == 1  # noqa: SLF001
    assert app._deferred_browser_refresh is None  # noqa: SLF001


def test_accounts_set_aside_for_the_sign_in_refresh_when_the_window_closes(monkeypatch):
    monkeypatch.setattr(app_module.QTimer, "singleShot", lambda delay, callback: callback())
    app = _sign_in_open_app()
    app._deferred_browser_refresh = ["claude"]  # noqa: SLF001
    started = []
    app._start_next_refresh = lambda: started.append(list(app._refresh_queue))  # noqa: SLF001
    app._timer = SimpleNamespace(stop=lambda: None)  # noqa: SLF001
    app._cleared_sessions = set()  # noqa: SLF001

    app._on_login_finished(  # noqa: SLF001
        "claude", "Claude", {"ok": True, "accepted": False, "session_may_have_changed": False}
    )

    assert app._login_job is None  # noqa: SLF001
    assert started == [["claude"]]
    assert app._deferred_browser_refresh is None  # noqa: SLF001


def test_a_sign_in_refresh_joins_a_round_that_is_already_running(monkeypatch):
    app = _sign_in_open_app(sign_in_open=False)
    app._inflight = {"copilot"}  # noqa: SLF001
    app._refresh_queue = ["openrouter"]  # noqa: SLF001

    app._refresh_after_login("claude")  # noqa: SLF001
    app._refresh_after_login("claude")  # noqa: SLF001
    app._refresh_after_login("copilot")  # noqa: SLF001

    assert app._refresh_queue == ["openrouter", "claude"]  # noqa: SLF001


def test_pasting_a_cookie_closes_an_open_sign_in_window_first(monkeypatch):
    events = []
    login_job = object()

    class _Host:
        def cancel(self, job):
            events.append(("cancel", job))

    class _Dialog:
        def __init__(self, *args, **kwargs):
            events.append("dialog created")

        def exec(self):
            events.append("dialog shown")
            return 0

    monkeypatch.setattr(app_module, "get_host", lambda: _Host())
    monkeypatch.setattr(app_module, "CookieDialog", _Dialog)
    app = App.__new__(App)
    app._config = Config()  # noqa: SLF001
    app._settings_dialog = None  # noqa: SLF001
    app._login_job = login_job  # noqa: SLF001
    app._widget = SimpleNamespace(  # noqa: SLF001
        suspend_always_on_top=lambda: None, restore_always_on_top=lambda: None
    )

    app.open_cookie_paste("claude")

    assert events == ["dialog created", ("cancel", login_job), "dialog shown"]


def test_restart_stops_the_browser_worker_before_the_new_process_starts(monkeypatch):
    events = []
    monkeypatch.setattr(app_module, "_flush_log_handlers", lambda: None)
    monkeypatch.setattr(
        app_module.subprocess, "Popen", lambda *a, **k: events.append("new process started")
    )
    monkeypatch.setattr(
        app_module,
        "QApplication",
        SimpleNamespace(instance=lambda: SimpleNamespace(quit=lambda: events.append("quit"))),
    )
    app = App.__new__(App)
    app._instance_lock = None  # noqa: SLF001
    app._stop_worker_host = lambda: events.append("worker stopped")  # noqa: SLF001

    app.restart()

    assert events == ["worker stopped", "new process started", "quit"]


# ----- a sign-in opened during a round: the round still ends (review 3, F1) -----


class _RoundProvider:
    """Hands its emit callback to the test, which delivers the reading later."""

    def __init__(self):
        self.emits = []

    def refresh(self, emit):
        self.emits.append(emit)


class _CountingTimer(_Timer):
    def __init__(self):
        super().__init__()
        self.starts = 0

    def start(self, ms: int):
        self.starts += 1
        super().start(ms)


def _ok(name: str) -> UsageSnapshot:
    return UsageSnapshot(
        provider=name,
        status=SnapshotStatus.OK,
        metrics=[UsageMetric(label="Session", percent_used=10.0)],
    )


def _round_app(monkeypatch, *names: str):
    """An App whose refresh, snapshot and sign-in code is the real one."""
    from unittest.mock import MagicMock

    from PyQt6.QtCore import QObject

    host = _FakeHost()
    monkeypatch.setattr(app_module, "get_host", lambda: host)
    monkeypatch.setattr(app_module, "existing_host", lambda: host)
    app = App.__new__(App)
    QObject.__init__(app)
    app._config = Config()  # noqa: SLF001
    app._settings_dialog = None  # noqa: SLF001
    app._providers = {name: _RoundProvider() for name in names}  # noqa: SLF001
    app._inflight = set()  # noqa: SLF001
    app._refresh_queue = []  # noqa: SLF001
    app._login_job = None  # noqa: SLF001
    app._cycle_signatures = {}  # noqa: SLF001
    app._last_cycle_signatures = None  # noqa: SLF001
    app._snapshots = {}  # noqa: SLF001
    app._cleared_sessions = set()  # noqa: SLF001
    app._unchanged_cycles = 0  # noqa: SLF001
    app._active_until = datetime.now()  # noqa: SLF001
    app._current_refresh_manual = False  # noqa: SLF001
    app._timer = _CountingTimer()  # noqa: SLF001
    app._widget = MagicMock()  # noqa: SLF001
    app._history = MagicMock()  # noqa: SLF001
    app._history.record_snapshot.return_value = []
    app._ratio = MagicMock()  # noqa: SLF001
    app._ratio_recent = lambda provider: []  # noqa: SLF001
    app._local_usage_on_snapshot = lambda snapshot, closed: None  # noqa: SLF001
    app._sync_usage_cache = MagicMock()  # noqa: SLF001
    app._update_tray = MagicMock()  # noqa: SLF001
    app._signals = app_module.ProviderSignals()  # noqa: SLF001
    app._signals.snapshot_ready.connect(app._on_snapshot)  # noqa: SLF001
    app.cycles = 0
    real_finish = app._finish_refresh_cycle  # noqa: SLF001

    def counting_finish():
        app.cycles += 1
        real_finish()

    app._finish_refresh_cycle = counting_finish  # noqa: SLF001
    return app, host


def test_a_sign_in_opened_mid_round_lets_the_round_end_and_the_timer_restart(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude", "copilot")
    app.refresh_now(manual=False)
    assert app._inflight == {"claude"}  # noqa: SLF001 - handed to the worker
    assert app._refresh_queue == ["copilot"]  # noqa: SLF001

    app.open_login("codex")  # another account's sign-in takes the worker

    # copilot does not need the browser, so it runs although claude is held up
    qtbot.waitUntil(lambda: bool(app._providers["copilot"].emits), timeout=3000)  # noqa: SLF001
    app._providers["copilot"].emits[0](_ok("copilot"))  # noqa: SLF001
    qtbot.waitUntil(lambda: app.cycles == 1 and app._timer.active, timeout=3000)  # noqa: SLF001

    assert app._inflight == set()  # noqa: SLF001
    assert app._refresh_queue == []  # noqa: SLF001
    assert app._timer.starts == 1  # noqa: SLF001


def test_a_sign_in_opened_when_only_a_browser_scrape_is_left_ends_the_round(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude")
    app.refresh_now(manual=False)
    assert app._inflight == {"claude"} and app._refresh_queue == []  # noqa: SLF001

    app.open_login("codex")

    qtbot.waitUntil(lambda: app.cycles == 1, timeout=3000)
    assert app._timer.active  # noqa: SLF001


def test_the_late_reading_is_recorded_but_does_not_end_or_restart_anything(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude", "copilot")
    app.refresh_now(manual=False)
    app.open_login("codex")
    qtbot.waitUntil(lambda: bool(app._providers["copilot"].emits), timeout=3000)  # noqa: SLF001
    app._providers["copilot"].emits[0](_ok("copilot"))  # noqa: SLF001
    qtbot.waitUntil(lambda: app.cycles == 1, timeout=3000)
    starts = app._timer.starts  # noqa: SLF001
    records = app._history.record_snapshot.call_count  # noqa: SLF001
    update_tray_calls = app._update_tray.call_count  # noqa: SLF001

    app._providers["claude"].emits[0](_ok("claude"))  # noqa: SLF001
    qtbot.wait(100)

    assert app._snapshots["claude"].status == SnapshotStatus.OK  # noqa: SLF001
    assert app._history.record_snapshot.call_count == records + 1  # noqa: SLF001
    app._ratio.record_snapshot.assert_called_with(app._snapshots["claude"])  # noqa: SLF001
    app._widget.update_snapshot.assert_called()  # noqa: SLF001
    assert app._update_tray.call_count == update_tray_calls + 1  # noqa: SLF001
    assert app.cycles == 1, "no second end of round"
    assert app._timer.starts == starts, "the timer was not reset"  # noqa: SLF001
    assert app._detached_browser_scrapes == set()  # noqa: SLF001


def test_the_late_reading_reaches_the_mcp_cache(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude")
    app._config.mcp_enabled = True  # noqa: SLF001
    app.refresh_now(manual=False)
    app.open_login("codex")
    qtbot.waitUntil(lambda: app.cycles == 1, timeout=3000)

    app._providers["claude"].emits[0](_ok("claude"))  # noqa: SLF001
    qtbot.wait(100)

    app._sync_usage_cache.assert_called()  # noqa: SLF001


def test_a_new_round_while_the_sign_in_is_open_does_not_send_a_second_scrape(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude", "copilot")
    app.refresh_now(manual=False)
    app.open_login("codex")
    qtbot.waitUntil(lambda: bool(app._providers["copilot"].emits), timeout=3000)  # noqa: SLF001
    app._providers["copilot"].emits[0](_ok("copilot"))  # noqa: SLF001
    qtbot.waitUntil(lambda: app.cycles == 1, timeout=3000)
    assert app._detached_browser_scrapes == {"claude"}  # noqa: SLF001
    assert app._login_job is not None  # noqa: SLF001 - the window is still open

    app.refresh_now(manual=True)  # the round is free to start again

    qtbot.waitUntil(lambda: len(app._providers["copilot"].emits) == 2, timeout=3000)  # noqa: SLF001
    assert len(app._providers["claude"].emits) == 1, "still only the first claude scrape"  # noqa: SLF001
    app._providers["copilot"].emits[1](_ok("copilot"))  # noqa: SLF001
    qtbot.waitUntil(lambda: app.cycles == 2, timeout=3000)
    assert app._detached_browser_scrapes == {"claude"}  # noqa: SLF001

    # The old scrape finally reports in the middle of nothing: no new round.
    app._providers["claude"].emits[0](_ok("claude"))  # noqa: SLF001
    qtbot.wait(100)
    assert app.cycles == 2
    assert app._detached_browser_scrapes == set()  # noqa: SLF001


def test_a_reading_that_arrives_during_a_new_round_does_not_disturb_its_count(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude", "copilot", "openrouter")
    app.refresh_now(manual=False)  # openrouter first, then claude, copilot
    app._providers["openrouter"].emits[0](_ok("openrouter"))  # noqa: SLF001
    qtbot.waitUntil(lambda: app._inflight == {"claude"}, timeout=3000)  # noqa: SLF001
    app.open_login("codex")
    qtbot.waitUntil(lambda: bool(app._providers["copilot"].emits), timeout=3000)  # noqa: SLF001
    app._providers["copilot"].emits[0](_ok("copilot"))  # noqa: SLF001
    qtbot.waitUntil(lambda: app.cycles == 1, timeout=3000)

    app.refresh_now(manual=True)
    qtbot.waitUntil(lambda: len(app._providers["openrouter"].emits) == 2, timeout=3000)  # noqa: SLF001
    # the old claude scrape reports while the new round is waiting on openrouter
    app._providers["claude"].emits[0](_ok("claude"))  # noqa: SLF001
    qtbot.wait(100)

    assert app.cycles == 1, "the new round is still running"
    assert app._inflight == {"openrouter"}  # noqa: SLF001
    assert app._refresh_queue == ["claude", "copilot"]  # noqa: SLF001


def test_a_refresh_asked_for_a_detached_account_waits_for_its_running_scrape(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude")
    app.refresh_now(manual=False)
    app.open_login("codex")
    qtbot.waitUntil(lambda: app.cycles == 1, timeout=3000)
    assert app._detached_browser_scrapes == {"claude"}  # noqa: SLF001
    # the sign-in window closes (the person signed in) while the old scrape runs
    host.submitted[0].on_result({"ok": True, "accepted": True, "session_may_have_changed": True})
    assert app._login_job is None  # noqa: SLF001

    app.refresh_provider("claude")  # what the sign-in asks for
    app._queue_refresh_of(["claude"])  # noqa: SLF001
    qtbot.wait(50)

    assert len(app._providers["claude"].emits) == 1, "no duplicate scrape"  # noqa: SLF001
    assert app._refresh_queue == [] and app._inflight == set()  # noqa: SLF001

    app._providers["claude"].emits[0](_ok("claude"))  # noqa: SLF001
    qtbot.waitUntil(lambda: len(app._providers["claude"].emits) == 2, timeout=3000)  # noqa: SLF001


def test_login_dialogs_are_shown_after_the_result_callback_has_returned(qtbot, monkeypatch):
    shown = _capture_warnings(monkeypatch)
    app, host = _login_app(monkeypatch)

    app.open_login("claude")
    host.submitted[0].on_result({"ok": False, "error": "worker_timeout"})
    assert shown == [], "QMessageBox.warning was not called inside the callback"
    qtbot.waitUntil(lambda: bool(shown), timeout=3000)
    assert shown[0][0] == "Sign-in did not complete"


# ----- quitting while a scrape is running (review 3, F5) -----


def test_the_worker_is_stopped_before_the_caches_are_cleared_at_quit(monkeypatch):
    connected = []

    class _Signal:
        def connect(self, slot):
            connected.append(slot.__name__)

    class _FakeTimer:
        def __init__(self, *a, **k):
            self.timeout = _Signal()

        def setInterval(self, ms):
            pass

        def start(self):
            pass

    monkeypatch.setattr(
        app_module, "QApplication", SimpleNamespace(instance=lambda: SimpleNamespace(aboutToQuit=_Signal()))
    )
    monkeypatch.setattr(app_module, "QTimer", _FakeTimer)
    monkeypatch.setattr(app_module.atexit, "register", lambda *a: None)
    app = App.__new__(App)

    app._install_lifecycle_logging()  # noqa: SLF001

    assert connected.index("_stop_worker_host") < connected.index("_invalidate_usage_cache")
    assert connected.index("_stop_worker_host") < connected.index("_shutdown_local_usage")


def _cancelled(name: str) -> UsageSnapshot:
    return UsageSnapshot(provider=name, status=SnapshotStatus.ERROR, error="cancelled")


def test_a_scrape_cancelled_by_quitting_is_not_recorded_or_cached(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude", "copilot")
    app.refresh_now(manual=False)
    app._config.mcp_enabled = True  # noqa: SLF001

    def stop(graceful=True):
        # what WorkerHost.stop does: the running scrape is cancelled at once
        app._providers["claude"].emits[0](_cancelled("claude"))  # noqa: SLF001

    host.stop = stop

    app._stop_worker_host()  # noqa: SLF001
    qtbot.wait(100)

    assert app._snapshots == {}  # noqa: SLF001
    app._history.record_snapshot.assert_not_called()  # noqa: SLF001
    app._ratio.record_snapshot.assert_not_called()  # noqa: SLF001
    app._sync_usage_cache.assert_not_called()  # noqa: SLF001


def test_a_scrape_cancelled_by_restarting_is_not_recorded_or_cached(qtbot, monkeypatch):
    app, host = _round_app(monkeypatch, "claude")
    app.refresh_now(manual=False)
    app._config.mcp_enabled = True  # noqa: SLF001
    app._instance_lock = None  # noqa: SLF001
    monkeypatch.setattr(app_module, "_flush_log_handlers", lambda: None)
    monkeypatch.setattr(app_module.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(
        app_module, "QApplication", SimpleNamespace(instance=lambda: SimpleNamespace(quit=lambda: None))
    )
    host.stop = lambda graceful=True: app._providers["claude"].emits[0](_cancelled("claude"))  # noqa: SLF001

    app.restart()
    qtbot.wait(100)

    assert app._snapshots == {}  # noqa: SLF001
    app._history.record_snapshot.assert_not_called()  # noqa: SLF001
    app._sync_usage_cache.assert_not_called()  # noqa: SLF001
