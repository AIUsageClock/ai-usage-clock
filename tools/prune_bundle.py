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

A fourth step runs on Linux only: Qt's GTK3 platform theme plugin
(`libqgtk3.so`) is removed together with the system libraries that only it
needs (see prune_gtk3_theme). With `--analysis` the removed files are also
dropped from PyInstaller's Analysis-00.toc, which the notices generator reads.

Run after PyInstaller, before archiving:

    python tools/prune_bundle.py dist/ai-usage-clock
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import os
import pprint
import re
import shutil
import struct
import sys
from collections.abc import Iterable
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


# --------------------------------------------------------------------------
# Linux: Qt's GTK3 platform theme and the libraries only it pulls in
# --------------------------------------------------------------------------

# The plugin links GTK3, pango, cairo, gdk-pixbuf, atk, cups, krb5, gnutls and
# more, none of which the app uses. Without it Qt falls back to its own
# widget style (the xdg-desktop-portal theme plugin, which needs only DBus,
# stays). Only libraries that are in the plugin's NEEDED closure are removal
# candidates, and a candidate stays if any remaining ELF still needs it.
GTK3_THEME_PLUGIN = "libqgtk3.so"

_PT_LOAD = 1
_PT_DYNAMIC = 2
_DT_NEEDED = 1
_DT_STRTAB = 5


class ElfError(RuntimeError):
    """An ELF file could not be read well enough to know what it needs."""


def elf_needed(path: Path) -> list[str] | None:
    """DT_NEEDED names of an ELF file; None if *path* is not an ELF file.

    Reads the dynamic segment directly so it works on any host, without
    readelf. Raises ElfError for an ELF file that is damaged or unsupported,
    because guessing its dependencies could delete a library that is in use.
    """
    try:
        with path.open("rb") as handle:
            ident = handle.read(16)
            if ident[:4] != b"\x7fELF":
                return None
            if len(ident) < 16 or ident[4] not in (1, 2) or ident[5] not in (1, 2):
                raise ElfError(f"{path}: unsupported ELF header")
            is64 = ident[4] == 2
            end = "<" if ident[5] == 1 else ">"
            if is64:
                handle.seek(0x20)
                (phoff,) = struct.unpack(end + "Q", handle.read(8))
                handle.seek(0x36)
                phentsize, phnum = struct.unpack(end + "HH", handle.read(4))
                phdr_fmt = end + "IIQQQQQQ"  # type flags off vaddr paddr filesz memsz align
            else:
                handle.seek(0x1C)
                (phoff,) = struct.unpack(end + "I", handle.read(4))
                handle.seek(0x2A)
                phentsize, phnum = struct.unpack(end + "HH", handle.read(4))
                phdr_fmt = end + "IIIIIIII"  # type off vaddr paddr filesz memsz flags align
            segments = []
            for index in range(phnum):
                handle.seek(phoff + index * phentsize)
                raw = handle.read(struct.calcsize(phdr_fmt))
                if len(raw) != struct.calcsize(phdr_fmt):
                    raise ElfError(f"{path}: truncated program headers")
                fields = struct.unpack(phdr_fmt, raw)
                if is64:
                    p_type, _flags, offset, vaddr, _pa, filesz, _ms, _al = fields
                else:
                    p_type, offset, vaddr, _pa, filesz, _ms, _flags, _al = fields
                segments.append((p_type, offset, vaddr, filesz))

            dynamic = [s for s in segments if s[0] == _PT_DYNAMIC]
            if not dynamic:
                return []  # statically linked: needs nothing
            _t, dyn_off, _va, dyn_size = dynamic[0]
            handle.seek(dyn_off)
            blob = handle.read(dyn_size)
            entry_fmt = end + ("qQ" if is64 else "iI")
            entry_size = struct.calcsize(entry_fmt)
            needed_offsets: list[int] = []
            strtab_addr: int | None = None
            for pos in range(0, len(blob) - entry_size + 1, entry_size):
                tag, value = struct.unpack_from(entry_fmt, blob, pos)
                if tag == 0:
                    break
                if tag == _DT_NEEDED:
                    needed_offsets.append(value)
                elif tag == _DT_STRTAB:
                    strtab_addr = value
            if not needed_offsets:
                return []
            if strtab_addr is None:
                raise ElfError(f"{path}: NEEDED entries but no string table")
            strtab_off = None
            for p_type, offset, vaddr, filesz in segments:
                if p_type == _PT_LOAD and vaddr <= strtab_addr < vaddr + filesz:
                    strtab_off = strtab_addr - vaddr + offset
                    break
            if strtab_off is None:
                raise ElfError(f"{path}: string table is not in a loadable segment")
            names = []
            for rel in needed_offsets:
                handle.seek(strtab_off + rel)
                chunk = handle.read(512)
                nul = chunk.find(b"\0")
                if nul < 0:
                    raise ElfError(f"{path}: unterminated NEEDED name")
                names.append(chunk[:nul].decode("utf-8", "replace"))
            return names
    except (OSError, struct.error) as exc:
        raise ElfError(f"{path}: cannot read ELF dynamic section ({exc})") from exc


