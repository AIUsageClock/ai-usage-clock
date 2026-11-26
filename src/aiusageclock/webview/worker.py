"""The WebEngine worker: the only process that ever loads QtWebEngine.

Started by :class:`aiusageclock.webview.host.WorkerHost` as
``<same executable> --webengine-worker --ipc <name> --token <secret>``. It
connects back over a local socket, runs the jobs it is sent one at a time
(scrape, sign in, inject a pasted cookie and verify it) and exits when told to
or after sitting idle, which hands Chromium's memory back to the OS.

``--webengine-worker --selftest`` runs one browser round trip without any
parent process, for CI and for checking a packaged build.
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Callable

from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QTimer
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication, QDialog

from ..config import COOKIE_NAMES, Config, account_kind, app_data_dir, get_provider_cookie
from ..identity import LOGGER_NAME, QT_APPLICATION_NAME, QT_ORGANIZATION_NAME
from . import ipc
from . import runtime

log = logging.getLogger("aiusageclock.webview.worker")

WORKER_LOG_FILENAME = "worker.log"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NO_GL = 3
EXIT_NO_PARENT = 4

# Time allowed for the parent to accept the connection.
_CONNECT_DEADLINE_MS = 20_000
# A cookie written to the store reaches disk a moment later; give it that
# moment before the process (and with it the store) goes away.
_COOKIE_COMMIT_MS = 800

Finish = Callable[[dict[str, Any]], None]


def _setup_logging() -> None:
    """Log to ``worker.log``, separate from the main process's rotating log."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if getattr(logger, "_aiusageclock_worker_initialized", False):
        return
    path = app_data_dir() / WORKER_LOG_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            path, maxBytes=256 * 1024, backupCount=1, encoding="utf-8", delay=True
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] [worker %(process)d] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        # A native crash inside Chromium leaves no Python traceback; this puts
        # the stacks next to the log lines.
        crash_file = open(  # noqa: SIM115 - kept open for the life of the process
            path.with_name(WORKER_LOG_FILENAME + ".crash"), "a", encoding="utf-8"
        )
        faulthandler.enable(file=crash_file)
    except OSError:
        logger.addHandler(logging.StreamHandler())
    logger._aiusageclock_worker_initialized = True  # type: ignore[attr-defined]


def _bring_to_front(widget) -> None:
    """Show a window and take focus, including from a background agent app."""
    widget.show()
    widget.raise_()
    widget.activateWindow()
    if sys.platform == "darwin":
        # An agent app (LSUIElement) is not frontmost, so Qt's activateWindow
        # alone leaves the sign-in window behind other apps.
        try:
            from AppKit import NSApplication  # type: ignore[import-not-found]

            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:  # noqa: BLE001 - pyobjc missing or too old
            log.info("could not activate the app through AppKit")


def _account_kind(account_id: str) -> str | None:
    try:
        kind = account_kind(Config.load(), account_id)
    except Exception:  # noqa: BLE001
        kind = None
    if kind is None and account_id in COOKIE_NAMES:
        kind = account_id
    return kind


