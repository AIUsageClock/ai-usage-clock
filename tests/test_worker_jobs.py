"""The worker's job handlers, with the browser pieces replaced.

Importing aiusageclock.webview.worker is safe here (it loads no WebEngine until
a job needs it); the handlers' use of HeadlessScraper, LoginWindow and the
cookie store is replaced so no Chromium starts.
"""

from __future__ import annotations

import sys
import types

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from aiusageclock.config import BrowserAccount, Config
from aiusageclock.webview import cookies, ipc, runtime, worker


class _FakeScraper(QObject):
    done = pyqtSignal(object, str)
    instances: list["_FakeScraper"] = []

    def __init__(self, **kwargs):
        super().__init__(kwargs.get("parent"))
        self.kwargs = kwargs
        _FakeScraper.instances.append(self)


@pytest.fixture
def runner(qtbot, monkeypatch):
    _FakeScraper.instances.clear()
    monkeypatch.setattr(runtime, "probe", lambda: (True, ""))
    fake_module = types.ModuleType("aiusageclock.webview.scraper")
    fake_module.HeadlessScraper = _FakeScraper
    monkeypatch.setitem(sys.modules, "aiusageclock.webview.scraper", fake_module)
    job_runner = worker.JobRunner()
    yield job_runner
    job_runner.deleteLater()


def _run(runner, kind, params):
    results: list[dict] = []
    events: list[dict] = []
    runner.run(kind, params, results.append, events.append)
    return results, events


def test_ping_needs_no_browser(runner):
    results, _ = _run(runner, ipc.JOB_PING, {"echo": 3})

    assert results[0]["ok"] is True
    assert results[0]["echo"] == 3


def test_unknown_job_kind_is_reported(runner):
    results, _ = _run(runner, "nonsense", {})

    assert results[0]["ok"] is False
    assert results[0]["error"] == "unknown_job"


def test_a_handler_that_raises_becomes_an_error_result(runner):
    results, _ = _run(runner, ipc.JOB_SCRAPE, {})  # missing "provider"

    assert results[0]["ok"] is False
    assert results[0]["error"] == "worker_error"


def test_scrape_without_gl_reports_no_gl_and_starts_no_browser(runner, monkeypatch):
    monkeypatch.setattr(runtime, "probe", lambda: (False, "no GLX/EGL"))

    results, _ = _run(
        runner,
        ipc.JOB_SCRAPE,
        {"provider": "claude", "url": "https://x.test", "extractor_js": "1"},
    )

    assert results == [{"ok": False, "error": "no_gl", "reason": "no GLX/EGL"}]
    assert _FakeScraper.instances == []


@pytest.mark.parametrize(
    ("account", "kind", "hydrated"),
    [
        ("claude", "claude", True),
        ("codex-work", "codex", True),
        ("opencode_go-work", "opencode_go", False),
    ],
)
def test_scrape_seeds_the_profile_from_the_keyring_only_for_browser_accounts(
    runner, monkeypatch, account, kind, hydrated
):
    config = Config()
    config.browser_accounts.append(BrowserAccount(id=account, kind=kind, name="X", enabled=True))
    monkeypatch.setattr(worker.Config, "load", classmethod(lambda cls: config))
    seen = []
    monkeypatch.setattr(
        cookies, "hydrate_account_from_keyring", lambda k, a: seen.append((k, a)) or True
    )

    _run(
        runner,
        ipc.JOB_SCRAPE,
        {"provider": account, "url": "https://x.test", "extractor_js": "1", "wait_ms": 10},
    )

    assert seen == ([(kind, account)] if hydrated else [])
    assert _FakeScraper.instances[0].kwargs["provider"] == account
    assert _FakeScraper.instances[0].kwargs["wait_ms"] == 10


def test_scrape_result_and_error_are_forwarded(runner):
    results, _ = _run(
        runner,
        ipc.JOB_SCRAPE,
        {"provider": "claude", "url": "https://x.test", "extractor_js": "1"},
    )

    _FakeScraper.instances[0].done.emit({"percent": 12}, "")

    assert results == [{"ok": True, "result": {"percent": 12}, "error": ""}]


