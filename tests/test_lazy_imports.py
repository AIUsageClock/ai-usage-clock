"""The idle app must not carry requests or keyring (about 12 MB resident).

Only a provider that is actually enabled, or a secret that is actually read,
needs them. Everything runs in a subprocess: this test session has long since
imported both through other tests, so sys.modules here would prove nothing.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("requests", "urllib3", "charset_normalizer", "keyring")


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, r'{REPO_ROOT / 'src'}');" + code],
        capture_output=True,
        text=True,
        env=env,
    )


def _loaded(stdout: str) -> list[str]:
    line = stdout.strip().splitlines()[-1]
    return ast.literal_eval(line)


_REPORT = "print(sorted(m for m in sys.modules if m.split('.')[0] in %r))" % (HEAVY,)


def test_importing_the_app_does_not_load_requests_or_keyring():
    result = _run("import aiusageclock.app;" + _REPORT)
    assert result.returncode == 0, result.stderr
    assert _loaded(result.stdout) == [], result.stdout


def test_building_the_idle_widget_does_not_load_requests_or_keyring():
    code = (
        "from PyQt6.QtWidgets import QApplication;"
        "import aiusageclock.app, aiusageclock.settings_dialog, aiusageclock.ratio_dialog;"
        "from aiusageclock.config import Config;"
        "from aiusageclock.widget import UsageWidget;"
        "app = QApplication([]);"
        "w = UsageWidget(Config());"
        "w.set_collapsed(True); w.set_collapsed(False);"
    ) + _REPORT
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert _loaded(result.stdout) == [], result.stdout


@pytest.mark.parametrize(
    "module, attr, expected",
    [
        ("aiusageclock.providers.copilot", "requests.RequestException", "requests"),
        ("aiusageclock.providers.linear", "requests.post", "requests"),
        ("aiusageclock.providers.openrouter", "requests.get", "requests"),
        ("aiusageclock.providers.opencode_go", "requests.get", "requests"),
        ("aiusageclock.providers._resets_common", "requests.get", "requests"),
        ("aiusageclock.webview.external_login", "requests.Session", "requests"),
        ("aiusageclock.config", "keyring.errors.KeyringError", "keyring"),
    ],
)
def test_the_module_loads_on_first_use(module, attr, expected):
    code = (
        f"import {module} as m;"
        "before = %r in sys.modules;"
        f"obj = m.{attr};"
        "print([before, %r in sys.modules])" % (expected, expected)
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert _loaded(result.stdout) == [False, True], result.stdout
