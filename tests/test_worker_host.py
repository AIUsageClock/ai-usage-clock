"""WorkerHost: queueing, transport and failure handling, against a fake worker.

tests/fake_worker.py speaks the real protocol but loads no browser, so these run
everywhere and quickly. The real worker is covered by test_worker_integration.py.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from aiusageclock.webview import cookies, host as host_module, ipc, profile_cleanup
from aiusageclock.webview.host import WorkerHost, WorkerScraper

FAKE = str(Path(__file__).resolve().parent / "fake_worker.py")
WAIT_MS = 20000


@pytest.fixture
def make_host(qtbot, monkeypatch):
    created: list[WorkerHost] = []
    starts = {"count": 0}

    def _make(**kwargs) -> WorkerHost:
        kwargs.setdefault("idle_shutdown_ms", 60000)
        kwargs.setdefault("connect_timeout_ms", 8000)
        host = WorkerHost(command=lambda: [sys.executable, FAKE], **kwargs)
        original = host._start_worker

        def counting():
            starts["count"] += 1
            original()

        monkeypatch.setattr(host, "_start_worker", counting)
        created.append(host)
        return host

    _make.starts = starts
    yield _make
    for item in created:
        item.stop(graceful=False, wait_ms=3000)


def _submit(host, qtbot, params, *, timeout_s=15.0, **kwargs):
    results: list[dict] = []
    job = host.submit(ipc.JOB_PING, params, results.append, timeout_s=timeout_s, **kwargs)
    return job, results


def _wait(qtbot, results, count=1):
    qtbot.waitUntil(lambda: len(results) >= count, timeout=WAIT_MS)


def test_job_round_trip_through_a_separate_process(qtbot, make_host):
    host = make_host()
    _, results = _submit(host, qtbot, {"op": "echo", "value": "hi"})
    _wait(qtbot, results)

    assert results[0]["ok"] is True
    assert results[0]["echo"] == "hi"
    assert results[0]["pid"] != os.getpid()


def test_callback_is_never_called_from_inside_submit(qtbot, make_host):
    host = make_host()
    results: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "echo"}, results.append, timeout_s=15.0)
    assert results == []
    _wait(qtbot, results)


def test_wrong_token_is_rejected_and_the_job_fails(qtbot, make_host, monkeypatch):
    monkeypatch.setenv("FAKE_WORKER_BAD_TOKEN", "1")
    host = make_host(connect_timeout_ms=1500)
    _, results = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, results)

    assert results[0]["ok"] is False
    assert results[0]["error"] == ipc.ERR_START_FAILED


def test_worker_that_never_says_hello_is_killed(qtbot, make_host, monkeypatch):
    monkeypatch.setenv("FAKE_WORKER_NO_HELLO", "1")
    host = make_host(connect_timeout_ms=1000)
    _, results = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, results)

    assert results[0]["error"] == ipc.ERR_START_FAILED
    qtbot.waitUntil(lambda: not host.worker_running, timeout=5000)


def test_worker_that_cannot_start_fails_every_queued_job_without_looping(
    qtbot, make_host, monkeypatch
):
    monkeypatch.setenv("FAKE_WORKER_EXIT_AT_START", "1")
    host = make_host()
    _, first = _submit(host, qtbot, {"op": "echo"})
    _, second = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, first)
    _wait(qtbot, second)

    assert first[0]["error"] == ipc.ERR_START_FAILED
    assert second[0]["error"] == ipc.ERR_START_FAILED
    assert make_host.starts["count"] == 1, "a worker that never connects is not restarted"


def test_jobs_run_one_at_a_time_on_a_single_worker(qtbot, make_host):
    host = make_host()
    results: list[dict] = []
    for index in range(3):
        host.submit(
            ipc.JOB_PING,
            {"op": "sleep", "ms": 200},
            lambda result, i=index: results.append((i, result)),
            timeout_s=15.0,
        )
    qtbot.waitUntil(lambda: len(results) == 3, timeout=WAIT_MS)

    assert [i for i, _ in results] == [0, 1, 2]
    assert len({result["pid"] for _, result in results}) == 1
    assert make_host.starts["count"] == 1


def test_priority_job_goes_ahead_of_queued_background_work(qtbot, make_host):
    host = make_host()
    order: list[str] = []
    host.submit(ipc.JOB_PING, {"op": "sleep", "ms": 400}, lambda r: order.append("running"), timeout_s=15.0)
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)
    host.submit(ipc.JOB_PING, {"op": "echo"}, lambda r: order.append("background"), timeout_s=15.0)
    host.submit(
        ipc.JOB_PING, {"op": "echo"}, lambda r: order.append("priority"), timeout_s=15.0, priority=True
    )
    qtbot.waitUntil(lambda: len(order) == 3, timeout=WAIT_MS)

    assert order == ["running", "priority", "background"]


def test_watchdog_kills_a_hung_worker_and_the_next_job_gets_a_new_one(qtbot, make_host):
    host = make_host()
    _, hung = _submit(host, qtbot, {"op": "hang"}, timeout_s=1.0)
    _, after = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, hung)
    _wait(qtbot, after)

    assert hung[0]["error"] == ipc.ERR_TIMEOUT
    assert after[0]["ok"] is True
    assert make_host.starts["count"] == 2


def test_crash_during_a_job_reports_it_and_recovers(qtbot, make_host):
    host = make_host()
    _, crashed = _submit(host, qtbot, {"op": "crash"})
    _, after = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, crashed)
    _wait(qtbot, after)

    assert crashed[0]["error"] == ipc.ERR_CRASHED
    assert "7" in crashed[0]["detail"]
    assert after[0]["ok"] is True


def test_idle_worker_is_shut_down_and_restarted_on_demand(qtbot, make_host):
    host = make_host(idle_shutdown_ms=200)
    _, first = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, first)
    qtbot.waitUntil(lambda: not host.worker_running, timeout=10000)

    _, second = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, second)

    assert second[0]["pid"] != first[0]["pid"]
    assert make_host.starts["count"] == 2


def test_job_sent_to_a_worker_that_was_already_leaving_is_retried(
    qtbot, make_host, monkeypatch, tmp_path
):
    monkeypatch.setenv("FAKE_WORKER_DIE_ONCE", str(tmp_path / "died"))
    host = make_host()
    _, results = _submit(host, qtbot, {"op": "echo", "value": 1})
    _wait(qtbot, results)

    assert results[0]["ok"] is True
    assert make_host.starts["count"] == 2


def test_events_reach_the_job_owner(qtbot, make_host):
    host = make_host()
    events: list[dict] = []
    results: list[dict] = []
    host.submit(
        ipc.JOB_PING,
        {"op": "event"},
        results.append,
        timeout_s=15.0,
        on_event=events.append,
    )
    _wait(qtbot, results)

    assert events and events[0]["event"] == "hello"


def test_release_profile_cancels_that_accounts_jobs_and_keeps_the_others(qtbot, make_host):
    host = make_host()
    mine: list[dict] = []
    queued_mine: list[dict] = []
    other: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "hang"}, mine.append, timeout_s=60.0, account_id="a")
    host.submit(ipc.JOB_PING, {"op": "echo"}, queued_mine.append, timeout_s=60.0, account_id="a")
    host.submit(ipc.JOB_PING, {"op": "echo"}, other.append, timeout_s=60.0, account_id="b")
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)

    host.release_profile("a")
    _wait(qtbot, mine)
    _wait(qtbot, queued_mine)
    _wait(qtbot, other)

    assert mine[0]["error"] == ipc.ERR_CANCELLED
    assert queued_mine[0]["error"] == ipc.ERR_CANCELLED
    assert other[0]["ok"] is True


def test_release_profile_leaves_a_worker_alone_that_never_held_that_profile(qtbot, make_host):
    host = make_host()
    other: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "sleep", "ms": 1500}, other.append, timeout_s=60.0, account_id="b")
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)
    proc = host._proc

    host.release_profile("a")  # a was never given to this worker

    assert host._proc is proc, "the worker, and the other account's job, are not disturbed"
    _wait(qtbot, other)
    assert other[0]["ok"] is True


def test_release_profile_asks_a_worker_that_held_it_to_shut_down_first(
    qtbot, make_host, monkeypatch, tmp_path
):
    mark = tmp_path / "shutdown-mark"
    monkeypatch.setenv("FAKE_WORKER_SHUTDOWN_MARK", str(mark))
    host = make_host()
    first: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "echo"}, first.append, timeout_s=60.0, account_id="a")
    _wait(qtbot, first)
    other: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "sleep", "ms": 1500}, other.append, timeout_s=60.0, account_id="b")
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)

    host.release_profile("a")

    assert mark.exists(), "the worker was asked to flush and exit, not killed"
    assert host.worker_running is False
    _wait(qtbot, other)
    assert other[0]["ok"] is True, "the other account's job runs again on a new worker"
    assert other[0]["pid"] != first[0]["pid"]


def test_release_profile_does_not_requeue_a_job_that_is_already_being_ended(
    qtbot, make_host, monkeypatch
):
    monkeypatch.setenv("FAKE_WORKER_IGNORE_SHUTDOWN", "1")
    monkeypatch.setattr(host_module, "RELEASE_WAIT_MS", 300)
    host = make_host()
    touched: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "echo"}, touched.append, timeout_s=60.0, account_id="b")
    _wait(qtbot, touched)
    timed_out: list[dict] = []
    # a's job runs out of time and the worker is being shut down (it will not
    # leave by itself), when b's sign-in is cleared.
    host.submit(ipc.JOB_PING, {"op": "hang"}, timed_out.append, timeout_s=0.5, account_id="a")
    qtbot.waitUntil(lambda: host._kill_reason == ipc.ERR_TIMEOUT, timeout=WAIT_MS)
    assert make_host.starts["count"] == 1

    host.release_profile("b")
    _wait(qtbot, timed_out)

    assert timed_out[0]["error"] == ipc.ERR_TIMEOUT
    assert make_host.starts["count"] == 1, "the ended job was not sent to a new worker"
    assert not host._queue


def test_cancelling_a_running_job_asks_the_worker_to_shut_down_first(
    qtbot, make_host, monkeypatch, tmp_path
):
    mark = tmp_path / "shutdown-mark"
    monkeypatch.setenv("FAKE_WORKER_SHUTDOWN_MARK", str(mark))
    host = make_host()
    results: list[dict] = []
    job = host.submit(ipc.JOB_PING, {"op": "hang"}, results.append, timeout_s=60.0)
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)

    host.cancel(job)
    _wait(qtbot, results)

    assert results[0]["error"] == ipc.ERR_CANCELLED
    assert mark.exists()


def test_a_job_that_runs_out_of_time_is_shut_down_politely_and_reports_a_timeout(
    qtbot, make_host, monkeypatch, tmp_path
):
    mark = tmp_path / "shutdown-mark"
    monkeypatch.setenv("FAKE_WORKER_SHUTDOWN_MARK", str(mark))
    host = make_host()
    results: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "hang"}, results.append, timeout_s=0.5)
    _wait(qtbot, results)

    assert results[0]["error"] == ipc.ERR_TIMEOUT
    assert mark.exists()


def test_a_worker_that_ignores_the_shutdown_request_is_killed_after_the_grace_period(
    qtbot, make_host, monkeypatch
):
    monkeypatch.setenv("FAKE_WORKER_IGNORE_SHUTDOWN", "1")
    monkeypatch.setattr(host_module, "STOP_GRACE_MS", 300)
    host = make_host()
    results: list[dict] = []
    job = host.submit(ipc.JOB_PING, {"op": "hang"}, results.append, timeout_s=60.0)
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)

    host.cancel(job)
    _wait(qtbot, results)

    assert results[0]["error"] == ipc.ERR_CANCELLED, "the reason survives the later kill"
    qtbot.waitUntil(lambda: not host.worker_running, timeout=WAIT_MS)


def test_focus_job_lets_the_worker_take_the_foreground_again(qtbot, make_host, monkeypatch):
    host = make_host()
    allowed: list[bool] = []
    monkeypatch.setattr(host, "_allow_worker_foreground", lambda: allowed.append(True))
    host.submit(ipc.JOB_LOGIN, {"op": "hang"}, lambda result: None, timeout_s=60.0)
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)
    allowed.clear()  # the dispatch itself asked once

    assert host.focus_job(ipc.JOB_LOGIN) is True

    assert allowed == [True]

def test_stop_cancels_everything_and_ends_the_worker(qtbot, make_host):
    host = make_host()
    running: list[dict] = []
    queued: list[dict] = []
    host.submit(ipc.JOB_PING, {"op": "hang"}, running.append, timeout_s=60.0)
    host.submit(ipc.JOB_PING, {"op": "echo"}, queued.append, timeout_s=60.0)
    qtbot.waitUntil(lambda: host._current is not None and host._current.acked, timeout=WAIT_MS)

    host.stop(graceful=False)

    assert running[0]["error"] == ipc.ERR_CANCELLED
    assert queued[0]["error"] == ipc.ERR_CANCELLED
    assert host.worker_running is False


def test_graceful_stop_lets_an_idle_worker_exit_by_itself(qtbot, make_host):
    host = make_host()
    _, results = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, results)
    proc = host._proc

    started = time.monotonic()
    host.stop(graceful=True)

    assert time.monotonic() - started < 5
    assert host.worker_running is False
    assert proc is not None


# ----- WorkerScraper (the HeadlessScraper stand-in) -----


def test_worker_scraper_maps_results_to_the_done_signal(qtbot, make_host, monkeypatch):
    host = make_host()
    monkeypatch.setattr(host_module, "_host", host)
    seen: list[tuple] = []

    original_submit = host.submit

    def submit_ping(kind, params, on_result, **kwargs):
        # The fake worker understands ping ops, not scrape jobs.
        return original_submit(ipc.JOB_PING, {"op": "echo", "value": 5}, on_result, **kwargs)

    monkeypatch.setattr(host, "submit", submit_ping)
    scraper = WorkerScraper("claude", "https://example.test", "1+1")
    scraper.done.connect(lambda result, error: seen.append((result, error)))
    qtbot.waitUntil(lambda: bool(seen), timeout=WAIT_MS)

    assert seen[0][1] == ""


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"ok": True, "result": {"a": 1}, "error": ""}, ({"a": 1}, "")),
        ({"ok": True, "result": None, "error": "timeout"}, (None, "timeout")),
        (
            {"ok": False, "error": ipc.ERR_TIMEOUT},
            (None, "the browser helper process stopped responding"),
        ),
    ],
)
def test_worker_scraper_finish_mapping(qtbot, make_host, monkeypatch, result, expected):
    host = make_host()
    monkeypatch.setattr(host_module, "_host", host)
    monkeypatch.setattr(host, "submit", lambda *a, **k: None)
    scraper = WorkerScraper("claude", "https://example.test", "1+1")
    seen: list[tuple] = []
    scraper.done.connect(lambda r, e: seen.append((r, e)))

    scraper._finish(result)

    assert seen == [expected]


def test_worker_scraper_reports_no_gl_with_the_override_hint(qtbot, make_host, monkeypatch):
    host = make_host()
    monkeypatch.setattr(host_module, "_host", host)
    monkeypatch.setattr(host, "submit", lambda *a, **k: None)
    scraper = WorkerScraper("claude", "https://example.test", "1+1")
    seen: list[tuple] = []
    scraper.done.connect(lambda r, e: seen.append((r, e)))

    scraper._finish({"ok": False, "error": ipc.ERR_NO_GL, "reason": "no GLX/EGL"})

    result, error = seen[0]
    assert result is None
    assert "no GLX/EGL" in error
    assert "AIUSAGECLOCK_FORCE_WEBENGINE=1" in error


# ----- deleting a profile -----


def _make_profile(account_id: str) -> Path:
    from aiusageclock.config import webview_profile_dir

    path = webview_profile_dir(account_id)
    (path / "cache").mkdir(parents=True)
    (path / "Cookies").write_bytes(b"x")
    (path / "Local Storage").mkdir()
    return path


def test_delete_profile_removes_the_whole_directory():
    path = _make_profile("claude")

    assert profile_cleanup.delete_profile("claude") is True

    assert not path.exists()
    assert profile_cleanup.read_pending() == []


def test_locked_profile_is_queued_and_removed_later(monkeypatch):
    path = _make_profile("claude-work")
    real_rmtree = profile_cleanup.shutil.rmtree

    def locked(target, *args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(profile_cleanup.shutil, "rmtree", locked)

    assert profile_cleanup.delete_profile("claude-work", retries=2, delay_s=0) is False
    assert path.exists()
    assert profile_cleanup.read_pending() == ["claude-work"]

    monkeypatch.setattr(profile_cleanup.shutil, "rmtree", real_rmtree)
    assert profile_cleanup.process_pending() == ["claude-work"]
    assert not path.exists()
    assert profile_cleanup.read_pending() == []


def test_delete_profile_refuses_path_tricks():
    with pytest.raises(ValueError):
        profile_cleanup.delete_profile("..")
    with pytest.raises(ValueError):
        profile_cleanup.delete_profile("a/b")


def test_pending_deletion_runs_before_the_next_worker_starts(qtbot, make_host, monkeypatch):
    path = _make_profile("codex")
    profile_cleanup._write_pending(["codex"])
    host = make_host()
    _, results = _submit(host, qtbot, {"op": "echo"})
    _wait(qtbot, results)

    assert not path.exists()
    assert profile_cleanup.read_pending() == []


def test_clear_browser_session_stops_the_worker_then_deletes_the_profile(monkeypatch):
    path = _make_profile("claude")
    events: list[str] = []

    class FakeHost:
        def release_profile(self, account_id):
            events.append(f"release:{account_id}:{path.exists()}")

    monkeypatch.setattr(host_module, "_host", FakeHost())
    monkeypatch.setattr(cookies, "set_provider_cookie", lambda account_id, value: events.append("secret"))

    cookies.clear_browser_session("claude")

    assert events == ["secret", "release:claude:True"]
    assert not path.exists()


# ----- review fixes: the scraper stand-in is deleted, sign-out is reported -----


def test_worker_scraper_is_deleted_once_it_has_reported(qtbot, make_host, monkeypatch):
    from PyQt6.QtCore import QCoreApplication, QEvent, QObject

    host = make_host()
    monkeypatch.setattr(host_module, "_host", host)
    monkeypatch.setattr(host, "submit", lambda *a, **k: None)
    owner = QObject()  # stands in for the long-lived App the providers hang off

    for result in (
        {"ok": True, "result": {"a": 1}, "error": ""},
        {"ok": False, "error": ipc.ERR_CRASHED},
        {"ok": False, "error": ipc.ERR_NO_GL, "reason": "none"},
    ):
        WorkerScraper("claude", "https://example.test", "1+1", parent=owner)._finish(result)
    assert len(owner.findChildren(WorkerScraper)) == 3

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

    assert owner.findChildren(WorkerScraper) == []


def test_clear_browser_session_reports_a_profile_that_stays_locked(monkeypatch):
    path = _make_profile("claude")
    monkeypatch.setattr(host_module, "_host", None)
    monkeypatch.setattr(cookies, "set_provider_cookie", lambda account_id, value: None)
    monkeypatch.setattr(profile_cleanup, "_RETRIES", 1)

    def locked(target, *args, **kwargs):
        raise PermissionError("the file is in use by another process")

    monkeypatch.setattr(profile_cleanup.shutil, "rmtree", locked)

    with pytest.raises(RuntimeError, match="in use by another process"):
        cookies.clear_browser_session("claude")

    assert path.exists()
    assert profile_cleanup.read_pending() == ["claude"], "still queued for the next start"


def test_ensure_not_pending_finishes_a_queued_deletion_or_reports_why_not(monkeypatch):
    path = _make_profile("claude-work")
    profile_cleanup._write_pending(["claude-work"])
    real_rmtree = profile_cleanup.shutil.rmtree

    def locked(target, *args, **kwargs):
        raise PermissionError("still locked")

    monkeypatch.setattr(profile_cleanup.shutil, "rmtree", locked)
    monkeypatch.setattr(profile_cleanup, "_RETRIES", 1)
    assert "still locked" in profile_cleanup.ensure_not_pending("claude-work")
    assert path.exists()

    monkeypatch.setattr(profile_cleanup.shutil, "rmtree", real_rmtree)
    assert profile_cleanup.ensure_not_pending("claude-work") is None
    assert not path.exists()
    assert profile_cleanup.read_pending() == []
    assert profile_cleanup.ensure_not_pending("never-listed") is None


def test_stale_sign_in_profiles_are_removed(tmp_path):
    from aiusageclock.config import app_data_dir

    root = app_data_dir() / "browser-signin"
    (root / "claude-abc123" / "Default").mkdir(parents=True)
    (root / "claude-abc123" / "Default" / "Cookies").write_bytes(b"session")
    (root / "codex-xyz").mkdir()

    assert profile_cleanup.cleanup_stale_signin_profiles() == 2

    assert list(root.iterdir()) == []
    assert profile_cleanup.cleanup_stale_signin_profiles() == 0
