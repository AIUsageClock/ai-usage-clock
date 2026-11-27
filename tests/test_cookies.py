from aiusageclock.cookie_dialog import INSTRUCTIONS
from aiusageclock.webview.cookies import _parse_cookie_pairs
from aiusageclock.webview import cookies


def test_codex_cookie_instructions_link_to_usage_overview():
    _title, instructions = INSTRUCTIONS["codex"]

    assert "href='https://chatgpt.com/settings/usage'" in instructions
    assert "chatgpt.com/settings/usage" in instructions
    assert "codex/cloud/settings/analytics" not in instructions
    assert "<code>analytics</code>" not in instructions
def test_parse_codex_full_cookie_header_keeps_related_cookies():
    pasted = (
        "Cookie: __Host-next-auth.csrf-token=csrf; "
        "__Secure-oai-is=identity; "
        "__Secure-next-auth.session-token.0=first; "
        "__Secure-next-auth.session-token.1=second"
    )
    assert _parse_cookie_pairs("codex", pasted) == [
        ("__Host-next-auth.csrf-token", "csrf"),
        ("__Secure-oai-is", "identity"),
        ("__Secure-next-auth.session-token.0", "first"),
        ("__Secure-next-auth.session-token.1", "second"),
    ]


def test_parse_codex_full_cookie_header_with_json_cookie_keeps_related_cookies():
    pasted = (
        'Cookie: __cflb=load-balancer; g_state={"i_l":0}; '
        'oai-chat-web-route="route-value"; '
        "__Secure-next-auth.session-token=session"
    )
    assert _parse_cookie_pairs("codex", pasted) == [
        ("__cflb", "load-balancer"),
        ("g_state", '{"i_l":0}'),
        ("oai-chat-web-route", "route-value"),
        ("__Secure-next-auth.session-token", "session"),
    ]


def test_parse_codex_bare_cookie_header_value_with_json_cookie_keeps_related_cookies():
    pasted = (
        '__cflb=load-balancer; g_state={"i_l":0}; '
        'oai-chat-web-route="route-value"; '
        "__Secure-next-auth.session-token=session"
    )
    assert _parse_cookie_pairs("codex", pasted) == [
        ("__cflb", "load-balancer"),
        ("g_state", '{"i_l":0}'),
        ("oai-chat-web-route", "route-value"),
        ("__Secure-next-auth.session-token", "session"),
    ]


def test_parse_codex_split_name_value_lines():
    pasted = (
        "__Secure-next-auth.session-token.0=first\n"
        "__Secure-next-auth.session-token.1=second\n"
    )
    assert _parse_cookie_pairs("codex", pasted) == [
        ("__Secure-next-auth.session-token.0", "first"),
        ("__Secure-next-auth.session-token.1", "second"),
    ]


def test_parse_codex_split_raw_value_lines():
    assert _parse_cookie_pairs("codex", "first\nsecond") == [
        ("__Secure-next-auth.session-token.0", "first"),
        ("__Secure-next-auth.session-token.1", "second"),
    ]


def test_parse_codex_raw_value_uses_current_and_legacy_names():
    assert _parse_cookie_pairs("codex", "single-token") == [
        ("next-auth.session-token", "single-token"),
        ("__Secure-next-auth.session-token", "single-token"),
    ]

def test_parse_claude_raw_value():
    assert _parse_cookie_pairs("claude", "session-value") == [
        ("sessionKey", "session-value")
    ]


def test_parse_claude_full_cookie_header_requires_session_key():
    pasted = "Cookie: other=value; sessionKey=claude-session; another=thing"
    assert _parse_cookie_pairs("claude", pasted) == [
        ("other", "value"),
        ("sessionKey", "claude-session"),
        ("another", "thing"),
    ]


def test_parse_claude_rejects_chatgpt_cookie_header():
    pasted = (
        "Cookie: __Secure-oai-is=identity; "
        "__Secure-next-auth.session-token.0=first"
    )
    assert _parse_cookie_pairs("claude", pasted) == []


