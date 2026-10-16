#!/usr/bin/env python
"""Write THIRD_PARTY_NOTICES.txt: the licenses of everything bundled with the app.

PyInstaller copies PyQt6, Qt, QtWebEngine and every other runtime dependency
into the release archives, and each of them carries its own license terms.
This script lists those packages with their declared license and the license
text they ship, so the notice can travel with the build.

Run it with the build virtualenv's interpreter, after the project and its
dependencies are installed:

    .venv/bin/python tools/write_third_party_notices.py dist/ai-usage-clock/THIRD_PARTY_NOTICES.txt \\
        build/ai-usage-clock/Analysis-00.toc build/ai-usage-clock-mcp/Analysis-00.toc

Which packages are listed comes from the installed distribution metadata:
the project's runtime ``Requires-Dist`` entries (plus the extras it ships, see
SHIPPED_EXTRAS), followed recursively, plus the build tools whose code is
embedded in the executables (see EMBEDDED_BUILD_TOOLS). The Python runtime that
PyInstaller bundles is listed first, with the license file found in the Python
installation the virtualenv was created from. Between the introduction and the
component index the file carries the notice of the code AI Usage Clock builds
on, read from docs/legal/UPSTREAM-LICENSE.txt; the script stops before it
collects anything when that file cannot be read. The output is UTF-8 with LF
line endings and carries no timestamp, so the same environment always yields
the same bytes.

That list is derived from metadata, not from what PyInstaller really packed, so
the two can drift apart: an optional import can drag in a package that is only
installed for development (pytest through anyio, PyYAML through uvicorn,
setuptools through cffi). The build scripts exclude those modules where they
can, and tools/check_bundled_notices.py then compares PyInstaller's analysis of
each executable with the file written here and fails the build when something
ships without being listed.

Python packages are not the whole story on Linux. PyInstaller leaves out only
the C library, the graphics stack and a few others there, so shared libraries
of the build machine (NSS, GLib, ALSA, XKB and so on) are copied into the
build. When the Analysis-00.toc files are given and this runs on Linux, a
"System libraries bundled on Linux" section is added: every packed shared
library that does not come from the Python environment or this repository,
the Debian package that owns it (``dpkg -S``) and that package's
/usr/share/doc/<package>/copyright, followed by the standard license texts
from /usr/share/common-licenses that those copyright files refer to (each
once). Windows and macOS builds get no such section. What cannot be found (no
dpkg, no owning package, no copyright file, no referenced license text) is said
so in the section rather than left out.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if __package__:
    from . import pyinstaller_analysis as analysis
else:  # run as a script: tools/ is sys.path[0]
    import pyinstaller_analysis as analysis

PROJECT = "ai-usage-clock"
REPO_URL = "https://github.com/AIUsageClock/ai-usage-clock"

# Extras of the project whose dependencies end up in a release archive. The
# packaged MCP helper bundles the "mcp" extra. The "dev" extra (pytest and
# friends) is not a runtime dependency and is not listed; if PyInstaller's
# analysis finds a dev-only package in an executable anyway, the build fails in
# tools/check_bundled_notices.py rather than shipping it unannounced.
SHIPPED_EXTRAS = ("mcp",)
# Build tools whose own code is embedded in the executables: PyInstaller's
# bootloader and runtime hooks, and the runtime hooks that
# pyinstaller-hooks-contrib adds (see its license text for the terms). Only the
# tools are listed, not their dependencies.
EMBEDDED_BUILD_TOOLS = ("pyinstaller", "pyinstaller-hooks-contrib")

# Files in a dist-info folder that are license texts even when the metadata
# does not list them under License-File.
_LICENSE_FILE_NAME = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)
# A License field longer than this (or spanning lines) is the license text
# itself, not a short declaration.
_MAX_DECLARATION_LENGTH = 200
# License files of a Python installation: the file name alone, unlike the
# prefix match above, because the standard library folder is searched too.
_PYTHON_LICENSE_FILE_NAME = re.compile(
    r"^(LICEN[CS]E|COPYING|NOTICE)(\.(txt|md|rst))?$", re.IGNORECASE
)
PYTHON_NAME = "Python"

_RULE = "=" * 80
_THIN_RULE = "-" * 80

INTRO = f"""\
THIRD-PARTY NOTICES

