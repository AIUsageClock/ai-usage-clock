# Setup guide

**English** · [繁體中文](setup.zh-TW.md) · [简体中文](setup.zh-CN.md)

[Back to the README](../README.md)

This page covers first-time setup for each service. For everyday use, see
[Using AI Usage Clock](usage.md).

On first launch the widget appears with the enabled service tiles. Claude,
Codex, and GitHub Copilot are on by default; OpenCode Go, OpenRouter,
Antigravity, and the two reset trackers are off until you enable them in
**Settings → General**. Claude and Codex use a **Sign in** or **Paste cookie**
flow; OpenCode Go, GitHub Copilot, and OpenRouter are configured from Settings
with API credentials. Open Settings to disable services you don't use or to add
more Claude, Codex, or OpenCode Go accounts.

## First-time setup per service

### Claude.ai

**Sign in (recommended):** asks which installed Chrome-family browser to use,
remembers that choice, supports Google and passkeys, and connects the resulting
Claude session automatically. No cookie copying is required. **Paste cookie**
remains available as a recovery fallback. Add extra Claude subscriptions from
**Settings → Claude**.

### ChatGPT Codex

Same as Claude. **Sign in** uses your chosen installed browser and automatically
connects the ChatGPT session, including Google-linked and passkey accounts.
**Paste cookie** remains available only as a fallback. Add extra Codex
subscriptions from **Settings → Codex**.

### OpenCode Go

Sign in at <https://opencode.ai/auth> and copy an API key. In **Settings →
OpenCode**, paste the key beside the subscription name. Each subscription has an
independent key and tile. AI Usage Clock stores keys in the system credential
store and reads Rolling, Weekly, and Monthly usage from the authenticated Go API.
The shorter name **OpenCode** is used in the app.

### GitHub Copilot

Create a **fine-grained PAT** at
<https://github.com/settings/personal-access-tokens/new>. For personal plans, add
**Account permissions → Plan → Read**. Paste it into Settings and set your
monthly AI credit allowance (Pro=1,500, Pro+=7,000, Max=20,000). If Copilot is
billed through an organization, enter the billing org and use a token/account
with org billing access and **Organization permissions → Administration → Read**.

### OpenRouter

Create an inference API key at <https://openrouter.ai/keys> and paste it into
Settings. To show account balance and model activity, also create a management
key at <https://openrouter.ai/settings/provisioning-keys>. Management keys cannot
be used for inference; AI Usage Clock stores it separately and only uses it for
OpenRouter management endpoints. Daily spend budget is optional.

### Antigravity

In **Settings → General**, enable **Antigravity**. AI Usage Clock runs the local
`agy` CLI's `/quota` command; no account or API key is entered in AI Usage Clock.
Leave **agy CLI** blank for auto-detection (`agy` on `PATH`, then
`%LOCALAPPDATA%\agy\bin\agy.exe` on Windows), or select the executable. A missing
file or a file not named `agy` is reported and not run. The tile can show Gemini
and Claude+GPT usage, each with 5-hour and weekly limits; choose which groups to
display in the Antigravity tab. AI Usage Clock disables `agy` background updates
for its own calls and hides its console window; this does not affect updates when
you run `agy` yourself. If a response indicates token use, or the result cannot
confirm no use, polling stops until AI Usage Clock is restarted.

## Multiple Claude / Codex / OpenCode Go accounts

Claude, Codex, and OpenCode Go can track more than one subscription at a time.
Open the provider's Settings tab, click **Add another**, and give the account a
short name. Use **Sign in** or **Paste cookie** for each Claude or Codex row;
paste the matching API key into each OpenCode row. Default accounts display as
`Claude`, `Codex`, or `OpenCode`; named accounts display as `Claude (Work)`,
`Codex (Account 2)`, `OpenCode (Team)`, etc. Claude and Codex accounts keep
separate browser sessions, while OpenCode accounts keep separate system-keychain
entries.

The **General** tab controls provider groups. Enabling Claude, Codex, or OpenCode
shows every configured account in that family. Any account can be removed from
its provider tab, including the original account; the **Add another** button
remains available when no accounts are configured. Every account has separate
credentials, widget tile state, and history records.

Use **Clear sign-in** beside an account to remove its session from AI Usage Clock.
This clears both the OS-protected saved cookie and the account's live embedded
browser cookies. It does not revoke sessions in other browsers or devices; use
the provider's security settings when you need to sign out everywhere.

## Optional local usage and cost

Enable **Settings → Local usage** to estimate what Claude Code and Codex
activity on this computer would cost at API prices. AI Usage Clock stores token
counts, model names, timestamps, and log metadata (message and session IDs, the
Claude Code version, the paths of the log files, and the usage-limit readings
that Codex logs contain) locally; nothing is uploaded and the estimates are not
charges.

Open **Usage details** to compare allowance use with estimated cost, including
views by model, day, and trend. Browser chats, cloud tasks, other computers,
and logs deleted before AI Usage Clock imports them are not included.

## Optional reset announcements

