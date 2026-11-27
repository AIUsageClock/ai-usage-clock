"""Tests for tools/check_bundle_deps.py.

No platform tools are needed: otool, ldd and readelf output is faked, and the
PE import table is replaced by a lookup table. Files are real (so the walker
and the magic-byte detection run) but contain only their magic bytes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools import check_bundle_deps as cbd

PE = b"MZ\x90\x00"
ELF = b"\x7fELF"
MACHO = bytes.fromhex("cffaedfe")


def make(path: Path, magic: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(magic + b"\0" * 8)
    return path


def completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


# --- Windows -----------------------------------------------------------------


def windows_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "ai-usage-clock"
    make(root / "ai-usage-clock.exe", PE)
    make(root / "_internal" / "python314.dll", PE)
    make(root / "_internal" / "PyQt6" / "QtCore.pyd", PE)
    make(root / "_internal" / "PyQt6" / "Qt6" / "bin" / "Qt6Core.dll", PE)
    make(root / "_internal" / "PyQt6" / "Qt6" / "bin" / "Qt6Quick.dll", PE)
    make(root / "_internal" / "data.bin")  # not a PE
    return root


def fake_imports(table: dict[str, list[str]]):
    return lambda path: table.get(path.name, [])


def test_windows_all_present(tmp_path):
    root = windows_bundle(tmp_path)
    sysdir = tmp_path / "System32"
    make(sysdir / "KERNEL32.dll")
    table = {
        "QtCore.pyd": ["Qt6Core.dll", "python314.dll", "KERNEL32.dll"],
        "Qt6Core.dll": ["KERNEL32.dll", "VCRUNTIME140.dll", "MSVCP140.dll",
                        "api-ms-win-crt-runtime-l1-1-0.dll", "ext-ms-win-foo-l1-1-0.dll"],
        "Qt6Quick.dll": ["QT6CORE.DLL"],  # case-insensitive
    }  # fmt: skip
    missing, count = cbd.check_windows(
        [root], imports_of=fake_imports(table), system_dirs=[sysdir]
    )
    assert missing == {}
    assert count == 5


def test_windows_missing_dependency_is_reported_with_its_user(tmp_path):
    root = windows_bundle(tmp_path)
    table = {
        "Qt6Quick.dll": ["Qt6Core.dll", "Qt6QuickShapes.dll"],
        "QtCore.pyd": ["Qt6QuickShapes.dll"],
    }
    missing, _ = cbd.check_windows(
        [root], imports_of=fake_imports(table), system_dirs=[tmp_path / "System32"]
    )
    assert set(missing) == {"Qt6QuickShapes.dll"}
    assert len(missing["Qt6QuickShapes.dll"]) == 2
    assert any(p.endswith("Qt6Quick.dll") for p in missing["Qt6QuickShapes.dll"])


def test_windows_unknown_dll_is_not_waved_through(tmp_path):
    root = windows_bundle(tmp_path)
    sysdir = tmp_path / "System32"
    sysdir.mkdir()
    table = {"Qt6Core.dll": ["somevendor.dll", "KERNEL32.dll"]}
    missing, _ = cbd.check_windows(
        [root], imports_of=fake_imports(table), system_dirs=[sysdir]
    )
    # KERNEL32 is absent from this fake System32, so it is missing too.
    assert set(missing) == {"somevendor.dll", "KERNEL32.dll"}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("api-ms-win-core-file-l1-1-0.dll", True),
        ("ext-ms-win-ntuser-uicontext-ext-l1-1-0.dll", True),
        ("VCRUNTIME140_1.dll", True),
        ("MSVCP140_2.dll", True),
        ("ucrtbase.dll", True),
        ("msvcp100.dll", False),
        ("api-ms-win.dll", False),
        ("Qt6Core.dll", False),
    ],
)
def test_windows_system_dll_rules(tmp_path, name, expected):
    assert cbd.is_windows_system_dll(name, [tmp_path]) is expected


def test_windows_dll_in_system_dir_counts(tmp_path):
    make(tmp_path / "USER32.dll", PE)
    assert cbd.is_windows_system_dll("user32.DLL", [tmp_path])
    assert not cbd.is_windows_system_dll("user33.dll", [tmp_path])


def test_windows_system_dir_match_does_not_depend_on_filesystem_case(tmp_path, monkeypatch):
    """Windows matches DLL names case-insensitively; Linux file systems do not.

    Simulate a case-sensitive file system (Path.is_file looks for the exact
    spelling in the directory listing) and check the verdict is unchanged.
    """
    make(tmp_path / "USER32.dll", PE)
    make(tmp_path / "kernel32.DLL", PE)
    real_listdir = os.listdir
    real_is_file = Path.is_file

    def case_sensitive_is_file(self):
        return self.name in real_listdir(self.parent) and real_is_file(self)

    monkeypatch.setattr(Path, "is_file", case_sensitive_is_file)
    assert not (tmp_path / "user32.DLL").is_file()  # the simulation bites
    assert cbd.is_windows_system_dll("user32.DLL", [tmp_path])
    assert cbd.is_windows_system_dll("KERNEL32.dll", [tmp_path])
    assert not cbd.is_windows_system_dll("gdi32.dll", [tmp_path])


# --- macOS -------------------------------------------------------------------

OTOOL_L = """\
/x/app/Contents/Frameworks/PyQt6/QtCore.abi3.so:
\t@rpath/QtCore.framework/Versions/A/QtCore (compatibility version 6.0.0, current version 6.12.0)
\t@loader_path/libhelper.dylib (compatibility version 1.0.0, current version 1.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 1700.0.0)
\t/System/Library/Frameworks/AppKit.framework/Versions/C/AppKit (compatibility version 45.0.0, current version 2487.0.0)
"""

OTOOL_FAT = """\
/x/lib:
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)
/x/lib (architecture arm64):
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)
\t/opt/homebrew/lib/libfoo.dylib (compatibility version 1.0.0, current version 1.0.0)
"""

OTOOL_RPATHS = """\
Load command 11
          cmd LC_RPATH
      cmdsize 40
         path @loader_path/../../Qt6/lib (offset 12)