AI Usage Clock is licensed under the MIT License; see the LICENSE file that
ships next to this file. This file lists the third-party components that are
distributed with it, with each component's declared license and the license
text it ships. The source code of AI Usage Clock is available at
{REPO_URL}
"""

# The copyright and permission notice of the code AI Usage Clock builds on.
# The MIT License requires it to be included in all copies or substantial
# portions of the software, so the repository keeps it word for word in
# docs/legal/UPSTREAM-LICENSE.txt and render() writes it into every notices
# file, between the introduction and the component index. It is read from that
# file at run time, never copied into this script.
REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LICENSE_RELATIVE_PATH = "docs/legal/UPSTREAM-LICENSE.txt"
UPSTREAM_LICENSE_PATH = REPO_ROOT / UPSTREAM_LICENSE_RELATIVE_PATH
UPSTREAM_NOTICE_TITLE = "Notice for the code AI Usage Clock builds on"
UPSTREAM_NOTICE_NOTE = (
    "AI Usage Clock builds on earlier code that is also licensed under the MIT\n"
    "License. The MIT License requires this notice to be included in all copies\n"
    "or substantial portions of the software, so it is reproduced here word for\n"
    "word."
)

# Notes for packages whose wheel bundles a large body of code that carries
# further notices of its own, which the wheel does not reproduce.
_QT_THIRD_PARTY = "https://doc.qt.io/qt-6/licenses-used-in-qt.html"
_QT_WEBENGINE_LICENSING = "https://doc.qt.io/qtwebengine/qtwebengine-licensing.html"
NOTES = {
    "pyqt6-qt6": (
        "This wheel carries the Qt libraries that PyQt6 uses. It ships only the\n"
        "LGPL v3 text below, not the notices of the third-party code inside Qt.\n"
        "That code is listed at:\n"
        f"{_QT_THIRD_PARTY}"
    ),
    "pyqt6-webengine-qt6": (
        "This wheel carries Qt WebEngine, which contains the Chromium engine and\n"
        "the third-party code Chromium builds on. It ships only the LGPL v3 text\n"
        "below, not the notices of that code. The Qt WebEngine licensing page\n"
        "describes the licenses involved and lists the third-party licenses:\n"
        f"{_QT_WEBENGINE_LICENSING}"
    ),
}

# Python's own license file covers Python itself and a few pieces of third-party
# code (for example bzip2 and Tcl/Tk on Windows), but not every library a Python
# distribution incorporates or links against.
_PYTHON_DOCS_LICENSE = "https://docs.python.org/3/license.html"
PYTHON_NOTE = (
    "The Python runtime is bundled with the application. Its license text is\n"
    "taken from the Python installation used for this build. That file does not\n"
    "reproduce the notices of all third-party code that a Python distribution\n"
    "incorporates (for example OpenSSL, expat, libffi, zlib and libmpdec).\n"
    "Python's documentation lists that code with its license terms under\n"
    '"Licenses and Acknowledgements for Incorporated Software":\n'
    f"{_PYTHON_DOCS_LICENSE}"
)
PYTHON_MISSING = (
    "No license file (LICENSE, COPYING or NOTICE) was found in the Python\n"
    "installation used for this build."
)


@dataclass
class LicenseText:
    """One license file shipped in a distribution's metadata folder."""

    name: str
    text: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass
class Package:
    name: str
    version: str
    declaration: str
    texts: list[LicenseText] = field(default_factory=list)
    # Optional extras for components that are not installed distributions.
    detail: str = ""
    note: str = ""
    missing_message: str = ""

    @property
    def canonical_name(self) -> str:
        return str(canonicalize_name(self.name))

    @property
    def title(self) -> str:
        return f"{self.name} {self.version}"


