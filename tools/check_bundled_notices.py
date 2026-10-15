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

What this guarantees: every Python package packed from site-packages is listed.
A packed file is attributed to the installed distribution that lists it in its
RECORD. A file inside site-packages that no distribution lists falls back to
the distributions that provide its top-level module name; one that nothing
claims at all is an error too, because the notices cannot account for it.
Files outside site-packages (the standard library, this project's own source)
are not third-party packages and are skipped.

What it does not guarantee: the licenses of the system libraries that a Linux
build copies from the build machine (NSS, GLib, ALSA and so on). Those are
written by the dpkg section of write_third_party_notices.py, which looks up the
owning Debian package of each file; this tool cannot tell whether that lookup
found the right text. It lists such files as ``info:`` and, on Linux, checks
that the section names exactly the libraries that were packed, so a notices
file from another build, or one written without the analyses, is caught. Away
from Linux the list is information only.

An analysis in which not a single file matches an installed package is refused
rather than passed: it means the paths do not line up with this environment.

Exit status: 0 when every packed package is listed, 1 when one is missing or
cannot be attributed (or, on Linux, the system library section does not match
what was packed), 2 when an input cannot be read or matches nothing.
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
import sysconfig
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

from packaging.utils import canonicalize_name

if __package__:
    from . import pyinstaller_analysis as analysis
    from . import write_third_party_notices as notices
else:  # run as a script: tools/ is sys.path[0]
    import pyinstaller_analysis as analysis
    import write_third_party_notices as notices

# The reading of Analysis-00.toc lives in pyinstaller_analysis; these names stay
# available here because this tool is where they were first defined.
InputError = analysis.InputError
TocEntry = analysis.TocEntry
iter_toc_entries = analysis.iter_toc_entries
read_analysis_toc = analysis.read_analysis_toc
_normal = analysis.normal_path
_spellings = analysis.path_spellings

_SITE_DIR_NAMES = ("site-packages", "dist-packages")
_METADATA_DIR_SUFFIXES = (".dist-info", ".egg-info")
_EXAMPLES = 3


def _distribution_name(dist: metadata.Distribution) -> str | None:
    """The distribution's Name, or None when its metadata is missing or empty.

    Python 3.12 reports such a folder as having no Name. On 3.11 a dependency
    installs the importlib_metadata backport, whose finder also feeds
    importlib.metadata.distributions() and raises MetadataNotFound (a
    FileNotFoundError) for it instead.
    """
    try:
        return dist.metadata.get("Name") or None
    except FileNotFoundError:
        return None


def _top_level_names(dist: metadata.Distribution) -> set[str]:
    """Importable top-level names, found the way packages_distributions() finds them."""
    declared = dist.read_text("top_level.txt")
    if declared:
        return set(declared.split())
    names: set[str] = set()
    for entry in dist.files or ():
        parts = entry.parts
        name = parts[0] if len(parts) > 1 else inspect.getmodulename(entry)
        if name and "." not in name:
            names.add(name)
    return names


def _packages_distributions() -> dict[str, list[str]]:
    """importlib.metadata.packages_distributions(), minus distributions without a Name.

    The standard version reads every distribution's Name and so fails on 3.11
    for the same unreadable metadata that _distribution_name() tolerates.
    """
    mapping: dict[str, list[str]] = {}
    for dist in metadata.distributions():
        name = _distribution_name(dist)
        if not name:
            continue
        for top in _top_level_names(dist):
            mapping.setdefault(top, []).append(name)
    return mapping


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
        raw_name = _distribution_name(dist)
        if not raw_name:
            continue
        name = str(canonicalize_name(raw_name))
        for entry in dist.files or ():
            owners.setdefault(_normal(dist.locate_file(entry)), name)
    return owners


def top_level_module_owners(
    mapping: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, list[str]]:
    """Case-folded top-level name -> canonical names of the distributions providing it.

    A distribution whose metadata has no Name is left out, as it is from
    installed_file_owners(): it cannot be listed in the notices under any name.
    """
    if mapping is None:
        mapping = _packages_distributions()
    owners: dict[str, list[str]] = {}
    for top, names in mapping.items():
        named = sorted({str(canonicalize_name(name)) for name in names if name})
        if named:
            owners[top.casefold()] = named
    return owners


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


@dataclass
class SystemLibraryReport:
    """What the executables pack from the build machine, and what the notices say about it."""

    # label of an analysis -> sorted names of the shared libraries it packs from
    # outside the Python environment and this repository
    packed: dict[str, list[str]] = field(default_factory=dict)
    # names the notices' system library section lists; None without that section
    listed: list[str] | None = None
    # whether the notices are held to what was packed (only on Linux, where the
    # generator writes the section); elsewhere the list is information only
    enforced: bool = False
    unlisted: list[str] = field(default_factory=list)  # packed, not in the notices
    not_packed: list[str] = field(default_factory=list)  # in the notices, not packed

    @property
    def mismatch(self) -> bool:
        return self.enforced and bool(self.unlisted or self.not_packed)


def check_system_libraries(
    notices_text: str,
    analyses: Mapping[str, Sequence[TocEntry]],
    *,
    roots: Sequence[str] | None = None,
    enforce: bool | None = None,
) -> SystemLibraryReport:
    """Compare the shared libraries packed from the build machine with the notices.

    The library set comes from notices.bundled_system_libraries(), the same
    function the generator uses, so the two sides can differ only when the
    notices file was not written from these analyses: hand-edited, left over
    from another build, or written without the analyses. *enforce* defaults to
    "this is Linux". Raises ValueError when the notices' section is malformed.
    """
    if enforce is None:
        enforce = notices.is_linux()
    report = SystemLibraryReport(enforced=enforce)
    for label, entries in analyses.items():
        names = sorted(notices.bundled_system_libraries(entries, roots))
        if names:
            report.packed[label] = names
    report.listed = notices.listed_system_library_names(notices_text)
    if enforce:
        packed = {name for names in report.packed.values() for name in names}
        listed = set(report.listed or ())
        report.unlisted = sorted(packed - listed)
        report.not_packed = sorted(listed - packed)
    return report


def _wrapped(names: Sequence[str]) -> str:
    return textwrap.fill(
        ", ".join(names),
        width=100,
        initial_indent="    ",
        subsequent_indent="    ",
        break_long_words=False,
        break_on_hyphens=False,
    )


def _format_system_libraries_info(report: SystemLibraryReport) -> str:
    lines = [
        "info: shared libraries packed from outside the Python environment (this check "
        "does not look at their licenses; a Linux build lists them, with their Debian "
        f"packages, in the '{notices.SYSTEM_LIBRARIES_TITLE}' section of the notices):"
    ]
    for label, names in report.packed.items():
        lines.append(f"  {label} ({len(names)})")
        lines.append(_wrapped(names))
    return "\n".join(lines)


def _system_library_errors(report: SystemLibraryReport, notices_path: Path) -> list[str]:
    section = f"the '{notices.SYSTEM_LIBRARIES_TITLE}' section of {notices_path}"
    errors = []
    if report.unlisted:
        if report.listed is None:
            heading = (
                f"error: {notices_path} has no '{notices.SYSTEM_LIBRARIES_TITLE}' section, "
                "but these shared libraries were packed from the build machine:"
            )
        else:
            heading = f"error: packed into an executable but not listed in {section}:"
        errors.append(f"{heading}\n{_wrapped(report.unlisted)}")
    if report.not_packed:
        errors.append(
            f"error: listed in {section} but not packed into any executable:\n"
            f"{_wrapped(report.not_packed)}"
        )
    if errors:
        errors.append(
            "The notices file does not match this build. Write it again with "
            "tools/write_third_party_notices.py, giving it the same Analysis-00.toc files."
        )
    return errors


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
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read {args.notices}: {exc}", file=sys.stderr)
        return 2
    try:
        analyses = {str(path): read_analysis_toc(path) for path in args.analysis}
        unlisted, unattributed = check_bundles(notices_text, analyses)
        libraries = check_system_libraries(notices_text, analyses)
    except (InputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    status = 0
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
            "build.sh. If it has to ship, list it: declare it in the dependencies of "
            "pyproject.toml (the runtime dependencies are followed from there, and the 'mcp' "
            "extra covers the helper), or, for a build tool embedded in the executables, add "
            "it to EMBEDDED_BUILD_TOOLS in tools/write_third_party_notices.py.",
            file=sys.stderr,
        )
        status = 1

    if libraries.packed:
        print(_format_system_libraries_info(libraries))
    if libraries.mismatch:
        for message in _system_library_errors(libraries, args.notices):
            print(message, file=sys.stderr)
        status = 1

    if status:
        return status
    print(
        f"{args.notices} accounts for every package packed into "
        f"{len(analyses)} executable(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
