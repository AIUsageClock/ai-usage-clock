from __future__ import annotations

import logging
import shutil
import sqlite3
import sys
import tempfile
import time
from http.cookies import SimpleCookie
from pathlib import Path

from PyQt6.QtCore import QByteArray, QDateTime, QUrl
from PyQt6.QtNetwork import QNetworkCookie

from ..config import (
    COOKIE_DOMAINS,
    COOKIE_NAME_ALIASES,
    COOKIE_NAMES,
    get_provider_cookie,
    set_provider_cookie,
    webview_profile_dir,
)
from . import profile_cleanup
from .host import existing_host

log = logging.getLogger("aiusageclock.webview.cookies")


# Resolved on first use rather than imported at module scope: .profile pulls in
# QtWebEngine. The main process imports this module (cookie parsing, sign-out)
# and must never load Chromium; only the worker process calls the functions
# that need a profile. Kept as a module attribute so it remains patchable.
get_profile = None


def _get_profile(account_id: str):
    global get_profile
    if get_profile is None:
        from .profile import get_profile as _resolved

        get_profile = _resolved
    return get_profile(account_id)


# 60-day expiry — Claude/ChatGPT session tokens last weeks; we re-set on each
# launch anyway, so this is just to keep the cookie persistent across the
# WebEngine restart cycle.
_COOKIE_TTL_DAYS = 60


def _unquote_cookie_value(value: str) -> str:
    if len(value) < 2 or value[0] != '"' or value[-1] != '"':
        return value

    try:
        jar = SimpleCookie()
        jar.load(f"cookie={value}")
        morsel = jar.get("cookie")
        if morsel is not None:
            return morsel.value
    except Exception:  # noqa: BLE001 - fall back to a plain quote trim
        pass
    return value[1:-1]


def _parse_name_value_pairs_manually(cookie_text: str) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for part in cookie_text.replace("\r\n", ";").replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        name, item_value = part.split("=", 1)
        name = name.strip()
        if name.lower().startswith("cookie:"):
            name = name.split(":", 1)[1].strip()
        if name:
            parsed.append((name, _unquote_cookie_value(item_value.strip())))
    return parsed


def _parse_name_value_pairs(cookie_text: str) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    try:
        jar = SimpleCookie()
        jar.load(cookie_text.replace("\r\n", "; ").replace("\n", "; "))
        for name, morsel in jar.items():
            parsed.append((name, morsel.value))
    except Exception:  # noqa: BLE001 - fall through to the manual parser
        parsed = []

    manual = _parse_name_value_pairs_manually(cookie_text)
    if len(manual) > len(parsed):
        simple_values = {name: value for name, value in parsed}
        return [
            (name, simple_values.get(name, item_value))
            for name, item_value in manual
        ]

    return parsed or manual


def _has_auth_cookie(provider: str, pairs: list[tuple[str, str]]) -> bool:
    names = {name for name, _ in pairs}
    aliases = set(COOKIE_NAME_ALIASES.get(provider, ()))
    if provider == "codex":
        return bool(names & aliases) or "__Secure-oai-is" in names
    return bool(names & aliases)


def _parse_cookie_pairs(provider: str, pasted: str) -> list[tuple[str, str]]:
    """Parse raw values, `name=value` lines, or a full Cookie header.

    Browser DevTools has changed ChatGPT's auth cookie name over time, and very
    large values may be split as `.0` / `.1` cookies. If the user pastes only a
    raw value, inject it under every known non-split alias for the provider.
    When a full request Cookie header is pasted, keep all cookies for that
    provider; modern ChatGPT sessions can need more than the next-auth token.
    """
    value = pasted.strip()
    if not value:
        return []
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if lines and lines[0].lower() == "cookie":
        value = "\n".join(lines[1:]).strip()
        if not value:
            return []

    aliases = COOKIE_NAME_ALIASES.get(provider, (COOKIE_NAMES.get(provider, ""),))
    alias_set = {a for a in aliases if a}
    raw_names = [a for a in aliases if a and not a.endswith((".0", ".1"))]
    raw_lines = [line.strip() for line in value.splitlines() if line.strip()]
    if provider == "codex" and len(raw_lines) > 1 and all("=" not in line for line in raw_lines):
        return [
            (f"__Secure-next-auth.session-token.{i}", line)
            for i, line in enumerate(raw_lines[:2])
        ]

    cookie_text = value
    if cookie_text.lower().startswith("cookie:"):
        cookie_text = cookie_text.split(":", 1)[1].strip()

    parsed: list[tuple[str, str]] = []
    if "=" in cookie_text:
        keep_all = ";" in cookie_text
        all_pairs = _parse_name_value_pairs(cookie_text)
        if keep_all and _has_auth_cookie(provider, all_pairs):
            parsed = all_pairs
        else:
            parsed = [
                (name, item_value)
                for name, item_value in all_pairs
                if name in alias_set
            ]
        return parsed

    if parsed:
        return parsed
    return [(name, value) for name in raw_names]


