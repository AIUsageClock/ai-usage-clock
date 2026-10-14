#!/usr/bin/env python
"""Fail when an executable ships a package that THIRD_PARTY_NOTICES.txt leaves out.

write_third_party_notices.py lists packages from installed metadata. PyInstaller
packs whatever the executable can reach by import, and an optional import can
reach well beyond that list: anyio tries ``_pytest``, uvicorn and
pydantic-settings try ``yaml``, cffi tries ``setuptools``. This tool reads the
analysis PyInstaller wrote for each executable (``build/<name>/Analysis-00.toc``)
and checks every packed file that came from an installed package against the
notices file that ships next to the executables.

Run it with the build virtualenv's interpreter, after PyInstaller and the
notices generator:

    .venv/bin/python tools/check_bundled_notices.py \\
        dist/ai-usage-clock/THIRD_PARTY_NOTICES.txt \\
        build/ai-usage-clock/Analysis-00.toc build/ai-usage-clock-mcp/Analysis-00.toc

A packed file is attributed to the installed distribution that lists it in its
RECORD. A file inside site-packages that no distribution lists falls back to
the distributions that provide its top-level module name; one that nothing
claims at all is an error too, because the notices cannot account for it.
Files outside site-packages (the standard library, this project's own source,
system libraries) are not third-party packages and are skipped.

An analysis in which not a single file matches an installed package is refused
rather than passed: it means the paths do not line up with this environment.

Exit status: 0 when every packed package is listed, 1 when one is missing or
cannot be attributed, 2 when an input cannot be read or matches nothing.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import sysconfig
from collections.abc import Iterator, Mapping, Sequence
from importlib import metadata
from pathlib import Path

from packaging.utils import canonicalize_name

if __package__:
    from . import write_third_party_notices as notices
else:  # run as a script: tools/ is sys.path[0]
    import write_third_party_notices as notices

_SITE_DIR_NAMES = ("site-packages", "dist-packages")
_METADATA_DIR_SUFFIXES = (".dist-info", ".egg-info")
# PYMODULE, PYMODULE-1, PYSOURCE, EXTENSION, BINARY, DATA, SYMLINK, ...
_TYPECODE = re.compile(r"^[A-Z][A-Z0-9]*(-[0-9]+)?$")
_EXAMPLES = 3

TocEntry = tuple[str, str, str]


class InputError(Exception):
    """A file the check needs cannot be read or does not look as expected."""


def iter_toc_entries(node: object) -> Iterator[TocEntry]:
    """Every ``(name, source path, typecode)`` triple in a parsed analysis.

    Analysis-00.toc is a pprint of PyInstaller's analysis state. The fields are
    positional and have been added to over the releases, so this walks the
    whole structure for the triple shape instead of indexing into it. That also
    covers the files the build was told to collect (the ``datas`` and
    ``binaries`` inputs), not only the ones PyInstaller found.
    """
    if (
        isinstance(node, tuple)
        and len(node) == 3
        and all(isinstance(value, str) for value in node)
        and _TYPECODE.match(node[2])
    ):
        yield node
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from iter_toc_entries(child)
    elif isinstance(node, dict):
        for child in node.values():
            yield from iter_toc_entries(child)


def read_analysis_toc(path: Path) -> list[TocEntry]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read the PyInstaller analysis {path}: {exc}") from exc
    try:
        data = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError) as exc:
        raise InputError(f"{path} is not a PyInstaller Analysis-00.toc: {exc}") from exc
    entries = list(iter_toc_entries(data))
    if not entries:
        raise InputError(f"{path} lists no packed files; is it an Analysis-00.toc?")
    return entries


def _normal(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(path))


def _spellings(path: str | os.PathLike[str]) -> list[str]:
    """The path as given and with symlinks resolved, normalised; one when they agree.

    A virtualenv reached through a symlink can show up under either spelling,
    depending on whether PyInstaller or the package metadata recorded it.
    """
    plain = _normal(path)
    resolved = os.path.normcase(os.path.realpath(path))
    return [plain] if resolved == plain else [plain, resolved]


def installed_file_owners(search_path: Sequence[str] | None = None) -> dict[str, str]:
    """Absolute file path -> canonical name of the distribution whose RECORD lists it.

    When a name is installed twice the first one wins, as it does for imports.
    """
    if search_path is None:
        distributions = metadata.distributions()
    else:
        distributions = metadata.distributions(path=list(search_path))
    owners: dict[str, str] = {}
    for dist in distributions:
        raw_name = dist.metadata.get("Name")
        if not raw_name:
            continue
        name = str(canonicalize_name(raw_name))
        for entry in dist.files or ():
            owners.setdefault(_normal(dist.locate_file(entry)), name)
    return owners


def top_level_module_owners(
    mapping: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, list[str]]:
    """Case-folded top-level name -> canonical names of the distributions providing it."""
    if mapping is None:
        mapping = metadata.packages_distributions()
    return {
        top.casefold(): sorted({str(canonicalize_name(name)) for name in names})
        for top, names in mapping.items()
    }


def default_site_dirs() -> list[str]:
    candidates = [sysconfig.get_path("purelib"), sysconfig.get_path("platlib")]
    candidates.extend(entry for entry in sys.path if Path(entry).name in _SITE_DIR_NAMES)
    unique: dict[str, None] = {}
    for candidate in candidates:
        if candidate:
            for spelling in _spellings(candidate):
                unique.setdefault(spelling, None)
    return list(unique)


def _top_level_under(normal_path: str, site_dirs: Sequence[str]) -> str | None:
    """The first path component below a site directory, or None when outside all of them."""
    for site_dir in site_dirs:
        try:
            relative = os.path.relpath(normal_path, site_dir)
        except ValueError:  # another drive
            continue
        parts = Path(relative).parts
        if not parts or parts[0] == os.pardir:
            continue
        return parts[0]
    return None


def _module_name_of(component: str) -> str:
    """``six.py`` -> ``six``; ``_ssl.cp312-win_amd64.pyd`` -> ``_ssl``; a package folder as is."""
    return component.split(".", 1)[0]


class Attribution:
    """Which installed distributions the files of one executable came from."""

    def __init__(self) -> None:
        # canonical distribution name -> a few of its packed files
        self.distributions: dict[str, list[str]] = {}
        # top-level name below site-packages -> a few packed files nothing claims
        self.unattributed: dict[str, list[str]] = {}

    def _note(self, bucket: dict[str, list[str]], key: str, example: str) -> None:
        examples = bucket.setdefault(key, [])
        if example not in examples and len(examples) < _EXAMPLES:
            examples.append(example)

    def add_distribution(self, name: str, example: str) -> None:
        self._note(self.distributions, name, example)

    def add_unattributed(self, top_level: str, example: str) -> None:
        self._note(self.unattributed, top_level, example)


def attribute_entries(
    entries: Sequence[TocEntry],
    file_owners: Mapping[str, str],
    site_dirs: Sequence[str],
    module_owners: Mapping[str, Sequence[str]],
) -> Attribution:
    result = Attribution()
    for name, source, _typecode in entries:
        # Namespace packages have no source file; a SYMLINK entry's "source" is
        # the link target, not a path. Neither is a file of an installed package.
        if not source or source == "-":
            continue
        spellings = _spellings(source)
        owner = next((file_owners[s] for s in spellings if s in file_owners), None)
        if owner is not None:
            result.add_distribution(owner, name)
            continue
        component = next(
            (c for c in (_top_level_under(s, site_dirs) for s in spellings) if c is not None),
            None,
        )
        if component is None:
            continue
        if component.endswith(_METADATA_DIR_SUFFIXES):
            stem = component.rsplit(".", 1)[0]
            result.add_distribution(str(canonicalize_name(stem.partition("-")[0])), name)
            continue
        providers = module_owners.get(_module_name_of(component).casefold())
        if providers:
            for provider in providers:
                result.add_distribution(provider, name)
        else:
            result.add_unattributed(component, name)
    return result


def check_bundles(
    notices_text: str,
    analyses: Mapping[str, Sequence[TocEntry]],
    *,
    file_owners: Mapping[str, str] | None = None,
    site_dirs: Sequence[str] | None = None,
    module_owners: Mapping[str, Sequence[str]] | None = None,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, dict[str, list[str]]]]:
    """Compare executables' packed files with the components the notices list.

    *analyses* maps a label (the toc's path) to its entries. Returns
    ``(unlisted, unattributed)``, each ``{label: {name: [example file, ...]}}``
    and empty when everything is accounted for. The project itself and the
    bundled Python runtime need no entry of their own. Raises InputError for an
    analysis that matches no installed package at all.
    """
    listed = set(notices.listed_component_names(notices_text))
    listed.add(str(canonicalize_name(notices.PROJECT)))
    if file_owners is None:
        file_owners = installed_file_owners()
    if site_dirs is None:
        site_dirs = default_site_dirs()
    module_owner_map = (
        top_level_module_owners() if module_owners is None else module_owners
    )

    unlisted: dict[str, dict[str, list[str]]] = {}
    unattributed: dict[str, dict[str, list[str]]] = {}
    for label, entries in analyses.items():
        found = attribute_entries(entries, file_owners, site_dirs, module_owner_map)
        if not found.distributions and not found.unattributed:
            # Every real executable packs files of installed packages (PyInstaller's
            # own runtime hooks at the least). None matched means the paths do not
            # line up with this environment, and "nothing to report" would be a
            # false all-clear.
            raise InputError(
                f"none of the {len(entries)} files packed according to {label} belongs to "
                "an installed package; is this the build virtualenv's interpreter, and "
                "is the analysis from this build?"
            )
        missing = {
            name: examples
            for name, examples in sorted(found.distributions.items())
            if name not in listed
        }
        if missing:
            unlisted[label] = missing
        if found.unattributed:
            unattributed[label] = dict(sorted(found.unattributed.items()))
    return unlisted, unattributed


def _format_problems(heading: str, problems: Mapping[str, Mapping[str, Sequence[str]]]) -> str:
    lines = [heading]
    for label, names in problems.items():
        lines.append(f"  {label}")
        for name, examples in names.items():
            lines.append(f"    {name}  (for example {', '.join(examples)})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that every package packed into the executables is listed "
        "in THIRD_PARTY_NOTICES.txt"
    )
    parser.add_argument("notices", type=Path, help="the THIRD_PARTY_NOTICES.txt that ships")
    parser.add_argument(
        "analysis", type=Path, nargs="+", help="PyInstaller Analysis-00.toc of an executable"
    )
    args = parser.parse_args(argv)

    try:
        notices_text = args.notices.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {args.notices}: {exc}", file=sys.stderr)
        return 2
    try:
        analyses = {str(path): read_analysis_toc(path) for path in args.analysis}
        unlisted, unattributed = check_bundles(notices_text, analyses)
    except (InputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if unlisted:
        print(
            _format_problems(
                f"error: packed into an executable but not listed in {args.notices}:",
                unlisted,
            ),
            file=sys.stderr,
        )
    if unattributed:
        print(
            _format_problems(
                "error: files packed from site-packages that no installed package claims, "
                "so the notices cannot account for them:",
                unattributed,
            ),
            file=sys.stderr,
        )
    if unlisted or unattributed:
        print(
            "Keep the package out of the executable with --exclude-module in build.ps1 and "
            "build.sh, or list it (EMBEDDED_BUILD_TOOLS or the runtime dependencies in "
            "tools/write_third_party_notices.py).",
            file=sys.stderr,
        )
        return 1

    print(
        f"{args.notices} accounts for every package packed into "
        f"{len(analyses)} executable(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