def test_parse_codex_rejects_unrelated_cookie_header():
    assert _parse_cookie_pairs("codex", "Cookie: unrelated=value; other=thing") == []


def test_import_browser_cookies_preserves_attributes_and_saves_fallback(monkeypatch):
    imported = []
    saved = []
    cleared = []

    class FakeStore:
        def deleteAllCookies(self):  # noqa: N802 - Qt-shaped test double
            cleared.append(True)

        def setCookie(self, cookie, origin):  # noqa: N802 - Qt-shaped test double
            imported.append((cookie, origin))

    class FakeProfile:
        def cookieStore(self):  # noqa: N802 - Qt-shaped test double
            return FakeStore()

    monkeypatch.setattr(cookies, "get_profile", lambda account_id: FakeProfile())
    monkeypatch.setattr(
        cookies,
        "set_provider_cookie",
        lambda account_id, value: saved.append((account_id, value)),
    )

    assert cookies.import_browser_cookies(
        "codex",
        "codex-work",
        [
            {
                "name": "__Secure-next-auth.session-token",
                "value": "session-secret",
                "domain": ".chatgpt.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expires": 2_000_000_000,
            },
            {
                "name": "google-cookie",
                "value": "must-not-import",
                "domain": ".google.com",
            },
        ],
    )

    assert len(imported) == 1
    assert cleared == [True]
    cookie, origin = imported[0]
    assert bytes(cookie.name()).decode() == "__Secure-next-auth.session-token"
    assert bytes(cookie.value()).decode() == "session-secret"
    assert cookie.isSecure()
    assert cookie.isHttpOnly()
    assert origin.host() == "chatgpt.com"
    assert saved == [
        (
            "codex-work",
            "__Secure-next-auth.session-token=session-secret",
        )
    ]


def test_clear_browser_session_removes_secret_and_the_whole_profile(monkeypatch):
    from aiusageclock.config import webview_profile_dir

    profile = webview_profile_dir("codex-work")
    (profile / "cache").mkdir(parents=True)
    (profile / "Cookies").write_bytes(b"x")
    calls = []
    monkeypatch.setattr(
        cookies,
        "set_provider_cookie",
        lambda account_id, value: calls.append((account_id, value)),
    )

    cookies.clear_browser_session("codex-work")

    assert calls == [("codex-work", None)]
    assert not profile.exists()


def test_clear_browser_session_attempts_profile_cleanup_if_secret_fails(monkeypatch):
    from aiusageclock.config import webview_profile_dir

    profile = webview_profile_dir("claude")
    profile.mkdir(parents=True)
    (profile / "Cookies").write_bytes(b"x")
    monkeypatch.setattr(
        cookies,
        "set_provider_cookie",
        lambda account_id, value: (_ for _ in ()).throw(RuntimeError("locked")),
    )

    try:
        cookies.clear_browser_session("claude")
    except RuntimeError as exc:
        assert "encrypted cookie: locked" in str(exc)
    else:
        raise AssertionError("partial cleanup failure was not reported")

    assert not profile.exists()


def test_cookie_hydration_logs_names_without_values(monkeypatch, caplog):
    def fake_get_provider_cookie(provider):
        if provider == "claude":
            return "Cookie: other=value; sessionKey=secret-session"
        return None

    injected = []
    monkeypatch.setattr(cookies, "get_provider_cookie", fake_get_provider_cookie)
    monkeypatch.setattr(
        cookies,
        "inject_session_cookie",
        lambda provider, value: injected.append((provider, value)) or True,
    )
    caplog.set_level("INFO", logger="aiusageclock.webview.cookies")

    assert cookies.hydrate_account_from_keyring("claude", "claude") is True

    assert "provider=claude" in caplog.text
    assert "sessionKey" in caplog.text
    assert "secret-session" not in caplog.text
    assert injected == [("claude", "Cookie: other=value; sessionKey=secret-session")]


