"""Deleting an account's browser profile directory.

Signing an account out used to ask the live WebEngine profile to drop its
cookies and cache. The main process no longer has a browser, so the sign-out
removes the profile directory instead, which also takes localStorage and the
rest with it. On Windows a directory can be locked for a moment after the
worker that used it was killed; whatever cannot be removed is listed in a small
file and retried before the next worker starts and at the next launch.

A profile that is still listed must never be used again: the worker resolves
the listing (``ensure_not_pending``) before it opens a profile, so neither a
scrape of a signed-out account nor a fresh sign-in can be mixed up with the
directory that was meant to disappear.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path

from ..config import app_data_dir, webview_profile_dir

log = logging.getLogger("aiusageclock.webview.profile_cleanup")

PENDING_FILENAME = "pending-profile-delete.json"

_RETRIES = 8
_RETRY_DELAY_S = 0.25


class ProfileLocked(OSError):
    """The profile directory could not be removed yet; its deletion is queued."""


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
        # The main process and the worker both update this file: replace it in
        # one step so neither can read a half-written list.
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(sorted(set(items))), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        log.warning("could not update %s", path, exc_info=True)


def _remove_tree(path: Path, *, retries: int, delay_s: float) -> OSError | None:
    """Remove ``path``; return None when it is gone, else the last error."""
    error: OSError | None = None
    for attempt in range(max(1, retries)):
        try:
            if path.exists():
                shutil.rmtree(path)
            return None
        except OSError as exc:
            error = exc
            if attempt + 1 < retries:
                time.sleep(delay_s)
    if not path.exists():
        return None
    return error or OSError(f"could not remove {path}")


def delete_profile(
    account_id: str,
    *,
    retries: int = _RETRIES,
    delay_s: float = _RETRY_DELAY_S,
    raise_if_locked: bool = False,
) -> bool:
    """Remove ``profiles/<account_id>``; queue it for later if it is locked.

    Returns True when the directory is gone, False when it was queued (or
    raises :class:`ProfileLocked`, carrying the operating system's own error
    text, when ``raise_if_locked`` is set).
    """
    if not _safe_id(account_id):
        raise ValueError(f"unsafe account id: {account_id!r}")
    path = webview_profile_dir(account_id)
    error = _remove_tree(path, retries=retries, delay_s=delay_s)
    if error is None:
        _write_pending([item for item in read_pending() if item != account_id])
        log.info("browser profile removed account=%s", account_id)
        return True
    _write_pending(read_pending() + [account_id])
    log.warning("browser profile is locked; deletion queued account=%s", account_id)
    if raise_if_locked:
        raise ProfileLocked(str(error))
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
        if _remove_tree(webview_profile_dir(account_id), retries=1, delay_s=0.0) is None:
            done.append(account_id)
    if done:
        _write_pending([item for item in read_pending() if item not in done])
        log.info("queued browser profile deletions completed: %s", done)
    return done


def ensure_not_pending(account_id: str) -> str | None:
    """Finish a queued deletion of ``account_id`` before its profile is used.

    Returns None when the profile is free to use (nothing queued, or the
    directory is now gone), else the operating system's error text; the caller
    must then not open that profile.
    """
    if not _safe_id(account_id) or account_id not in read_pending():
        return None
    try:
        if delete_profile(account_id, raise_if_locked=True):
            return None
    except ProfileLocked as exc:
        return str(exc)
    return None


def cleanup_stale_signin_profiles() -> int:
    """Remove temporary sign-in browser profiles that a crash or a kill left.

    Each sign-in runs a real browser in a throwaway profile under
    ``browser-signin`` and removes it when the window closes. A worker that was
    killed, or a main process that crashed, never gets to; once signed in, such
    a directory holds a live session cookie. Only one sign-in ever runs at a
    time, so whatever is there when the app starts (or before a new sign-in
    begins) is stale. Returns how many directories were removed.
    """
    root = app_data_dir() / "browser-signin"
    removed = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            entry.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed += 1
        else:
            log.warning("stale sign-in profile could not be removed path=%s", entry)
    if removed:
        log.info("removed %s stale temporary sign-in profile(s)", removed)
    return removed
