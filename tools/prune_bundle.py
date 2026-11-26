#!/usr/bin/env python
"""Strip files PyInstaller collects but AI Usage Clock never uses.

`--collect-all PyQt6.QtWebEngineCore` rakes in everything shipped alongside
Qt's Chromium build: debug variants of every resource pack, the DevTools
front-end, Qt's UI translations for every language, and Chromium's locale
packs. Issue #7 asked, reasonably, why a small gauge is a 200 MB download.

Three tiers, because they are not equally free:

* **unreachable** (~89 MB) — debug resource packs and the DevTools front-end.
  The release variants sit right next to the debug ones and are the files
  actually loaded, and the app never opens an inspector. Nothing can observe
  their absence.
* **localisation** (~54 MB) — Qt's `.qm` files and Chromium's locale packs.
  Removing these does have an effect: on a non-English system the embedded
  sign-in browser's context menus and error pages, and Qt's stock dialog
  buttons, fall back to English. AI Usage Clock's own UI is English-only, so this is
  consistent rather than broken — but it is a real change, so
  `--keep-localisation` opts out.
* **unused Qt modules** — Qt libraries, `qml/` and plugins that the Qt
  WebEngine chain never pulls in (Quick3D, QuickControls2, Multimedia, ...),
  and PyQt6 extension modules the app never imports. The list is by Qt module
  name and matched exactly; see UNUSED_QT_MODULES. `tools/check_bundle_deps.py`
  runs afterwards and fails the build if anything still needs a removed file.

Run after PyInstaller, before archiving:

    python tools/prune_bundle.py dist/ai-usage-clock
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import sys
from pathlib import Path

# en-US is always kept: Chromium needs a loadable locale pak to fall back to,
# and removing every one of them stops the embedded browser from starting.
KEEP_LOCALES = {"en-US", "en-GB"}
KEEP_TRANSLATION_SUFFIXES = ("_en",)

# Qt modules (the <Name> in Qt6<Name>.dll, libQt6<Name>.so.6, Qt<Name>.framework)
# that are provably not reachable from the PyQt6 modules the app imports, from
# QtWebEngineProcess, or from the plugins that are kept. Derived by walking the
# import tables of a Qt 6.12 Windows build (the module dependency graph is the
# same on every platform, and check_bundle_deps.py re-verifies each build).
# Entries are matched against the whole module name with fnmatch, so
# "Quick" never matches "Quick3D" and a trailing "*" is only used for families
# whose every member is unused.
UNUSED_QT_MODULES = (
    "Multimedia*",
    "PositioningQuick",
    "QmlCore",
    "Quick3D*",
    "QuickControls2*",
    "QuickDialogs2*",
    "QuickEffects",
    "QuickLayouts",
    "QuickNativeStyle",
    "QuickParticles",
    "QuickShapes",
    "QuickTemplates2",
    "QuickTest",
    "QuickTimeline*",
    "QuickVectorImage*",
    "RemoteObjects*",
    "Sensors*",
    "ShaderTools",
    "SpatialAudio",
    "StateMachine*",
    "Test",
    "TextToSpeech",
    "WebChannelQuick",
    "WebEngineQuick*",
    "WebSockets",
)

# Modules that must never be removed. Checked after the patterns above as a
# guard (and by the tests, which assert no pattern can reach one of these).
PROTECTED_QT_MODULES = frozenset(
    {
        "Core", "Gui", "Widgets", "Network", "OpenGL", "PrintSupport", "Svg",
        "DBus", "XcbQpa", "Positioning", "SerialPort", "Qml", "QmlMeta",
        "QmlModels", "QmlWorkerScript", "Quick", "QuickWidgets",
        "WebChannel", "WebEngineCore", "WebEngineWidgets",
    }
)  # fmt: skip

# PyQt6 extension modules the app imports (directly or because a sip module
# imports them: QtWebEngineCore pulls in QtPrintSupport and QtWebChannel).
# Everything else under PyQt6/ (QtQml, QtQuick, QtOpenGL, ...) is dead weight.
KEEP_PYQT_MODULES = frozenset(
    {
        "Core", "Gui", "Network", "Widgets", "PrintSupport", "WebChannel",
        "WebEngineCore", "WebEngineWidgets",
    }
)  # fmt: skip

# Plugin directories that only serve removed modules. Anything not listed
# (platforms, styles, imageformats, tls, iconengines, networkinformation,
# position, generic, printsupport, ...) is kept.
UNUSED_PLUGIN_DIRS = frozenset(
    {
        "assetimporters", "canbus", "designer", "geometryloaders", "multimedia",
        "qmllint", "qmlls", "qmltooling", "renderers", "scxmldatasources",
        "sceneparsers", "sensorgestures", "sensors", "texttospeech", "webview",
    }
)  # fmt: skip

_QT_LIB_PATTERNS = (
    re.compile(r"^Qt6(?P<m>[A-Za-z0-9]+)\.dll$", re.IGNORECASE),  # Windows
    re.compile(r"^libQt6(?P<m>[A-Za-z0-9]+)\.so(?:\.\d+)*$"),  # Linux
    re.compile(r"^Qt(?P<m>[A-Za-z0-9]+)\.framework$"),  # macOS
)
_PYQT_EXT = re.compile(r"^Qt(?P<m>[A-Za-z0-9]+)\.(?:pyd|abi3\.so|so|pyi)$")


def is_unused_qt_module(name: str) -> bool:
    """True if the Qt module called *name* (e.g. "Quick3D") may be removed."""
    if name in PROTECTED_QT_MODULES:
        return False
    return any(fnmatch.fnmatchcase(name, pat) for pat in UNUSED_QT_MODULES)


def _unused_qt_entry(path: Path) -> bool:
    """Decide whether one file or directory is part of an unused Qt module."""
    name = path.name
    parent = path.parent.name
    if parent == "Qt6" and name == "qml":
        return True
    if parent == "plugins" and path.parent.parent.name == "Qt6":
        return name in UNUSED_PLUGIN_DIRS
    if parent == "PyQt6":
        match = _PYQT_EXT.match(name)
        if match:
            return match.group("m") not in KEEP_PYQT_MODULES
    for pattern in _QT_LIB_PATTERNS:
        match = pattern.match(name)
        if match:
            return is_unused_qt_module(match.group("m"))
    return False


def _iter_qt_dirs(root: Path, name: str):
    """Yield every Qt subdirectory called *name*.

    Globbed rather than hard-coded because the layout differs per platform:
    `_internal/PyQt6/Qt6/...` on Windows and Linux,
    `Contents/Frameworks/PyQt6/Qt6/...` inside a macOS .app.
    """
    yield from (p for p in root.rglob(name) if p.is_dir())


def _delete(path: Path, report: list[tuple[Path, int]]) -> None:
    try:
        if path.is_symlink():
            path.unlink()
            report.append((path, 0))
            return
        if path.is_dir():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path)
        else:
            size = path.stat().st_size
            path.unlink()
    except OSError as exc:
        print(f"  ! could not remove {path}: {exc}", file=sys.stderr)
        return
    report.append((path, size))


def prune_unreachable(root: Path, removed: list[tuple[Path, int]]) -> None:
    """Debug resource packs and the DevTools front-end — never loaded."""
    for resources in _iter_qt_dirs(root, "resources"):
        for pattern in ("*.debug.pak", "*.debug.bin"):
            for path in resources.glob(pattern):
                _delete(path, removed)
        for path in resources.glob("qtwebengine_devtools_resources*.pak"):
            _delete(path, removed)


def prune_localisation(root: Path, removed: list[tuple[Path, int]]) -> None:
    """Non-English Qt translations and Chromium locale packs."""
    for translations in _iter_qt_dirs(root, "translations"):
        for path in translations.glob("*.qm"):
            if not path.stem.endswith(KEEP_TRANSLATION_SUFFIXES):
                _delete(path, removed)

    for locales in _iter_qt_dirs(root, "qtwebengine_locales"):
        kept = 0
        for path in sorted(locales.glob("*.pak")):
            if path.stem in KEEP_LOCALES:
                kept += 1
                continue
            _delete(path, removed)
        if not kept:
            print(
                f"  ! {locales} has no en-US.pak; the embedded browser may "
                "fail to start",
                file=sys.stderr,
            )


def _broken_symlinks(root: Path) -> set[Path]:
    broken: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if path.is_symlink() and not path.exists():
                broken.add(path)
    return broken


def prune_unused_qt(root: Path, removed: list[tuple[Path, int]]) -> None:
    """Qt modules, qml/, plugins and PyQt6 extensions nothing can load."""
    before_broken = _broken_symlinks(root)
    doomed: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):  # does not follow links
        here = Path(dirpath)
        kept_dirs = []
        for name in dirnames:
            if _unused_qt_entry(here / name):
                doomed.append(here / name)  # whole directory goes; no descent
            else:
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        doomed.extend(here / n for n in filenames if _unused_qt_entry(here / n))
    for path in doomed:
        if path.is_symlink() or path.exists():
            _delete(path, removed)
    # macOS bundles link frameworks and libraries from several places; a link
    # left pointing at something just removed would fail code signing.
    for link in sorted(_broken_symlinks(root) - before_broken):
        _delete(link, removed)


def _report(removed: list[tuple[Path, int]], label: str) -> int:
    total = sum(size for _, size in removed)
    for path, size in sorted(removed, key=lambda item: -item[1])[:6]:
        print(f"    {size / 1_048_576:8.1f} MB  {path.name}")
    if len(removed) > 6:
        print(f"    ...and {len(removed) - 6} smaller files")
    print(f"  {label}: {len(removed)} files, {total / 1_048_576:.1f} MB")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="PyInstaller output directory")
    parser.add_argument(
        "--keep-localisation",
        action="store_true",
        help="keep Qt translations and Chromium locale packs",
    )
    args = parser.parse_args()

    root: Path = args.bundle
    if not root.exists():
        print(f"Bundle not found: {root}", file=sys.stderr)
        return 1

    before = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())

    unreachable: list[tuple[Path, int]] = []
    prune_unreachable(root, unreachable)
    _report(unreachable, "unreachable")

    if not args.keep_localisation:
        localisation: list[tuple[Path, int]] = []
        prune_localisation(root, localisation)
        _report(localisation, "localisation")

    unused_qt: list[tuple[Path, int]] = []
    prune_unused_qt(root, unused_qt)
    _report(unused_qt, "unused Qt modules")

    after = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    print(
        f"Bundle {before / 1_048_576:.0f} MB -> {after / 1_048_576:.0f} MB "
        f"({(before - after) / 1_048_576:.0f} MB smaller)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