def _resolve_in_bundle(root: Path, path: Path) -> Path | None:
    """The regular file a bundle path ends at, or None if it leaves the bundle."""
    try:
        target = path.resolve(strict=True)
        target.relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return None
    return target if target.is_file() else None


def find_orphans_of_gtk3_theme(root: Path) -> list[Path]:
    """Files to delete when the GTK3 theme plugin goes: the plugin itself and
    each library in its NEEDED closure that no remaining ELF still needs.

    Libraries that are only dlopen()ed never show up in NEEDED; those are not
    in the closure and are therefore never candidates.
    """
    by_name: dict[str, list[Path]] = {}
    elves: dict[Path, list[str]] = {}
    plugins: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):  # does not follow links
        for name in filenames:
            path = Path(dirpath) / name
            real = _resolve_in_bundle(root, path)
            if real is None:
                continue
            by_name.setdefault(name, []).append(real)
            if path.is_symlink() or real in elves:
                continue
            needed = elf_needed(path)
            if needed is not None:
                elves[real] = needed
            if name == GTK3_THEME_PLUGIN and needed is not None:
                plugins.append(real)
    if not plugins:
        return []

    def closure(start: Iterable[Path]) -> set[Path]:
        seen: set[Path] = set()
        stack = list(start)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for dep in elves.get(node, ()):
                stack.extend(by_name.get(dep, ()))
        return seen

    candidates = closure(plugins)
    live = closure(node for node in elves if node not in candidates)
    return sorted(candidates - live)


def prune_gtk3_theme(
    root: Path,
    removed: list[tuple[Path, int]],
    platform: str = sys.platform,
) -> None:
    """Linux only: drop libqgtk3.so and the libraries nothing else needs."""
    if not platform.startswith("linux"):
        return
    before_broken = _broken_symlinks(root)
    for path in find_orphans_of_gtk3_theme(root):
        _delete(path, removed)
    for link in sorted(_broken_symlinks(root) - before_broken):
        _delete(link, removed)


def sync_analysis_toc(toc: Path, removed: Iterable[Path], root: Path) -> int:
    """Drop the entries of deleted files from a PyInstaller Analysis-00.toc.

    The notices generator reads that file to learn which system libraries were
    packed; without this it would still list the ones pruned above. Returns
    the number of entries dropped. Destination names in the toc are relative
    to the bundle's library directory (`_internal` in a PyInstaller 6 onedir).
    """
    lib_dir = root / "_internal"
    if not lib_dir.is_dir():
        lib_dir = root
    gone: set[str] = set()
    for path in removed:
        try:
            gone.add(path.relative_to(lib_dir).as_posix())
        except ValueError:
            continue
    dropped = 0

    def is_entry(node: object) -> bool:
        return (
            isinstance(node, tuple)
            and len(node) == 3
            and all(isinstance(v, str) for v in node)
            and re.match(r"^[A-Z][A-Z0-9]*(-[0-9]+)?$", node[2]) is not None
        )

    def walk(node):
        nonlocal dropped
        if is_entry(node):
            return node
        if isinstance(node, (list, tuple)):
            kept = []
            for child in node:
                if is_entry(child) and child[0].replace("\\", "/") in gone:
                    dropped += 1
                    continue
                kept.append(walk(child))
            return type(node)(kept) if isinstance(node, list) else tuple(kept)
        return node

    data = ast.literal_eval(toc.read_text(encoding="utf-8"))
    data = walk(data)
    if dropped:
        toc.write_text(pprint.pformat(data, width=160) + "\n", encoding="utf-8")
    return dropped


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
    parser.add_argument(
        "--platform",
        default=sys.platform,
        help="override the platform detected from sys.platform (win32, darwin, linux)",
    )
    parser.add_argument(
        "--analysis",
        type=Path,
        nargs="*",
        default=[],
        help="PyInstaller Analysis-00.toc files to update after Linux pruning",
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

    if args.platform.startswith("linux"):
        gtk3: list[tuple[Path, int]] = []
        try:
            prune_gtk3_theme(root, gtk3, args.platform)
        except ElfError as exc:
            print(f"prune_bundle: {exc}", file=sys.stderr)
            return 1
        for path, size in sorted(gtk3, key=lambda item: str(item[0])):
            print(f"    {size:>12,} B  {path.relative_to(root).as_posix()}")
        _report(gtk3, "GTK3 platform theme and its libraries")
        for toc in args.analysis:
            dropped = sync_analysis_toc(toc, [p for p, _ in gtk3], root)
            print(f"  {toc}: dropped {dropped} entries of removed files")

    after = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    print(
        f"Bundle {before / 1_048_576:.0f} MB -> {after / 1_048_576:.0f} MB "
        f"({(before - after) / 1_048_576:.0f} MB smaller)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
