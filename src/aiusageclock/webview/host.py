"""Main-process side of the WebEngine worker: queue, process and transport.

Nothing here imports QtWebEngine. Work that needs a browser is described as a
job, handed to :class:`WorkerHost`, and run by a worker process started from
the same executable (see :mod:`aiusageclock.webview.worker`). The host keeps at
most one worker alive, runs jobs one at a time (so two processes never open the
same browser profile), starts the worker for the first job, and shuts it down
shortly after the queue empties so Chromium's memory goes back to the OS.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from ..identity import ENV_FORCE_WEBENGINE
from ..platforms import autostart_command
from . import ipc, profile_cleanup

log = logging.getLogger("aiusageclock.webview.host")

# After the last job the worker is told to exit. A short grace period keeps one
# process for a whole refresh round (each provider's scrape is submitted right
# after the previous one finishes) instead of paying a start per provider.
IDLE_SHUTDOWN_MS = 1500
# How long a worker may take to connect back after it was started.
CONNECT_TIMEOUT_MS = 30_000
# How long a worker may take to exit after being asked to.
SHUTDOWN_GRACE_MS = 8_000

Result = dict[str, Any]
ResultCallback = Callable[[Result], None]


@dataclass(eq=False)
class Job:
    id: int
    kind: str
    params: dict[str, Any]
    on_result: ResultCallback
    timeout_s: float
    account_id: str | None = None
    on_event: Callable[[dict[str, Any]], None] | None = None
    priority: bool = False
    acked: bool = False
    attempts: int = 0
    done: bool = False


def _failure(code: str, detail: str = "") -> Result:
    return {"ok": False, "error": code, "detail": detail}


class WorkerHost(QObject):
    """Owns the worker process and the queue of jobs waiting for it."""

    def __init__(
        self,
        *,
        command: Callable[[], list[str]] | None = None,
        idle_shutdown_ms: int = IDLE_SHUTDOWN_MS,
        connect_timeout_ms: int = CONNECT_TIMEOUT_MS,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._command = command or autostart_command
        self._idle_shutdown_ms = idle_shutdown_ms
        self._connect_timeout_ms = connect_timeout_ms
        self._queue: deque[Job] = deque()
        self._current: Job | None = None
        self._next_id = 1
        self._proc: QProcess | None = None
        self._server: QLocalServer | None = None
        self._sock: QLocalSocket | None = None
        self._token = ""
        self._ready = False
        self._ever_ready = False
        self._shutting_down = False
        self._kill_reason: str | None = None

        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._begin_shutdown)
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._on_connect_timeout)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._on_shutdown_overdue)

    # ----- public API -----

    @property
    def worker_running(self) -> bool:
        return self._proc is not None

    def submit(
        self,
        kind: str,
        params: dict[str, Any],
        on_result: ResultCallback,
        *,
        timeout_s: float,
        account_id: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        priority: bool = False,
    ) -> Job:
        """Queue a job. ``on_result`` is always called, never from inside here.

        ``priority`` jobs (anything a person is waiting on) go ahead of queued
        background work but never interrupt the job that is already running.
        """
        job = Job(
            id=self._next_id,
            kind=kind,
            params=params,
            on_result=on_result,
            timeout_s=timeout_s,
            account_id=account_id,
            on_event=on_event,
            priority=priority,
        )
        self._next_id += 1
        if priority:
            index = 0
            for index, queued in enumerate(self._queue):
                if not queued.priority:
                    break
            else:
                index = len(self._queue)
            self._queue.insert(index, job)
        else:
            self._queue.append(job)
        self._idle_timer.stop()
        QTimer.singleShot(0, self._pump)
        return job

    def cancel(self, job: Job) -> None:
        """Cancel a queued or running job; a running one costs the worker."""
        if job.done:
            return
        if job in self._queue:
            self._queue.remove(job)
            self._deliver_later(job, _failure(ipc.ERR_CANCELLED))
            return
        if job is self._current and self._proc is not None:
            self._kill_worker(ipc.ERR_CANCELLED)

    def focus_job(self, kind: str) -> bool:
        """Ask the worker to bring a running job's window to the front."""
        current = self._current
        if current is None or current.kind != kind or not self._ready:
            return False
        self._send({"type": ipc.MSG_FOCUS, "id": current.id})
        return True

    def release_profile(self, account_id: str) -> None:
        """Make sure no worker holds ``account_id``'s profile open.

        Queued jobs for the account are cancelled. A live worker is killed
        (its profile directory is about to be deleted, so there is nothing
        worth flushing); a running job for a different account is put back at
        the front of the queue to run on the next worker.
        """
        for job in [j for j in self._queue if j.account_id == account_id]:
            self._queue.remove(job)
            self._deliver_later(job, _failure(ipc.ERR_CANCELLED))
        if self._proc is None:
            return
        current = self._current
        self._current = None
        self._watchdog.stop()
        self._terminate_worker(graceful=False, wait_ms=3000)
        if current is not None:
            if current.account_id == account_id:
                self._deliver_later(current, _failure(ipc.ERR_CANCELLED))
            else:
                current.acked = False
                self._queue.appendleft(current)
        if self._queue:
            QTimer.singleShot(0, self._pump)

    def stop(self, *, graceful: bool = True, wait_ms: int = 8000) -> None:
        """Cancel everything and end the worker (application quit)."""
        self._idle_timer.stop()
        pending = list(self._queue)
        self._queue.clear()
        current = self._current
        self._current = None
        self._watchdog.stop()
        self._terminate_worker(graceful=graceful, wait_ms=wait_ms)
        if current is not None:
            pending.append(current)
        for job in pending:
            self._deliver(job, _failure(ipc.ERR_CANCELLED))

    # ----- delivery -----

    def _deliver(self, job: Job, result: Result) -> None:
        if job.done:
            return
        job.done = True
        try:
            job.on_result(result)
        except Exception:  # noqa: BLE001 - one bad callback must not stall the queue
            log.exception("worker job callback failed kind=%s", job.kind)

    def _deliver_later(self, job: Job, result: Result) -> None:
        QTimer.singleShot(0, lambda: self._deliver(job, result))

    # ----- dispatch -----

    def _pump(self) -> None:
        if self._current is not None or not self._queue or self._shutting_down:
            return
        if self._proc is None:
            self._start_worker()
            return
        if not self._ready:
            return
        job = self._queue.popleft()
        self._current = job
        job.acked = False
        if job.kind == ipc.JOB_LOGIN:
            self._allow_worker_foreground()
        self._send(
            {"type": ipc.MSG_JOB, "id": job.id, "kind": job.kind, "params": job.params}
        )
        self._watchdog.start(max(1, int(job.timeout_s * 1000)))
        log.info("worker job dispatched id=%s kind=%s account=%s", job.id, job.kind, job.account_id)

    def _allow_worker_foreground(self) -> None:
        """Let the worker's sign-in window take focus from this (foreground) app."""
        if sys.platform != "win32" or self._proc is None:
            return
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(int(self._proc.processId()))
        except Exception:  # noqa: BLE001 - focus is best effort
            log.debug("AllowSetForegroundWindow failed", exc_info=True)

    def _finish_current(self, result: Result) -> None:
        job = self._current
        self._current = None
        self._watchdog.stop()
        if job is not None:
            self._deliver(job, result)
        if self._queue:
            QTimer.singleShot(0, self._pump)
        else:
            self._idle_timer.start(self._idle_shutdown_ms)

    # ----- process -----

    def _start_worker(self) -> None:
        try:
            profile_cleanup.process_pending()
        except Exception:  # noqa: BLE001 - never let cleanup block a refresh
            log.exception("could not process queued profile deletions")

        name = f"aiusageclock-worker-{os.getpid()}-{secrets.token_hex(6)}"
        token = secrets.token_urlsafe(24)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(name)
        if not server.listen(name):
            detail = server.errorString()
            server.deleteLater()
            log.error("worker IPC server could not listen: %s", detail)
            self._fail_all(ipc.ERR_START_FAILED, detail)
            return
        server.newConnection.connect(self._on_new_connection)

        try:
            argv = list(self._command()) + [
                ipc.ARG_WORKER,
                ipc.ARG_IPC,
                name,
                ipc.ARG_TOKEN,
                token,
            ]
        except Exception as exc:  # noqa: BLE001
            server.close()
            server.deleteLater()
            self._fail_all(ipc.ERR_START_FAILED, str(exc))
            return

        proc = QProcess(self)
        proc.setProgram(argv[0])
        proc.setArguments(argv[1:])
        # Nothing is read from the pipes; a full pipe would stall the worker.
        proc.setStandardOutputFile(QProcess.nullDevice())
        proc.setStandardErrorFile(QProcess.nullDevice())
        proc.finished.connect(
            lambda code, status, p=proc: self._on_proc_finished(p, code, int(status.value))
        )
        proc.errorOccurred.connect(lambda error, p=proc: self._on_proc_error(p, error))

        self._proc = proc
        self._server = server
        self._token = token
        self._ready = False
        self._ever_ready = False
        self._shutting_down = False
        self._kill_reason = None
        log.info("starting worker process: %s", argv[0])
        proc.start()
        self._connect_timer.start(self._connect_timeout_ms)

    def _on_new_connection(self) -> None:
        server = self._server
        if server is None:
            return
        while server.hasPendingConnections():
            sock = server.nextPendingConnection()
            if sock is None:
                break
            sock._aa_buffer = ipc.LineBuffer()  # type: ignore[attr-defined]
            sock.readyRead.connect(lambda s=sock: self._on_sock_ready(s))
            sock.disconnected.connect(lambda s=sock: self._on_sock_disconnected(s))

    def _on_sock_ready(self, sock: QLocalSocket) -> None:
        buffer: ipc.LineBuffer = sock._aa_buffer  # type: ignore[attr-defined]
        for message in buffer.feed(bytes(sock.readAll())):
            if sock is not self._sock:
                if not self._authenticate(sock, message):
                    return
                continue
            self._on_message(message)

    def _authenticate(self, sock: QLocalSocket, message: dict[str, Any]) -> bool:
        token = message.get("token")
        if (
            self._sock is not None
            or message.get("type") != ipc.MSG_HELLO
            or not isinstance(token, str)
            or not secrets.compare_digest(token, self._token)
        ):
            log.warning("worker IPC connection rejected (bad hello)")
            sock.abort()
            return False
        self._sock = sock
        self._ready = True
        self._ever_ready = True
        self._connect_timer.stop()
        if self._server is not None:
            self._server.close()
        self._send({"type": ipc.MSG_WELCOME})
        log.info("worker connected pid=%s", message.get("pid"))
        QTimer.singleShot(0, self._pump)
        return True

    def _on_sock_disconnected(self, sock: QLocalSocket) -> None:
        if sock is not self._sock:
            return
        self._sock = None
        self._ready = False
        current = self._current
        if (
            current is not None
            and current.acked
            and self._proc is not None
            and self._kill_reason is None
        ):
            # The worker dropped its connection in the middle of a job but is
            # still alive; it would never answer, so end it now. (Before the
            # ack the process is just leaving; its exit decides what happens.)
            self._kill_worker(ipc.ERR_CRASHED)

    def _send(self, message: dict[str, Any]) -> None:
        sock = self._sock
        if sock is None:
            return
        sock.write(ipc.encode(message))
        sock.flush()

    def _on_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        current = self._current
        if current is None or message.get("id") != current.id:
            return
        if kind == ipc.MSG_ACK:
            current.acked = True
        elif kind == ipc.MSG_EVENT:
            current.acked = True
            if current.on_event is not None:
                try:
                    current.on_event(message)
                except Exception:  # noqa: BLE001
                    log.exception("worker event callback failed")
        elif kind == ipc.MSG_RESULT:
            result = message.get("result")
            if not isinstance(result, dict):
                result = _failure(ipc.ERR_CRASHED, "malformed result")
            self._finish_current(result)

    def _on_watchdog(self) -> None:
        job = self._current
        if job is None:
            return
        log.warning("worker job timed out id=%s kind=%s", job.id, job.kind)
        if self._proc is None:
            self._finish_current(_failure(ipc.ERR_TIMEOUT))
            return
        self._kill_worker(ipc.ERR_TIMEOUT)

    def _on_connect_timeout(self) -> None:
        if self._proc is not None and not self._ever_ready:
            log.warning("worker did not connect in time; killing it")
            self._kill_worker(ipc.ERR_START_FAILED)

    def _kill_worker(self, reason: str) -> None:
        proc = self._proc
        if proc is None:
            return
        self._kill_reason = reason
        proc.kill()

    def _begin_shutdown(self) -> None:
        if self._current is not None or self._queue or self._proc is None:
            return
        if self._ready:
            self._shutting_down = True
            self._send({"type": ipc.MSG_SHUTDOWN})
            self._kill_timer.start(SHUTDOWN_GRACE_MS)
        else:
            self._kill_worker(ipc.ERR_CANCELLED)

    def _on_shutdown_overdue(self) -> None:
        if self._proc is not None and self._shutting_down:
            log.warning("worker did not exit after shutdown; killing it")
            self._kill_worker(ipc.ERR_CANCELLED)

    def _on_proc_error(self, proc: QProcess, error: QProcess.ProcessError) -> None:
        if proc is not self._proc:
            return
        if error == QProcess.ProcessError.FailedToStart:
            self._on_proc_gone(proc, f"failed to start: {proc.errorString()}")

    def _on_proc_finished(self, proc: QProcess, exit_code: int, status: int) -> None:
        if proc is not self._proc:
            return
        self._on_proc_gone(proc, f"exit code {exit_code}, status {status}")

    def _on_proc_gone(self, proc: QProcess, detail: str) -> None:
        reason = self._kill_reason
        was_ready = self._ever_ready
        job = self._current
        self._current = None
        self._watchdog.stop()
        self._detach_process()
        log.info("worker process ended (%s) reason=%s", detail, reason or "-")

        if not was_ready:
            # It never reached the handshake: retrying would loop forever.
            jobs = list(self._queue)
            self._queue.clear()
            if job is not None:
                jobs.insert(0, job)
            for item in jobs:
                self._deliver(item, _failure(ipc.ERR_START_FAILED, detail))
            return

        if job is not None:
            if reason is None and not job.acked and job.attempts < 1:
                # The worker was already leaving (idle exit) when the job
                # arrived; it never started it, so run it on a fresh worker.
                job.attempts += 1
                self._queue.appendleft(job)
            else:
                self._deliver(job, _failure(reason or ipc.ERR_CRASHED, detail))
        if self._queue:
            QTimer.singleShot(0, self._pump)

    def _fail_all(self, code: str, detail: str) -> None:
        jobs = list(self._queue)
        self._queue.clear()
        for job in jobs:
            self._deliver_later(job, _failure(code, detail))

    def _detach_process(self) -> None:
        """Forget the current process, socket and server (not the queue)."""
        self._connect_timer.stop()
        self._kill_timer.stop()
        proc, self._proc = self._proc, None
        sock, self._sock = self._sock, None
        server, self._server = self._server, None
        self._ready = False
        self._ever_ready = False
        self._shutting_down = False
        self._kill_reason = None
        if sock is not None:
            sock.abort()
            sock.deleteLater()
        if server is not None:
            server.close()
            server.deleteLater()
        if proc is not None:
            proc.deleteLater()

    def _terminate_worker(self, *, graceful: bool, wait_ms: int) -> None:
        proc = self._proc
        if proc is None:
            return
        if graceful and self._ready:
            self._send({"type": ipc.MSG_SHUTDOWN})
        # Detach first so the finished signal fired while waiting is ignored.
        self._proc = None
        sock, self._sock = self._sock, None
        server, self._server = self._server, None
        self._connect_timer.stop()
        self._kill_timer.stop()
        self._ready = False
        self._ever_ready = False
        self._shutting_down = False
        self._kill_reason = None
        try:
            if graceful and sock is not None:
                if not proc.waitForFinished(wait_ms):
                    proc.kill()
                    proc.waitForFinished(3000)
            else:
                proc.kill()
                proc.waitForFinished(3000)
        finally:
            if sock is not None:
                sock.abort()
                sock.deleteLater()
            if server is not None:
                server.close()
                server.deleteLater()
            proc.deleteLater()