class MissingDependencies(Exception):
    """Packages the metadata requires but this environment does not have."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(", ".join(names))
        self.names = names


def _normalise_text(raw: bytes) -> str:
    text = raw.decode("utf-8-sig", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n")


class UpstreamNoticeError(Exception):
    """The archived notice of the code AI Usage Clock is based on cannot be used."""


def read_upstream_notice(path: Path | None = None) -> str:
    """The text of the archived upstream notice, normalised like every license text here.

    Fails loudly when the file is missing, unreadable, empty, or not clean
    UTF-8: a notices file without that notice, or with a garbled one, would
    leave the MIT License's condition unmet. Unlike the license texts of the
    dependencies, which are decoded leniently, nothing is replaced here.
    """
    path = UPSTREAM_LICENSE_PATH if path is None else path
    try:
        raw = path.read_bytes()
    except OSError as exc:
        message = f"cannot read the upstream license notice {path}: {exc}"
        raise UpstreamNoticeError(message) from exc
    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        message = f"the upstream license notice {path} is not valid UTF-8 ({exc.reason})"
        raise UpstreamNoticeError(message) from exc
    text = _normalise_text(raw)
    if "\0" in text:
        # UTF-16 text without a byte order mark still decodes as UTF-8, with NULs in it.
        raise UpstreamNoticeError(
            f"the upstream license notice {path} contains NUL characters (UTF-16?); "
            "save it as UTF-8"
        )
    return _require_text(text, f"the upstream license notice {path}")


def _require_text(text: str, what: str) -> str:
    """*text* itself; raises UpstreamNoticeError when it is empty or only whitespace."""
    if not text.strip():
        raise UpstreamNoticeError(f"{what} is empty")
    return text


def collect_distributions(
    project: str = PROJECT,
    extras: tuple[str, ...] = SHIPPED_EXTRAS,
    build_tools: tuple[str, ...] = EMBEDDED_BUILD_TOOLS,
) -> list[metadata.Distribution]:
    """Installed distributions that ship with the app, sorted by canonical name.

    The project itself is not included: its license is the LICENSE file.
    """
    root = str(canonicalize_name(project))
    wanted: dict[str, set[str]] = {}
    missing: set[str] = set()
    pending: list[tuple[str, set[str]]] = [(project, set(extras))]

    while pending:
        name, requested = pending.pop()
        key = str(canonicalize_name(name))
        known = wanted.get(key)
        if known is not None and requested <= known:
            continue
        wanted.setdefault(key, set()).update(requested)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.add(key)
            continue
        environments = [{"extra": extra} for extra in {""} | wanted[key]]
        for line in dist.requires or ():
            requirement = Requirement(line)
            marker = requirement.marker
            if marker is not None and not any(marker.evaluate(env) for env in environments):
                continue
            pending.append((requirement.name, set(requirement.extras)))

    if root in missing:
        raise metadata.PackageNotFoundError(project)

    # Build tools are listed on their own: their dependencies are not part of
    # the executables, so they are not followed.
    for tool in build_tools:
        key = str(canonicalize_name(tool))
        wanted.setdefault(key, set())
        try:
            metadata.distribution(tool)
        except metadata.PackageNotFoundError:
            missing.add(key)

    if missing:
        raise MissingDependencies(sorted(missing))
    return [metadata.distribution(key) for key in sorted(wanted) if key != root]


def declaration_of(dist: metadata.Distribution) -> str:
    """The license the package declares: expression, License field, or classifiers."""
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    field_value = (meta.get("License") or "").strip()
    if (
        field_value
        and field_value.upper() != "UNKNOWN"
        and "\n" not in field_value
        and len(field_value) <= _MAX_DECLARATION_LENGTH
    ):
        return field_value
    classifiers = []
    for classifier in meta.get_all("Classifier") or ():
        parts = [part.strip() for part in classifier.split("::")]
        if parts[0] == "License" and len(parts) > 1 and parts[-1] != "OSI Approved":
            classifiers.append(parts[-1])
    if classifiers:
        return "; ".join(sorted(set(classifiers)))
    if field_value and field_value.upper() != "UNKNOWN":
        return "see the license text below"
    return "not declared"


def license_texts_of(dist: metadata.Distribution) -> list[LicenseText]:
    """License files from the distribution's metadata folder, sorted by name."""
    listed = {
        value.strip().replace("\\", "/")
        for value in dist.metadata.get_all("License-File") or ()
    }
    found: dict[str, LicenseText] = {}
    for entry in dist.files or ():
        parts = entry.parts
        if len(parts) < 2 or not parts[0].endswith((".dist-info", ".egg-info")):
            continue
        relative = list(parts[1:])
        if relative[0] == "licenses" and len(relative) > 1:
            relative = relative[1:]
        name = "/".join(relative)
        if name not in listed and not _LICENSE_FILE_NAME.match(relative[-1]):
            continue
        try:
            raw = Path(str(dist.locate_file(entry))).read_bytes()
        except OSError:
            continue
        text = _normalise_text(raw)
        if text:
            found[name] = LicenseText(name, text)
    if not found:
        long_field = (dist.metadata.get("License") or "").strip()
        if "\n" in long_field or len(long_field) > _MAX_DECLARATION_LENGTH:
            found["License field"] = LicenseText("License field", _normalise_text(long_field.encode()))
    return [found[name] for name in sorted(found)]


def collect_packages(
    project: str = PROJECT,
    extras: tuple[str, ...] = SHIPPED_EXTRAS,
    build_tools: tuple[str, ...] = EMBEDDED_BUILD_TOOLS,
) -> list[Package]:
    packages = [
        Package(
            name=dist.metadata["Name"],
            version=dist.version,
            declaration=declaration_of(dist),
            texts=license_texts_of(dist),
        )
        for dist in collect_distributions(project, extras, build_tools)
    ]
    packages.sort(key=lambda package: package.canonical_name)
    return packages


def python_license_dirs() -> list[Path]:
    """Where a Python installation keeps its license file.

    The interpreter the virtualenv was created from, not the virtualenv: on
    Windows the file sits in the installation root, and CPython's own install
    step also copies it into the standard library folder.
    """
    directories = [Path(sys.base_prefix)]
    stdlib = sysconfig.get_path("stdlib")
    if stdlib:
        directories.append(Path(stdlib))
    return directories


