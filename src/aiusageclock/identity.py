"""Runtime identifiers for the product, in one place.

Renaming the product should mean editing this file (plus the files that cannot
import the package; ``tests/test_identity_consistency.py`` lists them and fails
when one of them drifts). Keep this a dependency-free leaf module: it may not
import anything from the package, so every other module can import it without
creating an import cycle.

Only identifiers and short labels live here. Sentences shown to the user keep
the product name inline.
"""
from __future__ import annotations

# --- Product ---------------------------------------------------------------

#: Name shown to the user (window titles, tray tooltip, toast, MCP server name).
PRODUCT_NAME = "AI Usage Clock"
#: Shorter name for headers that cannot fit ``PRODUCT_NAME``.
PRODUCT_SHORT_NAME = "AI Clock"
#: Lower-case, hyphenated form used for files, folders and service names.
SLUG = "ai-usage-clock"
#: Python import name; also the root of the logger hierarchy.
PACKAGE_NAME = "aiusageclock"
LOGGER_NAME = PACKAGE_NAME
#: Stem of the packaged icon files (``<stem>.png`` / ``.ico`` / ``.icns``).
ICON_BASENAME = "aiusageclockicon"
#: Name used for task authors and similar publisher fields.
PUBLISHER = "AI Usage Clock contributors"
REPO_URL = "https://github.com/AIUsageClock/ai-usage-clock"

# --- Files, folders and stores ---------------------------------------------

#: Per-user data folder name (under %APPDATA%, Application Support or XDG config).
APP_NAME = SLUG
KEYRING_SERVICE = SLUG
LOG_FILENAME = f"{SLUG}.log"
LOCK_FILENAME = f"{SLUG}.lock"
QT_APPLICATION_NAME = SLUG
QT_ORGANIZATION_NAME = SLUG
#: QtWebEngine profile names are ``<prefix>-<provider>``.
WEBENGINE_PROFILE_PREFIX = SLUG

# --- Platform integration --------------------------------------------------

#: Windows Task Scheduler entry that starts the app at login.
WINDOWS_TASK_NAME = PRODUCT_NAME
WINDOWS_TASK_AUTHOR = PUBLISHER
#: Windows AppUserModelID used to register toast notifications.
WINDOWS_AUMID = "AIUsageClock.AIUsageClock"
#: macOS bundle identifier; the login LaunchAgent uses it as its label.
MACOS_BUNDLE_ID = "com.aiusageclock.ai-usage-clock"
MACOS_LAUNCH_AGENT_LABEL = MACOS_BUNDLE_ID
#: XDG autostart entry on Linux.
LINUX_DESKTOP_FILENAME = f"{SLUG}.desktop"

# --- Environment variables -------------------------------------------------

ENV_FORCE_WEBENGINE = "AIUSAGECLOCK_FORCE_WEBENGINE"
ENV_ALLOW_PLAINTEXT_SECRETS = "AIUSAGECLOCK_ALLOW_PLAINTEXT_SECRETS"

# --- MCP helper ------------------------------------------------------------

#: Console script / executable name of the MCP helper.
MCP_COMMAND = f"{SLUG}-mcp"
MCP_SERVER_NAME = PRODUCT_NAME
MCP_URI_SCHEME = PACKAGE_NAME