def test_a_second_result_for_the_same_job_is_dropped(runner):
    results, _ = _run(
        runner,
        ipc.JOB_SCRAPE,
        {"provider": "claude", "url": "https://x.test", "extractor_js": "1"},
    )

    _FakeScraper.instances[0].done.emit(None, "timeout")
    _FakeScraper.instances[0].done.emit({"late": True}, "")

    assert len(results) == 1


def test_inject_verify_without_a_stored_cookie_reports_not_injected(runner, qtbot, monkeypatch):
    monkeypatch.setattr(worker, "get_provider_cookie", lambda account_id: None)
    monkeypatch.setattr(worker, "_COOKIE_COMMIT_MS", 10)

    results, _ = _run(
        runner,
        ipc.JOB_INJECT_VERIFY,
        {"kind": "claude", "account_id": "claude", "verify": True},
    )
    qtbot.waitUntil(lambda: bool(results), timeout=3000)

    assert results == [{"ok": True, "injected": False}]


def test_inject_without_verify_finishes_after_the_cookie_commit_wait(runner, qtbot, monkeypatch):
    monkeypatch.setattr(worker, "get_provider_cookie", lambda account_id: "sessionKey=x")
    monkeypatch.setattr(cookies, "inject_session_cookie", lambda kind, value, *, account_id=None: True)
    monkeypatch.setattr(worker, "_COOKIE_COMMIT_MS", 10)

    results, _ = _run(
        runner,
        ipc.JOB_INJECT_VERIFY,
        {"kind": "claude", "account_id": "claude", "verify": False},
    )
    qtbot.waitUntil(lambda: bool(results), timeout=3000)

    assert results == [{"ok": True, "injected": True}]


def test_inject_verify_reports_the_verifier_outcome(runner, qtbot, monkeypatch):
    monkeypatch.setattr(worker, "get_provider_cookie", lambda account_id: "sessionKey=x")
    monkeypatch.setattr(cookies, "inject_session_cookie", lambda kind, value, *, account_id=None: True)
    fake_verify = types.ModuleType("aiusageclock.webview.verify")
    seen = {}

    def verify_session(provider, on_done, *, account_id=None, parent=None, verify_url=None):
        seen.update(provider=provider, account_id=account_id, verify_url=verify_url)
        on_done(True, "")
        return object()

    fake_verify.verify_session = verify_session
    monkeypatch.setitem(sys.modules, "aiusageclock.webview.verify", fake_verify)

    results, _ = _run(
        runner,
        ipc.JOB_INJECT_VERIFY,
        {"kind": "claude", "account_id": "claude-work", "verify": True, "verify_url": None},
    )
    qtbot.waitUntil(lambda: bool(results), timeout=3000)

    assert results == [{"ok": True, "injected": True, "verified": True, "verify_error": ""}]
    assert seen == {"provider": "claude", "account_id": "claude-work", "verify_url": None}


def test_worker_exits_when_told_to_shut_down(qtbot, monkeypatch):
    instance = worker.Worker("name", "token")
    exits = []
    monkeypatch.setattr(worker.QCoreApplication, "exit", staticmethod(exits.append))
    monkeypatch.setattr(instance._runner, "release_browser_state", lambda: None)  # noqa: SLF001
    monkeypatch.setattr(worker.QTimer, "singleShot", staticmethod(lambda ms, cb: cb()))

    instance._quit(0)  # noqa: SLF001

    assert exits == [0]
    instance.deleteLater()


# ----- review fixes: leaving cleanly, refusing a signed-out profile, excepthook -----


@pytest.fixture
def fake_profile_module(monkeypatch):
    module = types.ModuleType("aiusageclock.webview.profile")
    events: list[str] = []

    class _Profiles(dict):
        def clear(self):
            events.append("profiles dropped")
            super().clear()

    module._profiles = _Profiles({"claude": object()})
    module.events = events
    monkeypatch.setitem(sys.modules, "aiusageclock.webview.profile", module)
    return module


