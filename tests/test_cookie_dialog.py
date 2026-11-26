"""CookieDialog hands injection and verification to the worker process."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QDialog, QMessageBox

from aiusageclock import cookie_dialog as dialog_module
from aiusageclock.cookie_dialog import CookieDialog

COOKIE = "Cookie: other=value; sessionKey=secret-session"


class _Host:
    def __init__(self):
        self.jobs = []

    def submit(self, kind, params, on_result, **kwargs):
        job = SimpleNamespace(kind=kind, params=params, on_result=on_result, kwargs=kwargs)
        self.jobs.append(job)
        return job


@pytest.fixture
def setup(qtbot, monkeypatch):
    host = _Host()
    saved = {}
    monkeypatch.setattr(dialog_module, "get_host", lambda: host)
    monkeypatch.setattr(
        dialog_module, "set_provider_cookie", lambda account_id, value: saved.update({account_id: value})
    )
    monkeypatch.setattr(dialog_module, "get_provider_cookie", lambda account_id: saved.get(account_id))
    infos: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: infos.append(a[2] if len(a) > 2 else "")
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: infos.append("warning"))

    dialog = CookieDialog("claude", account_id="claude-work", display_name="Claude (work)")
    qtbot.addWidget(dialog)
    dialog._cookie_input.setPlainText(COOKIE)  # noqa: SLF001
    return SimpleNamespace(dialog=dialog, host=host, saved=saved, infos=infos)


def test_save_stores_the_cookie_then_asks_the_worker_to_inject_and_verify(setup):
    setup.dialog._save()  # noqa: SLF001

    assert setup.saved == {"claude-work": COOKIE}
    job = setup.host.jobs[0]
    assert job.kind == "inject_verify"
    assert job.params["kind"] == "claude"
    assert job.params["account_id"] == "claude-work"
    assert job.params["verify"] is True
    assert "sessionKey" not in str(job.params), "the secret never goes over the pipe"
    assert not setup.dialog._buttons.isEnabled()  # noqa: SLF001
    assert "Verifying" in setup.dialog._status.text()  # noqa: SLF001


def test_verified_cookie_closes_the_dialog(setup):
    setup.dialog._save()  # noqa: SLF001
    setup.host.jobs[0].on_result({"ok": True, "injected": True, "verified": True, "verify_error": ""})

    assert setup.dialog.result() == QDialog.DialogCode.Accepted


def test_cookie_that_loads_signed_out_keeps_the_dialog_open(setup):
    setup.dialog._save()  # noqa: SLF001
    setup.host.jobs[0].on_result({"ok": True, "injected": True, "verified": False, "verify_error": ""})

    assert setup.dialog.result() != QDialog.DialogCode.Accepted
    assert "didn't authenticate" in setup.dialog._status.text()  # noqa: SLF001
    assert setup.dialog._buttons.isEnabled()  # noqa: SLF001


def test_inconclusive_check_still_accepts_the_saved_cookie(setup):
    setup.dialog._save()  # noqa: SLF001
    setup.host.jobs[0].on_result(
        {"ok": True, "injected": True, "verified": False, "verify_error": "timeout"}
    )

    assert setup.dialog.result() == QDialog.DialogCode.Accepted
    assert any("timeout" in text for text in setup.infos) or setup.infos


def test_worker_failure_is_treated_as_an_inconclusive_check(setup):
    setup.dialog._save()  # noqa: SLF001
    setup.host.jobs[0].on_result({"ok": False, "error": "worker_crashed", "detail": "exit code 7"})

    assert setup.dialog.result() == QDialog.DialogCode.Accepted


def test_no_gl_skips_verification_but_keeps_the_cookie(setup):
    setup.dialog._save()  # noqa: SLF001
    setup.host.jobs[0].on_result({"ok": False, "error": "no_gl", "reason": "no GLX/EGL"})

    assert setup.dialog.result() == QDialog.DialogCode.Accepted
    assert setup.saved == {"claude-work": COOKIE}


def test_result_after_the_dialog_was_closed_is_ignored(setup):
    setup.dialog._save()  # noqa: SLF001
    setup.dialog.reject()
    setup.host.jobs[0].on_result({"ok": True, "injected": True, "verified": True, "verify_error": ""})

    assert setup.dialog.result() == QDialog.DialogCode.Rejected


def test_empty_paste_does_not_start_a_job(setup):
    setup.dialog._cookie_input.setPlainText("   ")  # noqa: SLF001
    setup.dialog._save()  # noqa: SLF001

    assert setup.host.jobs == []
