"""A stand-in for the WebEngine worker, for testing WorkerHost.

Speaks the real wire protocol (aiusageclock.webview.ipc) but never loads a
browser, so the host's queueing, watchdog, crash and idle handling can be tested
quickly and on any machine. Behaviour per job comes from the job's params
(``op``); a few environment variables change how the process itself behaves:

* FAKE_WORKER_BAD_TOKEN=1   send a wrong token in the hello
* FAKE_WORKER_NO_HELLO=1    connect but never say hello
* FAKE_WORKER_EXIT_AT_START=1  exit immediately without connecting
* FAKE_WORKER_IDLE_EXIT_MS=n   exit n ms after the welcome / last result
* FAKE_WORKER_SHUTDOWN_MARK=path  write a file when a shutdown message arrives
* FAKE_WORKER_IGNORE_SHUTDOWN=1   keep running after a shutdown message (a hung worker)
* FAKE_WORKER_DIE_ONCE=path  the first worker to get a job exits before acknowledging it
  (it creates `path`; later workers see the file and behave normally)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import QCoreApplication, QTimer  # noqa: E402
from PyQt6.QtNetwork import QLocalSocket  # noqa: E402

from aiusageclock.webview import ipc  # noqa: E402


def _arg(name: str) -> str:
    argv = sys.argv
    return argv[argv.index(name) + 1]


def main() -> int:
    if os.environ.get("FAKE_WORKER_EXIT_AT_START") == "1":
        return 9
    app = QCoreApplication(sys.argv)
    name = _arg(ipc.ARG_IPC)
    token = _arg(ipc.ARG_TOKEN)
    sock = QLocalSocket()
    buffer = ipc.LineBuffer()
    idle_ms = int(os.environ.get("FAKE_WORKER_IDLE_EXIT_MS", "0"))
    idle = QTimer()
    idle.setSingleShot(True)
    idle.timeout.connect(lambda: app.exit(0))

    def send(message: dict) -> None:
        sock.write(ipc.encode(message))
        sock.flush()

    def start_idle() -> None:
        if idle_ms:
            idle.start(idle_ms)

    def run_job(message: dict) -> None:
        job_id = message["id"]
        params = message.get("params") or {}
        op = params.get("op") or {
            ipc.JOB_LOGIN: "login_ok",
            ipc.JOB_INJECT_VERIFY: "inject_ok",
            ipc.JOB_SCRAPE: "scrape_empty",
        }.get(message.get("kind"), "echo")
        idle.stop()
        marker = os.environ.get("FAKE_WORKER_DIE_ONCE")
        if marker and not os.path.exists(marker):
            Path(marker).write_text("died", encoding="utf-8")
            os._exit(0)
        send({"type": ipc.MSG_ACK, "id": job_id})

        def finish(result: dict) -> None:
            send({"type": ipc.MSG_RESULT, "id": job_id, "result": result})
            start_idle()

        if op == "echo":
            finish({"ok": True, "echo": params.get("value"), "pid": os.getpid()})
        elif op == "sleep":
            QTimer.singleShot(
                int(params.get("ms", 100)),
                lambda: finish({"ok": True, "pid": os.getpid()}),
            )
        elif op == "hang":
            pass
        elif op == "crash":
            os._exit(7)
        elif op == "event":
            send({"type": ipc.MSG_EVENT, "id": job_id, "event": "hello", "value": 1})
            finish({"ok": True})
        elif op == "login_ok":
            finish({"ok": True, "accepted": True, "session_may_have_changed": True})
        elif op == "inject_ok":
            finish({"ok": True, "injected": True, "verified": True, "verify_error": ""})
        elif op == "scrape_empty":
            finish({"ok": True, "result": None, "error": "no data extracted"})
        elif op == "no_gl":
            finish({"ok": False, "error": ipc.ERR_NO_GL, "reason": "fake: no GL"})
        else:
            finish({"ok": False, "error": "unknown_op", "detail": op})

    def on_ready() -> None:
        for message in buffer.feed(bytes(sock.readAll())):
            kind = message.get("type")
            if kind == ipc.MSG_WELCOME:
                start_idle()
            elif kind == ipc.MSG_JOB:
                run_job(message)
            elif kind == ipc.MSG_SHUTDOWN:
                mark = os.environ.get("FAKE_WORKER_SHUTDOWN_MARK")
                if mark:
                    Path(mark).write_text("shutdown", encoding="utf-8")
                if os.environ.get("FAKE_WORKER_IGNORE_SHUTDOWN") == "1":
                    continue
                app.exit(0)

    def on_connected() -> None:
        if os.environ.get("FAKE_WORKER_NO_HELLO") == "1":
            return
        wrong = os.environ.get("FAKE_WORKER_BAD_TOKEN") == "1"
        send({"type": ipc.MSG_HELLO, "token": "wrong" if wrong else token, "pid": os.getpid()})

    sock.connected.connect(on_connected)
    sock.readyRead.connect(on_ready)
    sock.disconnected.connect(lambda: app.exit(0))
    QTimer.singleShot(15000, lambda: app.exit(5))  # never outlive a failed test
    sock.connectToServer(name)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
