# Using AI Usage Clock

**English** · [繁體中文](usage.zh-TW.md) · [简体中文](usage.zh-CN.md)

[Back to the README](../README.md)

This page covers everyday use and known limitations. To connect your accounts
first, see the [setup guide](setup.md).

## Daily use

- **Windows / Linux:** drag the floating widget to move it and use the
  bottom-right grip to resize it. Collapse it to a compact pill or hide it in
  the system tray. Right-click the widget or tray icon for the full menu. On
  desktops without a system tray, right-click the widget instead.
- **macOS:** the menu-bar item shows the highest usage for each enabled
  provider or account. Click it to open the popover.
- Settings control providers, accounts, colors, window behavior, UI scale,
  refresh timing, and start-at-login.
- Auto-refresh runs every 5 minutes while usage is changing, then backs off to
  a maximum of 60 minutes by default.
- On refresh errors, tiles show the short cause; retained values are marked
  `<cause> · stale` (for example, `offline · stale` or `timeout · stale`), and
  errors without retained values show `error · <cause>`.

## Reset notifications

Reset alerts come from the optional Codex Resets and Claude Resets trackers
(see [Optional reset announcements](setup.md#optional-reset-announcements)).

- On Windows, alerts use native notifications in Notification Center; clicking
  one opens its original post in your browser, including after AI Usage Clock
  exits. Alerts that arrive together are shown at the same time.
- If native notifications fail, or on non-Windows systems, a system tray balloon
  is used when a Qt system tray is available. Balloons are spaced at least 8
  seconds apart; clicking one opens the last balloon's post.
- Reset notifications are not shown in macOS menu-bar mode or on Linux without a
  system tray. Reset tiles still update in the macOS popover and the tray-less
  Linux floating widget.
- If balloon tips are turned off in Windows, the fallback balloons are not shown.
- AI Usage Clock registers its notification name and bundled icon under
  `HKCU\Software\Classes\AppUserModelId\AIUsageClock.AIUsageClock` (`DisplayName` =
  `AI Usage Clock`, `IconUri` = the bundled icon path); you can delete this key
  after uninstalling.

## Notes and limitations

- Reset-announcement tiles have no percentage and are omitted from the macOS
  menu-bar summary.
- Antigravity usage, reset tiles, and native notifications have been tested on
  Windows 11 only; macOS and Linux are untested.
- **Why does Sign in open a separate Chrome-family window?** Google blocks OAuth in embedded user-agents, while Chrome's App-Bound Encryption prevents AI Usage Clock from reading an existing everyday browser profile. AI Usage Clock therefore opens a fresh temporary browser profile, receives only the selected provider's cookies through Chrome's loopback debugging interface, imports them into the app, and deletes the temporary profile.
- **Claude / Codex layouts may change.** If a browser-backed provider tile shows "error" after the provider updates its UI, its page-extractor JS under `src/aiusageclock/providers/` may need adjusting — the rest of the app keeps working.
- **Remote desktops and GPU-less sessions need one caveat.** The widget is plain Qt Widgets and runs anywhere, including over RDP/XRDP and on machines with no GPU. Claude and Codex are read by driving an embedded Chromium, which needs an OpenGL context; a session offering neither GLX nor EGL cannot provide one. In that case those tiles report that they need a browser, while OpenCode Go, GitHub Copilot, OpenRouter, and Linear use API credentials and work normally. Most Linux desktops supply software GL through Mesa, so this only bites on bare X servers and some remote sessions. If AI Usage Clock misjudges your session, set `AIUSAGECLOCK_FORCE_WEBENGINE=1` to skip the check.
- The Copilot REST endpoint returns the _current calendar month_ of billing usage. The widget tracks gross AI credits consumed against the included allowance; net quantity/amount is only the billable overage. Reset is computed as the 1st of the next month. GitHub does not currently expose a reliable personal-plan allowance field, so Settings uses a plan dropdown with a Custom fallback. Annual/request-based accounts are handled with a legacy premium-request fallback.
- **Copilot usage lags.** The Copilot REST endpoint updates noticeably slower than Claude or Codex — credit counts can take hours to reflect recent activity. The widget shows the most recent value GitHub returns; treat the Copilot tile as a trailing indicator, not real-time.
- **Copilot AI credits.** GitHub moved Copilot from per-request quotas to token-based AI credits. Code completions and next edit suggestions remain included for paid plans, while Chat, CLI, cloud agent, Spaces, Spark, and third-party coding agents consume AI credits. The app shows the credit usage GitHub returns; if your account is org-billed, enter the billing organization so AI Usage Clock reads the organization billing pool.
- **OpenRouter uses two key types.** The inference key is used for `/key` spend data. The management key is required for `/credits` account balance and `/activity` model history. Without a management key, AI Usage Clock still shows key-level spend but cannot show balance or model activity.
- **OpenRouter time windows are UTC.** Today/month spend come from OpenRouter's current UTC day and month fields. Model activity comes from OpenRouter's default `/activity` history window: the last 30 completed UTC days, excluding the current UTC day.
- **Linear counts issues, not tokens.** The Linear tile shows the number of non-archived issues across all teams the API key can see, against the Free plan's limit of 250 (adjustable in Settings → Linear), as one **Issues** bar with no reset time. A key that cannot see every team undercounts. Paid workspaces have no issue limit, so the row shows "no limit" instead of a bar.
- **Idle limits.** A limit that is at 0% and whose window has not started shows `idle` instead of a countdown; the countdown starts when you next use it.
