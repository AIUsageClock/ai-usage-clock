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
