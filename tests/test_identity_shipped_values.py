"""The identifiers 1.0.0 shipped are a contract with installed copies.

Installed copies store these names (the data folder, the keyring entry, the
login task, the notification identity) and other programs call them (the MCP
command and server name, the environment variables). Changing one does not
rename anything on a user's machine: settings and sign-ins stay behind in the
old folder, a second login task appears, MCP clients keep starting a command
that no longer exists.

``aiusageclock.identity`` keeps them in a second part of the file, written as
literals. This test pins each value, and checks that the second part holds
exactly the pinned names and nothing derived. It fails on purpose when someone
changes one: the change then needs migration steps and a CHANGELOG entry, and
this table updated in the same commit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import aiusageclock
from aiusageclock import identity

IDENTITY_FILE = Path(aiusageclock.__file__).resolve().parent / "identity.py"
#: The banner line that opens the shipped part of identity.py.
SHIPPED_BANNER = "# === Shipped identifiers"

WHAT_TO_DO = (
    "changing a shipped identifier strands existing installs; add migration "
    "steps, update CHANGELOG, then update SHIPPED_IN_1_0_0 in this test"
)

SHIPPED_IN_1_0_0 = {
    # Program names
    "SLUG": "ai-usage-clock",
    "PACKAGE_NAME": "aiusageclock",
    "LOGGER_NAME": "aiusageclock",
    # Files, folders and stores
    "APP_NAME": "ai-usage-clock",
    "KEYRING_SERVICE": "ai-usage-clock",
    "LOG_FILENAME": "ai-usage-clock.log",
    "LOCK_FILENAME": "ai-usage-clock.lock",
    "QT_APPLICATION_NAME": "ai-usage-clock",
    "QT_ORGANIZATION_NAME": "ai-usage-clock",
    "WEBENGINE_PROFILE_PREFIX": "ai-usage-clock",
    # Platform integration
    "WINDOWS_TASK_NAME": "AI Usage Clock",
    "WINDOWS_AUMID": "AIUsageClock.AIUsageClock",
    "MACOS_BUNDLE_ID": "com.aiusageclock.ai-usage-clock",
    "MACOS_LAUNCH_AGENT_LABEL": "com.aiusageclock.ai-usage-clock",
    "LINUX_DESKTOP_FILENAME": "ai-usage-clock.desktop",
    # Environment variables
    "ENV_FORCE_WEBENGINE": "AIUSAGECLOCK_FORCE_WEBENGINE",
    "ENV_ALLOW_PLAINTEXT_SECRETS": "AIUSAGECLOCK_ALLOW_PLAINTEXT_SECRETS",
    # MCP helper
    "MCP_COMMAND": "ai-usage-clock-mcp",
    "MCP_SERVER_NAME": "AI Usage Clock",
    "MCP_URI_SCHEME": "aiusageclock",
}

_MISSING = object()


def changed_identifiers(module=identity, pinned=SHIPPED_IN_1_0_0) -> dict[str, tuple[object, object]]:
    """``{name: (shipped value, current value)}`` for every pinned name that differs."""
    return {
        name: (expected, getattr(module, name, _MISSING))
        for name, expected in pinned.items()
        if getattr(module, name, _MISSING) != expected
    }


def shipped_part(source: str) -> dict[str, ast.expr]:
    """Top-level constants below the banner in an identity module's source.

    Raises ValueError when the banner is missing.
    """
    banner_line = next(
        (
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if line.startswith(SHIPPED_BANNER)
        ),
        None,
    )
    if banner_line is None:
        raise ValueError(f"no line starting with {SHIPPED_BANNER!r}")
    constants: dict[str, ast.expr] = {}
    for node in ast.parse(source).body:
        if node.lineno <= banner_line:
            continue
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value
    return constants


def derived(constants: dict[str, ast.expr]) -> list[str]:
    """Names whose value is anything but a plain string literal."""
    return sorted(
        name
        for name, value in constants.items()
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str))
    )


# --- the values -----------------------------------------------------------------


@pytest.mark.parametrize(("name", "expected"), sorted(SHIPPED_IN_1_0_0.items()))
def test_a_shipped_identifier_keeps_its_1_0_0_value(name, expected):
    assert getattr(identity, name, _MISSING) == expected, f"{name}: {WHAT_TO_DO}"


def test_changing_a_shipped_value_is_reported(monkeypatch):
    assert changed_identifiers() == {}

    monkeypatch.setattr(identity, "KEYRING_SERVICE", "renamed-service")
    monkeypatch.setattr(identity, "WINDOWS_AUMID", "Renamed.Id")
    monkeypatch.delattr(identity, "LOCK_FILENAME")

    assert changed_identifiers() == {
        "KEYRING_SERVICE": ("ai-usage-clock", "renamed-service"),
        "WINDOWS_AUMID": ("AIUsageClock.AIUsageClock", "Renamed.Id"),
        "LOCK_FILENAME": ("ai-usage-clock.lock", _MISSING),
    }


# --- the shape of the file ------------------------------------------------------


def test_the_shipped_part_holds_exactly_the_pinned_identifiers():
    constants = shipped_part(IDENTITY_FILE.read_text(encoding="utf-8"))

    assert sorted(constants) == sorted(SHIPPED_IN_1_0_0), (
        "every constant below the banner in identity.py needs a pinned value "
        "here, and every pinned name needs a constant there"
    )


def test_every_shipped_identifier_is_a_literal():
    constants = shipped_part(IDENTITY_FILE.read_text(encoding="utf-8"))

    assert derived(constants) == [], (
        "a shipped identifier must be written out, not built from a display "
        "name or another constant"
    )


def test_a_derived_shipped_identifier_is_reported():
    source = (
        "PRODUCT_NAME = 'Some Product'\n"
        "# === Shipped identifiers ===\n"
        "SLUG = 'some-product'\n"
        "WINDOWS_TASK_NAME = PRODUCT_NAME\n"
        "LOG_FILENAME = f'{SLUG}.log'\n"
        "LOCK_FILENAME = SLUG + '.lock'\n"
    )

    assert derived(shipped_part(source)) == ["LOCK_FILENAME", "LOG_FILENAME", "WINDOWS_TASK_NAME"]


def test_only_constants_below_the_banner_count_as_shipped():
    source = (
        "PRODUCT_NAME = 'Some Product'\n"
        "SHORT: str = 'Some'\n"
        "# === Shipped identifiers ===\n"
        "SLUG: str = 'some-product'\n"
        "def helper():\n"
        "    return 1\n"
    )

    assert sorted(shipped_part(source)) == ["SLUG"]


def test_an_identity_file_without_the_banner_is_rejected():
    with pytest.raises(ValueError, match="Shipped identifiers"):
        shipped_part("SLUG = 'x'\n")


def test_display_names_are_not_pinned():
    # They are free to change; pinning them would make a rename impossible.
    display = {"PRODUCT_NAME", "PRODUCT_SHORT_NAME", "PRODUCT_TINY_NAME", "PUBLISHER", "REPO_URL"}

    assert display.isdisjoint(SHIPPED_IN_1_0_0)
    assert display.isdisjoint(shipped_part(IDENTITY_FILE.read_text(encoding="utf-8")))