def _fake_login_window(monkeypatch, dialog_class):
    fake_window = types.ModuleType("aiusageclock.webview.login_window")
    fake_window.LoginWindow = dialog_class
    monkeypatch.setitem(sys.modules, "aiusageclock.webview.login_window", fake_window)
    monkeypatch.setattr(worker, "_bring_to_front", lambda widget: None)


_LOGIN_PARAMS = {"kind": "claude", "url": "https://x.test", "title": "t", "account_id": "claude"}


def test_leaving_stops_the_running_scrape_before_the_profiles_are_dropped(
    runner, fake_profile_module
):
    events = fake_profile_module.events
    _run(runner, ipc.JOB_SCRAPE, {"provider": "claude", "url": "https://x.test", "extractor_js": "1"})
    scraper = _FakeScraper.instances[0]
    scraper.abort = lambda: events.append("scraper aborted")

    runner.release_browser_state()

    assert events == ["scraper aborted", "profiles dropped"]


def test_leaving_closes_the_sign_in_window_before_the_profiles_are_dropped(
    runner, monkeypatch, fake_profile_module
):
    events = fake_profile_module.events

    class _Dialog(QObject):
        finished = pyqtSignal(int)
        browser_preference_changed = pyqtSignal(str)
        session_may_have_changed = False

        def __init__(self, *args, **kwargs):
            super().__init__()

        def reject(self):
            # The real window's done() also stops the real browser it started
            # and waits for its temporary profile to be removed.
            events.append("sign-in window rejected")
            self.finished.emit(0)

    _fake_login_window(monkeypatch, _Dialog)
    results, _ = _run(runner, ipc.JOB_LOGIN, _LOGIN_PARAMS)

    runner.release_browser_state()

    assert events == ["sign-in window rejected", "profiles dropped"]
    assert results == [], "the job is abandoned, not reported as a finished sign-in"


def test_signing_in_clears_stale_temporary_browser_profiles_first(runner, monkeypatch):
    from aiusageclock.config import app_data_dir

    stale = app_data_dir() / "browser-signin" / "claude-left-behind"
    stale.mkdir(parents=True)
    seen = {}

    class _Dialog(QObject):
        finished = pyqtSignal(int)
        browser_preference_changed = pyqtSignal(str)

        def __init__(self, *args, **kwargs):
            super().__init__()
            seen["stale existed"] = stale.exists()

    _fake_login_window(monkeypatch, _Dialog)

    _run(runner, ipc.JOB_LOGIN, _LOGIN_PARAMS)

    assert seen == {"stale existed": False}


def test_a_scrape_is_refused_while_the_accounts_profile_is_waiting_for_deletion(
    runner, monkeypatch
):
    from aiusageclock.webview import profile_cleanup

    monkeypatch.setattr(profile_cleanup, "ensure_not_pending", lambda account_id: "in use")

    results, _ = _run(
        runner,
        ipc.JOB_SCRAPE,
        {"provider": "claude", "url": "https://x.test", "extractor_js": "1"},
    )

    assert results == [{"ok": False, "error": "profile_locked", "detail": "in use"}]
    assert _FakeScraper.instances == []


def test_signing_in_again_finishes_the_pending_deletion_before_the_window_opens(
    runner, monkeypatch
):
    from aiusageclock.config import webview_profile_dir
    from aiusageclock.webview import profile_cleanup

    old_profile = webview_profile_dir("claude")
    (old_profile / "cache").mkdir(parents=True)
    (old_profile / "Cookies").write_bytes(b"the signed-out session")
    profile_cleanup._write_pending(["claude"])
    seen = {}

    class _Dialog(QObject):
        finished = pyqtSignal(int)
        browser_preference_changed = pyqtSignal(str)

        def __init__(self, *args, **kwargs):
            super().__init__()
            seen["old profile still there"] = old_profile.exists()
            seen["still listed"] = profile_cleanup.read_pending()

    _fake_login_window(monkeypatch, _Dialog)

    _run(runner, ipc.JOB_LOGIN, _LOGIN_PARAMS)

    assert seen == {"old profile still there": False, "still listed": []}


