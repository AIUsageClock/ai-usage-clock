"""Tests for the Linux-only GTK3 platform theme tier of tools/prune_bundle.py.

The bundle trees are fake: each ELF file is a minimal shared object generated
here whose only content is a dynamic section listing its NEEDED names, so the
dependency walk runs on any host (the real build only happens on Linux CI).
"""

from __future__ import annotations

import os
import pprint
import struct
import sys
from pathlib import Path

import pytest

from tools import prune_bundle as prune

PLUGINS = "_internal/PyQt6/Qt6/plugins/platformthemes"


def touch(path: Path, size: int = 8) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def make_elf(path: Path, needed=(), *, bits: int = 64, big: bool = False) -> Path:
    """Write a minimal ELF shared object whose dynamic section lists *needed*."""
    end = ">" if big else "<"
    strtab = b"\0" + b"".join(n.encode() + b"\0" for n in needed)
    offsets, pos = [], 1
    for n in needed:
        offsets.append(pos)
        pos += len(n) + 1
    is64 = bits == 64
    ehsize, phentsize = (64, 56) if is64 else (52, 32)
    dyn_fmt = end + ("qQ" if is64 else "iI")
    entries = [(1, o) for o in offsets]
    dyn_off = ehsize + 2 * phentsize
    dyn_size = (len(entries) + 2) * struct.calcsize(dyn_fmt)
    str_off = dyn_off + dyn_size
    vbase = 0x10000  # the string table's virtual address differs from its file offset
    entries += [(5, vbase + str_off), (0, 0)]
    dyn = b"".join(struct.pack(dyn_fmt, t, v) for t, v in entries)
    total = str_off + len(strtab)
    ident = b"\x7fELF" + bytes([2 if is64 else 1, 2 if big else 1, 1]) + b"\0" * 9
    if is64:
        header = ident + struct.pack(
            end + "HHIQQQIHHHHHH", 3, 62, 1, 0, ehsize, 0, 0, ehsize, phentsize, 2, 64, 0, 0
        )
        load = struct.pack(end + "IIQQQQQQ", 1, 5, 0, vbase, vbase, total, total, 0x1000)
        dynamic = struct.pack(
            end + "IIQQQQQQ", 2, 6, dyn_off, vbase + dyn_off, vbase + dyn_off, dyn_size, dyn_size, 8
        )
    else:
        header = ident + struct.pack(
            end + "HHIIIIIHHHHHH", 3, 3, 1, 0, ehsize, 0, 0, ehsize, phentsize, 2, 40, 0, 0
        )
        load = struct.pack(end + "IIIIIIII", 1, 0, vbase, vbase, total, total, 5, 0x1000)
        dynamic = struct.pack(
            end + "IIIIIIII", 2, dyn_off, vbase + dyn_off, vbase + dyn_off, dyn_size, dyn_size, 6, 4
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + load + dynamic + dyn + strtab)
    return path


@pytest.mark.parametrize("bits,big", [(64, False), (32, False), (64, True)])
def test_elf_needed_reads_the_dynamic_section(tmp_path, bits, big):
    elf = make_elf(tmp_path / "libx.so", ["libgtk-3.so.0", "libc.so.6"], bits=bits, big=big)
    assert prune.elf_needed(elf) == ["libgtk-3.so.0", "libc.so.6"]


def test_elf_needed_handles_no_needed_entries_and_non_elf(tmp_path):
    assert prune.elf_needed(make_elf(tmp_path / "libx.so", [])) == []
    assert prune.elf_needed(touch(tmp_path / "data.pak")) is None


def test_elf_needed_rejects_a_damaged_elf(tmp_path):
    bad = tmp_path / "libbad.so"
    bad.write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 20)  # header cut short
    with pytest.raises(prune.ElfError):
        prune.elf_needed(bad)


def gtk_bundle(tmp_path: Path) -> Path:
    """A Linux bundle where libqgtk3.so pulls in a chain of system libraries."""
    root = tmp_path / "ai-usage-clock"
    lib = root / "_internal"
    qt = lib / "PyQt6" / "Qt6"
    make_elf(root / "ai-usage-clock", ["libpython3.so", "libc.so.6"])
    make_elf(lib / "PyQt6" / "QtWidgets.abi3.so", ["libQt6Widgets.so.6"])
    make_elf(qt / "lib" / "libQt6Widgets.so.6", ["libQt6Core.so.6"])
    make_elf(qt / "lib" / "libQt6Core.so.6", ["libglib-2.0.so.0", "libc.so.6"])
    make_elf(
        qt / "plugins" / "platformthemes" / "libqgtk3.so",
        ["libgtk-3.so.0", "libQt6Widgets.so.6", "libglib-2.0.so.0", "libc.so.6"],
    )
    make_elf(
        qt / "plugins" / "platformthemes" / "libqxdgdesktopportal.so",
        ["libQt6DBus.so.6", "libdbus-1.so.3"],
    )
    make_elf(qt / "lib" / "libQt6DBus.so.6", ["libdbus-1.so.3"])
    make_elf(lib / "libdbus-1.so.3", [])
    make_elf(lib / "libglib-2.0.so.0", [])  # also needed by Qt6Core
    make_elf(lib / "libgtk-3.so.0", ["libpango-1.0.so.0", "libglib-2.0.so.0"])
    make_elf(lib / "libpango-1.0.so.0", ["libcairo.so.2"])
    make_elf(lib / "libcairo.so.2", [])
    make_elf(lib / "libkrb5.so.3", [])  # nothing lists it: dlopen()ed, not in the closure
    return root


def prune_linux(root: Path) -> list[tuple[Path, int]]:
    removed: list[tuple[Path, int]] = []
    prune.prune_gtk3_theme(root, removed, "linux")
    return removed