# ----- shared instance -----

_host: WorkerHost | None = None


def get_host() -> WorkerHost:
    global _host
    if _host is None:
        _host = WorkerHost()
    return _host


def existing_host() -> WorkerHost | None:
    return _host


def set_host(host: WorkerHost | None) -> None:
    """Replace the shared host (tests, and the application's own instance)."""
    global _host
    _host = host


# ----- messages for the places that show a worker failure to the user -----


def no_gl_message(reason: str) -> str:
    return (
        "needs an embedded browser, which this session can't "
        f"start — {reason} "
        # The probe reports whether *Qt* can get a context. Chromium sometimes
        # finds one where Qt cannot, so point at the override rather than
        # leaving a dead end.
        "If this machine does have working OpenGL, set "
        f"{ENV_FORCE_WEBENGINE}=1 to skip this check."
    )


def failure_reason(result: Result) -> str:
    """One line for a job that did not complete (host- or worker-side)."""
    code = str(result.get("error") or "")
    detail = str(result.get("detail") or "")
    if code == ipc.ERR_TIMEOUT:
        return "the browser helper process stopped responding"
    if code == ipc.ERR_CRASHED:
        return "the browser helper process exited unexpectedly" + (
            f" ({detail})" if detail else ""
        )
    if code == ipc.ERR_START_FAILED:
        return "the browser helper process could not be started" + (
            f" ({detail})" if detail else ""
        )
    if code == ipc.ERR_CANCELLED:
        return "cancelled"
    return detail or code or "browser helper failed"