def collect_python(license_dirs: list[Path] | None = None) -> Package:
    """The bundled Python runtime, with the license files found in *license_dirs*."""
    if license_dirs is None:
        license_dirs = python_license_dirs()
    found: dict[str, LicenseText] = {}
    for directory in license_dirs:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in found or not _PYTHON_LICENSE_FILE_NAME.match(entry.name):
                continue
            try:
                if not entry.is_file():
                    continue
                text = _normalise_text(entry.read_bytes())
            except OSError:
                continue
            if text:
                found[entry.name] = LicenseText(entry.name, text)

    implementation = sys.implementation.name
    return Package(
        name=PYTHON_NAME,
        version=sys.version.split()[0],
        declaration="PSF-2.0" if implementation == "cpython" else "not declared",
        texts=[found[name] for name in sorted(found)],
        detail=f"{implementation} {' '.join(sys.version.split())}",
        note=PYTHON_NOTE,
        missing_message=PYTHON_MISSING,
    )


# --- system libraries of a Linux build ------------------------------------

SYSTEM_LIBRARIES_TITLE = "System libraries bundled on Linux"
SYSTEM_LIBRARIES_NOTE = (
    "PyInstaller copies the shared libraries that the bundled components link\n"
    "against from the machine that built the application. It leaves out only a\n"
    "few (the C library and the graphics stack, for example), so the libraries\n"
    "below travel with the Linux build. Each one is listed with the Debian\n"
    "package that owns the file on the build machine (found with dpkg -S),\n"
    "followed by the license information that package ships in\n"
    "/usr/share/doc/<package>/copyright. Those files may refer to the standard\n"
    "license texts that a Debian system keeps under /usr/share/common-licenses\n"
    "instead of reproducing them; the texts they refer to follow the packages,\n"
    "under \"Referenced license texts\"."
)
REFERENCED_LICENSES_TITLE = "Referenced license texts"
REFERENCED_LICENSES_NOTE = (
    "The copyright files above refer to these license texts, which a Debian\n"
    "system keeps under /usr/share/common-licenses. They are copied from the\n"
    "machine that built the application."
)
NO_OWNING_PACKAGE = "no Debian package owns this file"
PACKAGE_UNKNOWN = "package unknown (dpkg could not be used on the build machine)"
_SYSTEM_LIBRARIES_HEADING = re.compile(r"^System libraries \((\d+)\)$")
# Typecodes of the entries in an Analysis-00.toc that are shared libraries.
LIBRARY_TYPECODES = ("BINARY", "EXTENSION")
DEBIAN_DOC_ROOT = Path("/usr/share/doc")
DEBIAN_LICENSES_ROOT = Path("/usr/share/common-licenses")
# Debian package names: lower-case letters, digits and + - . only.
_DEBIAN_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
# The name of a file under /usr/share/common-licenses (GPL-3, LGPL-2.1,
# Apache-2.0, ...): it starts with a letter or digit and contains only letters,
# digits, + _ - and inner dots, so it can be neither "." / ".." nor a path.
_COMMON_LICENSE_NAME = r"[A-Za-z0-9][A-Za-z0-9+_-]*(?:\.[A-Za-z0-9+_-]+)*"
_COMMON_LICENSE_FULL_NAME = re.compile(_COMMON_LICENSE_NAME)
# A reference in a copyright text. The lookahead keeps a name that is followed by
# more path ("…/licenses/sub/dir") or by more name characters from being cut
# short and taken for another file; a full stop that ends a sentence is not
# part of the name.
_COMMON_LICENSE_REFERENCE = re.compile(
    re.escape(f"{DEBIAN_LICENSES_ROOT.as_posix()}/") + f"({_COMMON_LICENSE_NAME})" + r"(?![\w+/-])"
)
# How many paths one dpkg call is asked about.
_DPKG_BATCH = 100
# Spellings of one directory under a merged /usr, where /lib is a link to
# /usr/lib. dpkg's file lists use the spelling of the package that ships the
# file, which is not necessarily the one the loader reported.
_MERGED_USR_PAIRS = (("/usr/lib/", "/lib/"), ("/usr/lib64/", "/lib64/"))
_SITE_DIR_NAMES = ("site-packages", "dist-packages")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class DpkgUnavailable(Exception):
    """dpkg could not be run or did not answer."""


@dataclass(frozen=True)
class SystemLibrary:
    """One shared library packed into the build."""

    name: str  # its name inside the build
    # Debian packages that own the file; empty when none does (or when dpkg
    # could not be asked, see SystemLibraries.dpkg_problem).
    packages: tuple[str, ...] = ()


@dataclass
class DebianPackage:
    """A Debian package that owns at least one packed library."""

    name: str
    libraries: list[str]
    copyright_path: str
    copyright_text: str | None  # None when the file does not exist


@dataclass
class ReferencedLicense:
    """A standard license text that a package's copyright file points to."""

    name: str  # its file name under /usr/share/common-licenses
    path: str  # where it was looked for
    text: str | None  # None when the file does not exist


