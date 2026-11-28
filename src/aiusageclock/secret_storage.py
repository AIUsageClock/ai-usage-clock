"""Encrypted on-disk storage for values too large for Windows Credential Manager.

Windows Credential Manager caps the credential blob at ~2560 bytes, which is fine
for short tokens (GitHub PAT) but fails for long session JWTs (ChatGPT's
__Secure-next-auth.session-token can be 5-10KB).

We store these in %APPDATA%/ai-usage-clock/secrets.dat, encrypted with DPAPI
(CryptProtectData) — same per-user encryption that pre-v127 Chrome used. No
new Python dependencies; calls into crypt32.dll via ctypes.

This module is Windows-only by design. On non-Windows hosts (used during
cross-platform development of pure-Python helpers), writes are routed to a
plaintext file under a sandboxed test directory and a loud warning is logged.
Production callers should never reach the non-Windows branch.
"""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as wt
import json
import logging
import os
import sys
import time
from pathlib import Path

from ._filelock import file_lock
from .config import app_data_dir
from .identity import ENV_ALLOW_PLAINTEXT_SECRETS

log = logging.getLogger("aiusageclock.secret_storage")

_SECRETS_FILENAME = "secrets.dat"
_REPLACE_ATTEMPTS = 20
_REPLACE_DELAY_S = 0.05

# Opt-in escape hatch for the cross-platform test suite. When unset (the
# normal case) writes on non-Windows refuse loudly so a misconfigured macOS
# or Linux box cannot silently produce an unencrypted secrets.dat next to a
# real cookie.
_ALLOW_PLAINTEXT_ENV = ENV_ALLOW_PLAINTEXT_SECRETS


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wt.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


if sys.platform == "win32":
    _CRYPT32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _CRYPT32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wt.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _CRYPT32.CryptProtectData.restype = wt.BOOL

    _CRYPT32.CryptUnprotectData.argtypes = _CRYPT32.CryptProtectData.argtypes
    _CRYPT32.CryptUnprotectData.restype = wt.BOOL


def _to_blob(data: bytes) -> _DataBlob:
    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _from_blob(blob: _DataBlob) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    _KERNEL32.LocalFree(blob.pbData)
    return out


def _protect(plaintext: bytes) -> bytes:
    in_blob = _to_blob(plaintext)
    out_blob = _DataBlob()
    ok = _CRYPT32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    return _from_blob(out_blob)


def _unprotect(ciphertext: bytes) -> bytes:
    in_blob = _to_blob(ciphertext)
    out_blob = _DataBlob()
    ok = _CRYPT32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    return _from_blob(out_blob)


def _secrets_path() -> Path:
    return app_data_dir() / _SECRETS_FILENAME


def _load_all() -> dict[str, str]:
    path = _secrets_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
        if not raw:
            return {}
        if sys.platform == "win32":
            decrypted = _unprotect(raw).decode("utf-8")
        else:
            decrypted = raw.decode("utf-8")  # plaintext fallback for non-Windows dev
        loaded = json.loads(decrypted)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _write_atomically(path: Path, payload: bytes) -> None:
    """Replace ``path`` with ``payload`` so a reader sees the old file or the new
    one, never a half-written one."""
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                # Windows: another process has the file open for a moment.
                if attempt + 1 == _REPLACE_ATTEMPTS:
                    raise
                time.sleep(_REPLACE_DELAY_S)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _save_all(data: dict[str, str]) -> None:
    path = _secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data).encode("utf-8")
    if sys.platform == "win32":
        _write_atomically(path, _protect(payload))
        return
    if os.environ.get(_ALLOW_PLAINTEXT_ENV) == "1":
        log.warning(
            "secret_storage: writing PLAINTEXT secrets.dat on non-Windows host "
            f"({_ALLOW_PLAINTEXT_ENV}=1). This is a development-only "
            "escape hatch; do not use it with real provider cookies."
        )
        _write_atomically(path, payload)
        return
    raise RuntimeError(
        "secret_storage: refusing to write secrets on non-Windows host. "
        "DPAPI encryption is unavailable, so writing here would store the "
        "value in plaintext. Run on Windows, or set "
        f"{_ALLOW_PLAINTEXT_ENV}=1 to opt in (development only)."
    )


def _lock_in_use() -> bool:
    # macOS and Linux keep their secrets in the OS keyring and never write this
    # file (production refuses to); the lock file is only for hosts that do.
    return sys.platform == "win32" or os.environ.get(_ALLOW_PLAINTEXT_ENV) == "1"


@contextlib.contextmanager
def _file_lock():
    """Cross-process lock around reading and writing ``secrets.dat``.

    The main process and the browser worker both read and change this file. A
    read-modify-write without a lock can lose a change the other process made
    in between (and a reader of a file being rewritten could see it empty).
    """
    if not _lock_in_use():
        yield
        return
    # A hung holder must not make every secret unreadable: file_lock gives up
    # waiting after a while and carries on.
    with file_lock(_secrets_path().with_name(_SECRETS_FILENAME + ".lock")):
        yield


def save_secret(name: str, value: str | None) -> None:
    with _file_lock():
        data = _load_all()
        if value:
            data[name] = value
        else:
            data.pop(name, None)
        _save_all(data)


def load_secret(name: str) -> str | None:
    with _file_lock():
        return _load_all().get(name)
