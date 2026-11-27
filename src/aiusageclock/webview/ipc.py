"""Wire format between the main process and a WebEngine worker process.

The main process never imports QtWebEngine (it is Chromium, and it keeps
hundreds of megabytes resident for as long as the process lives). Anything that
needs a browser runs in a short-lived worker started from the same executable
with ``--webengine-worker``. The two sides talk over a ``QLocalServer`` /
``QLocalSocket`` pair using UTF-8 JSON lines; stdout is not used because the
windowed PyInstaller builds may not have one.

This module is imported by both sides and must stay free of Qt.
"""

from __future__ import annotations

import json
from typing import Any

# Command line.
ARG_WORKER = "--webengine-worker"
ARG_IPC = "--ipc"
ARG_TOKEN = "--token"
ARG_SELFTEST = "--selftest"
ARG_ALLOW_NO_GL = "--allow-no-gl"

# Message types, main -> worker.
MSG_WELCOME = "welcome"
MSG_JOB = "job"
MSG_SHUTDOWN = "shutdown"
MSG_FOCUS = "focus"

# Message types, worker -> main.
MSG_HELLO = "hello"
MSG_ACK = "ack"
MSG_RESULT = "result"
MSG_EVENT = "event"

# Job kinds.
JOB_SCRAPE = "scrape"
JOB_LOGIN = "login"
JOB_INJECT_VERIFY = "inject_verify"
JOB_SELFTEST = "selftest"
JOB_PING = "ping"  # no browser at all; used to test the transport

# Error codes in a result's "error" field (host-generated unless noted).
ERR_NO_GL = "no_gl"  # worker: Qt cannot get a GL context in this session
ERR_TIMEOUT = "worker_timeout"
ERR_CRASHED = "worker_crashed"
ERR_START_FAILED = "worker_start_failed"
ERR_CANCELLED = "cancelled"
ERR_UNKNOWN_JOB = "unknown_job"  # worker: a job kind it does not know
ERR_WORKER_ERROR = "worker_error"  # worker: a job raised an exception
ERR_PROFILE_LOCKED = "profile_locked"  # worker: the profile folder could not be deleted yet
ERR_SELFTEST_TIMEOUT = "selftest_timeout"  # worker: the self-test page never finished loading
ERR_SELFTEST_LOAD = "selftest_load"  # worker: the self-test page failed to load
ERR_SELFTEST_MISMATCH = "selftest_mismatch"  # worker: the JavaScript result was not the expected one

# Seconds a single job may run before the host kills the worker.
SCRAPE_TIMEOUT_S = 120.0
INJECT_VERIFY_TIMEOUT_S = 60.0
LOGIN_TIMEOUT_S = 30 * 60.0
SELFTEST_TIMEOUT_S = 60.0
PING_TIMEOUT_S = 15.0

# A worker with nothing to do exits on its own after this long.
WORKER_IDLE_EXIT_S = 15.0


def encode(message: dict[str, Any]) -> bytes:
    """One message as a single newline-terminated JSON line (ASCII only)."""
    return json.dumps(message, ensure_ascii=True, default=str).encode("ascii") + b"\n"


class LineBuffer:
    """Accumulates socket bytes and yields complete JSON messages."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._pending += data
        messages: list[dict[str, Any]] = []
        while True:
            newline = self._pending.find(b"\n")
            if newline < 0:
                break
            line, self._pending = self._pending[:newline], self._pending[newline + 1 :]
            line = line.strip()
            if not line:
                continue
            try:
                decoded = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(decoded, dict):
                messages.append(decoded)
        return messages
