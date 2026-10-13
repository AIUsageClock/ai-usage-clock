"""Keep ``aiusageclock.identity`` and the files that cannot import it in step.

Build scripts, CI workflows and the smoke-test tools run outside the package,
so they spell the product's identifiers out. This test reads their text and
checks each spelling against ``identity``: renaming a constant there fails here
until every such file follows. The package itself is covered by an AST scan
that rejects a bare string literal equal to an identifier outside ``identity``.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

import aiusageclock
from aiusageclock import identity

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = Path(aiusageclock.__file__).resolve().parent
IDENTITY_FILE = SRC_ROOT / "identity.py"

Expectation = tuple[str, re.Pattern[str]]


def _lit(label: str, text: str) -> Expectation:
    """The text must appear verbatim."""
    return label, re.compile(re.escape(text))


def _name(label: str, text: str) -> Expectation:
    """The text must appear as a whole name: ``app`` does not match ``app-mcp``."""
    return label, re.compile(re.escape(text) + r"(?![\w.-])")


def expectations() -> dict[str, list[Expectation]]:
    """What each non-importing file must say, built from ``identity`` on every call."""
    slug = identity.SLUG
    mcp = identity.MCP_COMMAND
    pkg = identity.PACKAGE_NAME
    icon = identity.ICON_BASENAME
    return {
        "build.sh": [
            _lit("macOS bundle id", f"--osx-bundle-identifier {identity.MACOS_BUNDLE_ID})"),
            _name("GUI executable name", f"--name {slug}"),
            _name("MCP helper name", f"--name {mcp}"),
            _name("bundled package data", f"--collect-data {pkg}"),
            _lit("macOS icon", f"--icon src/{pkg}/assets/{icon}.icns"),
            _lit("Linux icon", f"--icon src/{pkg}/assets/{icon}.png"),
            _lit("macOS app bundle", f"dist/{slug}.app/Contents/Info.plist"),
            _lit("MCP helper inside the bundle", f"dist/{slug}/{mcp}"),
        ],
        "build.ps1": [
            _lit("GUI executable name", f'"--name", "{slug}",'),
            _lit("MCP helper name", f'"--name", "{mcp}",'),
            _lit("bundled package data", f'"--collect-data", "{pkg}"'),
            _lit("Windows icon", f"src\\{pkg}\\assets\\{icon}.ico"),
            _lit("one-file executable", f"dist\\{slug}.exe"),
            _lit("MCP helper inside the bundle", f"dist\\{slug}\\{mcp}.exe"),
        ],
        "tools/smoke_test_mcp.py": [
            _lit("MCP server name", f'serverInfo.name != "{identity.MCP_SERVER_NAME}"'),
        ],
        "tools/smoke_test_gui.py": [
            _lit("macOS binary", f'"MacOS" / "{slug}"'),
            _lit("Windows and Linux binary", f'"{slug}.exe" if platform == "win32" else "{slug}"'),
            _lit("data folder", f'Path(env["APPDATA"]) / "{identity.APP_NAME}"'),
            _lit("log file", f'config_dir / "{identity.LOG_FILENAME}"'),
            _lit("startup log prefix", f'f"{slug} {{expected_version}} starting platform="'),
        ],
        # The smoke test above expects exactly this prefix in the startup log.
        "src/aiusageclock/app.py": [
            _lit(
                "startup log prefix",
                '"%s %s starting platform=%s frozen=%s executable=%s cwd=%s app_data=%s",\n'
                "            SLUG,\n"
                "            __version__,",
            ),
        ],
        ".github/workflows/release.yml": [
            _lit("Windows MCP smoke test", f"dist\\{slug}\\{mcp}.exe"),
            _lit("macOS MCP smoke test", f"smoke_test_mcp.py dist/{mcp}\n"),
            _lit("Linux MCP smoke test", f"smoke_test_mcp.py dist/{slug}/{mcp}\n"),
            _lit("Windows GUI smoke test", f"smoke_test_gui.py dist\\{slug}\n"),
            _lit("macOS GUI smoke test", f"smoke_test_gui.py dist/{slug}.app"),
            _lit("Windows archive", f'"{slug}-$version-windows.zip"'),
            _lit("Unix archive", f'archive="{slug}-${{version}}-'),
            _lit("macOS archive members", f"{slug}.app {mcp}"),
            _lit("release title", f"name: {identity.PRODUCT_NAME} $"),
        ],
        ".github/workflows/test.yml": [
            _lit("MCP helper name", f"--name {mcp} "),
            _lit("MCP helper smoke test", f"smoke_test_mcp.py dist/{mcp}"),
        ],
        "tools/make_icons.py": [
            _lit("icon file stem", f'NAME = "{icon}"'),
        ],
        "tools/wdsi_submission.py": [
            _lit("default executable", f'"dist" / "{slug}" / "{slug}.exe"'),
            _lit("repository URL", f'REPO_URL = "{identity.REPO_URL}"'),
        ],
        "tools/write_pyinstaller_version_info.py": [
            _lit("GUI target", f'"{slug}": '),
            _lit("MCP target", f'"{mcp}": '),
            _lit("product name", f'"ProductName": "{identity.PRODUCT_NAME}"'),
        ],
    }


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def missing(relative_path: str, text: str | None = None) -> list[str]:
    """Labels of the expectations ``text`` (default: the file itself) does not meet."""
    if text is None:
        text = _read(relative_path)
    return [
        label for label, pattern in expectations()[relative_path] if not pattern.search(text)
    ]


@pytest.mark.parametrize("relative_path", sorted(expectations()))
def test_file_spells_identifiers_like_identity(relative_path):
    assert missing(relative_path) == []


def test_pyproject_matches_identity():
    project = tomllib.loads(_read("pyproject.toml"))
    metadata = project["project"]

    assert metadata["name"] == identity.SLUG
    assert metadata["scripts"] == {
        identity.SLUG: f"{identity.PACKAGE_NAME}.__main__:main",
        identity.MCP_COMMAND: f"{identity.PACKAGE_NAME}.mcp_server:main",
    }
    assert metadata["urls"]
    for label, url in metadata["urls"].items():
        assert url.startswith(identity.REPO_URL), label
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == [f"src/{identity.PACKAGE_NAME}"]


def test_packaged_icon_files_exist():
    assets = SRC_ROOT / "assets"
    for extension in ("png", "ico", "icns", "svg"):
        assert (assets / f"{identity.ICON_BASENAME}.{extension}").is_file(), extension


# --- the check itself must catch drift -------------------------------------


def test_a_file_that_disagrees_with_identity_is_reported():
    shell = _read("build.sh")
    wrong = shell.replace(identity.MACOS_BUNDLE_ID, "com.example.other")
    assert wrong != shell

    assert missing("build.sh") == []
    assert missing("build.sh", wrong) == ["macOS bundle id"]


def test_a_wrong_mcp_server_name_in_a_smoke_test_is_reported():
    script = _read("tools/smoke_test_mcp.py")
    wrong = script.replace(f'"{identity.MCP_SERVER_NAME}"', '"Some Other Name"')
    assert wrong != script

    assert missing("tools/smoke_test_mcp.py", wrong) == ["MCP server name"]


def test_a_longer_name_does_not_satisfy_a_shorter_one():
    # "--name <slug>-mcp" must not pass for "--name <slug>".
    only_mcp = f"--name {identity.MCP_COMMAND} \\\n"
    assert _name("x", f"--name {identity.SLUG}")[1].search(only_mcp) is None


@pytest.mark.parametrize(
    ("attribute", "path"),
    [
        ("SLUG", "build.sh"),
        ("SLUG", "build.ps1"),
        ("SLUG", "tools/smoke_test_gui.py"),
        ("SLUG", ".github/workflows/release.yml"),
        ("MCP_COMMAND", "build.ps1"),
        ("MCP_COMMAND", ".github/workflows/test.yml"),
        ("MACOS_BUNDLE_ID", "build.sh"),
        ("MCP_SERVER_NAME", "tools/smoke_test_mcp.py"),
        ("PACKAGE_NAME", "build.sh"),
        ("ICON_BASENAME", "tools/make_icons.py"),
        ("LOG_FILENAME", "tools/smoke_test_gui.py"),
        ("APP_NAME", "tools/smoke_test_gui.py"),
        ("REPO_URL", "tools/wdsi_submission.py"),
        ("PRODUCT_NAME", "tools/write_pyinstaller_version_info.py"),
    ],
)
def test_changing_an_identifier_is_reported_by_the_files_that_use_it(
    monkeypatch, attribute, path
):
    assert missing(path) == []

    monkeypatch.setattr(identity, attribute, "changed-value")

    assert missing(path) != []


# --- identity stays a leaf and well-formed ----------------------------------


def test_identity_imports_nothing_from_the_package():
    tree = ast.parse(IDENTITY_FILE.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "identity must not use relative imports"
            imported.append(node.module or "")
    assert all(name == "__future__" for name in imported), imported


def test_identifiers_have_the_shape_their_consumers_need():
    for filename in (
        identity.APP_NAME,
        identity.LOG_FILENAME,
        identity.LOCK_FILENAME,
        identity.LINUX_DESKTOP_FILENAME,
        identity.ICON_BASENAME,
    ):
        assert filename == Path(filename).name and filename == filename.strip(), filename
    for env_name in (identity.ENV_FORCE_WEBENGINE, identity.ENV_ALLOW_PLAINTEXT_SECRETS):
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name), env_name
    assert re.fullmatch(r"[a-z][a-z0-9+.-]*", identity.MCP_URI_SCHEME)
    assert re.fullmatch(r"[A-Za-z0-9]+(\.[A-Za-z0-9-]+)+", identity.MACOS_BUNDLE_ID)
    assert re.fullmatch(r"[A-Za-z0-9]+\.[A-Za-z0-9.]+", identity.WINDOWS_AUMID)
    assert len(identity.WINDOWS_AUMID) <= 128
    assert identity.REPO_URL.startswith("https://")
    assert identity.MCP_COMMAND.startswith(identity.SLUG)
    assert identity.LOGGER_NAME == identity.PACKAGE_NAME == aiusageclock.__name__


# --- the package spells nothing out itself ----------------------------------


def _identifier_values() -> set[str]:
    values = {
        value
        for name, value in vars(identity).items()
        if name.isupper() and isinstance(value, str)
    }
    # Short generic words are not identifiers worth guarding by exact match.
    return {value for value in values if len(value) >= 8}


def hardcoded_identifiers(source: str, forbidden: set[str]) -> list[tuple[int, str]]:
    """Line and value of every string literal that equals a forbidden identifier."""
    return [
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in forbidden
    ]


def test_package_modules_use_identity_instead_of_spelling_identifiers():
    forbidden = _identifier_values()
    offenders = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path == IDENTITY_FILE:
            continue
        found = hardcoded_identifiers(path.read_text(encoding="utf-8"), forbidden)
        if found:
            offenders[path.relative_to(SRC_ROOT).as_posix()] = found
    assert offenders == {}


def test_hardcoded_identifier_scan_catches_a_literal():
    forbidden = _identifier_values()
    source = (
        "KEYRING = " + repr(identity.KEYRING_SERVICE) + "\n"
        "TITLE = f'{PREFIX} ok'\n"
        "SENTENCE = 'Sign in to ' 'somewhere else'\n"
    )

    assert hardcoded_identifiers(source, forbidden) == [(1, identity.KEYRING_SERVICE)]