def test_a_sign_in_that_cannot_get_its_profile_free_fails_instead_of_opening(runner, monkeypatch):
    from aiusageclock.webview import profile_cleanup

    monkeypatch.setattr(profile_cleanup, "ensure_not_pending", lambda account_id: "locked")

    def _must_not_open(*args, **kwargs):
        raise AssertionError("the window must not open")

    _fake_login_window(monkeypatch, _must_not_open)

    results, _ = _run(runner, ipc.JOB_LOGIN, _LOGIN_PARAMS)

    assert results[0]["ok"] is False
    assert results[0]["detail"] == "locked"


def test_a_job_arriving_after_the_worker_decided_to_leave_is_not_acknowledged(
    qtbot, monkeypatch
):
    instance = worker.Worker("name", "token")
    sent = []
    monkeypatch.setattr(instance, "_send", sent.append)
    monkeypatch.setattr(instance._runner, "release_browser_state", lambda: None)  # noqa: SLF001
    monkeypatch.setattr(worker.QCoreApplication, "exit", staticmethod(lambda code: None))
    monkeypatch.setattr(worker.QTimer, "singleShot", staticmethod(lambda ms, cb: None))
    ran = []
    monkeypatch.setattr(instance._runner, "run", lambda *a: ran.append(a))  # noqa: SLF001

    instance._quit(0)  # noqa: SLF001 - the idle exit
    instance._start_job({"id": 7, "kind": "ping", "params": {}})  # noqa: SLF001

    assert sent == [], "no acknowledgement, so the host runs the job again on a new worker"
    assert ran == []
    instance.deleteLater()


def test_a_parent_that_disappears_still_gets_the_worker_cleaned_up(qtbot, monkeypatch):
    instance = worker.Worker("name", "token")
    released = []
    monkeypatch.setattr(instance._runner, "release_browser_state", lambda: released.append(1))  # noqa: SLF001
    monkeypatch.setattr(worker.QCoreApplication, "exit", staticmethod(lambda code: None))
    monkeypatch.setattr(worker.QTimer, "singleShot", staticmethod(lambda ms, cb: None))

    instance._on_disconnected()  # noqa: SLF001

    assert released == [1], "a sign-in window or a real browser may still be open"
    instance.deleteLater()


def test_an_exception_in_a_callback_fails_the_job_and_is_logged(qtbot, monkeypatch, caplog):
    instance = worker.Worker("name", "token")
    sent = []
    monkeypatch.setattr(instance, "_send", sent.append)
    monkeypatch.setattr(worker, "_active_worker", instance)
    # A job that is still running when the exception arrives.
    monkeypatch.setattr(instance._runner, "_ping", lambda params, finish, events: None)  # noqa: SLF001
    instance._start_job({"id": 3, "kind": "ping", "params": {}})  # noqa: SLF001
    caplog.set_level("ERROR", logger="aiusageclock.webview.worker")
    saved_hook = sys.excepthook
    try:
        worker._install_excepthook()  # noqa: SLF001
        try:
            raise ValueError("boom inside a Qt slot")
        except ValueError:
            sys.excepthook(*sys.exc_info())
    finally:
        sys.excepthook = saved_hook

    results = [m for m in sent if m.get("type") == ipc.MSG_RESULT]
    assert results and results[0]["id"] == 3
    assert results[0]["result"]["ok"] is False
    assert "ValueError: boom inside a Qt slot" in results[0]["result"]["detail"]
    assert "boom inside a Qt slot" in caplog.text
    assert instance._job_id is None  # noqa: SLF001 - the worker can take the next job
    instance.deleteLater()


def test_the_worker_gives_its_windows_the_application_icon(qtbot):
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance()
    saved = (qt_app.windowIcon(), qt_app.applicationName(), qt_app.organizationName())
    try:
        qt_app.setWindowIcon(QIcon())
        worker._configure_application(qt_app)  # noqa: SLF001
        assert not qt_app.windowIcon().isNull()
    finally:
        qt_app.setWindowIcon(saved[0])
        qt_app.setApplicationName(saved[1])
        qt_app.setOrganizationName(saved[2])
