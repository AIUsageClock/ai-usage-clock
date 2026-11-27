#!/usr/bin/env python
"""Fail if any binary in a PyInstaller bundle needs a library that is not there.

`tools/prune_bundle.py` deletes Qt modules the app never loads. If one of them
was actually needed (by a Qt library, a plugin or an extension module), the
program would only fail on a user's machine, at the moment that code path
loads. This check makes the build fail instead, on every platform:

* Windows: read each PE file's import table (static and delay-load) with
  pefile. A dependency is satisfied if a DLL of that name exists anywhere in
  the bundle, or it is a system DLL: present in System32, an API-set name
  (api-ms-win-*, ext-ms-*), or one of the Microsoft C/C++ runtime DLLs.
* macOS: `otool -L` for every Mach-O file. @loader_path / @executable_path /
  @rpath references must resolve to a file that exists in the bundle; only
  /usr/lib and /System/Library count as system.
* Linux: `ldd` with the bundle directory on LD_LIBRARY_PATH (what the
  PyInstaller bootloader sets); "not found" entries fail. Without `ldd`, the
  NEEDED entries from `readelf -d` are checked against the bundle and the
  system's ldconfig cache instead.

Usage:

    python tools/check_bundle_deps.py dist/ai-usage-clock [more paths...]

Exit status: 0 nothing missing, 1 something missing, 2 the tool itself failed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

# name -> files that need it
Missing = dict[str, list[str]]


class CheckError(RuntimeError):
    """The check could not be performed (as opposed to finding a problem)."""


# --------------------------------------------------------------------------
# file discovery
# --------------------------------------------------------------------------


def iter_files(root: Path) -> Iterable[Path]:
    """Every regular file under *root*, symlinks not followed or duplicated."""
    if root.is_file():
        yield root
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if not path.is_symlink():
                yield path


def _magic(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(4)
    except OSError:
        return b""


_PE_SUFFIXES = {".dll", ".pyd", ".exe", ".ocx"}


def is_pe(path: Path) -> bool:
    return path.suffix.lower() in _PE_SUFFIXES and _magic(path)[:2] == b"MZ"


def is_elf(path: Path) -> bool:
    return _magic(path) == b"\x7fELF"


_MACHO_MAGICS = {
    bytes.fromhex(h)
    for h in ("feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca")
}


def is_macho(path: Path) -> bool:
    # 0xcafebabe is also the Java class magic, but Mach-O fat headers share
    # it; otool simply reports an error for a non-Mach-O file, which is
    # tolerated below.
    return _magic(path) in _MACHO_MAGICS


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

_WIN_RUNTIME = re.compile(
    r"^(?:vcruntime140(?:_1|_threads)?|msvcp140(?:_1|_2|_atomic_wait|_codecvt_ids)?"
    r"|concrt140|vcomp140|vccorlib140|ucrtbase)\.dll$"
)
_WIN_API_SET = re.compile(r"^(?:api-ms-win-|ext-ms-)[a-z0-9\-]+\.dll$")


def system_dll_names(system_dirs: Iterable[Path]) -> set[str]:
    """Lower-cased names of the regular files in *system_dirs*.

    Windows matches DLL names case-insensitively, so the comparison is done on
    this set instead of asking the file system, which on Linux (where the
    checker's own tests also run) would be case-sensitive.
    """
    names: set[str] = set()
    for directory in system_dirs:
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        names.update(e.lower() for e in entries if (Path(directory) / e).is_file())
    return names


def is_windows_system_dll(
    name: str,
    system_dirs: Iterable[Path],
    system_names: set[str] | None = None,
) -> bool:
    """Whether *name* may be left to the operating system.

    *system_names* is the precomputed `system_dll_names(system_dirs)`; callers
    checking many names pass it to avoid listing System32 each time.
    """
    lowered = name.lower()
    if _WIN_API_SET.match(lowered) or _WIN_RUNTIME.match(lowered):
        return True
    if system_names is None:
        system_names = system_dll_names(system_dirs)
    return lowered in system_names


def pe_imports(path: Path) -> list[str]:
    """DLL names a PE file imports, static and delay-loaded."""
    try:
        import pefile
    except ImportError as exc:  # pragma: no cover - dev dependency
        raise CheckError("pefile is required on Windows (uv sync --extra dev)") from exc
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
            ]
        )
    except pefile.PEFormatError as exc:
        raise CheckError(f"{path}: not a readable PE file ({exc})") from exc
    try:
        entries = list(getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])) + list(
            getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
        )
        return [entry.dll.decode("ascii", "replace") for entry in entries]
    finally:
        pe.close()


def default_windows_system_dirs() -> list[Path]:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return [Path(root) / "System32"]


def check_windows(
    roots: list[Path],
    *,
    imports_of: Callable[[Path], list[str]] = pe_imports,
    system_dirs: list[Path] | None = None,
) -> tuple[Missing, int]:
    if system_dirs is None:
        system_dirs = default_windows_system_dirs()
    files = [f for root in roots for f in iter_files(root) if is_pe(f)]
    present = {f.name.lower() for root in roots for f in iter_files(root)}
    system_names = system_dll_names(system_dirs)
    missing: Missing = defaultdict(list)
    for path in files:
        for dep in imports_of(path):
            if dep.lower() in present or is_windows_system_dll(dep, system_dirs, system_names):
                continue
            missing[dep].append(str(path))
    return dict(missing), len(files)


# --------------------------------------------------------------------------
# macOS
# --------------------------------------------------------------------------

_OTOOL_DEP = re.compile(r"^\s+(\S.*?) \(compatibility version")
_SYSTEM_PREFIXES = ("/usr/lib/", "/System/Library/")


def parse_otool_deps(text: str) -> list[str]:
    """Dependencies listed by `otool -L` (all architectures of a fat file)."""
    deps: list[str] = []
    for line in text.splitlines():
        match = _OTOOL_DEP.match(line)
        if match and match.group(1) not in deps:
            deps.append(match.group(1))
    return deps


def parse_otool_ids(text: str) -> set[str]:
    """Install names (LC_ID_DYLIB) printed by `otool -D`, all architectures.

    Output is a "<file>:" header (or "<file> (architecture x):") followed by
    the install name; a file with no ID, such as an MH_BUNDLE, has only the
    header.
    """
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.rstrip().endswith(":")
    }


def parse_otool_rpaths(text: str) -> list[str]:
    """LC_RPATH values from `otool -l`."""
    rpaths: list[str] = []
    in_rpath = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("cmd "):
            in_rpath = stripped == "cmd LC_RPATH"
        elif in_rpath and stripped.startswith("path "):
            value = stripped[len("path ") :].rsplit(" (offset", 1)[0]
            if value not in rpaths:
                rpaths.append(value)
    return rpaths


def _expand(template: str, loader_dir: Path, exec_dir: Path) -> Path:
    return Path(
        template.replace("@loader_path", str(loader_dir)).replace(
            "@executable_path", str(exec_dir)
        )
    )


def resolve_macho_dep(
    dep: str,
    *,
    loader: Path,
    exec_dirs: list[Path],
    rpaths: list[str],
    exists: Callable[[Path], bool] = os.path.exists,
    suffix_hit: Callable[[str], bool] = lambda _suffix: False,
) -> str:
    """Return "system", "ok", "fallback" or "missing" for one dependency.

    "fallback" means the exact @rpath search failed but a file with the same
    path tail (for example QtCore.framework/Versions/A/QtCore) exists
    elsewhere in the bundle; it is reported as a warning, not an error.
    """
    if dep.startswith(_SYSTEM_PREFIXES):
        return "system"
    loader_dir = loader.parent
    if dep.startswith(("@loader_path/", "@executable_path/")):
        return (
            "ok"
            if any(exists(_expand(dep, loader_dir, d)) for d in exec_dirs)
            else "missing"
        )
    if dep.startswith("@rpath/"):
        tail = dep[len("@rpath/") :]
        for rpath in rpaths:
            for exec_dir in exec_dirs:
                if exists(_expand(rpath, loader_dir, exec_dir) / tail):
                    return "ok"
        return "fallback" if suffix_hit(tail) else "missing"
    # An absolute path outside the system locations (Homebrew, /opt, ...) will
    # not exist on a user's machine.
    return "missing"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", env=env, check=False
        )
    except FileNotFoundError as exc:
        raise CheckError(f"{cmd[0]} not found: {exc}") from exc


def check_macos(
    roots: list[Path],
    *,
    run: Callable[[list[str]], subprocess.CompletedProcess] = _run,
    warnings: list[str] | None = None,
) -> tuple[Missing, int]:
    files = [f for root in roots for f in iter_files(root) if is_macho(f)]
    all_paths = [f for root in roots for f in iter_files(root)]
    # Where @executable_path points: Contents/MacOS of an .app, otherwise the
    # directory of the main executables.
    exec_dirs = sorted({f.parent for f in files if f.parent.name == "MacOS"}) or sorted(
        {f.parent for f in files if os.access(f, os.X_OK)}
    )
    if not exec_dirs:
        exec_dirs = list(roots)
    path_strings = [str(p) for p in all_paths]
    # Also include link names: a framework reached through a symlink is fine.
    link_strings = [
        str(Path(dp) / n)
        for root in roots
        for dp, dns, fns in os.walk(root)
        for n in dns + fns
        if (Path(dp) / n).is_symlink()
    ]

    def suffix_hit(tail: str) -> bool:
        needle = os.sep + tail.replace("/", os.sep)
        return any(p.endswith(needle) for p in path_strings + link_strings)

    # Main-executable rpaths apply to everything it loads.
    exec_rpaths: list[str] = []
    for f in files:
        if f.parent in exec_dirs:
            for rp in parse_otool_rpaths(run(["otool", "-l", str(f)]).stdout):
                if rp not in exec_rpaths:
                    exec_rpaths.append(rp)

    missing: Missing = defaultdict(list)
    for path in files:
        proc = run(["otool", "-L", str(path)])
        if proc.returncode != 0:
            continue  # not a Mach-O file after all (e.g. a Java class)
        rpaths = parse_otool_rpaths(run(["otool", "-l", str(path)]).stdout) + exec_rpaths
        # `otool -L` lists a dylib's own install name among its dependencies.
        # PyInstaller renames extension modules but leaves the ID, so the ID
        # never resolves inside the bundle; it is not something the file needs.
        id_proc = run(["otool", "-D", str(path)])
        if id_proc.returncode != 0:
            raise CheckError(f"otool -D failed on {path}: {id_proc.stderr.strip()}")
        own_ids = parse_otool_ids(id_proc.stdout)
        for dep in parse_otool_deps(proc.stdout):
            if dep in own_ids:
                continue
            verdict = resolve_macho_dep(
                dep,
                loader=path,
                exec_dirs=exec_dirs,
                rpaths=rpaths,
                suffix_hit=suffix_hit,
            )
            if verdict == "missing":
                missing[dep].append(str(path))
            elif verdict == "fallback" and warnings is not None:
                warnings.append(f"{dep} (needed by {path}) found only by path tail")
    return dict(missing), len(files)


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------

_LDD_MISSING = re.compile(r"^\s*(\S+)\s+=>\s+not found\s*$")
_READELF_NEEDED = re.compile(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]")


def parse_ldd_missing(text: str) -> list[str]:
    """Library names `ldd` could not resolve."""
    names: list[str] = []
    for line in text.splitlines():
        match = _LDD_MISSING.match(line)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def parse_readelf_needed(text: str) -> list[str]:
    """NEEDED entries from `readelf -d`."""
    return _READELF_NEEDED.findall(text)


def parse_ldconfig(text: str) -> set[str]:
    """Library names listed by `ldconfig -p`."""
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if "=>" in line and not line.endswith(":"):
            names.add(line.split()[0])
    return names


def _library_dir(root: Path) -> Path:
    inner = root / "_internal"
    return inner if inner.is_dir() else root


def check_linux(
    roots: list[Path],
    *,
    run: Callable[..., subprocess.CompletedProcess] = _run,
    have_ldd: Callable[[], bool] = lambda: _which("ldd"),
) -> tuple[Missing, int]:
    files = [f for root in roots for f in iter_files(root) if is_elf(f)]
    missing: Missing = defaultdict(list)
    if have_ldd():
        lib_path = os.pathsep.join(str(_library_dir(r)) for r in roots if r.is_dir())
        env = dict(os.environ, LD_LIBRARY_PATH=lib_path)
        for path in files:
            proc = run(["ldd", str(path)], env=env)
            if "not a dynamic executable" in (proc.stdout + proc.stderr):
                continue
            for name in parse_ldd_missing(proc.stdout):
                missing[name].append(str(path))
        return dict(missing), len(files)

    # No ldd: cross-check NEEDED against the bundle and the ldconfig cache.
    in_bundle = {f.name for root in roots for f in iter_files(root)}
    system = parse_ldconfig(run(["ldconfig", "-p"]).stdout)
    for path in files:
        proc = run(["readelf", "-d", str(path)])
        if proc.returncode != 0:
            raise CheckError(f"readelf failed on {path}: {proc.stderr.strip()}")
        for name in parse_readelf_needed(proc.stdout):
            if name not in in_bundle and name not in system:
                missing[name].append(str(path))
    return dict(missing), len(files)


def _which(tool: str) -> bool:
    import shutil

    return shutil.which(tool) is not None


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


def format_missing(missing: Missing) -> str:
    lines = []
    for name in sorted(missing, key=str.lower):
        users = sorted(set(missing[name]))
        shown = ", ".join(users[:3]) + (f" (+{len(users) - 3} more)" if len(users) > 3 else "")
        lines.append(f"  MISSING {name}\n          needed by: {shown}")
    return "\n".join(lines)


def check(roots: list[Path], platform: str) -> tuple[Missing, int, list[str]]:
    warnings: list[str] = []
    if platform == "win32":
        missing, count = check_windows(roots)
    elif platform == "darwin":
        missing, count = check_macos(roots, warnings=warnings)
    else:
        missing, count = check_linux(roots)
    return missing, count, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("bundle", type=Path, nargs="+", help="PyInstaller output (folder, .app or file)")
    parser.add_argument(
        "--platform",
        default=sys.platform,
        choices=("win32", "darwin", "linux"),
        help="override the platform detected from sys.platform",
    )
    args = parser.parse_args(argv)

    for root in args.bundle:
        if not root.exists():
            print(f"Bundle not found: {root}", file=sys.stderr)
            return 2
    platform = "linux" if args.platform.startswith("linux") else args.platform
    try:
        missing, count, warnings = check(args.bundle, platform)
    except CheckError as exc:
        print(f"check_bundle_deps: {exc}", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"  warning: {warning}", file=sys.stderr)
    if missing:
        print(f"Dependency check FAILED ({len(missing)} missing, {count} binaries checked):")
        print(format_missing(missing))
        return 1
    print(f"Dependency check passed: {count} binaries, no missing libraries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
