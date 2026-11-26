"""The real worker process (``python -m aiusageclock --webengine-worker``).

The transport and a no-browser job always run. The browser round trip needs a
GL context, which the offscreen platform used by the test suite does not have,
so it is skipped there. To run it on a desktop session:

    AIUSAGECLOCK_TEST_REAL_WEBENGINE=1 python -m pytest tests/test_worker_integration.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from aiusageclock.webview import ipc
from aiusageclock.webview.host import WorkerHost

SRC = Path(__file__).resolve().parents[1] / "src"
WAIT_MS = 60000


@pytest.fixture
def real_host(qtbot, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    if os.environ.get("AIUSAGECLOCK_TEST_REAL_WEBENGINE") == "1":
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    else:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    host = WorkerHost(
        command=lambda: [sys.executable, "-m", "aiusageclock"],
        idle_shutdown_ms=100,
        connect_timeout_ms=60000,
    )
    yield host
    host.stop(graceful=False, wait_ms=5000)


def _run_job(qtbot, host, kind, params, timeout_s=60.0):
    results: list[dict] = []
    host.submit(kind, params, results.append, timeout_s=timeout_s)
    qtbot.waitUntil(lambda: bool(results), timeout=WAIT_MS)
    return results[0]


def test_real_worker_handshake_runs_a_job_and_exits_when_idle(qtbot, real_host):
    result = _run_job(qtbot, real_host, ipc.JOB_PING, {"echo": "x"})

    assert result["ok"] is True
    assert result["echo"] == "x"
    assert result["pid"] != os.getpid()
    qtbot.waitUntil(lambda: not real_host.worker_running, timeout=30000)


def test_real_worker_browser_round_trip(qtbot, real_host):
    result = _run_job(qtbot, real_host, ipc.JOB_SELFTEST, {})

    if result.get("error") == ipc.ERR_NO_GL:
        pytest.skip(
            "the worker has no OpenGL context here (offscreen test platform): "
            f"{result.get('reason')}"
        )
    assert result["ok"] is True, result
    assert result["result"] == "hello:42"
    qtbot.waitUntil(lambda: not real_host.worker_running, timeout=30000)


def test_worker_selftest_command_line_exits_cleanly_without_a_parent():
    env = dict(os.environ, PYTHONPATH=str(SRC), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-m", "aiusageclock", "--webengine-worker", "--selftest", "--allow-no-gl"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "WORKER-SELFTEST" in result.stdout


def test_worker_selftest_command_line_reports_missing_gl_as_exit_3_by_default():
    env = dict(os.environ, PYTHONPATH=str(SRC), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-m", "aiusageclock", "--webengine-worker", "--selftest"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    if result.returncode == 0:
        pytest.skip("this session does have a GL context; the failure path cannot be shown")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "no_gl" in result.stdout


def test_worker_without_ipc_arguments_is_a_usage_error():
    env = dict(os.environ, PYTHONPATH=str(SRC), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-m", "aiusageclock", "--webengine-worker"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert result.returncode == 2