@dataclass
class SystemLibraries:
    libraries: list[SystemLibrary]  # sorted by name
    packages: list[DebianPackage]  # sorted by name
    # Why the owners could not be determined; empty when dpkg answered.
    dpkg_problem: str = ""
    # The standard license texts the packages' copyright files refer to,
    # sorted by name, each once.
    licenses: list[ReferencedLicense] = field(default_factory=list)


def is_linux() -> bool:
    return sys.platform.startswith("linux")


# Folders that hold much more than one Python installation. A Python whose
# prefix is one of these (a distribution's under /usr, a source build or an
# official Docker image under /usr/local, something dropped into /opt) would
# otherwise make every library next to it look like part of Python.
_BROAD_ROOTS = ("/usr", "/usr/local", "/opt")


def _too_broad(root: str) -> bool:
    """The whole file system or one of _BROAD_ROOTS, rather than one Python installation."""
    cleaned = os.path.normpath(root)
    return os.path.dirname(cleaned) == cleaned or cleaned in {
        os.path.normpath(broad) for broad in _BROAD_ROOTS
    }


def environment_roots() -> list[str]:
    """Folders whose files are the Python environment or this repository.

    Shared libraries from here are not system libraries: the Python
    installation (the interpreter's own libraries and extension modules), the
    virtualenv, site-packages (wheels carry their own libraries and their own
    metadata) and the repository. A root as broad as /usr, /usr/local or /opt
    is not used (see _BROAD_ROOTS): the libraries under it that are not
    Python's own, libpython included, are listed, and show up as "no Debian
    package owns this file" when no package does. Listing too much is the safe
    side; leaving a library out would hide it.
    """
    candidates = [sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix]
    candidates.extend(
        sysconfig.get_path(key) for key in ("stdlib", "platstdlib", "purelib", "platlib")
    )
    candidates.extend(entry for entry in sys.path if Path(entry).name in _SITE_DIR_NAMES)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    unique: dict[str, None] = {}
    for candidate in candidates:
        if candidate and not _too_broad(candidate):
            for spelling in analysis.path_spellings(candidate):
                unique.setdefault(spelling, None)
    return list(unique)


def _is_under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def bundled_system_libraries(
    entries: Iterable[analysis.TocEntry], roots: Sequence[str] | None = None
) -> dict[str, str]:
    """Packed shared libraries from outside *roots*: name in the build -> source file.

    Only BINARY and EXTENSION entries count (not Python modules and data), and
    only those whose source is not under any of *roots* (default:
    environment_roots()). Sources are returned as the analysis recorded them.
    """
    if roots is None:
        roots = environment_roots()
    normal_roots = [analysis.normal_path(root) for root in roots]
    found: dict[str, str] = {}
    for name, source, typecode in entries:
        if typecode not in LIBRARY_TYPECODES or not source or source == "-":
            continue
        if any(
            _is_under(spelling, root)
            for spelling in analysis.path_spellings(source)
            for root in normal_roots
        ):
            continue
        # The same library can be packed from two places in two executables;
        # the smaller path wins so the result does not depend on their order.
        if name not in found or source < found[name]:
            found[name] = source
    return found


def _lookup_spellings(source: str, realpath: Callable[[str], str]) -> list[str]:
    """The paths dpkg is asked about for one file, most specific first.

    The file with symlinks resolved, then the path as recorded, each also in the
    other spelling of a merged /usr (see _MERGED_USR_PAIRS). Only absolute
    POSIX paths: dpkg -S would read anything else as a search for a substring.
    """
    spellings: list[str] = []
    for path in (realpath(source), source):
        variants = [path]
        for merged, split in _MERGED_USR_PAIRS:
            if path.startswith(merged):
                variants.append(split + path[len(merged) :])
            elif path.startswith(split):
                variants.append(merged + path[len(split) :])
        for variant in variants:
            if variant.startswith("/") and variant not in spellings:
                spellings.append(variant)
    return spellings


def parse_dpkg_search(output: str) -> dict[str, set[str]]:
    """``dpkg -S`` output -> path -> names of the packages that own it.

    Lines look like ``libnss3:amd64: /usr/lib/x86_64-linux-gnu/libnss3.so`` and,
    for a path two packages share, ``pkg-a:amd64, pkg-b:amd64: /usr/share/x``.
    The architecture qualifier is dropped. Diversion notices (``diversion by
    pkg from: /path``, ``local diversion from: /path``) and anything else that
    is not an owner line are ignored.
    """
    owners: dict[str, set[str]] = {}
    for line in output.splitlines():
        if line.startswith(("diversion by ", "local diversion ")):
            continue
        head, separator, tail = line.partition(": /")
        if not separator:
            continue
        for token in head.split(", "):
            # Whatever precedes the colon must be a package name; a notice that
            # happens to contain ": /" is not an owner line.
            name = token.partition(":")[0].strip()
            if _DEBIAN_PACKAGE_NAME.match(name):
                owners.setdefault("/" + tail, set()).add(name)
    return owners


