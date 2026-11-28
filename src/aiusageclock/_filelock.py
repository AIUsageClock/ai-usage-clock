"""A small cross-process file lock (``msvcrt`` on Windows, ``fcntl`` elsewhere).

The main process and the browser worker both read and change a few small files
in the app-data folder. A read-modify-write without a lock can lose a change the
other process made in between.
"""
from __future__ import annotations

import contextlib
import logging
import sys
import time
from pathlib import Path

log = logging.getLogger("aiusageclock.filelock")

LOCK_WAIT_S = 10.0
_LOCK_POLL_S = 0.02


@contextlib.contextmanager
def file_lock(lock_path: Path, *, wait_s: float = LOCK_WAIT_S):
    """Hold an exclusive lock on ``lock_path`` (created if missing).

    Waits up to ``wait_s`` seconds. A hung holder must not make the protected
    file unusable forever, so after that a warning is logged and the caller
    continues without the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")  # noqa: SIM115 - closed in the finally below
    locked = False
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                handle.seek(0)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    log.warning(
                        "lock %s not acquired in time; continuing without it", lock_path.name
                    )
                    break
                time.sleep(_LOCK_POLL_S)
        yield
    finally:
        try:
            if locked:
                handle.seek(0)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
