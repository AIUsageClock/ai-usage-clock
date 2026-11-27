#!/usr/bin/env python
"""Fail the build when a lazily imported module did not make it into an executable.

``lazy_module("requests")`` (src/aiusageclock/_lazy.py) imports a module by name
at run time, which PyInstaller's static analysis cannot see. The modules are
listed in tools/lazy_modules.txt, which the build scripts turn into
``--hidden-import`` flags. This tool is the other half: it reads the PYZ
archive table PyInstaller wrote (``build/<name>/PYZ-00.toc``) and fails when a
listed module is not in it, so a packaged build that would die with
ModuleNotFoundError on a user's machine fails here instead.

    python tools/check_lazy_modules.py --list-hidden gui
    python tools/check_lazy_modules.py gui build/ai-usage-clock/PYZ-00.toc

Exit status: 0 everything present, 1 something missing, 2 an input is unusable.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

MANIFEST = Path(__file__).resolve().with_name("lazy_modules.txt")
KINDS = ("hidden", "require")
TARGETS = ("gui", "mcp")
PLATFORMS = ("win32", "darwin", "linux")


class InputError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    kind: str
    target: str
    platform: str | None
    module: str


def parse_manifest(path: Path = MANIFEST) -> list[Entry]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    entries = []
    for number, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3 or parts[0] not in KINDS:
            raise InputError(f"{path}:{number}: expected '<hidden|require> <target>[@platform] <module>'")
        target, _, platform = parts[1].partition("@")
        if target not in TARGETS or (platform and platform not in PLATFORMS):
            raise InputError(f"{path}:{number}: unknown target or platform {parts[1]!r}")
        entries.append(Entry(parts[0], target, platform or None, parts[2]))
    if not entries:
        raise InputError(f"{path} lists no modules")
    return entries


def applies(entry: Entry, target: str, platform: str) -> bool:
    return entry.target == target and (entry.platform is None or platform.startswith(entry.platform))


def hidden_imports(target: str, entries: list[Entry] | None = None) -> list[str]:
    entries = parse_manifest() if entries is None else entries
    return [e.module for e in entries if e.kind == "hidden" and e.target == target]


def packed_modules(toc_path: Path) -> set[str]:
    try:
        data = ast.literal_eval(toc_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, SyntaxError, MemoryError, RecursionError) as exc:
        raise InputError(f"cannot read the PYZ table {toc_path}: {exc}") from exc
    names: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, tuple) and len(node) == 3 and all(isinstance(v, str) for v in node):
            if node[2].startswith("PYMODULE"):
                names.add(node[0])
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(data)
    if not names:
        raise InputError(f"{toc_path} lists no modules; is it a PYZ-00.toc?")
    return names


def missing_modules(target: str, toc_path: Path, platform: str = sys.platform,
                    entries: list[Entry] | None = None) -> list[str]:
    entries = parse_manifest() if entries is None else entries
    packed = packed_modules(toc_path)
    return [e.module for e in entries if applies(e, target, platform) and e.module not in packed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list-hidden", metavar="TARGET", choices=TARGETS,
                        help="print the --hidden-import module names of a target, one per line")
    parser.add_argument("target", nargs="?", choices=TARGETS)
    parser.add_argument("pyz_toc", nargs="?", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.list_hidden:
            for module in hidden_imports(args.list_hidden):
                print(module)
            return 0
        if not args.target or not args.pyz_toc:
            parser.error("give a target and a PYZ-00.toc, or --list-hidden TARGET")
        missing = missing_modules(args.target, args.pyz_toc)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if missing:
        print(f"error: {args.pyz_toc} lacks lazily imported modules the {args.target} build needs:",
              file=sys.stderr)
        for module in missing:
            print(f"  {module}", file=sys.stderr)
        print("Add the missing ones to the build via tools/lazy_modules.txt.", file=sys.stderr)
        return 1
    print(f"ok: all lazily imported modules for {args.target} are in {args.pyz_toc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