def dpkg_owners(paths: Sequence[str], run: Runner = subprocess.run) -> dict[str, set[str]]:
    """Ask ``dpkg -S`` who owns each path; paths nobody owns are absent from the result.

    Raises DpkgUnavailable when dpkg cannot be run or fails (an unknown path is
    not a failure: dpkg exits with 1 for it and still answers for the rest).
    """
    owners: dict[str, set[str]] = {}
    unique = sorted(set(paths))
    for start in range(0, len(unique), _DPKG_BATCH):
        batch = unique[start : start + _DPKG_BATCH]
        try:
            done = run(
                ["dpkg", "-S", *batch],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "LC_ALL": "C"},
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DpkgUnavailable(f"dpkg could not be run: {exc}") from exc
        if done.returncode not in (0, 1):
            detail = (done.stderr or "").strip().splitlines()
            raise DpkgUnavailable(
                f"dpkg exited with status {done.returncode}"
                + (f": {detail[0]}" if detail else "")
            )
        for path, names in parse_dpkg_search(done.stdout or "").items():
            owners.setdefault(path, set()).update(names)
    return owners


def read_debian_copyright(package: str, doc_root: Path) -> tuple[str, str | None]:
    """``(path, text)`` of a package's copyright file; text is None when it is not there."""
    path = doc_root / package / "copyright"
    shown = f"{doc_root.as_posix().rstrip('/')}/{package}/copyright"
    if not _DEBIAN_PACKAGE_NAME.match(package):
        return shown, None
    try:
        text = _normalise_text(path.read_bytes())
    except OSError:
        return shown, None
    return shown, text or None


def common_license_references(text: str) -> list[str]:
    """Names of the files under /usr/share/common-licenses that *text* points to, sorted.

    Only plain file names are taken (see _COMMON_LICENSE_NAME): a reference with
    ``..`` or a deeper path in it is not a reference to one of those files.
    """
    return sorted(set(_COMMON_LICENSE_REFERENCE.findall(text)))


def read_common_license(name: str, licenses_root: Path) -> ReferencedLicense:
    """The standard license text called *name*; its text is None when it cannot be read.

    A name that is not a plain file name is never looked up, whatever the
    caller passes.
    """
    shown = f"{licenses_root.as_posix().rstrip('/')}/{name}"
    if not _COMMON_LICENSE_FULL_NAME.fullmatch(name):
        return ReferencedLicense(name, shown, None)
    try:
        text = _normalise_text((licenses_root / name).read_bytes())
    except OSError:
        return ReferencedLicense(name, shown, None)
    return ReferencedLicense(name, shown, text or None)


def collect_system_libraries(
    analyses: Mapping[str, Sequence[analysis.TocEntry]],
    *,
    roots: Sequence[str] | None = None,
    run: Runner = subprocess.run,
    realpath: Callable[[str], str] = os.path.realpath,
    doc_root: Path | None = None,
    licenses_root: Path | None = None,
) -> SystemLibraries:
    """The system libraries packed according to *analyses*, with their Debian packages.

    The result does not depend on the order of the analyses or of their
    entries. If dpkg cannot be used the libraries are still returned, with
    ``dpkg_problem`` saying why no package is known. The standard license
    texts that the collected copyright files refer to are read from
    *licenses_root* (default: /usr/share/common-licenses), each once.
    """
    sources: dict[str, str] = {}
    for entries in analyses.values():
        for name, source in bundled_system_libraries(entries, roots).items():
            if name not in sources or source < sources[name]:
                sources[name] = source

    spellings = {name: _lookup_spellings(source, realpath) for name, source in sources.items()}
    problem = ""
    owners: dict[str, set[str]] = {}
    try:
        owners = dpkg_owners([path for paths in spellings.values() for path in paths], run)
    except DpkgUnavailable as exc:
        problem = str(exc)

    libraries = []
    for name in sorted(sources):
        found = next((owners[path] for path in spellings[name] if path in owners), set())
        libraries.append(SystemLibrary(name, tuple(sorted(found))))

    by_package: dict[str, list[str]] = {}
    for library in libraries:
        for package in library.packages:
            by_package.setdefault(package, []).append(library.name)
    if doc_root is None:
        doc_root = DEBIAN_DOC_ROOT
    packages = []
    for package in sorted(by_package):
        copyright_path, text = read_debian_copyright(package, doc_root)
        packages.append(DebianPackage(package, by_package[package], copyright_path, text))

    if licenses_root is None:
        licenses_root = DEBIAN_LICENSES_ROOT
    referenced = sorted(
        {
            name
            for package in packages
            if package.copyright_text
            for name in common_license_references(package.copyright_text)
        }
    )
    licenses = [read_common_license(name, licenses_root) for name in referenced]
    return SystemLibraries(libraries, packages, problem, licenses)