def _set_cookie(kind: str, account_id: str, name: str, value: str) -> None:
    domain = COOKIE_DOMAINS[kind]
    profile = _get_profile(account_id)
    store = profile.cookieStore()

    cookie = QNetworkCookie(
        QByteArray(name.encode("utf-8")),
        QByteArray(value.strip().encode("utf-8")),
    )
    if not name.startswith("__Host-"):
        cookie.setDomain(domain)
    cookie.setPath("/")
    cookie.setSecure(True)
    cookie.setHttpOnly(True)
    cookie.setExpirationDate(QDateTime.currentDateTime().addDays(_COOKIE_TTL_DAYS))

    # Origin URL must match the cookie domain (drop the leading dot).
    origin = QUrl(f"https://{domain.lstrip('.')}/")
    store.setCookie(cookie, origin)


def inject_session_cookie(
    provider: str,
    value: str,
    *,
    account_id: str | None = None,
) -> bool:
    """Push a cookie into the WebEngine profile so subsequent loads are signed-in.

    Returns True if a cookie was injected, False if no name/domain mapping exists
    for this provider.
    """
    kind = provider
    profile_id = account_id or provider
    domain = COOKIE_DOMAINS.get(kind)
    if not COOKIE_NAMES.get(kind) or not domain:
        return False

    pairs = _parse_cookie_pairs(kind, value)
    for name, cookie_value in pairs:
        _set_cookie(kind, profile_id, name, cookie_value)
    return bool(pairs)


def import_browser_cookies(
    provider: str,
    account_id: str,
    cookies: list[dict],
) -> bool:
    """Import cookies captured from a real browser into a WebEngine profile."""
    domain = COOKIE_DOMAINS.get(provider)
    if not domain:
        return False
    wanted = domain.lstrip(".").lower()
    matching = [
        item
        for item in cookies
        if isinstance(item, dict)
        and (
            str(item.get("domain", "")).lstrip(".").lower() == wanted
            or str(item.get("domain", ""))
            .lstrip(".")
            .lower()
            .endswith("." + wanted)
        )
        and item.get("name")
        and item.get("value") is not None
    ]
    if not matching:
        return False

    store = _get_profile(account_id).cookieStore()
    # A signed-out visit may already have created a host-only cookie with the
    # same name as the authenticated cookie. If the imported cookie is then
    # converted into a domain cookie, Chromium keeps both and may send the
    # stale value first. This profile belongs to one account, so queue removal
    # of its old cookie set before importing the new session.
    store.deleteAllCookies()
    for item in matching:
        name = str(item["name"])
        value = str(item["value"])
        cookie_domain = str(item.get("domain") or domain)
        cookie = QNetworkCookie(
            QByteArray(name.encode("utf-8")),
            QByteArray(value.encode("utf-8")),
        )
        # CDP represents host-only cookies without a leading dot. Omitting
        # setDomain preserves that property in Qt; explicitly setting the
        # domain would turn it into a separate `.example.com` cookie instead
        # of replacing an existing host-only cookie.
        if cookie_domain.startswith(".") and not name.startswith("__Host-"):
            cookie.setDomain(cookie_domain)
        cookie.setPath(str(item.get("path") or "/"))
        cookie.setSecure(bool(item.get("secure", True)))
        cookie.setHttpOnly(bool(item.get("httpOnly", True)))
        expires = item.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            cookie.setExpirationDate(QDateTime.fromSecsSinceEpoch(int(expires)))
        origin = QUrl(f"https://{cookie_domain.lstrip('.')}/")
        store.setCookie(cookie, origin)

    # Keep the same encrypted fallback used by the paste-cookie flow. Values
    # are never logged; only cookie names appear in diagnostics.
    header = "; ".join(f"{item['name']}={item['value']}" for item in matching)
    set_provider_cookie(account_id, header)
    log.info(
        "browser cookies imported provider=%s cookie_names=%s",
        account_id,
        sorted({str(item["name"]) for item in matching}),
    )
    return True