def test_cookie_hydration_uses_account_ids_for_secrets_and_profiles(monkeypatch):
    def fake_get_provider_cookie(account_id):
        if account_id == "codex-work":
            return "__Secure-next-auth.session-token=secret"
        return None

    injected = []
    monkeypatch.setattr(cookies, "get_provider_cookie", fake_get_provider_cookie)
    monkeypatch.setattr(
        cookies,
        "inject_session_cookie",
        lambda provider, value, *, account_id=None: injected.append(
            (provider, value, account_id)
        )
        or True,
    )

    assert cookies.hydrate_account_from_keyring("codex", "codex-work") is True
    assert injected == [
        ("codex", "__Secure-next-auth.session-token=secret", "codex-work")
    ]


def test_cookie_hydration_skips_injection_when_profile_has_persistent_cookies(
    monkeypatch, caplog
):
    # If Chromium has already persisted cookies for this profile, re-injecting
    # the stored blob would overwrite session tokens the site has rotated
    # since the original paste. Skip injection in that case.
    from aiusageclock.config import webview_profile_dir

    profile_dir = webview_profile_dir("codex-home")
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "Cookies").write_bytes(b"SQLite format 3\x00")

    monkeypatch.setattr(
        cookies,
        "get_provider_cookie",
        lambda account_id: (
            "__Secure-next-auth.session-token=stale" if account_id == "codex-home" else None
        ),
    )
    injected = []
    monkeypatch.setattr(
        cookies,
        "inject_session_cookie",
        lambda *a, **kw: injected.append((a, kw)) or True,
    )
    caplog.set_level("INFO", logger="aiusageclock.webview.cookies")

    assert cookies.hydrate_account_from_keyring("codex", "codex-home") is False
    assert injected == []
    assert "profile_has_cookies=True" in caplog.text
    assert "skip_reason=profile_has_live_cookies" in caplog.text


def test_cookie_hydration_injects_when_profile_cookies_file_is_missing(
    monkeypatch,
):
    # Fresh profile (no Cookies file): hydration must seed it from the keyring
    # so the first scrape can sign in.
    monkeypatch.setattr(
        cookies,
        "get_provider_cookie",
        lambda account_id: (
            "__Secure-next-auth.session-token=fresh" if account_id == "codex-fresh" else None
        ),
    )
    injected = []
    monkeypatch.setattr(
        cookies,
        "inject_session_cookie",
        lambda provider, value, *, account_id=None: injected.append(
            (provider, account_id)
        )
        or True,
    )

    assert cookies.hydrate_account_from_keyring("codex", "codex-fresh") is True
    assert injected == [("codex", "codex-fresh")]


def test_cookie_hydration_does_nothing_without_a_stored_cookie(monkeypatch):
    monkeypatch.setattr(cookies, "get_provider_cookie", lambda account_id: None)
    monkeypatch.setattr(
        cookies,
        "inject_session_cookie",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not inject")),
    )

    assert cookies.hydrate_account_from_keyring("claude", "claude") is False


# ----- hydration decides from the auth cookie itself, not from the file size -----


def _write_cookies_db(account_id: str, rows: list[tuple[str, str, int]]) -> None:
    """A Chromium-shaped ``Cookies`` database: (host_key, name, expires_utc)."""
    import sqlite3

    from aiusageclock.config import webview_profile_dir

    profile_dir = webview_profile_dir(account_id)
    profile_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(profile_dir / "Cookies")
    connection.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER, value TEXT)"
    )
    connection.executemany(
        "INSERT INTO cookies (host_key, name, expires_utc, value) VALUES (?, ?, ?, '')", rows
    )
    connection.commit()
    connection.close()


def _chromium_time(seconds_from_now: int) -> int:
    import time

    return int((time.time() + 11_644_473_600 + seconds_from_now) * 1_000_000)