def _append_text_once(
    lines: list[str], printed: dict[str, str], path: str, text: str
) -> None:
    """Add *text* under a ``--- path ---`` heading, unless the same text is already printed.

    *printed* maps the digest of each text printed so far to where it is; a
    repeat gets a heading that points there instead of the text again.
    """
    digest = LicenseText(path, text).digest
    earlier = printed.get(digest)
    if earlier is not None:
        lines.append(f"--- {path} (same text as {earlier}) ---")
        return
    printed[digest] = f"{path}, above"
    lines.append(f"--- {path} ---")
    lines.append(text)


def render_system_libraries(
    system: SystemLibraries, printed: dict[str, str] | None = None
) -> list[str]:
    """The lines of the "System libraries bundled on Linux" section.

    *printed* maps the digest of a license text that appears earlier in the
    file to where. A copyright file or referenced license text with the same
    digest is not repeated (binary packages built from one source often ship
    the same copyright file). The texts printed here are added to it.
    """
    if printed is None:
        printed = {}
    lines = ["", _RULE, SYSTEM_LIBRARIES_TITLE, _RULE, SYSTEM_LIBRARIES_NOTE]
    if system.dpkg_problem:
        lines.extend(["", f"The owning packages could not be determined: {system.dpkg_problem}."])
    lines.extend(["", f"System libraries ({len(system.libraries)})", _THIN_RULE])
    for library in system.libraries:
        if system.dpkg_problem:
            status = PACKAGE_UNKNOWN
        else:
            status = ", ".join(library.packages) or NO_OWNING_PACKAGE
        lines.append(f"{library.name} - {status}")
    for package in system.packages:
        lines.extend(
            ["", _THIN_RULE, f"{package.name} (Debian package)", _THIN_RULE]
        )
        lines.append("Bundled files: " + ", ".join(package.libraries))
        lines.append("")
        if package.copyright_text is None:
            lines.append(f"No copyright text was found at {package.copyright_path}.")
        else:
            _append_text_once(lines, printed, package.copyright_path, package.copyright_text)
    if system.licenses:
        lines.extend(
            ["", _THIN_RULE, REFERENCED_LICENSES_TITLE, _THIN_RULE, REFERENCED_LICENSES_NOTE]
        )
        for referenced in system.licenses:
            lines.append("")
            if referenced.text is None:
                lines.append(f"Not found at {referenced.path}.")
            else:
                _append_text_once(lines, printed, referenced.path, referenced.text)
    return lines


def listed_system_library_names(text: str) -> list[str] | None:
    """Names of the libraries a rendered notices file lists, or None without that section.

    Reads the index that render_system_libraries() writes under
    "System libraries (N)": one ``<name> - <package or reason>`` line per
    library, up to the next blank line. Raises ValueError when the section
    title is there but the index is missing or does not hold N lines.
    """
    lines = text.split("\n")
    if SYSTEM_LIBRARIES_TITLE not in lines:
        return None
    start = lines.index(SYSTEM_LIBRARIES_TITLE)
    for position in range(start, len(lines)):
        heading = _SYSTEM_LIBRARIES_HEADING.match(lines[position])
        if heading:
            break
    else:
        raise ValueError("the system libraries section has no 'System libraries (N)' index")
    if lines[position + 1 : position + 2] != [_THIN_RULE]:
        raise ValueError("the system library index is not followed by its rule")
    names = []
    for entry in lines[position + 2 :]:
        if not entry:
            break
        name = entry.split(" - ", 1)[0]
        if not name or " - " not in entry:
            raise ValueError(f"cannot read a library from the index line: {entry!r}")
        names.append(name)
    if len(names) != int(heading.group(1)):
        raise ValueError(
            f"the index announces {heading.group(1)} system libraries but lists {len(names)}"
        )
    return names