# A freshly pasted cookie is saved first and only then handed to the worker. If
# the worker never gets to inject it (it failed to start, crashed, or the app
# was quit meanwhile), the profile may still hold an older auth cookie that the
# site has already revoked, and the "never overwrite a rotated session" rule
# would then keep that dead cookie for ever. An empty marker file beside the
# profile folder says "the saved cookie is newer than the profile": the next
# hydration pushes it in regardless, then removes the marker. Only ever created
# or deleted, never read-modified-written, so two processes cannot race on it.


def reseed_marker_path(account_id: str) -> Path:
    profile = webview_profile_dir(account_id)
    return profile.with_name(profile.name + ".reseed")


def request_reseed(account_id: str) -> None:
    """Record that the saved cookie must replace whatever the profile holds."""
    try:
        marker = reseed_marker_path(account_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except (OSError, ValueError):
        log.warning("could not mark account for re-seeding account=%s", account_id, exc_info=True)


def reseed_requested(account_id: str) -> bool:
    try:
        return reseed_marker_path(account_id).exists()
    except (OSError, ValueError):
        return False


def clear_reseed_request(account_id: str) -> None:
    try:
        reseed_marker_path(account_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        log.warning("could not remove re-seed marker account=%s", account_id, exc_info=True)


def clear_browser_session(account_id: str) -> None:
    """Remove an account's saved secret and its whole browser profile.

    The browser runs in a worker process, so there is no live cookie store to
    ask: any worker that could hold the profile open is stopped, then the
    profile directory is deleted (cookies, cache and localStorage together). A
    directory the OS still has locked is queued and removed before the next
    worker starts (see ``profile_cleanup``).

    Both the secret and the profile are attempted even if one fails, so an
    error in the OS secret backend cannot leave the browser session behind, nor
    a file error leave a secret that would be restored on restart.
    """
    errors: list[str] = []
    clear_reseed_request(account_id)
    try:
        set_provider_cookie(account_id, None)
    except Exception as exc:  # noqa: BLE001 - report partial cleanup to the UI
        errors.append(f"encrypted cookie: {exc}")

    try:
        host = existing_host()
        if host is not None:
            host.release_profile(account_id)
        # A directory that stays locked is queued for later, but the sign-out
        # is not complete until it is gone: raise so the caller says so.
        profile_cleanup.delete_profile(account_id, raise_if_locked=True)
    except Exception as exc:  # noqa: BLE001 - report partial cleanup to the UI
        errors.append(f"browser profile: {exc}")

    if errors:
        raise RuntimeError("; ".join(errors))
    log.info("browser session cleared provider=%s", account_id)


# Chromium stores expiry as microseconds since 1601-01-01 UTC.
_CHROMIUM_EPOCH_OFFSET_S = 11_644_473_600


def _profile_loaded_in_process(account_id: str) -> bool:
    """Whether this process already has the account's profile open."""
    module = sys.modules.get("aiusageclock.webview.profile")
    return module is not None and account_id in module.loaded_account_ids()


def _auth_cookie_rows(kind: str, db_path: Path) -> bool:
    """Whether the Cookies database holds an unexpired auth cookie for ``kind``."""
    domain = COOKIE_DOMAINS.get(kind, "").lstrip(".").lower()
    now_chromium = int((time.time() + _CHROMIUM_EPOCH_OFFSET_S) * 1_000_000)
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT host_key, name, expires_utc FROM cookies"
        ).fetchall()
    finally:
        connection.close()
    for host_key, name, expires_utc in rows:
        host = str(host_key).lstrip(".").lower()
        if domain and host != domain and not host.endswith("." + domain):
            continue
        if expires_utc and int(expires_utc) <= now_chromium:
            continue
        if _has_auth_cookie(kind, [(str(name), "")]):
            return True
    return False


def _profile_auth_cookie_state(kind: str, account_id: str) -> bool | None:
    """Whether the profile on disk really holds the account's auth cookie.

    True/False when the Cookies database could be read, None when it could not.
    The database is read from a copy (with its journal) so a database left
    mid-write by a killed worker is rolled back on the copy, never on the
    original, and so nothing here can lock the file Chromium is about to open.
    """
    cookies_path = webview_profile_dir(account_id) / "Cookies"
    if not cookies_path.exists():
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="aiuc-cookies-") as scratch:
            copy = Path(scratch) / "Cookies"
            shutil.copy2(cookies_path, copy)
            for suffix in ("-journal", "-wal"):
                extra = cookies_path.with_name(cookies_path.name + suffix)
                if extra.exists():
                    shutil.copy2(extra, copy.with_name(copy.name + suffix))
            return _auth_cookie_rows(kind, copy)
    except (OSError, sqlite3.Error):
        return None