# ----- scraper stand-in -----


class WorkerScraper(QObject):
    """Drop-in for ``HeadlessScraper`` that scrapes inside the worker.

    Same constructor arguments and ``done(object, str)`` signal, so
    ``ScrapeRunner`` (retries, snapshot building) is unchanged.
    """

    done = pyqtSignal(object, str)  # (result_or_None, error_or_empty_string)

    def __init__(
        self,
        provider: str,
        url: str,
        extractor_js: str,
        wait_ms: int = 4000,
        timeout_ms: int = 25000,
        max_attempts: int = 1,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._provider = provider

        def _on_result(result: Result) -> None:
            self._finish(result)

        self._job = get_host().submit(
            ipc.JOB_SCRAPE,
            {
                "provider": provider,
                "url": url,
                "extractor_js": extractor_js,
                "wait_ms": wait_ms,
                "timeout_ms": timeout_ms,
                "max_attempts": max_attempts,
            },
            _on_result,
            timeout_s=ipc.SCRAPE_TIMEOUT_S,
            account_id=provider,
        )

    def _finish(self, result: Result) -> None:
        payload: Any = None
        error = ""
        if result.get("ok"):
            payload = result.get("result")
            error = str(result.get("error") or "")
        elif result.get("error") == ipc.ERR_NO_GL:
            error = no_gl_message(str(result.get("reason") or "no OpenGL context"))
        else:
            error = failure_reason(result)
            log.warning(
                "worker scrape failed provider=%s code=%s detail=%s",
                self._provider,
                result.get("error"),
                result.get("detail"),
            )
        try:
            self.done.emit(payload, error)
        except RuntimeError:
            pass  # the owner was destroyed while the worker was busy
