"""Regression tests for issue #7 — the app must start without a GPU.

QtWebEngine is Chromium and needs a GL context to initialise. Importing it on
a session that has none (headless X11, XRDP, GPU-less VM) aborts the process,
which is why the gauge — plain QtWidgets, no GL required — must not pull it in
at startup.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from aiusageclock.webview import runtime

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    runtime.reset_probe_for_tests()
    yield
    runtime.reset_probe_for_tests()


def test_importing_the_app_does_not_load_webengine():
    """The guard that actually protects GL-less machines.

    Run in a subprocess: this test session has almost certainly imported
    QtWebEngine already via the webview tests, so checking sys.modules in-process
    would prove nothing.
    """
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import aiusageclock.app;"
        "print(sorted(m for m in sys.modules if 'WebEngine' in m))"
        % str(REPO_ROOT / "src")
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", (
        "importing aiusageclock.app pulled in QtWebEngine, which aborts on a "
        f"session with no GL context: {result.stdout}"
    )


_ALL_PATHS_SCRIPT = r"""
import logging
import sys
from types import SimpleNamespace

logging.basicConfig(level=logging.INFO)
sys.path.insert(0, {src!r})
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

qt_app = QApplication([])

from aiusageclock import app as app_module
from aiusageclock import cookie_dialog
from aiusageclock.config import Config
from aiusageclock.providers._scrape_runner import ScrapeRunner
from aiusageclock.webview import cookies, host as host_module

# A real WorkerHost talking over the real socket to a stand-in worker process.
host = host_module.WorkerHost(
    command=lambda: [sys.executable, {fake!r}], idle_shutdown_ms=200
)
host_module.set_host(host)
secrets = {{}}
cookies.set_provider_cookie = lambda account_id, value: secrets.update({{account_id: value}})
cookie_dialog.set_provider_cookie = cookies.set_provider_cookie
cookie_dialog.get_provider_cookie = lambda account_id: secrets.get(account_id)

pending = []

def wait_for(count):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(50)
    def poll():
        if len(pending) >= count:
            loop.quit()
    timer.timeout.connect(poll)
    timer.start()
    QTimer.singleShot(20000, loop.quit)
    loop.exec()
    assert len(pending) >= count, pending

# 1. refresh: ScrapeRunner -> WorkerScraper -> worker process
runner = ScrapeRunner(
    account_id="claude", url="https://example.test", extractor_js="1",
    build=lambda payload: SimpleNamespace(status="ok", error=""),
    log=__import__("logging").getLogger("t"),
)
runner.run(lambda snapshot: pending.append(("refresh", snapshot)))
wait_for(1)

# 2. sign-in window
stub = app_module.App.__new__(app_module.App)
stub._config = Config()
stub._settings_dialog = None
stub._cleared_sessions = set()
stub._widget = SimpleNamespace(
    suspend_always_on_top=lambda: None, restore_always_on_top=lambda: pending.append(("login", 1))
)
stub.refresh_provider = lambda provider: None
stub.open_login("claude")
wait_for(2)

# 3. pasted cookie: inject + verify
dialog = cookie_dialog.CookieDialog("claude", account_id="claude")
dialog._cookie_input.setPlainText("Cookie: sessionKey=abc")
dialog.accepted.connect(lambda: pending.append(("paste", 1)))
dialog.finished.connect(lambda code: pending.append(("paste", code)))
dialog._save()
wait_for(3)

# 4. clear sign-in
cookies.clear_browser_session("claude")

host.stop(graceful=True)
print("WEBENGINE:", sorted(m for m in sys.modules if "WebEngine" in m))
print("PATHS:", [name for name, _ in pending])
"""


def test_every_browser_path_leaves_the_main_process_without_webengine():
    """Refresh, sign-in, paste-a-cookie and clear-sign-in, end to end.

    Each runs through the real WorkerHost and a real socket to a stand-in worker
    process, in a subprocess so this session's own imports cannot hide a leak.
    """
    code = _ALL_PATHS_SCRIPT.format(
        src=str(REPO_ROOT / "src"), fake=str(REPO_ROOT / "tests" / "fake_worker.py")
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        output, _ = process.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        pytest.fail("browser-path script did not finish:\n" + output)
    result = subprocess.CompletedProcess(process.args, process.returncode, output, "")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WEBENGINE: []" in result.stdout, result.stdout
    assert "'refresh'" in result.stdout and "'login'" in result.stdout
    assert "'paste'" in result.stdout


def test_worker_modules_are_not_pulled_in_by_the_main_process_at_startup():
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import aiusageclock.app;"
        "print(sorted(m for m in sys.modules if m.startswith('aiusageclock.webview.') "
        "and m.rsplit('.', 1)[-1] in ('worker', 'scraper', 'profile', 'verify', 'login_window', "
        "'page', 'external_login')))" % str(REPO_ROOT / "src")
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout

def test_probe_reports_unavailable_without_a_gl_context(qapp, monkeypatch):
    monkeypatch.delenv("AIUSAGECLOCK_FORCE_WEBENGINE", raising=False)
    monkeypatch.setattr(
        runtime, "_gl_context_available", lambda: (False, "no GLX/EGL here")
    )

    assert runtime.is_available() is False
    assert "no GLX/EGL here" in runtime.unavailable_reason()
    with pytest.raises(runtime.WebEngineUnavailable, match="no GLX/EGL here"):
        runtime.require()


def test_probe_is_cached(qapp, monkeypatch):
    monkeypatch.delenv("AIUSAGECLOCK_FORCE_WEBENGINE", raising=False)
    calls = []

    def _probe():
        calls.append(1)
        return False, "nope"

    monkeypatch.setattr(runtime, "_gl_context_available", _probe)

    runtime.is_available()
    runtime.is_available()
    runtime.unavailable_reason()

    assert len(calls) == 1, "the GL probe must not run on every refresh"


def test_probe_refuses_to_run_before_a_qguiapplication_exists(monkeypatch):
    """QOpenGLContext.create() segfaults with no QGuiApplication.

    Found by running this on a real GL-less Linux session: asking the probe
    early took the whole process down, which is exactly the crash the probe is
    supposed to prevent.
    """
    monkeypatch.delenv("AIUSAGECLOCK_FORCE_WEBENGINE", raising=False)
    monkeypatch.setattr(runtime, "_gui_application_ready", lambda: False)
    monkeypatch.setattr(
        runtime,
        "_gl_context_available",
        lambda: pytest.fail("must not touch GL before QGuiApplication exists"),
    )

    assert runtime.is_available() is False
    assert "QGuiApplication" in runtime.unavailable_reason()


def test_missing_qguiapplication_answer_is_not_cached(qapp, monkeypatch):
    """A pre-startup 'no' must not poison the answer for the whole process."""
    monkeypatch.delenv("AIUSAGECLOCK_FORCE_WEBENGINE", raising=False)
    ready = [False]
    monkeypatch.setattr(runtime, "_gui_application_ready", lambda: ready[0])
    monkeypatch.setattr(runtime, "_gl_context_available", lambda: (True, ""))

    assert runtime.is_available() is False  # asked too early

    ready[0] = True
    assert runtime.is_available() is True  # re-probes once the app exists


def test_force_env_var_bypasses_the_probe(monkeypatch):
    monkeypatch.setenv("AIUSAGECLOCK_FORCE_WEBENGINE", "1")
    monkeypatch.setattr(
        runtime,
        "_gl_context_available",
        lambda: pytest.fail("probe should be bypassed"),
    )

    assert runtime.is_available() is True
    assert runtime.unavailable_reason() == ""