def _profile_has_persistent_cookies(kind: str, account_id: str) -> bool:
    """Whether the profile already owns a usable session, so the keyring's copy
    must not be pushed over it.

    The file's size says nothing: a worker that dies right after hydrating
    leaves a non-empty ``Cookies`` file whose table is empty, and a size check
    would then treat the account as "has live cookies" forever. So the decision
    looks for the auth cookie itself (name, domain, not expired):

    * an unexpired auth cookie is present: the profile owns the session, and
      the site may have rotated it since the user pasted the stored copy, so
      the stored (older) value must not overwrite it;
    * the database is readable but holds no auth cookie: nothing worth keeping,
      so the stored value is pushed in;
    * the database cannot be read: fall back to the old size check, which errs
      toward leaving the profile alone.

    A profile this very process already has open is never re-seeded either:
    its newest cookies may not have reached the file yet.
    """
    if _profile_loaded_in_process(account_id):
        return True
    state = _profile_auth_cookie_state(kind, account_id)
    if state is not None:
        return state
    try:
        cookies_path = webview_profile_dir(account_id) / "Cookies"
        return cookies_path.exists() and cookies_path.stat().st_size > 0
    except OSError:
        return False


def hydrate_account_from_keyring(kind: str, account_id: str) -> bool:
    """Push the account's saved cookie into its WebEngine profile if it has none.

    Runs inside the worker, right before a scrape. Skips an account whose
    profile already has Chromium-persisted cookies on disk: re-injecting then
    would overwrite session tokens that the site has rotated since the user
    pasted the cookie with the stale blob, which causes spurious "Sign in"
    prompts.

    Returns True when a cookie was injected.
    """
    value = get_provider_cookie(account_id)
    pairs = _parse_cookie_pairs(kind, value) if value else []
    names = sorted({name for name, _ in pairs})
    has_auth = _has_auth_cookie(kind, pairs) if pairs else False
    profile_has_cookies = _profile_has_persistent_cookies(kind, account_id)
    reseed = reseed_requested(account_id)

    if not value:
        injected = False
        skip_reason = "no_stored_cookie"
        if reseed:
            clear_reseed_request(account_id)
    elif profile_has_cookies and not reseed:
        injected = False
        skip_reason = "profile_has_live_cookies"
    else:
        skip_reason = ""
        if account_id != kind:
            injected = inject_session_cookie(kind, value, account_id=account_id)
        else:
            injected = bool(inject_session_cookie(kind, value))
        if injected and reseed:
            clear_reseed_request(account_id)

    log.info(
        "cookie hydration provider=%s kind=%s stored=%s parsed_cookie_names=%s "
        "has_auth_cookie=%s profile_has_cookies=%s injected=%s skip_reason=%s",
        account_id,
        kind,
        bool(value),
        names,
        has_auth,
        profile_has_cookies,
        injected,
        skip_reason or "-",
    )
    return injected