Load command 12
          cmd LC_LOAD_DYLIB
      cmdsize 56
         name /usr/lib/libSystem.B.dylib (offset 24)
Load command 13
          cmd LC_RPATH
      cmdsize 32
         path @executable_path/../Frameworks (offset 12)
"""


def test_parse_otool_deps():
    assert cbd.parse_otool_deps(OTOOL_L) == [
        "@rpath/QtCore.framework/Versions/A/QtCore",
        "@loader_path/libhelper.dylib",
        "/usr/lib/libc++.1.dylib",
        "/System/Library/Frameworks/AppKit.framework/Versions/C/AppKit",
    ]
    assert cbd.parse_otool_deps(OTOOL_FAT) == [
        "/usr/lib/libSystem.B.dylib",
        "/opt/homebrew/lib/libfoo.dylib",
    ]


def test_parse_otool_rpaths_ignores_other_load_commands():
    assert cbd.parse_otool_rpaths(OTOOL_RPATHS) == [
        "@loader_path/../../Qt6/lib",
        "@executable_path/../Frameworks",
    ]


def test_resolve_macho_dep_cases(tmp_path):
    exec_dir = tmp_path / "Contents" / "MacOS"
    frameworks = tmp_path / "Contents" / "Frameworks"
    loader = frameworks / "PyQt6" / "QtCore.abi3.so"
    make(frameworks / "PyQt6" / "Qt6" / "lib" / "QtCore.framework" / "Versions" / "A" / "QtCore")
    make(frameworks / "PyQt6" / "libhelper.dylib")
    exec_dir.mkdir(parents=True)
    common = dict(
        loader=loader,
        exec_dirs=[exec_dir],
        rpaths=["@loader_path/Qt6/lib", "@executable_path/../Frameworks"],
    )
    resolve = cbd.resolve_macho_dep
    assert resolve("/usr/lib/libc++.1.dylib", **common) == "system"
    assert resolve("/System/Library/Frameworks/AppKit.framework/AppKit", **common) == "system"
    assert resolve("@loader_path/libhelper.dylib", **common) == "ok"
    assert resolve("@loader_path/libgone.dylib", **common) == "missing"
    assert resolve("@executable_path/../Frameworks/PyQt6/libhelper.dylib", **common) == "ok"
    assert resolve("@rpath/QtCore.framework/Versions/A/QtCore", **common) == "ok"
    assert resolve("@rpath/QtQuick3D.framework/Versions/A/QtQuick3D", **common) == "missing"
    assert resolve("/opt/homebrew/lib/libfoo.dylib", **common) == "missing"
    # exact rpath fails but the same tail exists elsewhere in the bundle
    assert (
        resolve(
            "@rpath/QtCore.framework/Versions/A/QtCore",
            loader=loader,
            exec_dirs=[exec_dir],
            rpaths=[],
            suffix_hit=lambda tail: tail.endswith("QtCore"),
        )
        == "fallback"
    )


def test_check_macos_with_fake_otool(tmp_path):
    app = tmp_path / "ai-usage-clock.app"
    macos = app / "Contents" / "MacOS"
    frameworks = app / "Contents" / "Frameworks"
    exe = make(macos / "ai-usage-clock", MACHO)
    ext = make(frameworks / "PyQt6" / "QtWebEngineCore.abi3.so", MACHO)
    qtcore = make(frameworks / "PyQt6" / "Qt6" / "lib" / "QtCore.framework" / "Versions" / "A" / "QtCore", MACHO)
    make(frameworks / "readme.txt")

    deps = {
        exe: ["/usr/lib/libSystem.B.dylib"],
        qtcore: ["/usr/lib/libSystem.B.dylib"],
        ext: [
            "@rpath/QtCore.framework/Versions/A/QtCore",
            "@rpath/QtQuick3D.framework/Versions/A/QtQuick3D",
        ],
    }
    rpaths = {exe: ["@executable_path/../Frameworks/PyQt6/Qt6/lib"], ext: [], qtcore: []}

    def fake_run(cmd):
        path = Path(cmd[-1])
        if cmd[:2] == ["otool", "-D"]:
            return completed(f"{path}:\n")  # no ID (MH_BUNDLE style)
        if cmd[:2] == ["otool", "-L"]:
            body = "".join(f"\t{d} (compatibility version 1.0.0, current version 1.0.0)\n" for d in deps[path])
            return completed(f"{path}:\n{body}")
        body = "".join(f"          cmd LC_RPATH\n         path {r} (offset 12)\n" for r in rpaths[path])
        return completed(body)

    warnings: list[str] = []
    missing, count = cbd.check_macos([app], run=fake_run, warnings=warnings)
    assert count == 3
    assert set(missing) == {"@rpath/QtQuick3D.framework/Versions/A/QtQuick3D"}
    assert missing["@rpath/QtQuick3D.framework/Versions/A/QtQuick3D"] == [str(ext)]
    assert warnings == []

    deps[ext] = ["@rpath/QtCore.framework/Versions/A/QtCore"]
    missing, _ = cbd.check_macos([app], run=fake_run, warnings=warnings)
    assert missing == {}


OTOOL_D = """\
/x/app/Contents/Frameworks/pydantic_core/_pydantic_core.cpython-314-darwin.so:
@rpath/pydantic_core._pydantic_core.cpython-314-darwin.so
"""

OTOOL_D_FAT = """\
/x/lib (architecture x86_64):
@rpath/libfoo.dylib
/x/lib (architecture arm64):
@rpath/libfoo.dylib
"""


def test_parse_otool_ids():
    assert cbd.parse_otool_ids(OTOOL_D) == {
        "@rpath/pydantic_core._pydantic_core.cpython-314-darwin.so"
    }
    assert cbd.parse_otool_ids(OTOOL_D_FAT) == {"@rpath/libfoo.dylib"}
    # MH_BUNDLE: header only, no install name
    assert cbd.parse_otool_ids("/x/ext.so:\n") == set()
    assert cbd.parse_otool_ids("") == set()


def _macos_app(tmp_path):
    app = tmp_path / "ai-usage-clock.app"
    exe = make(app / "Contents" / "MacOS" / "ai-usage-clock", MACHO)
    frameworks = app / "Contents" / "Frameworks"
    # PyInstaller renamed the module (dots in the file name) but the install
    # name inside still has the original spelling.
    ext = make(frameworks / "pydantic_core" / "_pydantic_core.cpython-314-darwin.so", MACHO)
    bundle = make(frameworks / "plain" / "mh_bundle.so", MACHO)
    dylib = make(frameworks / "libcrypto.3.dylib", MACHO)
    return app, exe, ext, bundle, dylib


def _fake_otool(deps, ids):
    def fake_run(cmd):
        path = Path(cmd[-1])
        if cmd[:2] == ["otool", "-L"]:
            body = "".join(
                f"\t{d} (compatibility version 1.0.0, current version 1.0.0)\n" for d in deps[path]
            )
            return completed(f"{path}:\n{body}")
        if cmd[:2] == ["otool", "-D"]:
            return completed(f"{path}:\n" + "".join(f"{i}\n" for i in ids.get(path, [])))
        return completed("")  # otool -l: no rpaths

    return fake_run


def test_check_macos_ignores_a_binarys_own_install_name(tmp_path):
    app, exe, ext, bundle, dylib = _macos_app(tmp_path)
    own = "@rpath/pydantic_core._pydantic_core.cpython-314-darwin.so"
    deps = {
        exe: ["/usr/lib/libSystem.B.dylib"],
        # otool -L lists the ID first; a different file name than the ID.
        ext: [own, "/usr/lib/libSystem.B.dylib"],
        bundle: ["/usr/lib/libSystem.B.dylib"],  # MH_BUNDLE has no ID line
        dylib: ["@rpath/libcrypto.3.dylib", "/usr/lib/libSystem.B.dylib"],
    }
    ids = {ext: [own], dylib: ["@rpath/libcrypto.3.dylib"]}
    warnings: list[str] = []
    missing, count = cbd.check_macos([app], run=_fake_otool(deps, ids), warnings=warnings)
    assert missing == {}
    assert count == 4
    assert warnings == []  # the old path-tail warning for self IDs is gone too


def test_check_macos_real_missing_rpath_dep_still_fails_next_to_own_id(tmp_path):
    app, exe, ext, bundle, dylib = _macos_app(tmp_path)
    own = "@rpath/pydantic_core._pydantic_core.cpython-314-darwin.so"
    deps = {
        exe: ["/usr/lib/libSystem.B.dylib"],
        ext: [own, "@rpath/libgone.dylib"],
        bundle: ["@rpath/libgone.dylib"],
        dylib: ["@rpath/libcrypto.3.dylib"],
    }
    ids = {ext: [own], dylib: ["@rpath/libcrypto.3.dylib"]}
    missing, _ = cbd.check_macos([app], run=_fake_otool(deps, ids))
    assert set(missing) == {"@rpath/libgone.dylib"}
    assert sorted(missing["@rpath/libgone.dylib"]) == sorted([str(ext), str(bundle)])


def test_check_macos_one_files_id_is_not_another_files_free_pass(tmp_path):
    app, exe, ext, bundle, dylib = _macos_app(tmp_path)
    own = "@rpath/pydantic_core._pydantic_core.cpython-314-darwin.so"
    deps = {exe: [], ext: [own], bundle: [own], dylib: []}
    missing, _ = cbd.check_macos([app], run=_fake_otool(deps, {ext: [own]}))
    assert missing == {own: [str(bundle)]}


def test_check_macos_otool_d_failure_is_a_tool_error(tmp_path):
    app, exe, ext, bundle, dylib = _macos_app(tmp_path)
    inner = _fake_otool({f: [] for f in (exe, ext, bundle, dylib)}, {})

    def run(cmd):
        if cmd[:2] == ["otool", "-D"]:
            return completed("", returncode=1, stderr="boom")
        return inner(cmd)

    with pytest.raises(cbd.CheckError):
        cbd.check_macos([app], run=run)


# --- Linux -------------------------------------------------------------------

LDD_OK = """\
\tlinux-vdso.so.1 (0x00007ffd)
\tlibQt6Core.so.6 => /x/_internal/PyQt6/Qt6/lib/libQt6Core.so.6 (0x00007f)
\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f)
\t/lib64/ld-linux-x86-64.so.2 (0x00007f)
"""

LDD_BAD = """\
\tlibQt6Core.so.6 => /x/_internal/PyQt6/Qt6/lib/libQt6Core.so.6 (0x00007f)
\tlibQt6Quick3D.so.6 => not found
\tlibxcb-cursor.so.0 => not found
"""

READELF = """\
Dynamic section at offset 0x1000 contains 5 entries:
  Tag        Type                         Name/Value
 0x0000000000000001 (NEEDED)             Shared library: [libQt6Core.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libQt6Quick3D.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
 0x000000000000001d (RUNPATH)            Library runpath: [$ORIGIN]
"""

LDCONFIG = """\
2 libs found in cache `/etc/ld.so.cache'
\tlibc.so.6 (libc6,x86-64, OS ABI: Linux 3.2.0) => /lib/x86_64-linux-gnu/libc.so.6
\tlibxcb.so.1 (libc6,x86-64) => /lib/x86_64-linux-gnu/libxcb.so.1
"""


def test_parse_ldd_and_readelf_and_ldconfig():
    assert cbd.parse_ldd_missing(LDD_OK) == []
    assert cbd.parse_ldd_missing(LDD_BAD) == ["libQt6Quick3D.so.6", "libxcb-cursor.so.0"]
    assert cbd.parse_readelf_needed(READELF) == [
        "libQt6Core.so.6",
        "libQt6Quick3D.so.6",
        "libc.so.6",
    ]
    assert cbd.parse_ldconfig(LDCONFIG) == {"libc.so.6", "libxcb.so.1"}


def linux_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "ai-usage-clock"
    exe = make(root / "ai-usage-clock", ELF)
    make(root / "_internal" / "PyQt6" / "Qt6" / "lib" / "libQt6Core.so.6", ELF)
    plugin = make(root / "_internal" / "PyQt6" / "Qt6" / "plugins" / "platforms" / "libqxcb.so", ELF)
    make(root / "_internal" / "notes.txt")
    return root, exe, plugin


def test_check_linux_with_ldd(tmp_path):
    root, exe, plugin = linux_bundle(tmp_path)
    seen_env = {}

    def fake_run(cmd, env=None):
        assert cmd[0] == "ldd"
        seen_env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH"]
        return completed(LDD_BAD if cmd[1] == str(plugin) else LDD_OK)

    missing, count = cbd.check_linux([root], run=fake_run, have_ldd=lambda: True)
    assert count == 3
    assert set(missing) == {"libQt6Quick3D.so.6", "libxcb-cursor.so.0"}
    assert missing["libQt6Quick3D.so.6"] == [str(plugin)]
    assert seen_env["LD_LIBRARY_PATH"] == str(root / "_internal")


def test_check_linux_ldd_clean(tmp_path):
    root, *_ = linux_bundle(tmp_path)
    missing, _ = cbd.check_linux(
        [root], run=lambda cmd, env=None: completed(LDD_OK), have_ldd=lambda: True
    )
    assert missing == {}


def test_check_linux_skips_static_executables(tmp_path):
    root, *_ = linux_bundle(tmp_path)
    missing, _ = cbd.check_linux(
        [root],
        run=lambda cmd, env=None: completed("\tnot a dynamic executable\n", 1),
        have_ldd=lambda: True,
    )
    assert missing == {}


def test_check_linux_readelf_fallback(tmp_path):
    root, *_ = linux_bundle(tmp_path)

    def fake_run(cmd, env=None):
        if cmd[0] == "ldconfig":
            return completed(LDCONFIG)
        assert cmd[0] == "readelf"
        return completed(READELF)

    missing, _ = cbd.check_linux([root], run=fake_run, have_ldd=lambda: False)
    # libQt6Core.so.6 is in the bundle, libc.so.6 in the cache, Quick3D nowhere.
    assert set(missing) == {"libQt6Quick3D.so.6"}


# --- driver ------------------------------------------------------------------


def test_format_missing_lists_name_and_user():
    text = cbd.format_missing({"Qt6Foo.dll": ["a.dll", "b.dll", "c.dll", "d.dll"]})
    assert "MISSING Qt6Foo.dll" in text
    assert "(+1 more)" in text


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    root = tmp_path / "b"
    root.mkdir()
    monkeypatch.setattr(cbd, "check", lambda roots, platform: ({}, 4, []))
    assert cbd.main([str(root)]) == 0
    assert "passed" in capsys.readouterr().out

    monkeypatch.setattr(cbd, "check", lambda roots, platform: ({"x.dll": ["a.pyd"]}, 4, []))
    assert cbd.main([str(root)]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "x.dll" in out

    def boom(roots, platform):
        raise cbd.CheckError("otool not found")

    monkeypatch.setattr(cbd, "check", boom)
    assert cbd.main([str(root)]) == 2
    assert cbd.main([str(tmp_path / "does-not-exist")]) == 2


@pytest.mark.skipif(
    __import__("os").name != "nt", reason="reads real PE files with pefile"
)
def test_real_pe_import_table_is_parsed():
    import sys

    imports = [n.lower() for n in cbd.pe_imports(Path(sys.executable))]
    assert any(n.startswith(("kernel32", "api-ms-win")) for n in imports)