class JobRunner(QObject):
    """Runs one job at a time and reports through a ``finish`` callback."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._login_dialog: QDialog | None = None

    # ----- dispatch -----

    def run(self, kind: str, params: dict[str, Any], finish: Finish, events: Finish) -> None:
        handlers = {
            ipc.JOB_PING: self._ping,
            ipc.JOB_SCRAPE: self._scrape,
            ipc.JOB_LOGIN: self._login,
            ipc.JOB_INJECT_VERIFY: self._inject_verify,
            ipc.JOB_SELFTEST: self._selftest,
        }
        handler = handlers.get(kind)
        if handler is None:
            finish({"ok": False, "error": "unknown_job", "detail": kind})
            return
        done = {"flag": False}

        def _once(result: dict[str, Any]) -> None:
            if done["flag"]:
                return
            done["flag"] = True
            finish(result)

        try:
            handler(params, _once, events)
        except Exception as exc:  # noqa: BLE001 - report instead of dying silently
            log.exception("job failed kind=%s", kind)
            _once({"ok": False, "error": "worker_error", "detail": f"{type(exc).__name__}: {exc}"})

    def focus_login(self) -> None:
        if self._login_dialog is not None:
            _bring_to_front(self._login_dialog)

    def release_browser_state(self) -> None:
        """Destroy cached profiles so Chromium flushes them before exit."""
        module = sys.modules.get("aiusageclock.webview.profile")
        if module is None:
            return
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        module._profiles.clear()

    # ----- helpers -----

    @staticmethod
    def _gl_ok(finish: Finish) -> bool:
        available, reason = runtime.probe()
        if not available:
            finish({"ok": False, "error": ipc.ERR_NO_GL, "reason": reason})
        return available

    # ----- jobs -----

    def _ping(self, params: dict[str, Any], finish: Finish, events: Finish) -> None:
        finish({"ok": True, "pid": os.getpid(), "echo": params.get("echo")})

    def _scrape(self, params: dict[str, Any], finish: Finish, events: Finish) -> None:
        if not self._gl_ok(finish):
            return
        provider = str(params["provider"])
        kind = _account_kind(provider)
        if kind in ("claude", "codex"):
            from .cookies import hydrate_account_from_keyring

            try:
                hydrate_account_from_keyring(kind, provider)
            except Exception:  # noqa: BLE001 - scrape anyway, signed out at worst
                log.exception("cookie hydration failed provider=%s", provider)

        from .scraper import HeadlessScraper

        scraper = HeadlessScraper(
            provider=provider,
            url=str(params["url"]),
            extractor_js=str(params["extractor_js"]),
            wait_ms=int(params.get("wait_ms", 4000)),
            timeout_ms=int(params.get("timeout_ms", 25000)),
            max_attempts=int(params.get("max_attempts", 1)),
            parent=self,
        )
        scraper.done.connect(
            lambda result, error: finish({"ok": True, "result": result, "error": error})
        )

    def _login(self, params: dict[str, Any], finish: Finish, events: Finish) -> None:
        if not self._gl_ok(finish):
            return
        from .login_window import LoginWindow

        dialog = LoginWindow(
            str(params["kind"]),
            str(params["url"]),
            str(params["title"]),
            account_id=str(params["account_id"]),
            browser_preference=str(params.get("browser_preference", "ask")),
        )
        self._login_dialog = dialog
        dialog.browser_preference_changed.connect(
            lambda value: events({"event": "browser_preference", "value": value})
        )

        def _closed(code: int) -> None:
            self._login_dialog = None
            accepted = code == QDialog.DialogCode.Accepted.value
            changed = bool(getattr(dialog, "session_may_have_changed", False))
            dialog.deleteLater()
            if accepted or changed:
                # A cookie written just before the window closed still has to
                # reach disk before the worker is allowed to exit.
                QTimer.singleShot(
                    _COOKIE_COMMIT_MS,
                    lambda: finish(
                        {"ok": True, "accepted": accepted, "session_may_have_changed": changed}
                    ),
                )
            else:
                finish({"ok": True, "accepted": False, "session_may_have_changed": False})

        dialog.finished.connect(_closed)
        _bring_to_front(dialog)

    def _inject_verify(self, params: dict[str, Any], finish: Finish, events: Finish) -> None:
        if not self._gl_ok(finish):
            return
        from .cookies import inject_session_cookie

        kind = str(params["kind"])
        account_id = str(params["account_id"])
        value = get_provider_cookie(account_id) or ""
        injected = bool(inject_session_cookie(kind, value, account_id=account_id)) if value else False
        if not injected or not params.get("verify", True):
            QTimer.singleShot(
                _COOKIE_COMMIT_MS, lambda: finish({"ok": True, "injected": injected})
            )
            return

        def _start_verify() -> None:
            from .verify import verify_session

            self._verifier = verify_session(
                kind,
                lambda ok, error: finish(
                    {"ok": True, "injected": True, "verified": ok, "verify_error": error}
                ),
                account_id=account_id,
                parent=self,
                verify_url=params.get("verify_url") or None,
            )

        # Same pause the paste dialog always had: let the store take the cookie.
        QTimer.singleShot(500, _start_verify)

    def _selftest(self, params: dict[str, Any], finish: Finish, events: Finish) -> None:
        if not self._gl_ok(finish):
            return
        from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

        # An unnamed profile is off the record: no files, no shared state.
        profile = QWebEngineProfile(self)
        page = QWebEnginePage(profile, self)
        state = {"done": False}

        def _end(result: dict[str, Any]) -> None:
            if state["done"]:
                return
            state["done"] = True
            timeout.stop()
            result.setdefault("title", page.title())
            page.deleteLater()
            profile.deleteLater()
            finish(result)

        timeout = QTimer(self)
        timeout.setSingleShot(True)
        timeout.timeout.connect(
            lambda: _end({"ok": False, "error": "selftest_timeout", "detail": "page did not finish loading"})
        )
        timeout.start(30_000)

        def _loaded(ok: bool) -> None:
            if not ok:
                _end({"ok": False, "error": "selftest_load", "detail": "data page failed to load"})
                return
            page.runJavaScript(
                "document.getElementById('x').textContent + ':' + (6 * 7)",
                lambda value: _end(
                    {
                        "ok": value == "hello:42",
                        "result": value,
                        "error": "" if value == "hello:42" else "selftest_mismatch",
                    }
                ),
            )

        page.loadFinished.connect(_loaded)
        page.setHtml("<!doctype html><title>aiusageclock-selftest</title><p id=x>hello</p>")


class Worker(QObject):
    """Socket side: receives jobs from the host and sends results back."""

    def __init__(self, ipc_name: str, token: str):
        super().__init__()
        self._ipc_name = ipc_name
        self._token = token
        self._buffer = ipc.LineBuffer()
        self._runner = JobRunner(self)
        self._job_id: int | None = None
        self._connected = False
        self.exit_code = EXIT_OK

        self._sock = QLocalSocket(self)
        self._sock.connected.connect(self._on_connected)
        self._sock.readyRead.connect(self._on_ready)
        self._sock.disconnected.connect(self._on_disconnected)
        self._sock.errorOccurred.connect(self._on_socket_error)

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._on_idle)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._on_deadline)

    def start(self) -> None:
        self._deadline.start(_CONNECT_DEADLINE_MS)
        self._sock.connectToServer(self._ipc_name)

    # ----- socket -----

    def _send(self, message: dict[str, Any]) -> None:
        self._sock.write(ipc.encode(message))
        self._sock.flush()

    def _on_connected(self) -> None:
        self._connected = True
        self._send({"type": ipc.MSG_HELLO, "token": self._token, "pid": os.getpid()})

    def _on_socket_error(self, _error) -> None:
        if not self._connected:
            log.error("could not connect to the parent: %s", self._sock.errorString())
            self._quit(EXIT_NO_PARENT)

    def _on_deadline(self) -> None:
        if not self._connected:
            log.error("parent did not answer in time")
            self._quit(EXIT_NO_PARENT)

    def _on_disconnected(self) -> None:
        log.info("parent disconnected; exiting")
        self._quit(EXIT_OK, flush=False)

    def _on_ready(self) -> None:
        for message in self._buffer.feed(bytes(self._sock.readAll())):
            kind = message.get("type")
            if kind == ipc.MSG_WELCOME:
                self._deadline.stop()
                self._idle.start(int(ipc.WORKER_IDLE_EXIT_S * 1000))
            elif kind == ipc.MSG_JOB:
                self._start_job(message)
            elif kind == ipc.MSG_FOCUS:
                self._runner.focus_login()
            elif kind == ipc.MSG_SHUTDOWN:
                log.info("shutdown requested")
                self._quit(EXIT_OK)

    def _start_job(self, message: dict[str, Any]) -> None:
        job_id = message.get("id")
        if not isinstance(job_id, int) or self._job_id is not None:
            return
        self._job_id = job_id
        self._idle.stop()
        self._send({"type": ipc.MSG_ACK, "id": job_id})
        kind = str(message.get("kind"))
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        log.info("job start id=%s kind=%s", job_id, kind)

        def _finish(result: dict[str, Any]) -> None:
            log.info("job done id=%s kind=%s ok=%s error=%s", job_id, kind, result.get("ok"), result.get("error"))
            self._send({"type": ipc.MSG_RESULT, "id": job_id, "result": result})
            self._job_id = None
            self._idle.start(int(ipc.WORKER_IDLE_EXIT_S * 1000))

        def _event(payload: dict[str, Any]) -> None:
            self._send({"type": ipc.MSG_EVENT, "id": job_id, **payload})

        self._runner.run(kind, params, _finish, _event)

    # ----- exit -----

    def _on_idle(self) -> None:
        log.info("idle; exiting")
        self._quit(EXIT_OK)

    def _quit(self, code: int, *, flush: bool = True) -> None:
        self.exit_code = code
        self._idle.stop()
        self._deadline.stop()
        if flush:
            self._runner.release_browser_state()
            # Chromium commits cookies on its own schedule and when a profile
            # is destroyed; the short wait lets the destruction finish.
            QTimer.singleShot(300, lambda: QCoreApplication.exit(code))
        else:
            QCoreApplication.exit(code)


def _parse_args(argv: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {"selftest": False, "allow_no_gl": False, "ipc": None, "token": None}
    items = list(argv)
    index = 0
    while index < len(items):
        item = items[index]
        if item == ipc.ARG_SELFTEST:
            args["selftest"] = True
        elif item == ipc.ARG_ALLOW_NO_GL:
            args["allow_no_gl"] = True
        elif item in (ipc.ARG_IPC, ipc.ARG_TOKEN) and index + 1 < len(items):
            args["ipc" if item == ipc.ARG_IPC else "token"] = items[index + 1]
            index += 1
        index += 1
    return args


def _run_selftest(allow_no_gl: bool) -> int:
    runner = JobRunner()
    outcome = {"code": EXIT_FAILED}

    def _finish(result: dict[str, Any]) -> None:
        code = EXIT_OK if result.get("ok") else EXIT_FAILED
        if result.get("error") == ipc.ERR_NO_GL:
            code = EXIT_OK if allow_no_gl else EXIT_NO_GL
        outcome["code"] = code
        line = "WORKER-SELFTEST " + json.dumps(result, default=str)
        log.info(line)
        if sys.stdout is not None:
            try:
                print(line, flush=True)
            except OSError:
                pass
        runner.release_browser_state()
        QTimer.singleShot(300, lambda: QCoreApplication.exit(code))

    QTimer.singleShot(
        0, lambda: runner.run(ipc.JOB_SELFTEST, {}, _finish, lambda _payload: None)
    )
    QCoreApplication.exec()
    return outcome["code"]


def run(argv: list[str]) -> int:
    """Entry point for ``--webengine-worker`` (called from ``app.main``)."""
    args = _parse_args(argv)
    if not args["selftest"] and not (args["ipc"] and args["token"]):
        return EXIT_USAGE
    _setup_logging()

    from PyQt6.QtCore import Qt

    # Same two pre-QApplication settings as the main process: Chromium needs
    # shared GL contexts, and the UI scale decides the sign-in window's size.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from ..app import _apply_ui_scale_env

    _apply_ui_scale_env()

    qt_app = QApplication([sys.argv[0]])
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setApplicationName(QT_APPLICATION_NAME)
    qt_app.setOrganizationName(QT_ORGANIZATION_NAME)

    if args["selftest"]:
        code = _run_selftest(bool(args["allow_no_gl"]))
    else:
        worker = Worker(str(args["ipc"]), str(args["token"]))
        QTimer.singleShot(0, worker.start)
        qt_app.exec()
        code = worker.exit_code
    log.info("worker exiting code=%s", code)
    logging.shutdown()
    # Skip interpreter teardown: PyQt's finalisation of QtWebEngine objects can
    # crash after everything useful has already been written.
    os._exit(code)
