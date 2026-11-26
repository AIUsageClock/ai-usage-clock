"""Deleting an account's browser profile directory.

Signing an account out used to ask the live WebEngine profile to drop its
cookies and cache. The main process no longer has a browser, so the sign-out
removes the profile directory instead, which also takes localStorage and the
rest with it. On Windows a directory can be locked for a moment after the
worker that used it was killed; whatever cannot be removed is listed in a small
file and retried before the next worker starts and at the next launch.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from ..config import app_data_dir, webview_profile_dir

log = logging.getLogger("aiusageclock.webview.profile_cleanup")

PENDING_FILENAME = "pending-profile-delete.json"

_RETRIES = 8
_RETRY_DELAY_S = 0.25


def pending_path() -> Path:
    return app_data_dir() / PENDING_FILENAME


def _safe_id(account_id: str) -> bool:
    return bool(account_id) and Path(account_id).name == account_id and account_id not in (".", "..")


def read_pending() -> list[str]:
    try:
        data = json.loads(pending_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str) and _safe_id(item)]


def _write_pending(items: list[str]) -> None:
    path = pending_path()
    try:
        if not items:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(set(items))), encoding="utf-8")
    except OSError:
        log.warning("could not update %s", path, exc_info=True)


def _remove_tree(path: Path, *, retries: int, delay_s: float) -> bool:
    for attempt in range(max(1, retries)):
        try:
            if path.exists():
                shutil.rmtree(path)
            return True
        except OSError:
            if attempt + 1 < retries:
                time.sleep(delay_s)
    return not path.exists()


def delete_profile(account_id: str, *, retries: int = _RETRIES, delay_s: float = _RETRY_DELAY_S) -> bool:
    """Remove ``profiles/<account_id>``; queue it for later if it is locked.

    Returns True when the directory is gone, False when it was queued.
    """
    if not _safe_id(account_id):
        raise ValueError(f"unsafe account id: {account_id!r}")
    path = webview_profile_dir(account_id)
    if _remove_tree(path, retries=retries, delay_s=delay_s):
        _write_pending([item for item in read_pending() if item != account_id])
        log.info("browser profile removed account=%s", account_id)
        return True
    _write_pending(read_pending() + [account_id])
    log.warning("browser profile is locked; deletion queued account=%s", account_id)
    return False


def process_pending() -> list[str]:
    """Retry queued deletions once; return the ids that are now gone.

    Must run before any worker starts, so a signed-out account cannot be picked
    up again from a profile that was meant to disappear.
    """
    pending = read_pending()
    if not pending:
        return []
    done: list[str] = []
    for account_id in pending:
        if _remove_tree(webview_profile_dir(account_id), retries=1, delay_s=0.0):
            done.append(account_id)
    if done:
        _write_pending([item for item in pending if item not in done])
        log.info("queued browser profile deletions completed: %s", done)
    return done
