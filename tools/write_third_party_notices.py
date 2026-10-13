#!/usr/bin/env python
"""Write THIRD_PARTY_NOTICES.txt: the licenses of everything bundled with the app.

PyInstaller copies PyQt6, Qt, QtWebEngine and every other runtime dependency
into the release archives, and each of them carries its own license terms.
This script lists those packages with their declared license and the license
text they ship, so the notice can travel with the build.

Run it with the build virtualenv's interpreter, after the project and its
dependencies are installed:

    .venv/bin/python tools/write_third_party_notices.py dist/ai-usage-clock/THIRD_PARTY_NOTICES.txt

Which packages are listed comes from the installed distribution metadata:
the project's runtime ``Requires-Dist`` entries (plus the extras it ships, see
SHIPPED_EXTRAS), followed recursively, plus the build tool whose bootloader is
embedded in the executables. The Python runtime that PyInstaller bundles is
listed first, with the license file found in the Python installation the
virtualenv was created from. The output is UTF-8 with LF line endings and
carries no timestamp, so the same environment always yields the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import sysconfig
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PROJECT = "ai-usage-clock"
REPO_URL = "https://github.com/AIUsageClock/ai-usage-clock"

# Extras of the project whose dependencies end up in a release archive. The
# packaged MCP helper bundles the "mcp" extra; "dev" (pytest and friends) is
# never shipped.
SHIPPED_EXTRAS = ("mcp",)
# Build tools whose own code is embedded in the executables (PyInstaller's
# bootloader). Only the tool is listed, not its dependencies.
EMBEDDED_BUILD_TOOLS = ("pyinstaller",)

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


def render(packages: list[Package]) -> str:
    lines = [INTRO, f"Components ({len(packages)})", _THIN_RULE]
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
    return "\n".join(lines) + "\n"


def build_notices(
    project: str = PROJECT,
    extras: tuple[str, ...] = SHIPPED_EXTRAS,
    build_tools: tuple[str, ...] = EMBEDDED_BUILD_TOOLS,
    python_dirs: list[Path] | None = None,
) -> tuple[str, list[Package]]:
    """The notices text and every component in it: Python first, then the packages."""
    components = [collect_python(python_dirs), *collect_packages(project, extras, build_tools)]
    return render(components), components


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write THIRD_PARTY_NOTICES.txt")
    parser.add_argument("output", type=Path, help="file to write")
    args = parser.parse_args(argv)

    try:
        text, packages = build_notices()
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
    print(f"Wrote {args.output} ({len(packages)} components, {len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