def render(
    packages: list[Package],
    system_libraries: SystemLibraries | None = None,
    upstream_notice: str | None = None,
) -> str:
    """The notices text. *upstream_notice* defaults to read_upstream_notice().

    A notice that is given must not be empty or only whitespace either.
    """
    if upstream_notice is None:
        upstream_notice = read_upstream_notice()
    else:
        _require_text(upstream_notice, "the upstream license notice passed to render()")
    lines = [
        INTRO,
        _RULE,
        UPSTREAM_NOTICE_TITLE,
        _RULE,
        UPSTREAM_NOTICE_NOTE,
        "",
        upstream_notice,
        "",
        f"Components ({len(packages)})",
        _THIN_RULE,
    ]
    lines.extend(f"{package.title} - {package.declaration}" for package in packages)

    printed: dict[str, str] = {}
    for package in packages:
        lines.extend(["", _RULE, package.title, _RULE])
        lines.append(f"Declared license: {package.declaration}")
        if package.detail:
            lines.append(f"Interpreter: {package.detail}")
        note = package.note or NOTES.get(package.canonical_name)
        if note:
            lines.extend(["", note])
        if not package.texts:
            lines.extend(
                [
                    "",
                    package.missing_message
                    or "No license text is included in the installed package.",
                ]
            )
        for license_text in package.texts:
            lines.append("")
            earlier = printed.get(license_text.digest)
            if earlier is not None:
                lines.append(
                    f"--- {license_text.name} (same text as {earlier}) ---"
                )
                continue
            printed[license_text.digest] = f"{license_text.name} of {package.title}, above"
            lines.append(f"--- {license_text.name} ---")
            lines.append(license_text.text)
    if system_libraries is not None and system_libraries.libraries:
        lines.extend(render_system_libraries(system_libraries, printed))
    return "\n".join(lines) + "\n"


_COMPONENTS_HEADING = re.compile(r"^Components \((\d+)\)$")


def listed_component_names(text: str) -> list[str]:
    """Canonical names of the components that a rendered notices file lists.

    Reads the index that render() writes under "Components (N)": one
    ``<name> <version> - <declared license>`` line per component, up to the
    next blank line. The bundled Python runtime is in that index too (as
    "python"). Raises ValueError when the index is missing or does not hold N
    lines, so a file in some other format is never mistaken for a short list.
    """
    lines = text.split("\n")
    heading = None
    position = 0
    for position, line in enumerate(lines):
        heading = _COMPONENTS_HEADING.match(line)
        if heading:
            break
    if heading is None:
        raise ValueError("no 'Components (N)' index found in the notices text")
    if lines[position + 1 : position + 2] != [_THIN_RULE]:
        raise ValueError("the component index is not followed by its rule")
    names = []
    for entry in lines[position + 2 :]:
        if not entry:
            break
        title = entry.split(" - ", 1)[0]
        name, _, version = title.rpartition(" ")
        if not name or not version:
            raise ValueError(f"cannot read a component from the index line: {entry!r}")
        names.append(str(canonicalize_name(name)))
    if len(names) != int(heading.group(1)):
        raise ValueError(
            f"the index announces {heading.group(1)} components but lists {len(names)}"
        )
    return names


def build_notices(
    project: str = PROJECT,
    extras: tuple[str, ...] = SHIPPED_EXTRAS,
    build_tools: tuple[str, ...] = EMBEDDED_BUILD_TOOLS,
    python_dirs: list[Path] | None = None,
    system_libraries: SystemLibraries | None = None,
    upstream_notice: str | None = None,
) -> tuple[str, list[Package]]:
    """The notices text and every component in it: Python first, then the packages.

    *system_libraries* adds the Linux section (see collect_system_libraries()).
    *upstream_notice* defaults to the archived file (see render()).
    """
    components = [collect_python(python_dirs), *collect_packages(project, extras, build_tools)]
    return render(components, system_libraries, upstream_notice), components


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write THIRD_PARTY_NOTICES.txt")
    parser.add_argument("output", type=Path, help="file to write")
    parser.add_argument(
        "analysis",
        type=Path,
        nargs="*",
        help="PyInstaller Analysis-00.toc of each executable; on Linux they are read to "
        "list the system libraries packed into the build (ignored elsewhere)",
    )
    args = parser.parse_args(argv)

    # Read the archived upstream notice first: a missing or damaged file stops the
    # build before anything else is collected.
    try:
        upstream_notice = read_upstream_notice()
    except UpstreamNoticeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    system_libraries = None
    if args.analysis and is_linux():
        try:
            analyses = {str(path): analysis.read_analysis_toc(path) for path in args.analysis}
        except analysis.InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        system_libraries = collect_system_libraries(analyses)
        if system_libraries.dpkg_problem:
            print(
                f"warning: the Debian packages of the system libraries are unknown: "
                f"{system_libraries.dpkg_problem}",
                file=sys.stderr,
            )

    try:
        text, packages = build_notices(
            system_libraries=system_libraries, upstream_notice=upstream_notice
        )
    except metadata.PackageNotFoundError:
        print(f"{PROJECT} is not installed in this environment.", file=sys.stderr)
        return 1
    except MissingDependencies as exc:
        print(
            "Required packages are not installed in this environment: "
            + ", ".join(exc.names),
            file=sys.stderr,
        )
        return 1

    for package in packages:
        if not package.texts:
            print(f"warning: no license text found for {package.title}", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    args.output.write_bytes(data)
    detail = f"{len(packages)} components"
    if system_libraries is not None and system_libraries.libraries:
        detail += f", {len(system_libraries.libraries)} system libraries"
    print(f"Wrote {args.output} ({detail}, {len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
