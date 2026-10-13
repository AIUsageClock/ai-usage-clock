# MCP usage guard

AI Usage Clock includes an optional local stdio MCP server for tools and agents that
want to inspect subscription usage before starting expensive work. The
integration is disabled by default. Enable it under **Settings → MCP** and
configure an optional pause percentage for each account.

Bind each MCP client or profile to the AI Usage Clock account it actually uses:

```text
ai-usage-clock-mcp --account-id codex-work
```

Source installations need the optional dependency first:

```text
pip install -e '.[mcp]'
```

Release archives include the helper next to the application: inside the
`ai-usage-clock` folder on Windows and Linux, and alongside `ai-usage-clock.app` on macOS.

On macOS the helper is a separate unsigned binary outside the `.app`, so
clearing quarantine on the bundle does not cover it. Clear it once after
extracting:

```bash
xattr -dr com.apple.quarantine ai-usage-clock-mcp
```

Configure the client to call `check_current_account_usage` before costly work
and stop whenever the returned `allowed` value is `false`. Other tools provide
sanitized usage and recommend the account with the most configured headroom.

`--account-id` selects which account the guard applies to; it is not an access
boundary. `get_ai_usage` and `recommend_ai_account` report every enabled
account so they can make recommendations. A connected client therefore sees
all account display names.

MCP cannot suspend a client that ignores tool results. The server reads only
AI Usage Clock's sanitized local usage cache; credentials and raw provider responses
are never published. Configured guards fail closed when usage is stale,
unavailable, or from a failed refresh. Disabling the integration removes the
cache and stops publication.