def test_linux_rule_removes_the_plugin_and_libraries_only_it_needs(tmp_path):
    root = gtk_bundle(tmp_path)
    removed = prune_linux(root)
    assert sorted(p.name for p, _ in removed) == [
        "libcairo.so.2",
        "libgtk-3.so.0",
        "libpango-1.0.so.0",
        "libqgtk3.so",
    ]
    assert all(size > 0 for _, size in removed)
    lib = root / "_internal"
    # Still needed by something that stays: Qt itself, the portal plugin.
    for kept in ("libglib-2.0.so.0", "libdbus-1.so.3", "PyQt6/Qt6/lib/libQt6Widgets.so.6"):
        assert (lib / kept).exists(), kept
    assert (root / PLUGINS / "libqxdgdesktopportal.so").exists()
    # Outside the closure, so never a candidate.
    assert (lib / "libkrb5.so.3").exists()


def test_the_portal_plugin_needs_only_dbus(tmp_path):
    root = gtk_bundle(tmp_path)
    needed = prune.elf_needed(root / PLUGINS / "libqxdgdesktopportal.so")
    assert needed == ["libQt6DBus.so.6", "libdbus-1.so.3"]


def test_a_library_needed_by_a_python_extension_survives(tmp_path):
    root = gtk_bundle(tmp_path)
    make_elf(root / "_internal" / "lib-dynload" / "_ext.so", ["libcairo.so.2"])
    prune_linux(root)
    assert (root / "_internal" / "libcairo.so.2").exists()
    assert not (root / "_internal" / "libpango-1.0.so.0").exists()
    assert not (root / "_internal" / "libgtk-3.so.0").exists()


def test_a_dependency_of_a_surviving_library_survives_too(tmp_path):
    root = gtk_bundle(tmp_path)
    make_elf(root / "_internal" / "libkeep.so", ["libpango-1.0.so.0"])
    prune_linux(root)
    assert (root / "_internal" / "libpango-1.0.so.0").exists()
    assert (root / "_internal" / "libcairo.so.2").exists()  # pango needs it
    assert not (root / "_internal" / "libgtk-3.so.0").exists()


def test_a_symlinked_library_is_followed_and_the_dangling_link_removed(tmp_path):
    root = gtk_bundle(tmp_path)
    lib = root / "_internal"
    real = lib / "libcairo.so.2.11800.0"
    (lib / "libcairo.so.2").rename(real)
    try:
        (lib / "libcairo.so.2").symlink_to(real.name)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    prune_linux(root)
    assert not real.exists()
    assert not os.path.lexists(lib / "libcairo.so.2")


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_windows_and_macos_rules_remove_nothing(tmp_path, platform):
    root = gtk_bundle(tmp_path)
    before = sorted(root.rglob("*"))
    removed: list[tuple[Path, int]] = []
    prune.prune_gtk3_theme(root, removed, platform)
    assert removed == []
    assert sorted(root.rglob("*")) == before


def test_no_gtk3_plugin_means_nothing_is_removed(tmp_path):
    root = gtk_bundle(tmp_path)
    (root / PLUGINS / "libqgtk3.so").unlink()
    assert prune_linux(root) == []


def test_a_damaged_elf_stops_the_prune_without_deleting(tmp_path):
    root = gtk_bundle(tmp_path)
    (root / "_internal" / "libbad.so").write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 20)
    with pytest.raises(prune.ElfError):
        prune_linux(root)
    assert (root / PLUGINS / "libqgtk3.so").exists()
    assert (root / "_internal" / "libgtk-3.so.0").exists()


def test_sync_analysis_toc_drops_only_removed_entries(tmp_path):
    root = tmp_path / "b"
    gone = touch(root / "_internal" / "libgtk-3.so.0")
    toc = tmp_path / "Analysis-00.toc"
    first = ("libgtk-3.so.0", "/usr/lib/x86_64-linux-gnu/libgtk-3.so.0", "BINARY")
    second = ("libglib-2.0.so.0", "/usr/lib/x86_64-linux-gnu/libglib-2.0.so.0", "BINARY")
    toc.write_text(pprint.pformat(([first], [second], "other", 3)), encoding="utf-8")
    assert prune.sync_analysis_toc(toc, [gone], root) == 1
    text = toc.read_text(encoding="utf-8")
    assert "libgtk-3" not in text and "libglib-2.0.so.0" in text
    assert prune.sync_analysis_toc(toc, [gone], root) == 0


def test_main_prunes_on_linux_only_and_syncs_the_toc(tmp_path, capsys):
    def run(platform: str, base: Path) -> Path:
        base.mkdir()
        root = gtk_bundle(base)
        toc = base / "Analysis-00.toc"
        toc.write_text(
            pprint.pformat([("libgtk-3.so.0", "/usr/lib/libgtk-3.so.0", "BINARY")]),
            encoding="utf-8",
        )
        argv = sys.argv
        sys.argv = ["prune_bundle.py", str(root), "--platform", platform, "--analysis", str(toc)]
        try:
            assert prune.main() == 0
        finally:
            sys.argv = argv
        return root

    linux = run("linux", tmp_path / "l")
    out = capsys.readouterr().out
    assert "libqgtk3.so" in out and "GTK3 platform theme and its libraries: 4 files" in out
    assert not (linux / "_internal" / "libgtk-3.so.0").exists()
    assert "libgtk-3" not in (tmp_path / "l" / "Analysis-00.toc").read_text(encoding="utf-8")

    mac = run("darwin", tmp_path / "m")
    assert (mac / "_internal" / "libgtk-3.so.0").exists()
    assert "libgtk-3" in (tmp_path / "m" / "Analysis-00.toc").read_text(encoding="utf-8")