Both reset tiles are off by default. Enable **Codex Resets** or **Claude Resets**
in **Settings → General**. These third-party trackers are independent of OpenAI
and Anthropic, and their AI classification can mistake an ambiguous post for a
completed reset; open the linked original post to confirm.

- While AI Usage Clock is running, it contacts each tracker no more than once
  every 15 minutes, including after a failed request; if a tracker asks for a
  longer wait, it honors that. A restart asks again right away.
- The sites receive your IP address and the
  `ai-usage-clock/<version> (+https://github.com/AIUsageClock/ai-usage-clock)`
  User-Agent. Requests go to `https://codex-resets.com/api/v1/status` and
  `https://claude-resets.com/api/resets`.
- Each tile shows the latest event and how long ago it happened, labeled by
  type: **Announced** (a reset announced ahead of time; only Codex has this
  type), **Reset** (limits refilled), or **Banked** (a reset credit you can
  redeem). ↗ opens the original post; ✕ hides the tile until another entry
  arrives.
- Codex also shows an AI-predicted **Watch** row (a forecast level, an
  optional reset chance, and a time window). It is not an official announcement
  and does not trigger notifications. It disappears when its forecast expires.
- Claude provisional events are marked in the tooltip; Claude entries not marked
  as `reset` (including policy notices) are omitted.
- AI Usage Clock only opens links supplied by the trackers when they use `http`
  or `https`.
- Choose reset notification types in **Settings → Reset alerts**: Codex offers
  announced, reset, and banked alerts; Claude offers reset and banked alerts.
  The first event the app ever finds for a tracker is recorded without a
  notification. If you turn a tracker off and back on later, the newest event is
  compared with the last one recorded, so an event posted while it was off can
  trigger a notification.

[Data from Codex Resets](https://codex-resets.com) ·
[Data from Claude Resets](https://claude-resets.com)

How these alerts are delivered on each system is described in
[Using AI Usage Clock](usage.md#reset-notifications).

## How browser sign-in works

Google does not allow OAuth sign-in inside embedded browser controls, so AI
Usage Clock can open Chrome, Edge, Brave, or Chromium instead. On first use it asks
which one you want and remembers the choice; change it later under **Settings →
General → Sign-in browser**. The flow is local:

1. AI Usage Clock creates a new temporary browser profile containing none of your
   regular browser history, extensions, cookies, or saved accounts.
2. You sign in normally in that browser window, including with Google or a
   passkey.
3. AI Usage Clock watches the temporary browser through a random loopback-only
   debugging port and accepts cookies only for the selected provider:
   `claude.ai` or `chatgpt.com`.
4. The provider session is copied into that AI Usage Clock account's persistent
   browser profile and OS-protected secret storage. Google cookies and cookies
   for unrelated sites are ignored.
5. AI Usage Clock closes the temporary browser, deletes its temporary profile, and
   verifies that the provider's usage page is signed in.

The small AI Usage Clock window shown alongside the external browser is a status and
recovery dialog, not a second active browser. The embedded webview loads only
when you choose it. If the external browser closes before authentication, AI
Usage Clock returns to the browser choice instead of opening the fallback on its own.
In embedded mode, a recognized session is verified automatically; **I'm signed
in** remains available as a manual fallback.

Your everyday Chrome/Edge profile is never opened or inspected. The imported
provider session remains available across AI Usage Clock restarts, so sign-in only
needs to be repeated when the provider expires or revokes it. The embedded
browser and manual **Paste cookie** option remain available as recovery paths.

## Where your data is stored

Sessions and settings persist between runs under the per-OS app-data directory:

| OS      | App data                                        | Secrets backend                           |
| ------- | ----------------------------------------------- | ----------------------------------------- |
| Windows | `%APPDATA%/ai-usage-clock/`                     | Credential Manager (GitHub PAT, OpenRouter keys, and OpenCode Go keys) + DPAPI-encrypted `secrets.dat` (cookies, since the Credential Manager blob limit is too small for ChatGPT JWTs) |
| macOS   | `~/Library/Application Support/ai-usage-clock/` | Login Keychain                            |
| Linux   | `~/.config/ai-usage-clock/`                     | Secret Service (GNOME Keyring / KWallet)  |

AI Usage Clock does not include telemetry or a backend service. Provider requests
are made from the local app to the configured providers. See
[SECURITY.md](../SECURITY.md) for security and privacy notes.

## Paste cookie (fallback)

If automatic browser sign-in cannot start or import the provider session, you
can still copy an existing Claude or Codex session cookie into the
app manually. This is a recovery path; Google-linked and passkey accounts
should work with the normal **Sign in** button.

1. Sign into the provider in **Chrome / Edge / Firefox** as you normally do.
2. For ChatGPT, press **F12** → **Network**, reload the page, click a
   `chatgpt.com` request, and copy the full **Request Headers → Cookie:** value.
   This includes split session cookies plus companion auth cookies such as
   `__Secure-oai-is`.
3. For Claude, press **F12** → **Network**, reload `https://claude.ai/new#settings/usage`,
   click a `claude.ai` request, and copy the full **Request Headers → Cookie:**
   value. It must include `sessionKey`.
4. In the app, open the matching provider tab in Settings, click **Paste cookie**, paste the header, and Save.
