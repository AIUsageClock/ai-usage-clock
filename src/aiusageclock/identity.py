"""Runtime identifiers for the product, in one place.

Keep this a dependency-free leaf module: it may not import anything from the
package, so every other module can import it without creating an import cycle.
``tests/test_identity_consistency.py`` lists the files that cannot import it
(build scripts, CI workflows, tools) and fails when one of them drifts.

The module has two parts, and they are not equally free to change.

* **Display** (first part): names and labels that people read. Editing them
  changes text and nothing else.
* **Shipped identifiers** (second part, below the banner): names that installed
  copies already store, or that other programs refer to by name -- the data
  folder, the keyring entry, the login task, the notification identity, the MCP
  server and command, the environment variables and so on. Each one is written
  out as a literal and is never derived from a display name or from another
  constant, so editing a display name cannot move one by accident. Changing one
  strands existing installs: settings and sign-ins stay behind in the old
  folder, a second login task appears, MCP clients keep starting a command that
  no longer exists. Do it only together with migration steps and a CHANGELOG
  entry. ``tests/test_identity_shipped_values.py`` pins the values 1.0.0 shipped
  and fails until that test is updated on purpose.

Only identifiers and short labels live here. Sentences shown to the user keep
the product name inline.
"""
from __future__ import annotations

# --- Display ---------------------------------------------------------------

#: Name shown to the user (window titles, tray tooltip, toast).
PRODUCT_NAME = "AI Usage Clock"
#: Shorter name for headers that cannot fit ``PRODUCT_NAME``.
PRODUCT_SHORT_NAME = "AI Clock"
#: Shortest form, for a header too narrow even for ``PRODUCT_SHORT_NAME``.
PRODUCT_TINY_NAME = "AI"
#: Name used for task authors and similar publisher fields.
PUBLISHER = "AI Usage Clock contributors"
#: Author field of the login task. A label, not what identifies the task.
WINDOWS_TASK_AUTHOR = PUBLISHER
REPO_URL = "https://github.com/AIUsageClock/ai-usage-clock"
#: Stem of the packaged icon files (``<stem>.png`` / ``.ico`` / ``.icns``).
#: Renaming it means renaming those files and the build scripts that name them.
ICON_BASENAME = "aiusageclockicon"

# === Shipped identifiers ====================================================
# Everything below is a literal. See the module docstring before editing it.

# --- Program names ---------------------------------------------------------

#: Lower-case, hyphenated form: executable, distribution and archive names.
SLUG = "ai-usage-clock"
#: Python import name.
PACKAGE_NAME = "aiusageclock"
#: Root of the logger hierarchy.
LOGGER_NAME = "aiusageclock"

# --- Files, folders and stores ---------------------------------------------

#: Per-user data folder name (under %APPDATA%, Application Support or XDG config).
APP_NAME = "ai-usage-clock"
#: Service name of the stored sign-ins and tokens in the OS keyring.
KEYRING_SERVICE = "ai-usage-clock"
LOG_FILENAME = "ai-usage-clock.log"
LOCK_FILENAME = "ai-usage-clock.lock"
QT_APPLICATION_NAME = "ai-usage-clock"
QT_ORGANIZATION_NAME = "ai-usage-clock"
#: QtWebEngine profile names are ``<prefix>-<provider>``.
WEBENGINE_PROFILE_PREFIX = "ai-usage-clock"

# --- Platform integration --------------------------------------------------

#: Windows Task Scheduler entry that starts the app at login.
WINDOWS_TASK_NAME = "AI Usage Clock"
#: Windows AppUserModelID used to register toast notifications.
WINDOWS_AUMID = "AIUsageClock.AIUsageClock"
#: macOS bundle identifier.
MACOS_BUNDLE_ID = "com.aiusageclock.ai-usage-clock"
#: Label of the macOS login LaunchAgent.
MACOS_LAUNCH_AGENT_LABEL = "com.aiusageclock.ai-usage-clock"
#: XDG autostart entry on Linux.
LINUX_DESKTOP_FILENAME = "ai-usage-clock.desktop"

# --- Environment variables -------------------------------------------------

ENV_FORCE_WEBENGINE = "AIUSAGECLOCK_FORCE_WEBENGINE"
ENV_ALLOW_PLAINTEXT_SECRETS = "AIUSAGECLOCK_ALLOW_PLAINTEXT_SECRETS"

# --- MCP helper ------------------------------------------------------------

#: Console script / executable name of the MCP helper; MCP clients launch it by this name.
MCP_COMMAND = "ai-usage-clock-mcp"
#: Server name announced to MCP clients.
MCP_SERVER_NAME = "AI Usage Clock"
MCP_URI_SCHEME = "aiusageclock"