def _hydrate(monkeypatch, kind: str, account_id: str) -> list[tuple]:
    injected: list[tuple] = []
    monkeypatch.setattr(
        cookies, "get_provider_cookie", lambda name: "sessionKey=from-keyring" if name == account_id else None
    )
    monkeypatch.setattr(
        cookies,
        "inject_session_cookie",
        lambda provider, value, *, account_id=None: injected.append((provider, account_id)) or True,
    )
    cookies.hydrate_account_from_keyring(kind, account_id)
    return injected


def test_hydration_reseeds_a_profile_whose_cookies_file_is_not_empty_but_holds_no_session(
    monkeypatch,
):
    # What a worker that died right after hydrating leaves behind: the file has
    # a size (SQLite header, schema) but the table is empty. A size check called
    # this "has live cookies" for ever.
    _write_cookies_db("claude-crash", [])

    assert _hydrate(monkeypatch, "claude", "claude-crash") == [("claude", "claude-crash")]


def test_hydration_reseeds_when_the_only_cookies_are_for_other_sites_or_not_auth_cookies(
    monkeypatch,
):
    _write_cookies_db(
        "claude-other",
        [
            (".example.com", "sessionKey", _chromium_time(3600)),
            (".claude.ai", "lastActiveOrg", _chromium_time(3600)),
        ],
    )

    assert _hydrate(monkeypatch, "claude", "claude-other") == [("claude", "claude-other")]


def test_hydration_reseeds_when_the_auth_cookie_has_expired(monkeypatch):
    _write_cookies_db("claude-old", [(".claude.ai", "sessionKey", _chromium_time(-3600))])

    assert _hydrate(monkeypatch, "claude", "claude-old") == [("claude", "claude-old")]


def test_hydration_never_overwrites_a_session_cookie_the_site_has_rotated(monkeypatch):
    # The keyring copy is from the original paste; the profile's cookie is
    # newer. Pushing the old one over it would sign the account out.
    _write_cookies_db("claude-live", [(".claude.ai", "sessionKey", _chromium_time(3600))])

    assert _hydrate(monkeypatch, "claude", "claude-live") == []


def test_hydration_reads_a_database_left_with_a_hot_journal_without_touching_it(monkeypatch):
    from aiusageclock.config import webview_profile_dir

    _write_cookies_db("claude-journal", [(".claude.ai", "sessionKey", _chromium_time(3600))])
    original = (webview_profile_dir("claude-journal") / "Cookies").read_bytes()
    journal = webview_profile_dir("claude-journal") / "Cookies-journal"
    journal.write_bytes(b"\x00" * 512)  # an unusable leftover journal

    assert _hydrate(monkeypatch, "claude", "claude-journal") == []
    assert (webview_profile_dir("claude-journal") / "Cookies").read_bytes() == original
    assert journal.exists()


def test_hydration_leaves_a_profile_alone_that_this_process_already_has_open(monkeypatch):
    # Its newest cookies may not have reached the file yet, so the file can
    # look empty while the live profile holds a rotated session.
    import sys
    import types

    _write_cookies_db("claude-open", [])
    module = types.ModuleType("aiusageclock.webview.profile")
    module._profiles = {"claude-open": object()}
    monkeypatch.setitem(sys.modules, "aiusageclock.webview.profile", module)

    assert _hydrate(monkeypatch, "claude", "claude-open") == []


def test_hydration_for_codex_recognises_its_split_session_cookies(monkeypatch):
    _write_cookies_db(
        "codex-live", [("chatgpt.com", "__Secure-next-auth.session-token.0", _chromium_time(3600))]
    )
    injected: list[tuple] = []
    monkeypatch.setattr(
        cookies,
        "get_provider_cookie",
        lambda name: "__Secure-next-auth.session-token=x" if name == "codex-live" else None,
    )
    monkeypatch.setattr(
        cookies,
        "inject_session_cookie",
        lambda provider, value, *, account_id=None: injected.append(1) or True,
    )

    cookies.hydrate_account_from_keyring("codex", "codex-live")

    assert injected == []
