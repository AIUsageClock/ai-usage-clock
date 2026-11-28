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
collects anything when that file cannot be read. A few packages (the winrt
packages and pyobjc-core) ship no license file in their wheels; for those the
text of the source project's repository, archived under docs/legal/third-party/,
is used (see ARCHIVED_LICENSES). On Windows and macOS the libffi that the
bundled Python's _ctypes module uses is listed as a component of its own, with
its archived license text (see collect_libffi); on Linux the libffi.so that is
packed into the build is covered by the system libraries section below. The
other third-party components that CPython itself bundles (expat, libmpdec,
mimalloc, HACL*, OpenSSL on macOS) are components of their own as well, per
platform, together with the notices of CPython's own incorporated code from
Doc/license.rst (see PYTHON_BUNDLED_LICENSES and collect_python_components). The
output is UTF-8 with LF
line endings and carries no timestamp, so the same environment always yields
the same bytes.

How much of each license text is printed follows the user's rule of the minimum
the licenses ask for (see "how much of each license text is printed" below):
the Apache License 2.0 once, in a "Shared license texts" section after the
components; identical MIT/BSD wordings once, each component keeping its own
copyright line; of some packages only the license files of the packed parts;
no GPL text a file only reproduces and no history of Python. A "Source code of
copyleft components" section says where the source of the GPL, LGPL and MPL
components is.

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
so in the section rather than left out. In a Debian copyright file in the
machine-readable format the paragraphs about debian/* and about files that are
not part of the libraries are left out and a repeated license text is pointed
at (see trim_debian_copyright); the source packages of the copyleft libraries
are named in the source section.

The Rust crates linked into the cryptography, pydantic_core and rpds-py wheels
are read from the SBOM in each installed wheel and matched with the researched
data in docs/legal/third-party/rust-crates.json; a crate missing there fails
the build (see collect_rust_crates).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import sysconfig
import textwrap
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

# Packages whose wheels ship no license file, although they declare a license:
# the five winrt packages (Windows) and pyobjc-core (macOS). For these the
# license text of the project's source repository is archived word for word
# under docs/legal/third-party/ and used when the installed distribution has no
# license text of its own. A text the wheel does ship always wins. The packages
# are the names in pyproject.toml and what they pull in; the texts were copied
# from the tags below, which are the versions pinned in uv.lock when they were
# archived (a license change in a later release shows up as a changed file in
# the source repository, which is why the source is named in the output).
THIRD_PARTY_LICENSE_DIR = "docs/legal/third-party"


@dataclass(frozen=True)
class ArchivedLicense:
    """A license text kept in this repository for a package whose wheel ships none."""

    file: str  # relative to REPO_ROOT
    project: str  # name of the source project, as printed
    source_url: str  # where the text was copied from (a file at a fixed commit)
    ref: str  # the release tag that commit belongs to


_PYWINRT = ArchivedLicense(
    file=f"{THIRD_PARTY_LICENSE_DIR}/pywinrt-LICENSE.txt",
    project="pywinrt",
    source_url=(
        "https://github.com/pywinrt/pywinrt/blob/"
        "21cbd0fd7ff91422ed76b4e3611d3fb52716e017/LICENSE"
    ),
    ref="tag v3.2.1",
)
_PYOBJC_CORE = ArchivedLicense(
    file=f"{THIRD_PARTY_LICENSE_DIR}/pyobjc-core-License.txt",
    project="PyObjC",
    source_url=(
        "https://github.com/ronaldoussoren/pyobjc/blob/"
        "38cdf73fc049ef2d176973eff4ac8d5c76b0a34b/pyobjc-core/License.txt"
    ),
    ref="tag v12.2.2",
)
# libffi, which CPython's _ctypes module uses. The LICENSE of CPython installs
# that this build relies on is not known to carry libffi's notice (on Windows,
# python.org's LICENSE.txt is concatenated from several texts by
# PCbuild/regen.targets, which per that build rule includes libffi, bzip2, zstd,
# OpenSSL and the MS CRT; that is inferred from the rule alone, the installed
# file was not read). The text is archived here anyway, so that nothing depends
# on that inference: one file per platform
# because what the release builds ship differs (checked against release run
# 44103626977, CPython 3.14.10 from actions/setup-python, UV_PYTHON_DOWNLOADS
# never):
#   * Windows: python.org's installer build, which carries libffi-8.dll. CPython
#     v3.14.10 fetches libffi 3.4.4 for it (PCbuild/get_externals.bat,
#     Misc/externals.spdx.json). The text is libffi 3.4.4's LICENSE.
#   * macOS: python.org's pkg build. Its configure script uses the libffi of the
#     macOS SDK (-DUSING_APPLE_OS_LIBFFI=1, i.e. /usr/lib/libffi.dylib, Apple's
#     libffi); Mac/BuildScript/build-installer.py builds none of its own. So
#     the library is not part of the bundle, but the notice is shipped anyway.
#     The text is Apple's libffi LICENSE (apple-oss-distributions/libffi, tag
#     libffi-40; tags libffi-30 to libffi-40 all carry the same bytes, which
#     release ships in the runner's macOS is not known).
#   * Linux: libffi.so.8 of the build machine is packed, so the "System
#     libraries bundled on Linux" section carries the copyright file of its
#     Debian package (libffi8), which reproduces the MIT text. No component
#     here.
# A local build with another Python (for example uv's python-build-standalone,
# which on macOS links its own libffi 3.8.x statically) gets the same entry for
# its platform: the terms are the same MIT text, only the year in the first line
# can differ from the library actually linked. That is why the label names the
# role of the library and claims no release, and why the notes say what the
# text was taken from. pyobjc-core is not a reason for this entry: its _objc
# extension links /usr/lib/libffi.dylib, which is not part of the bundle (its
# License.txt only says libffi-src is a separate product).
LIBFFI_NAME = "libffi"
# The index line splits "<name> <version>" at the last space, so this is one
# word; it says what the library is for instead of naming a release.
LIBFFI_VERSION_LABEL = "(used-by-CPython-_ctypes)"
_LIBFFI_WINDOWS = ArchivedLicense(
    file=f"{THIRD_PARTY_LICENSE_DIR}/libffi-3.4.4-LICENSE.txt",
    project="libffi",
    source_url=(
        "https://github.com/libffi/libffi/blob/"
        "f24180be1367f942824365b131ae894b9c769c7d/LICENSE"
    ),
    ref="tag v3.4.4",
)
_LIBFFI_MACOS = ArchivedLicense(
    file=f"{THIRD_PARTY_LICENSE_DIR}/libffi-apple-40-LICENSE.txt",
    project="libffi (Apple)",
    source_url=(
        "https://github.com/apple-oss-distributions/libffi/blob/"
        "72e95a49029b75b2a0de094477f8410a32013c87/LICENSE"
    ),
    ref="tag libffi-40",
)
# By sys.platform; Linux has none (see above).
LIBFFI_LICENSES: dict[str, ArchivedLicense] = {
    "win32": _LIBFFI_WINDOWS,
    "darwin": _LIBFFI_MACOS,
}
LIBFFI_NOTES = {
    "win32": (
        "The Python runtime of the Windows build carries libffi-8.dll for its\n"
        "_ctypes module (libffi 3.4.4 in the python.org build of CPython 3.14.10).\n"
        "Python's own license text does not reproduce libffi's notice.\n"
        "The text below is the license of libffi, copied word for word from:\n"
        f"{_LIBFFI_WINDOWS.source_url}"
    ),
    "darwin": (
        "The Python runtime of the macOS build uses libffi for its _ctypes module.\n"
        "The python.org build of CPython links the libffi of macOS\n"
        "(/usr/lib/libffi.dylib) instead of carrying its own copy; the notice of\n"
        "that library is reproduced here all the same. Python's own license text\n"
        "does not reproduce it. The text below is the license of Apple's libffi,\n"
        "copied word for word from:\n"
        f"{_LIBFFI_MACOS.source_url}"
    ),
}
# Components that CPython itself bundles inside the runtime, whose notices
# neither CPython's LICENSE file nor (outside Windows) any other file of the
# installation reproduces. Found by reading CPython v3.14.10's build files
# (Misc/sbom.spdx.json, Misc/externals.spdx.json, PCbuild/*, Mac/BuildScript,
# the Ubuntu builder of actions/python-versions). What each platform carries:
#   * Windows (python.org build): expat, libmpdec 4.0.0, mimalloc and HACL*,
#     linked statically into pyexpat.pyd, _decimal.pyd and python314.dll.
#   * macOS (python.org universal2 build): OpenSSL, expat, libmpdec 4.0.1 and
#     HACL*. mimalloc is switched off there (--with-mimalloc=no) and is not
#     listed. cpython-source-deps has no tag for libmpdec 4.0.1; bytereef.org's
#     changelog lists only build/install fixes for it, but its own COPYRIGHT.txt
#     was not read, so the archived text is 4.0.0's and the note says so
#     instead of claiming the two are identical.
#   * Linux (actions/python-versions, built on Ubuntu 22.04): expat, libmpdec
#     2.5.1, mimalloc and HACL* are built into CPython. OpenSSL and the other
#     libraries it links are system libraries, covered by the Debian copyright
#     section, so there is no OpenSSL entry.
# Left out because they need no text: zlib-ng (the zlib License only governs
# source code), SQLite and xz (public domain). Entries are kept even where the
# exact build is not known for sure (a local python-build-standalone Python
# carries other versions): the terms are the same, so the labels name a role,
# never a release (see LIBFFI_VERSION_LABEL); the versions appear only in the
# notes and in the source URLs. The notices of the small pieces of code inside
# CPython itself (Mersenne Twister, SipHash, dtoa, the Unicode Character
# Database and others) that "Licenses and Acknowledgements for Incorporated
# Software" (Doc/license.rst) lists come with every platform, but only those
# sections whose code is in the bundle (see _INCORPORATED_NOTICES). The user's
# rule (2026-11-28) is the minimum the licenses ask for: a license that wants a
# notice gets its notice, one that asks for nothing gets no entry.
_GITHUB = "https://github.com"
_CPYTHON_COMMIT = "b703b2c5e704341d61e367b9b940b77ed11dded0"  # tag v3.14.10
_SOURCE_DEPS = f"{_GITHUB}/python/cpython-source-deps/blob"


@dataclass(frozen=True)
class PythonComponent:
    """A third-party component inside CPython, with its archived license text.

    *note* is written with a ``{url}`` placeholder for the source URL of
    *license*. *license* is None for a component whose license text is
    reproduced elsewhere in the file (see _OPENSSL); *more_licenses* are further
    archived texts of the same component.
    """

    name: str
    version_label: str  # one word naming the role, never a release
    declaration: str
    license: ArchivedLicense | None
    note: str
    more_licenses: tuple[ArchivedLicense, ...] = ()

    @property
    def licenses(self) -> tuple[ArchivedLicense, ...]:
        return (() if self.license is None else (self.license,)) + self.more_licenses


def _archived(project: str, file: str, url: str, ref: str) -> ArchivedLicense:
    return ArchivedLicense(
        file=f"{THIRD_PARTY_LICENSE_DIR}/{file}", project=project, source_url=url, ref=ref
    )


_EXPAT = PythonComponent(
    name="expat",
    version_label="(used-by-CPython-pyexpat)",
    declaration="MIT",
    license=_archived(
        "expat",
        "expat-2.9.0-COPYING.txt",
        f"{_GITHUB}/python/cpython/blob/{_CPYTHON_COMMIT}/Modules/expat/COPYING",
        "CPython tag v3.14.10, expat 2.9.0",
    ),
    note=(
        "The Python runtime carries the expat XML parser, which its pyexpat module\n"
        "(and with it xml.parsers.expat and xml.etree) uses. CPython 3.14.10\n"
        "bundles expat 2.9.0. Python's own license text does not reproduce\n"
        "expat's notice. The text below is the license of expat, copied word for\n"
        "word from:\n"
        "{url}"
    ),
)
_HACL = PythonComponent(
    name="HACL*",
    version_label="(used-by-CPython-hashlib)",
    declaration="MIT",
    license=_archived(
        "HACL*",
        "hacl-star-8ba599b-LICENSE.txt",
        f"{_GITHUB}/hacl-star/hacl-star/blob/8ba599b2f6c9701b3dc961db895b0856a2210f76/"
        "dist/LICENSE.txt",
        "commit 8ba599b, the one CPython 3.14.10 bundles",
    ),
    note=(
        "The Python runtime carries C code generated from HACL* (a library of\n"
        "formally verified cryptography), which its built-in hash modules (the\n"
        "algorithms behind hashlib, such as SHA-2 and SHA-3) use. The HACL*\n"
        "repository as a whole is licensed under Apache-2.0, but the generated C\n"
        "code that CPython bundles comes with the MIT license of the repository's\n"
        "dist folder, which is the text below. Python's own license text does not\n"
        "reproduce it. Copied word for word from:\n"
        "{url}"
    ),
)
_MIMALLOC = PythonComponent(
    name="mimalloc",
    version_label="(used-by-CPython-memory-allocator)",
    declaration="MIT",
    license=_archived(
        "mimalloc",
        "mimalloc-2.5.2-LICENSE.txt",
        f"{_GITHUB}/microsoft/mimalloc/blob/2406cc5f3ab6d6e54fe560cdd66fa46eee775312/LICENSE",
        "tag v2.5.2",
    ),
    note=(
        "The Python runtime carries the mimalloc memory allocator, which CPython\n"
        "bundles in its source tree (Objects/mimalloc) for its memory management.\n"
        "The Windows and Linux builds include it; the python.org macOS build\n"
        "switches it off, so it is not listed there. Python's own license text\n"
        "does not reproduce mimalloc's notice. The text below is the license of\n"
        "mimalloc 2.5.2, the version CPython 3.14.10 bundles, copied word for\n"
        "word from:\n"
        "{url}"
    ),
)
SHARED_TEXTS_TITLE = "Shared license texts"
# OpenSSL is Apache-2.0. Redistributing it needs the license text and, under
# section 4(d), the content of a NOTICE file if the project has one. The text
# is already in every notices file (several cross-platform dependencies, for
# example requests and cryptography, are Apache-2.0 and ship it; it is printed
# once, in the shared section), so no copy of it is archived here: the entry
# names the component and points there, and render() fails when the shared
# text is not available for an entry that needs it.
# The source tree of openssl-3.5.9 has no NOTICE file (checked in the root
# listing of that tag, 2026-11-28), so nothing else is owed.
_OPENSSL = PythonComponent(
    name="OpenSSL",
    version_label="(used-by-CPython-ssl-and-hashlib)",
    declaration="Apache-2.0",
    license=None,
    note=(
        "The python.org build of CPython for macOS builds its own OpenSSL\n"
        "(OpenSSL 3.5.9 in CPython 3.14.10: libssl and libcrypto) for the ssl and\n"
        "hashlib modules. Whether the application bundle ends up with those\n"
        "libraries was not confirmed; the component is listed anyway. OpenSSL 3.x\n"
        "is licensed under the Apache License 2.0, the full text of which is\n"
        f"printed once under \"{SHARED_TEXTS_TITLE}\" in this file. The source\n"
        "tree of OpenSSL 3.5.9 has no NOTICE file."
    ),
)
# What of CPython's Doc/license.rst ("Licenses and Acknowledgements for
# Incorporated Software") the bundled runtime needs, decided section by section
# (2026-11-28; "in the bundle" is read from the local PyInstaller build's
# PYZ/Analysis tables, the C code from the extension modules and the core):
#   reproduced (in the bundle, and the terms require the notice to travel with
#   copies or binaries): Mersenne Twister (_random), Cookie management
#   (http.cookies), UUencode (encodings.uu_codec), XML Remote Procedure Calls
#   (xmlrpc.client), SipHash24 (Python/pyhash.c), strtod and dtoa
#   (Python/dtoa.c), cfuhash (tracemalloc), asyncio, Global Unbounded Sequences
#   (Python/qsbr.c), Zstandard bindings (_zstd), Unicode Character Database
#   (unicodedata, str); Select kqueue (macOS only: it is compiled only where
#   kqueue exists).
#   left out: OpenSSL, expat, libffi, libmpdec and mimalloc (components of
#   their own, above), zlib (zlib-ng; the zlib License asks nothing of binaries
#   in this case), Sockets (WIDE getaddrinfo.c/getnameinfo.c are compiled only
#   where the platform has no getaddrinfo, which is none of the three),
#   Execution tracing (trace is not in the bundle), Asynchronous socket
#   services (test.support), test_epoll and the W3C C14N test suite (tests).
# The sections are copied word for word from the upstream file into the two
# files below (the second one for macOS only); the line endings are upstream's.
_INCORPORATED_URL = f"{_GITHUB}/python/cpython/blob/{_CPYTHON_COMMIT}/Doc/license.rst"
_INCORPORATED_NOTICES = _archived(
    "CPython Doc/license.rst",
    "cpython-3.14.10-incorporated-notices.txt",
    _INCORPORATED_URL,
    "CPython tag v3.14.10, sections as listed in the note",
)
_INCORPORATED_KQUEUE = _archived(
    "CPython Doc/license.rst (select kqueue)",
    "cpython-3.14.10-incorporated-notices-macos.txt",
    _INCORPORATED_URL,
    "CPython tag v3.14.10, section Select kqueue",
)
_INCORPORATED_NOTE = (
    "CPython's documentation lists, under \"Licenses and Acknowledgements for\n"
    "Incorporated Software\", code inside CPython that has license terms of its\n"
    "own, and reproduces their notices. Python's own license text does not.\n"
    "The sections below are copied word for word from that page ({url}),\n"
    "in reStructuredText; they are the ones whose code is in this build:\n"
    "Mersenne Twister, Cookie management, UUencode and UUdecode functions,\n"
    "XML Remote Procedure Calls, SipHash24, strtod and dtoa, cfuhash,\n"
    "asyncio, Global Unbounded Sequences (GUS), Zstandard bindings and Unicode\n"
    "Character Database{kqueue}. The page's other sections are either components\n"
    "of their own in this file (OpenSSL, expat, libffi, libmpdec, mimalloc) or\n"
    "cover code that is not in the build (the Sockets, Execution tracing,\n"
    "Asynchronous socket services, test_epoll and W3C C14N test suite\n"
    "sections), or ask nothing of a binary (zlib)."
)
_INCORPORATED = PythonComponent(
    name="CPython-incorporated-software",
    version_label="(Doc-license.rst)",
    declaration="various, see text",
    license=_INCORPORATED_NOTICES,
    note=_INCORPORATED_NOTE.replace("{kqueue}", ""),
)
_INCORPORATED_MACOS = PythonComponent(
    name="CPython-incorporated-software",
    version_label="(Doc-license.rst)",
    declaration="various, see text",
    license=_INCORPORATED_NOTICES,
    note=_INCORPORATED_NOTE.replace("{kqueue}", " (the macOS build also: Select kqueue)"),
    more_licenses=(_INCORPORATED_KQUEUE,),
)


def _mpdecimal(file: str, commit: str, ref: str, note: str) -> PythonComponent:
    leaf = "COPYRIGHT.txt" if file.endswith("COPYRIGHT.txt") else "LICENSE.txt"
    return PythonComponent(
        name="mpdecimal",
        version_label="(used-by-CPython-_decimal)",
        declaration="BSD-2-Clause",
        license=_archived("mpdecimal", file, f"{_SOURCE_DEPS}/{commit}/{leaf}", ref),
        note=note,
    )


_MPDECIMAL_400 = "48316ec025c1ebe500854c332be0a12c640c7301"
_MPDECIMAL_WINDOWS = _mpdecimal(
    "mpdecimal-4.0.0-COPYRIGHT.txt",
    _MPDECIMAL_400,
    "cpython-source-deps tag mpdecimal-4.0.0",
    "The Python runtime carries libmpdec (mpdecimal), which its _decimal\n"
    "module (the decimal module) uses. CPython 3.14.10 bundles libmpdec 4.0.0\n"
    "in the Windows build. Python's own license text does not reproduce its\n"
    "notice. The text below is the license of libmpdec 4.0.0, copied word for\n"
    "word from:\n"
    "{url}",
)
_MPDECIMAL_MACOS = _mpdecimal(
    "mpdecimal-4.0.0-COPYRIGHT.txt",
    _MPDECIMAL_400,
    "cpython-source-deps tag mpdecimal-4.0.0",
    "The Python runtime carries libmpdec (mpdecimal), which its _decimal\n"
    "module (the decimal module) uses. The text below is the text of libmpdec\n"
    "4.0.0; the macOS build of CPython uses libmpdec 4.0.1, for which\n"
    "cpython-source-deps has no tag. The changelog of libmpdec 4.0.1 lists only\n"
    "build and install fixes over 4.0.0, and the project states that its\n"
    "current releases are under the Simplified BSD License, but the 4.0.1 file\n"
    "itself was not compared, so this notice does not claim that the two texts\n"
    "are identical. Python's own license text does not reproduce it. Copied\n"
    "word for word from:\n"
    "{url}",
)
_MPDECIMAL_LINUX = _mpdecimal(
    "mpdecimal-2.5.1-LICENSE.txt",
    "5da6848fbab6bb6dc3aa09646c313fa4d3b5f522",
    "cpython-source-deps tag mpdecimal-2.5.1",
    "The Python runtime carries libmpdec (mpdecimal), which its _decimal\n"
    "module (the decimal module) uses. The Linux build of CPython 3.14.10\n"
    "builds libmpdec 2.5.1, the copy in its own source tree, into the\n"
    "runtime. Python's own license text does not reproduce its notice. The\n"
    "text below is the license of libmpdec 2.5.1, copied word for word from:\n"
    "{url}",
)

# By sys.platform; the order is the order in the notices file.
PYTHON_BUNDLED_LICENSES: dict[str, list[PythonComponent]] = {
    "win32": [_EXPAT, _MPDECIMAL_WINDOWS, _MIMALLOC, _HACL, _INCORPORATED],
    "darwin": [_OPENSSL, _EXPAT, _MPDECIMAL_MACOS, _HACL, _INCORPORATED_MACOS],
    "linux": [_EXPAT, _MPDECIMAL_LINUX, _MIMALLOC, _HACL, _INCORPORATED],
}

# Keyed by canonical package name (see Package.canonical_name).
ARCHIVED_LICENSES: dict[str, ArchivedLicense] = {
    "winrt-runtime": _PYWINRT,
    "winrt-windows-data-xml-dom": _PYWINRT,
    "winrt-windows-foundation": _PYWINRT,
    "winrt-windows-foundation-collections": _PYWINRT,
    "winrt-windows-ui-notifications": _PYWINRT,
    "pyobjc-core": _PYOBJC_CORE,
}

_RULE = "=" * 80
_THIN_RULE = "-" * 80

INTRO = f"""\
THIRD-PARTY NOTICES

AI Usage Clock is licensed under the MIT License; see the LICENSE file that
ships next to this file. The packaged program also contains components under
the GNU GPL and LGPL, among them PyQt6 (GPL-3.0); the package as a whole is
distributed under the terms those licenses require. Where to get their source
code is listed under "Source code of copyleft components".

This file lists the third-party components that are distributed with it, with
each component's declared license and the license text it ships. The source
code of AI Usage Clock is available at
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
    "pyinstaller": (
        "The executables embed PyInstaller's bootloader and run-time hooks. Of the\n"
        "license file of PyInstaller, this copy leaves out the full text of the GNU\n"
        "General Public License, version 2, which the file only reproduces, and\n"
        "refers to the Apache License 2.0 printed once under\n"
        f"\"{SHARED_TEXTS_TITLE}\"."
    ),
    "pyinstaller-hooks-contrib": (
        "Only the run-time hooks of this package are embedded in the executables;\n"
        "its other hooks are used while the executables are built. Of its license\n"
        "file, this copy leaves out the full text of the GNU General Public\n"
        "License, version 2, which the file only reproduces, and refers to the\n"
        f"Apache License 2.0 printed once under \"{SHARED_TEXTS_TITLE}\"."
    ),
    "pywin32": (
        "The executables contain only modules from the win32 folder of pywin32\n"
        "(win32api, win32cred, win32evtlog, win32evtlogutil, pywintypes and a few\n"
        "more). The license text below is the one of that folder; the other\n"
        "parts of the package (adodbapi, Scintilla, IDLE and so on) are not in\n"
        "the executables and their texts are not reproduced."
    ),
    "cryptography": (
        "This package is offered under either the Apache License 2.0 or the\n"
        "3-clause BSD license. AI Usage Clock uses it under the Apache License\n"
        f"2.0 (printed once under \"{SHARED_TEXTS_TITLE}\"); the BSD license text is\n"
        "not reproduced."
    ),
}

# Python's own license file covers Python itself and a few pieces of third-party
# code (for example bzip2 and Tcl/Tk on Windows), but not every library a Python
# distribution incorporates or links against. The notices of the components
# that the bundled runtime carries (PYTHON_BUNDLED_LICENSES, LIBFFI_LICENSES)
# follow it as components of their own.
_PYTHON_DOCS_LICENSE = "https://docs.python.org/3/license.html"
PYTHON_NOTE = (
    "The Python runtime is bundled with the application. Its license text is\n"
    "taken from the Python installation used for this build. That file does not\n"
    "reproduce the notices of all third-party code that a Python distribution\n"
    "incorporates. The notices of the components that the runtime carries\n"
    "(libffi, expat, libmpdec, mimalloc, HACL* and OpenSSL, depending on the\n"
    "platform) are listed as components of their own below, and so are the\n"
    "notices of the code incorporated into CPython itself that Python's\n"
    "documentation lists under \"Licenses and Acknowledgements for Incorporated\n"
    'Software", which is also online:\n'
    f"{_PYTHON_DOCS_LICENSE}"
)
PYTHON_MISSING = (
    "No license file (LICENSE, COPYING or NOTICE) was found in the Python\n"
    "installation used for this build."
)

# --- how much of each license text is printed -------------------------------
# The user's rule (2026-11-28) is the minimum the licenses ask for: a license
# that only wants a name gets a name, a text that several components share is
# printed once, and nothing a license requires is left out. Four mechanisms:
#   * PACKED_LICENSE_FILES: of a package that ships several license files, only
#     the ones that cover what the executables contain are printed.
#   * TEXT_CUTS: parts of a license file that the license does not ask to
#     travel with the program (the GPL text a file only reproduces, the history
#     of Python) are replaced by a one-line note. The cut points are literal
#     strings of the upstream files; a file in which they cannot be found is
#     printed whole, with a warning on stderr.
#   * the Apache License 2.0 is printed once (SHARED_TEXTS_TITLE); a component
#     whose text has the standard body keeps its copyright lines and any NOTICE.
#   * license texts that are word for word the same apart from the copyright
#     line (MIT, BSD) are printed once, at their first occurrence; the others
#     keep their own copyright lines and point there.
# Keys are canonical package names (see Package.canonical_name); the names in
# the tuples are the paths inside the dist-info folder, as license_texts_of()
# reports them. A listed file that is not there is an error, not a skip.
PACKED_LICENSE_FILES: dict[str, tuple[str, ...]] = {
    # The tool's own text; its other files are not license files.
    "pyinstaller": ("COPYING.txt",),
    "pyinstaller-hooks-contrib": ("LICENSE",),
    # win32/License.txt covers the win32 folder, the only part of pywin32 that
    # the executables contain (checked against the Analysis-00.toc files of the
    # local Windows build, 2026-11-28). The other files belong to adodbapi,
    # Scintilla, IDLE, the MAPI stub library and so on.
    "pywin32": ("win32/License.txt",),
    # Apache-2.0 OR BSD-3-Clause: the Apache License is the one used. LICENSE
    # (the file that says "either of") stays; LICENSE.BSD goes.
    "cryptography": ("LICENSE", "LICENSE.APACHE"),
}


class PackedLicenseFileError(Exception):
    """A license file named in PACKED_LICENSE_FILES is not in the installed package."""


def packed_license_texts(
    canonical_name: str,
    texts: list[LicenseText],
    table: Mapping[str, tuple[str, ...]] | None = None,
) -> list[LicenseText]:
    """The license texts of a package that are printed (all of them when it is not in *table*).

    Fails loudly when the table lists a file the package does not have: the
    table was written for particular versions, and a package that changed its
    layout must be looked at again rather than lose a license text in silence.
    """
    table = PACKED_LICENSE_FILES if table is None else table
    wanted = table.get(canonical_name)
    if wanted is None:
        return texts
    present = {text.name for text in texts}
    missing = [name for name in wanted if name not in present]
    if missing:
        raise PackedLicenseFileError(
            f"{canonical_name}: PACKED_LICENSE_FILES lists {', '.join(missing)}, which is not "
            f"among the license files of the installed package ({', '.join(sorted(present)) or 'none'})"
        )
    return [text for text in texts if text.name in wanted]


@dataclass(frozen=True)
class Cut:
    """A part of a license file that is replaced by one line.

    The part starts at the line that begins with *start* and ends after the
    line that contains *end* (the next occurrence after *start*), or, with
    *keep_end*, just before the line that begins with *end*. *needs_apache*:
    the part is the Apache License 2.0 and may only go when that text is
    printed once elsewhere and the part has the standard body.
    """

    start: str
    end: str
    replacement: str
    keep_end: bool = False
    needs_apache: bool = False


_GPL_CUT_NOTE = (
    "[The full text of the GNU General Public License, version 2\n"
    "(https://gnu.org/licenses/gpl-2.0.html), which follows here in the original\n"
    "file, is not reproduced in this copy.]"
)
_APACHE_CUT_NOTE = (
    "[The Apache License 2.0 that follows here in the original file is the one\n"
    f"printed once under \"{SHARED_TEXTS_TITLE}\".]"
)
_PSF_HISTORY_CUT = Cut(
    start="A. HISTORY OF THE SOFTWARE",
    end="B. TERMS AND CONDITIONS FOR ACCESSING OR OTHERWISE USING PYTHON",
    replacement=(
        "[Section A of the original file, \"HISTORY OF THE SOFTWARE\", is not\n"
        "reproduced in this copy; the license terms start with section B.]"
    ),
    keep_end=True,
)
TEXT_CUTS: dict[str, tuple[Cut, ...]] = {
    "pyinstaller": (
        Cut(
            "================================\nGNU General Public License\n"
            "================================",
            "END OF TERMS AND CONDITIONS",
            _GPL_CUT_NOTE,
        ),
        Cut(
            "================================\nApache License 2.0\n"
            "================================",
            "limitations under the License.",
            _APACHE_CUT_NOTE,
            needs_apache=True,
        ),
    ),
    "pyinstaller-hooks-contrib": (
        Cut(
            "GNU General Public License\n--------------------------",
            "END OF TERMS AND CONDITIONS",
            _GPL_CUT_NOTE,
        ),
        Cut(
            "Apache License 2.0\n++++++++++++++++++",
            "limitations under the License.",
            _APACHE_CUT_NOTE,
            needs_apache=True,
        ),
    ),
    # Python's own license file and typing_extensions' copy of it: the
    # history of the software is not part of the license terms (2026-11-28).
    PYTHON_NAME.lower(): (_PSF_HISTORY_CUT,),
    "typing-extensions": (_PSF_HISTORY_CUT,),
}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def apply_cut(text: str, cut: Cut, apache_available: bool) -> str | None:
    """*text* with the part *cut* describes replaced by its note; None when it does not apply."""
    start = text.find(cut.start)
    if start < 0 or (start > 0 and text[start - 1] != "\n"):
        return None
    end = text.find(cut.end, start + len(cut.start))
    if end < 0:
        return None
    if cut.keep_end:
        if text[end - 1] != "\n":
            return None
        return text[:start] + cut.replacement + "\n\n" + text[end:]
    newline = text.find("\n", end)
    stop = len(text) if newline < 0 else newline
    if cut.needs_apache and (
        not apache_available or apache_body_digest(text[start:stop]) != APACHE_BODY_SHA256
    ):
        return None
    return text[:start] + cut.replacement + text[stop:]


# The Apache License 2.0. Its body (from the heading of the terms to the last
# sentence of section 9) is the same word for word in every copy found in the
# installed packages (cryptography, requests, python-multipart,
# websocket-client, PyInstaller, pyinstaller-hooks-contrib; checked 2026-11-28);
# the digest is that of the body with whitespace collapsed. The headers
# ("https" or "http") and the appendix differ, which is why only the body counts.
_APACHE_BODY_START = "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION"
_APACHE_BODY_END = "accepting any such warranty or additional liability."
APACHE_BODY_SHA256 = "efc42672d5e2255417ab2bbcef2a39e8400f0ab6d32f4c790d95a3640087923c"
APACHE_TITLE = "Apache License, Version 2.0"
APACHE_POINTER = (
    "The Apache License, Version 2.0. Its text is printed once, under\n"
    f"\"{SHARED_TEXTS_TITLE}\"."
)
# What counts as a copyright line: "Copyright" followed by (c), the copyright
# sign or a year, a line that begins with "(c) <year>" or "©", or "All rights
# reserved". A sentence such as "The above copyright notice ..." does not.
_COPYRIGHT_LINE = re.compile(
    r"copyright\s*(?:\(c\)|©|\d)|^\W*(?:\(c\)|©)\s*\d|all rights reserved", re.IGNORECASE
)
# A text shorter than this (in characters, whitespace collapsed, copyright
# lines removed) is not worth pointing at.
_MIN_SHARED_TERMS = 200


def apache_body_digest(text: str) -> str | None:
    """Digest of the body of the Apache License 2.0 found in *text*; None when there is none."""
    start = text.find(_APACHE_BODY_START)
    if start < 0:
        return None
    end = text.find(_APACHE_BODY_END, start)
    if end < 0:
        return None
    body = _squash(text[start : end + len(_APACHE_BODY_END)])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def is_apache_license_file(text: str) -> bool:
    """A whole license file of the Apache License 2.0 with the standard body."""
    return text.lstrip().startswith("Apache License") and (
        apache_body_digest(text) == APACHE_BODY_SHA256
    )


def copyright_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.split("\n") if _COPYRIGHT_LINE.search(line)]


def shrink_apache(text: str, standard_lines: set[str]) -> str:
    """What stays of an Apache License file: a pointer, and the lines about copyright it adds.

    *standard_lines* are the stripped lines of the standard text; a line with
    "copyright" in it that is not one of them (a copyright notice at the end,
    for example) is kept.
    """
    extra = [
        line.rstrip()
        for line in text.split("\n")
        if "copyright" in line.lower() and line.strip() not in standard_lines
    ]
    return "\n".join([APACHE_POINTER, *extra])


def terms_digest(text: str) -> tuple[str, list[str]] | None:
    """``(digest, copyright lines)`` of a license text, or None when it takes no part.

    The digest is that of the text without its copyright lines, whitespace
    collapsed: two texts with the same digest differ only in who holds the
    copyright. None for a text without a copyright line, or with so little
    left that sharing it would save nothing.
    """
    lines = text.split("\n")
    notices = [line for line in lines if _COPYRIGHT_LINE.search(line)]
    if not notices:
        return None
    body = _squash(" ".join(line for line in lines if not _COPYRIGHT_LINE.search(line)))
    if len(body) < _MIN_SHARED_TERMS:
        return None
    return hashlib.sha256(body.encode("utf-8")).hexdigest(), [n.rstrip() for n in notices]


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
    # No text of its own on purpose: the license text is printed under other
    # components, and missing_message says so (no warning is due for it).
    text_elsewhere: bool = False

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


class ArchivedLicenseError(Exception):
    """An archived license text that a package needs cannot be used."""


def archived_license_for(
    canonical_name: str,
    archived: Mapping[str, ArchivedLicense] | None = None,
    root: Path | None = None,
) -> tuple[LicenseText, str] | None:
    """The archived license text of a package and the note that explains it.

    None when nothing is archived for *canonical_name*. Fails loudly (like the
    upstream notice) when the archived file is missing, unreadable, empty or
    not clean UTF-8: a notices file that quietly drops a text it promises, or
    carries a garbled one, is worse than a failed build. *archived* and *root*
    default to ARCHIVED_LICENSES and the repository root.
    """
    archived = ARCHIVED_LICENSES if archived is None else archived
    entry = archived.get(canonical_name)
    if entry is None:
        return None
    path = (REPO_ROOT if root is None else root) / entry.file
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ArchivedLicenseError(f"cannot read the archived license {path}: {exc}") from exc
    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ArchivedLicenseError(
            f"the archived license {path} is not valid UTF-8 ({exc.reason})"
        ) from exc
    text = _normalise_text(raw)
    if not text.strip():
        raise ArchivedLicenseError(f"the archived license {path} is empty")
    if "\0" in text:
        raise ArchivedLicenseError(
            f"the archived license {path} contains NUL characters (UTF-16?); save it as UTF-8"
        )
    note = (
        "The wheel of this package ships no license file. The text below is the\n"
        f"license of its source project ({entry.project}, {entry.ref}), copied word\n"
        "for word from:\n"
        f"{entry.source_url}"
    )
    return LicenseText(f"{entry.project} license ({entry.ref})", text), note


def collect_packages(
    project: str = PROJECT,
    extras: tuple[str, ...] = SHIPPED_EXTRAS,
    build_tools: tuple[str, ...] = EMBEDDED_BUILD_TOOLS,
    archived: Mapping[str, ArchivedLicense] | None = None,
    archive_root: Path | None = None,
    packed: Mapping[str, tuple[str, ...]] | None = None,
) -> list[Package]:
    """The installed packages that ship, with their license texts.

    *packed* (default PACKED_LICENSE_FILES) says which license files of a
    package are kept; see packed_license_texts().
    """
    packages = [
        Package(
            name=dist.metadata["Name"],
            version=dist.version,
            declaration=declaration_of(dist),
            texts=packed_license_texts(
                str(canonicalize_name(dist.metadata["Name"])), license_texts_of(dist), packed
            ),
        )
        for dist in collect_distributions(project, extras, build_tools)
    ]
    for package in packages:
        if package.texts:
            continue  # the wheel's own text always wins
        fallback = archived_license_for(package.canonical_name, archived, archive_root)
        if fallback is not None:
            package.texts = [fallback[0]]
            package.note = fallback[1]
    packages.sort(key=lambda package: package.canonical_name)
    return packages


def collect_libffi(platform: str, root: Path | None = None) -> Package | None:
    """The libffi of *platform*'s Python (sys.platform value), with its archived license text.

    None for a platform that has no entry of its own (Linux: its libffi.so is
    listed in the system libraries section). Fails like archived_license_for()
    when the archived file cannot be used.
    """
    entry = LIBFFI_LICENSES.get(platform)
    if entry is None:
        return None
    found = archived_license_for("libffi", {"libffi": entry}, root)
    assert found is not None  # the mapping above always has the key
    return Package(
        name=LIBFFI_NAME,
        version=LIBFFI_VERSION_LABEL,
        declaration="MIT",
        texts=[found[0]],
        note=LIBFFI_NOTES[platform],
    )


def collect_python_components(platform: str, root: Path | None = None) -> list[Package]:
    """The third-party components inside *platform*'s CPython, with their archived texts.

    One package per entry of PYTHON_BUNDLED_LICENSES[*platform*] (sys.platform
    value; none for a platform without an entry). Fails like archived_license_for()
    when an archived file cannot be used.
    """
    packages = []
    for component in PYTHON_BUNDLED_LICENSES.get(platform, []):
        texts = []
        for entry in component.licenses:
            found = archived_license_for("component", {"component": entry}, root)
            assert found is not None  # the mapping above always has the key
            texts.append(found[0])
        url = component.license.source_url if component.license is not None else ""
        packages.append(
            Package(
                name=component.name,
                version=component.version_label,
                declaration=component.declaration,
                texts=texts,
                note=component.note.format(url=url),
                text_elsewhere=component.license is None,
                missing_message=(
                    "The license text (the Apache License 2.0) is printed once under\n"
                    f"\"{SHARED_TEXTS_TITLE}\" in this file."
                    if component.license is None
                    else ""
                ),
            )
        )
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
    "/usr/share/doc/<package>/copyright. In a copyright file in Debian's\n"
    "machine-readable format, the paragraphs about the Debian packaging and about\n"
    "files that are not part of the libraries (documentation, tests, examples,\n"
    "translations, build scripts) are left out, and a license text that an earlier\n"
    "copyright file already has is not repeated. Those files may refer to the\n"
    "standard license texts that a Debian system keeps under\n"
    "/usr/share/common-licenses instead of reproducing them; the texts they refer\n"
    "to follow the packages, under \"Referenced license texts\"."
)
REFERENCED_LICENSES_TITLE = "Referenced license texts"
REFERENCED_LICENSES_NOTE = (
    "The copyright files above refer to these license texts, which a Debian\n"
    "system keeps under /usr/share/common-licenses. They are copied from the\n"
    "machine that built the application."
)
NOTHING_LEFT = (
    "The copyright file at {path} covers only the Debian packaging and files\n"
    "that are not part of the compiled library (documentation, tests, examples,\n"
    "translations, build scripts); nothing of it is reproduced here."
)
SOURCE_UNKNOWN = "dpkg-query could not be used on the build machine"
OS_RELEASE = Path("/etc/os-release")
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
    # The text as printed (see trim_debian_copyright()); None when the file
    # does not exist.
    copyright_text: str | None
    # The file is in the Debian machine-readable format and no section about
    # files is left after the trimming: everything it covers is packaging,
    # documentation, tests or build scripts.
    nothing_left: bool = False


@dataclass(frozen=True)
class SourcePackage:
    """A Debian source package that a copyleft system library is built from."""

    name: str
    version: str | None  # None when dpkg-query could not say
    packages: tuple[str, ...]  # the binary packages of it that own packed libraries


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
    # Source packages of the packages whose copyright files name the GPL, the
    # LGPL or the MPL, sorted by name (see where the source code is below).
    copyleft_sources: list[SourcePackage] = field(default_factory=list)
    # The distribution of the build machine from /etc/os-release, e.g.
    # "Ubuntu 22.04 LTS (jammy)", and its id ("ubuntu"); empty when unknown.
    distribution: str = ""
    distribution_id: str = ""


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


# --- trimming a Debian copyright file to what the binaries need -------------
# Debian's machine-readable copyright files (DEP-5, first line "Format:") are
# made of paragraphs separated by blank lines. A "Files:" paragraph says which
# files it covers. Of those that matter for the libraries that are copied into
# the build, the paragraphs about the packaging itself (debian/*) and about
# files that are not part of the compiled library (documentation, tests,
# examples, translations, build scripts) are left out, as are repeats of a
# license text that an earlier paragraph already has. A paragraph is left out
# only when every one of its file patterns is of that kind; one pattern that is
# not (or cannot be told) keeps the whole paragraph. A file in another format
# is never changed.
_DEP5_FIRST_LINE = "Format:"
_IN_NO_BINARY = re.compile(
    r"(?:^|/)(?:doc|docs|test|tests|testsuite|examples?|demos?|po|m4|man)(?:/|$)"
    r"|(?:^|/)(?:config\.guess|config\.sub|install-sh|ltmain\.sh|missing|compile|depcomp"
    r"|ylwrap|aclocal\.m4|configure|INSTALL)$"
    r"|(?:^|/)Makefile[^/]*$"
    r"|\.(?:am|in|m4)$",
    re.IGNORECASE,
)
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")
# A license paragraph that repeats an earlier one is pointed at only when its
# text is at least this long (whitespace collapsed): a pointer costs about 150
# characters.
_MIN_REPEATED_LICENSE = 400


def _field_value(paragraph: str, field_name: str) -> str | None:
    """The value of a field of a DEP-5 paragraph (continuation lines joined by newlines).

    None when the paragraph has no such field; the name is matched without
    regard to case, at the start of a line only.
    """
    lines = paragraph.split("\n")
    prefix = f"{field_name.lower()}:"
    for position, line in enumerate(lines):
        if line.lower().startswith(prefix):
            value = [line[len(prefix) :].strip()]
            for following in lines[position + 1 :]:
                if following[:1] not in (" ", "\t"):
                    break
                value.append(following.strip())
            return "\n".join(value)
    return None


def _is_dep5(text: str) -> bool:
    return text.split("\n", 1)[0].startswith(_DEP5_FIRST_LINE)


def _only_for_the_packaging_or_non_binaries(patterns: Sequence[str]) -> bool:
    return bool(patterns) and all(
        pattern == "debian" or pattern.startswith("debian/") or _IN_NO_BINARY.search(pattern)
        for pattern in patterns
    )


def _license_names(value: str) -> list[str]:
    """The names a License field value stands for: the first line, split at "or" / "and" / commas."""
    first = value.split("\n", 1)[0].strip()
    parts = [part.strip() for part in re.split(r"\s+(?:or|and)\s+|,\s*", first)]
    return [name for name in [first, *parts] if name]


def trim_debian_copyright(text: str) -> tuple[str, bool]:
    """*text* without the paragraphs of a DEP-5 file that do not concern the binaries.

    Returns ``(text, nothing_left)``; the second is true when the file had
    "Files:" paragraphs and none of them is left. A text that is not DEP-5, or
    from which nothing is taken out, is returned as it is. A left-out paragraph
    that holds the only full text of a license that a paragraph that stays names
    (Debian writes a license's text once, in the first paragraph that uses it)
    is put back.
    """
    if not _is_dep5(text):
        return text, False
    paragraphs = _PARAGRAPH_BREAK.split(text)
    files = [_field_value(paragraph, "Files") for paragraph in paragraphs]
    licenses = [_field_value(paragraph, "License") for paragraph in paragraphs]
    keep = [
        patterns is None or not _only_for_the_packaging_or_non_binaries(patterns.split())
        for patterns in files
    ]
    while True:
        wanted: set[str] = set()
        provided: set[str] = set()
        for index, value in enumerate(licenses):
            if value is None or not keep[index]:
                continue
            if "\n" in value:
                provided.update(_license_names(value))
            else:
                wanted.update(_license_names(value)[1:] or _license_names(value))
        restored = False
        for index, value in enumerate(licenses):
            if keep[index] or value is None or "\n" not in value:
                continue
            if wanted - provided and (set(_license_names(value)) & (wanted - provided)):
                keep[index] = True
                restored = True
                break
        if not restored:
            break
    if all(keep):
        return text, False
    kept = [paragraph for paragraph, stays in zip(paragraphs, keep) if stays]
    nothing_left = any(value is not None for value in files) and not any(
        value is not None for value, stays in zip(files, keep) if stays
    )
    return "\n\n".join(kept), nothing_left


def point_at_repeated_licenses(
    text: str, owner: str, seen: dict[str, tuple[str, str]]
) -> str:
    """*text* with each license paragraph that repeats an earlier one replaced by a pointer.

    Only a DEP-5 file's stand-alone license paragraphs (a ``License:`` field
    and no ``Files:``) count, and only when the text after the first line is at
    least _MIN_REPEATED_LICENSE characters. *seen* maps the digest of such a
    text (whitespace collapsed) to ``(license name, package)`` of the paragraph
    that holds it; paragraphs that are kept are added to it. *owner* is the
    Debian package of *text*.
    """
    if not _is_dep5(text):
        return text
    paragraphs = _PARAGRAPH_BREAK.split(text)
    changed = False
    for index, paragraph in enumerate(paragraphs):
        value = _field_value(paragraph, "License")
        if value is None or "\n" not in value or _field_value(paragraph, "Files") is not None:
            continue
        name, _, body = value.partition("\n")
        wording = _squash(body)
        if len(wording) < _MIN_REPEATED_LICENSE:
            continue
        digest = hashlib.sha256(wording.encode("utf-8")).hexdigest()
        earlier = seen.get(digest)
        if earlier is None:
            seen[digest] = (name, owner)
            continue
        other_name, other_owner = earlier
        where = "above" if other_owner == owner else f"in the copyright file of {other_owner}, above"
        paragraphs[index] = (
            f"License: {name}\n"
            f" The text of this license is word for word the one of \"{other_name}\", {where}."
        )
        changed = True
    return "\n\n".join(paragraphs) if changed else text


_COPYLEFT_NAME = re.compile(r"\b(?:A|L)?GPL|\bMPL|General Public License|Mozilla Public License")


def names_a_copyleft_license(text: str) -> bool:
    """Whether a copyright text mentions the GPL, LGPL, AGPL or MPL (by name or by their texts).

    Deliberately wide: a library listed for source code that did not need it
    does no harm, one that is left out would be missed.
    """
    return _COPYLEFT_NAME.search(text) is not None


def read_os_release(path: Path | None = None) -> tuple[str, str]:
    """``(description, id)`` of the build machine's distribution, e.g. ``("Ubuntu 22.04 LTS (jammy)", "ubuntu")``.

    Empty strings when /etc/os-release cannot be read.
    """
    try:
        raw = (OS_RELEASE if path is None else path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    values: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if separator and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("\"'")
    name = values.get("NAME", "")
    version = values.get("VERSION_ID", "")
    codename = values.get("VERSION_CODENAME", "")
    description = " ".join(part for part in (name, version) if part)
    if codename:
        description += f" ({codename})" if description else codename
    return description, values.get("ID", "")


def dpkg_sources(
    names: Sequence[str], run: Runner = subprocess.run
) -> dict[str, tuple[str, str]]:
    """``dpkg-query``: binary package -> (source package, source version) for each of *names*.

    Packages dpkg-query does not know are absent. Raises DpkgUnavailable when
    dpkg-query cannot be run or fails in some other way than for unknown names.
    """
    found: dict[str, tuple[str, str]] = {}
    unique = sorted(set(names))
    for start in range(0, len(unique), _DPKG_BATCH):
        batch = unique[start : start + _DPKG_BATCH]
        try:
            done = run(
                [
                    "dpkg-query",
                    "-W",
                    "-f",
                    "${Package}\t${source:Package}\t${source:Version}\n",
                    *batch,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "LC_ALL": "C"},
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DpkgUnavailable(f"dpkg-query could not be run: {exc}") from exc
        if done.returncode not in (0, 1):
            raise DpkgUnavailable(f"dpkg-query exited with status {done.returncode}")
        for line in (done.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and all(parts):
                found.setdefault(parts[0], (parts[1], parts[2]))
    return found


def read_common_license(name: str, licenses_root: Path) -> ReferencedLicense:
    """The standard license text called *name*; its text is None when it cannot be read.

    A name that is not a plain file name is never looked up, whatever the
    caller passes. Debian's own copyright files sometimes spell the name with a
    trailing ``.0`` that the file does not have (``GPL-2.0`` for ``GPL-2``), so
    when *name* is missing the name without that ``.0`` is tried; the result
    then points at the file that was read.
    """
    root = licenses_root.as_posix().rstrip("/")
    if not _COMMON_LICENSE_FULL_NAME.fullmatch(name):
        return ReferencedLicense(name, f"{root}/{name}", None)
    candidates = [name]
    if name.endswith(".0") and len(name) > 2:
        candidates.append(name[:-2])
    for candidate in candidates:
        try:
            text = _normalise_text((licenses_root / candidate).read_bytes())
        except OSError:
            continue
        return ReferencedLicense(name, f"{root}/{candidate}", text or None)
    return ReferencedLicense(name, f"{root}/{name}", None)


def collect_system_libraries(
    analyses: Mapping[str, Sequence[analysis.TocEntry]],
    *,
    roots: Sequence[str] | None = None,
    run: Runner = subprocess.run,
    realpath: Callable[[str], str] = os.path.realpath,
    doc_root: Path | None = None,
    licenses_root: Path | None = None,
    os_release: Path | None = None,
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
    # Trimmed text -> the text of the first package that had it, as it is printed.
    # A package whose trimmed text is the same as an earlier one gets exactly
    # that text, so render_system_libraries() points at the earlier file as a
    # whole; only the other texts have their repeated license paragraphs replaced.
    finals: dict[str, str] = {}
    licenses_seen: dict[str, tuple[str, str]] = {}
    for package in sorted(by_package):
        copyright_path, text = read_debian_copyright(package, doc_root)
        nothing_left = False
        if text is not None:
            text, nothing_left = trim_debian_copyright(text)
            if text in finals:
                text = finals[text]
            else:
                finals[text] = point_at_repeated_licenses(text, package, licenses_seen)
                text = finals[text]
        packages.append(
            DebianPackage(package, by_package[package], copyright_path, text, nothing_left)
        )

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

    # The copyleft packages and the source packages they are built from. The
    # version comes from the package database of the build machine, never from
    # a guess: when dpkg-query cannot answer, the package is listed without one.
    copyleft = sorted(
        package.name
        for package in packages
        if package.copyright_text and names_a_copyleft_license(package.copyright_text)
    )
    sources: list[SourcePackage] = []
    if copyleft and not problem:
        try:
            known = dpkg_sources(copyleft, run)
        except DpkgUnavailable:
            known = {}
        grouped: dict[tuple[str, str | None], list[str]] = {}
        for name in copyleft:
            source = known.get(name)
            key = (source[0], source[1]) if source else (name, None)
            grouped.setdefault(key, []).append(name)
        sources = [
            SourcePackage(source, version, tuple(names))
            for (source, version), names in sorted(
                grouped.items(), key=lambda item: (item[0][0], item[0][1] or "")
            )
        ]
    distribution, distribution_id = read_os_release(os_release)
    return SystemLibraries(
        libraries, packages, problem, licenses, sources, distribution, distribution_id
    )


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
    system: SystemLibraries,
    printed: dict[str, str] | None = None,
    apache_printed: bool = False,
) -> list[str]:
    """The lines of the "System libraries bundled on Linux" section.

    *printed* maps the digest of a license text that appears earlier in the
    file to where. A copyright file or referenced license text with the same
    digest is not repeated (binary packages built from one source often ship
    the same copyright file). The texts printed here are added to it.
    *apache_printed* says that the file prints the Apache License 2.0 once under
    "Shared license texts"; a referenced license text that is that license (the
    same body, whatever the header) points there instead of being repeated.
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
            if package.nothing_left:
                lines.extend(["", NOTHING_LEFT.format(path=package.copyright_path)])
    if system.licenses:
        lines.extend(
            ["", _THIN_RULE, REFERENCED_LICENSES_TITLE, _THIN_RULE, REFERENCED_LICENSES_NOTE]
        )
        for referenced in system.licenses:
            lines.append("")
            if referenced.text is None:
                lines.append(f"Not found at {referenced.path}.")
            elif apache_printed and is_apache_license_file(referenced.text):
                lines.append(
                    f"--- {referenced.path} (the Apache License, Version 2.0, printed once "
                    f"under \"{SHARED_TEXTS_TITLE}\", above) ---"
                )
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


class SharedLicenseError(Exception):
    """A text that the file prints once, in its shared section, is not available."""


def check_shared_texts(packages: Iterable[Package], text: str) -> None:
    """Raise SharedLicenseError when a component points at a shared text that *text* lacks.

    Only the Apache License 2.0 is shared on request of a component (OpenSSL,
    see PythonComponent.license); the section is written when some component
    ships the license file (see find_shared_apache_text()).
    """
    for package in packages:
        if package.text_elsewhere and f"\n--- {APACHE_TITLE} ---\n" not in text:
            raise SharedLicenseError(
                f"{package.title} refers to the Apache License 2.0 under "
                f"'{SHARED_TEXTS_TITLE}', but no component of this file carries that text"
            )


def find_shared_apache_text(packages: Iterable[Package]) -> str | None:
    """The Apache License 2.0 text that is printed once: a real file of a component.

    The first license file (in component order) with the standard body, a
    file without copyright lines of its own preferred, so that the shared text
    carries nobody's notice. None when no component ships such a file.
    """
    found = [
        text.text for package in packages for text in package.texts if is_apache_license_file(text.text)
    ]
    for candidate in found:
        if not copyright_lines(candidate):
            return candidate
    return found[0] if found else None


def apply_text_cuts(
    package: Package, license_text: LicenseText, apache_available: bool
) -> tuple[str, bool]:
    """The text of *license_text* as it is printed, and whether a cut pointed to the Apache text.

    Applies the cuts of TEXT_CUTS for the package. A cut whose points cannot be
    found, or whose Apache text is not the standard one, is not applied: the
    text stays whole and a warning says which file it was.
    """
    text = license_text.text
    used_apache = False
    for cut in TEXT_CUTS.get(package.canonical_name, ()):
        cut_text = apply_cut(text, cut, apache_available)
        if cut_text is None:
            _warn(
                f"cannot find the cut points ({cut.start.splitlines()[0]!r} ...) in "
                f"{license_text.name} of {package.title}; the file is printed whole"
            )
            continue
        text = cut_text
        used_apache = used_apache or cut.needs_apache
    return text, used_apache


# --- Rust crates linked into Python wheels ---------------------------------
# cryptography, pydantic_core and rpds-py are compiled from Rust, and their
# extension modules contain the crates they depend on. Each wheel lists those
# crates in a CycloneDX file under <dist-info>/sboms/, which is the list of what
# was really built into it. The licenses of the crates (which license of a
# dual-licensed crate is used, the copyright lines, the license text that has to
# travel with a binary) are researched once and kept in
# docs/legal/third-party/rust-crates.json, with the texts next to it; see that
# file for the evidence. A crate that is in a wheel's SBOM but not in the file
# stops the build: it is new (a wheel was upgraded) and needs the same research.
RUST_CRATES_FILE = f"{THIRD_PARTY_LICENSE_DIR}/rust-crates.json"
RUST_CRATES_TITLE = "Rust crates built into Python packages"
RUST_CRATES_NOTE = (
    "Some of the Python packages above are compiled from Rust and contain the\n"
    "Rust libraries (crates) listed here, each of which comes with its own\n"
    "license. The list is taken from the bill of materials (SBOM) that each of\n"
    "those packages carries. Crates that are used only while the package is\n"
    "compiled (procedural macros and the code that runs only inside them, build\n"
    "scripts) are not part of the program and are not listed."
)
_RUST_OBLIGATIONS = ("none", "shared-apache", "text", "source-offer")
_CARGO_PURL = re.compile(r"^pkg:cargo/([^@/?#]+)@([^?#]+)")
_GENERIC_PURL = re.compile(r"^pkg:generic/([^@/?#]+)@([^?#]+)")


class RustCratesError(Exception):
    """The Rust crates of the installed wheels cannot be matched with the license data."""


@dataclass(frozen=True)
class RustCrate:
    """A Rust crate in the SBOM of an installed wheel that has to be mentioned."""

    name: str
    version: str
    wheels: tuple[str, ...]  # the packages whose SBOM lists it
    obligation: str  # "shared-apache", "text" or "source-offer"
    chosen: str  # the license it is used under
    copyright_lines: tuple[str, ...] = ()
    text: str | None = None  # the license text to print, for obligation "text"
    notice: str | None = None  # NOTICE file of an Apache-2.0 crate
    copyright_note: str = ""  # where the copyright lines come from, when not from the text
    source_url: str = ""
    # What a non-crate component (SBOM purl "pkg:generic/...") is for; empty for crates.
    role: str = ""

    @property
    def title(self) -> str:
        return f"{self.name} {self.version}"

    @property
    def needs_apache(self) -> bool:
        return self.obligation == "shared-apache"


def load_rust_crate_data(root: Path | None = None) -> dict[tuple[str, str], dict]:
    """The researched crate entries, by (name, version); the license texts are read into them.

    Each entry with a ``license_text_file`` gets a ``text`` key. A text whose
    sha256 differs from the one in the file's ``texts`` table, a missing text,
    a bad obligation or a file that is not valid JSON raises RustCratesError.
    """
    base = REPO_ROOT if root is None else root
    path = base / RUST_CRATES_FILE
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
        crates = document["crates"]
        texts = document["texts"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RustCratesError(f"cannot read the Rust crate license data {path}: {exc}") from exc
    loaded: dict[str, str] = {}
    for file_name, pinned in texts.items():
        text_path = path.parent / file_name
        try:
            raw = text_path.read_bytes()
            raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RustCratesError(f"cannot read the crate license text {text_path}: {exc}") from exc
        if hashlib.sha256(raw).hexdigest() != pinned["sha256"]:
            raise RustCratesError(
                f"{text_path} does not match the sha256 recorded in {RUST_CRATES_FILE}"
            )
        loaded[file_name] = _normalise_text(raw)
    entries: dict[tuple[str, str], dict] = {}
    for entry in crates:
        key = (entry["name"], entry["version"])
        if entry.get("obligation") not in _RUST_OBLIGATIONS:
            raise RustCratesError(f"{key[0]} {key[1]} in {RUST_CRATES_FILE} has no valid obligation")
        entry = dict(entry)
        file_name = entry.get("license_text_file")
        if entry["obligation"] == "text":
            if file_name not in loaded:
                raise RustCratesError(
                    f"{key[0]} {key[1]} in {RUST_CRATES_FILE} needs a license text that is not "
                    "in its 'texts' table"
                )
            entry["text"] = loaded[file_name]
        entries[key] = entry
    return entries


def _sbom_purls(dist: metadata.Distribution) -> list[str]:
    """The package URLs of all components in the ``sboms/*.json`` files of *dist*."""
    purls: list[str] = []
    for file in dist.files or ():
        if file.parent.name != "sboms" or file.suffix != ".json":
            continue
        try:
            document = json.loads(Path(str(dist.locate_file(file))).read_bytes().decode("utf-8"))
            components = document.get("components", [])
        except (OSError, ValueError, AttributeError) as exc:
            raise RustCratesError(f"cannot read the SBOM {file} of {dist.metadata['Name']}: {exc}")
        purls.extend(str(component.get("purl", "")) for component in components)
    return purls


def sbom_rust_crates(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """``(name, version)`` of the Rust crates in the SBOM files of *dist*, sorted.

    Takes the components whose package URL is ``pkg:cargo/<name>@<version>``.
    """
    found = {m.groups() for m in map(_CARGO_PURL.match, _sbom_purls(dist)) if m}
    return sorted(found)


def sbom_generic_components(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """``(name, version)`` of the ``pkg:generic/`` components of the SBOMs of *dist*, sorted.

    These are libraries other than crates that a wheel links in statically (the
    OpenSSL of the cryptography wheel); see "generic_components" in
    docs/legal/third-party/rust-crates.json.
    """
    found = {m.groups() for m in map(_GENERIC_PURL.match, _sbom_purls(dist)) if m}
    return sorted(found)


def load_generic_components(root: Path | None = None) -> dict[tuple[str, str], dict]:
    """The researched non-crate components of the data file, by (name, version)."""
    path = (REPO_ROOT if root is None else root) / RUST_CRATES_FILE
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
        entries = {(e["name"], e["version"]): e for e in document["generic_components"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RustCratesError(f"cannot read the generic components of {path}: {exc}") from exc
    for key, entry in entries.items():
        if entry.get("obligation") not in ("none", "shared-apache") or not entry.get("role"):
            raise RustCratesError(f"{key[0]} {key[1]} in {RUST_CRATES_FILE} is not usable")
    return entries

def collect_rust_crates(
    dists: Iterable[metadata.Distribution], root: Path | None = None
) -> list[RustCrate]:
    """The Rust crates of *dists* that the notices have to mention, sorted by name and version.

    A crate that needs nothing (a license without duties for binaries, or one
    that is only used at build time) is left out. A crate of an SBOM that the
    data file does not know raises RustCratesError saying so.
    """
    dists = list(dists)
    wheels: dict[tuple[str, str], list[str]] = {}
    generic_wheels: dict[tuple[str, str], list[str]] = {}
    for dist in dists:
        for key in sbom_rust_crates(dist):
            wheels.setdefault(key, []).append(dist.metadata["Name"])
        for key in sbom_generic_components(dist):
            generic_wheels.setdefault(key, []).append(dist.metadata["Name"])
    if not wheels and not generic_wheels:
        return []
    generic = load_generic_components(root) if generic_wheels else {}
    unknown_generic = sorted(key for key in generic_wheels if key not in generic)
    if unknown_generic:
        listed = ", ".join(
            f"{name} {version} ({'/'.join(generic_wheels[(name, version)])})"
            for name, version in unknown_generic
        )
        raise RustCratesError(
            f"{len(unknown_generic)} non-crate component(s) (pkg:generic) in the SBOM of an "
            f"installed wheel are not in \"generic_components\" of {RUST_CRATES_FILE}: {listed}. "
            "A wheel was probably upgraded: find out its license, whether the upstream project "
            "ships a NOTICE file, and add it to that table."
        )
    data = load_rust_crate_data(root) if wheels else {}
    unknown = sorted(key for key in wheels if key not in data)
    if unknown:
        listed = ", ".join(f"{name} {version} ({'/'.join(wheels[(name, version)])})"
                           for name, version in unknown)
        raise RustCratesError(
            f"{len(unknown)} Rust crate(s) in the SBOM of an installed wheel are not in "
            f"{RUST_CRATES_FILE}: {listed}. A wheel was probably upgraded: research the "
            "license of each new crate (which license applies, copyright lines, the license "
            "text, a NOTICE file) and add it to that file together with its text."
        )
    crates = []
    for key in sorted(generic_wheels):
        entry = generic[key]
        if entry["obligation"] == "none":
            continue
        crates.append(
            RustCrate(
                name=key[0],
                version=key[1],
                wheels=tuple(sorted(set(generic_wheels[key]))),
                obligation=entry["obligation"],
                chosen=entry.get("chosen", ""),
                notice=entry.get("notice"),
                source_url=entry.get("source_url", ""),
                role=entry["role"],
            )
        )
    for key in sorted(wheels):
        entry = data[key]
        if entry["obligation"] == "none":
            continue
        crates.append(
            RustCrate(
                name=key[0],
                version=key[1],
                wheels=tuple(sorted(set(wheels[key]))),
                obligation=entry["obligation"],
                chosen=entry.get("chosen", ""),
                copyright_lines=tuple(entry.get("copyright_lines", ())),
                text=entry.get("text"),
                notice=entry.get("notice"),
                copyright_note=entry.get("copyright_note", ""),
                source_url=entry.get("source_url", ""),
            )
        )
    return crates


def _wrap_list(items: Sequence[str]) -> list[str]:
    return textwrap.wrap(", ".join(items), width=78, break_long_words=False, break_on_hyphens=False)


def _crate_label(crate: RustCrate) -> str:
    return f"{crate.title} ({'/'.join(crate.wheels)})"


def render_rust_crates(
    crates: Sequence[RustCrate], printed: dict[str, str], terms_printed: dict[str, str]
) -> list[str]:
    """The lines of the Rust crates section; *printed* and *terms_printed* as in render()."""
    lines = ["", _RULE, RUST_CRATES_TITLE, _RULE, RUST_CRATES_NOTE]
    apache = [crate for crate in crates if crate.needs_apache]
    if apache:
        lines.extend(
            [
                "",
                _THIN_RULE,
                f"Crates used under the Apache License 2.0 ({len(apache)})",
                _THIN_RULE,
                "These crates are licensed under the Apache License 2.0 (alone, or as one of\n"
                "two or three licenses to choose from, in which case this is the one used).\n"
                f"Its text is printed once, under \"{SHARED_TEXTS_TITLE}\".",
            ]
        )
        for wheel in sorted({wheel for crate in apache for wheel in crate.wheels}):
            lines.extend(["", f"In {wheel}:"])
            lines.extend(
                _wrap_list([crate.title for crate in apache if wheel in crate.wheels])
            )
        others = [crate for crate in apache if crate.role]
        for crate in others:
            lines.extend(
                ["", f"{_crate_label(crate)}: {crate.role}. License: {crate.chosen}, see above."]
            )
        for crate in apache:
            if crate.notice:
                lines.extend(["", f"NOTICE of {crate.title}:", crate.notice])
    # Crates that print the same license text, copyright lines included, are
    # shown under one heading; the text of a heading is printed only when no
    # earlier text has the same wording (render() decides, see _append_deduplicated).
    groups: dict[tuple[str, tuple[str, ...], str], list[RustCrate]] = {}
    for crate in crates:
        if crate.obligation != "text" or crate.text is None:
            continue
        # Copyright lines that the text does not carry (its file has none, or
        # the name was taken from elsewhere) are printed above it.
        missing = tuple(line for line in crate.copyright_lines if line not in crate.text)
        note = crate.copyright_note if missing else ""
        groups.setdefault((crate.text, missing, note), []).append(crate)
    for (text, missing, note), members in groups.items():
        lines.extend(["", _THIN_RULE])
        lines.extend(_wrap_list([_crate_label(member) for member in members]))
        lines.append(_THIN_RULE)
        for line in missing:
            lines.append(f"Copyright: {line}")
        if missing and note:
            lines.append(f"({note}.)")
        if missing:
            lines.append("")
        first = members[0]
        _append_deduplicated(
            lines,
            f"license text of {first.title}",
            text,
            f"the license text of {first.title}, above",
            printed,
            terms_printed,
        )
    return lines


# --- where the source code of copyleft components is ----------------------
# GPL-3.0 section 6, LGPL-3.0 section 4(d) and MPL-2.0 section 3.2 want the
# source code, or where to get it, to go along with the binaries. What is
# listed comes from the installed metadata (name and version), not from
# numbers written here. Qt's version is the one of its wheel (PyQt6-Qt6 6.12.1
# carries Qt 6.12.1); Qt WebEngine's is the one of its wheel (6.140.0). The
# addresses were checked on 2026-11-28 against the releases of this build.
COPYLEFT_TITLE = "Source code of copyleft components"
COPYLEFT_NOTE = (
    "Some components of this program are under licenses that call for their source\n"
    "code to be available to the recipients of the program. For the versions that\n"
    "are part of this package it can be downloaded from the addresses below."
)
_PYPI_FILES = "https://files.pythonhosted.org/packages/source"


def _pypi_source(package: Package) -> list[str]:
    archive = f"{package.canonical_name.replace('-', '_')}-{package.version}.tar.gz"
    return [
        "Source distribution on PyPI:",
        f"{_PYPI_FILES}/{package.name[0]}/{package.name}/{archive}",
    ]


def _qt_source(package: Package) -> list[str]:
    series = ".".join(package.version.split(".")[:2])
    base = f"https://download.qt.io/archive/qt/{series}/{package.version}"
    return [
        f"Qt {package.version} source code, as one archive:",
        f"{base}/single/",
        "or one archive per module:",
        f"{base}/submodules/",
    ]


def _qt_webengine_source(package: Package) -> list[str]:
    series = ".".join(package.version.split(".")[:2])
    return [
        f"Qt WebEngine {package.version} source code:",
        f"https://download.qt.io/archive/qtwebengine/{series}/{package.version}/src/",
    ]


COPYLEFT_SOURCES: dict[str, Callable[[Package], list[str]]] = {
    "pyqt6": _pypi_source,
    "pyqt6-webengine": _pypi_source,
    "pyqt6-qt6": _qt_source,
    "pyqt6-webengine-qt6": _qt_webengine_source,
    "certifi": _pypi_source,
}


LINUX_SOURCES_NOTE = (
    "The Linux build carries shared libraries of the build machine (see \"{system}\"). "
    "The libraries of the Debian packages below are under the GNU GPL, LGPL or MPL "
    "(their copyright files name one of them). The source code of each is the source "
    "package (<source>) of the same name and version in the archive of {distribution}. With a "
    "deb-src entry for that archive in the APT sources, it is downloaded with "
    "\"apt-get source <source>=<version>\""
)
_LAUNCHPAD = "https://launchpad.net/ubuntu/+source"


def linux_source_lines(system: SystemLibraries) -> list[str]:
    """Where the source code of the copyleft system libraries is; none when there are none."""
    if system.dpkg_problem:
        return textwrap.wrap(
            "The Debian packages of the system libraries could not be determined "
            f"({system.dpkg_problem}), so the source packages of the copyleft libraries "
            "among them cannot be named here.",
            width=76,
        )
    if not system.copyleft_sources:
        return []
    note = LINUX_SOURCES_NOTE.format(
        system=SYSTEM_LIBRARIES_TITLE,
        distribution=system.distribution or "the Linux distribution of the build machine",
    )
    if system.distribution_id == "ubuntu":
        note += f" or from {_LAUNCHPAD}/<source>/<version>"
    lines = textwrap.wrap(note + ".", width=76, break_long_words=False, break_on_hyphens=False)
    lines.append("")
    for source in system.copyleft_sources:
        binaries = ", ".join(source.packages)
        if source.version is None:
            lines.append(
                f"{source.name} - version unknown ({SOURCE_UNKNOWN}); Debian package(s): {binaries}"
            )
        else:
            lines.append(f"{source.name} {source.version} - Debian package(s): {binaries}")
    return lines


def copyleft_source_lines(
    packages: Iterable[Package],
    system: SystemLibraries | None = None,
    rust_crates: Sequence[RustCrate] = (),
) -> list[str]:
    """The lines of the "Source code of copyleft components" section; none without a component.

    The Python packages come first, then the Rust crates that ask for their
    source to be offered, then the copyleft system libraries of a Linux build.
    """
    entries: list[str] = []
    for package in packages:
        where = COPYLEFT_SOURCES.get(package.canonical_name)
        if where is None:
            continue
        entries.extend(["", f"{package.title} ({package.declaration})"])
        entries.extend(f"  {line}" for line in where(package))
    for crate in rust_crates:
        if crate.obligation == "source-offer":
            entries.extend(["", f"{_crate_label(crate)} ({crate.chosen}), Rust crate", f"  {crate.source_url}"])
    if system is not None and system.libraries:
        linux = linux_source_lines(system)
        if linux:
            entries.extend(["", "System libraries of the Linux build", *(f"  {line}" for line in linux)])
    return [COPYLEFT_NOTE, *entries] if entries else []


def _append_deduplicated(
    lines: list[str],
    label: str,
    text: str,
    here: str,
    printed: dict[str, str],
    terms_printed: dict[str, str],
) -> None:
    """Add a license text under ``--- label ---``, or something shorter when it is already there.

    *printed* maps the digest of each text printed so far to where it is, and
    *terms_printed* the digest of the wording without its copyright lines (see
    terms_digest()); *here* says where this text is, for the entries after it.
    A text that is word for word one printed before becomes a pointer; one that
    differs only in its copyright lines keeps those and points to the wording.
    """
    digest = LicenseText(label, text).digest
    earlier = printed.get(digest)
    if earlier is not None:
        lines.append(f"--- {label} (same text as {earlier}) ---")
        return
    terms = terms_digest(text)
    if terms is not None and terms[0] in terms_printed:
        lines.append(f"--- {label} ---")
        lines.extend(terms[1])
        lines.append("")
        lines.append(
            "[The permission notice and conditions are word for word those of\n"
            f"{terms_printed[terms[0]]}; only the copyright notice differs.]"
        )
        return
    printed[digest] = here
    if terms is not None:
        terms_printed[terms[0]] = here
    lines.append(f"--- {label} ---")
    lines.append(text)


def render(
    packages: list[Package],
    system_libraries: SystemLibraries | None = None,
    upstream_notice: str | None = None,
    rust_crates: Sequence[RustCrate] | None = None,
) -> str:
    """The notices text. *upstream_notice* defaults to read_upstream_notice().

    A notice that is given must not be empty or only whitespace either.
    *rust_crates* (see collect_rust_crates()) adds the section of the Rust
    crates linked into the Python packages.
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
    terms_printed: dict[str, str] = {}
    rust_crates = list(rust_crates or ())
    shared_apache = find_shared_apache_text(packages)
    standard_lines = (
        set() if shared_apache is None else {line.strip() for line in shared_apache.split("\n")}
    )
    apache_used = False
    for package in packages:
        lines.extend(["", _RULE, package.title, _RULE])
        lines.append(f"Declared license: {package.declaration}")
        if package.detail:
            lines.append(f"Interpreter: {package.detail}")
        note = package.note or NOTES.get(package.canonical_name)
        if note:
            lines.extend(["", note])
        if package.text_elsewhere:
            # Its license text is the Apache License, printed in the shared section.
            # (main() refuses to write a file in which the text is missing.)
            apache_used = True
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
            text, cut_apache = apply_text_cuts(package, license_text, shared_apache is not None)
            apache_used = apache_used or cut_apache
            if shared_apache is not None and is_apache_license_file(text):
                apache_used = True
                lines.append(f"--- {license_text.name} ---")
                lines.append(shrink_apache(text, standard_lines))
                continue
            _append_deduplicated(
                lines,
                license_text.name,
                text,
                f"{license_text.name} of {package.title}, above",
                printed,
                terms_printed,
            )
    if rust_crates:
        needs_apache = any(crate.needs_apache for crate in rust_crates)
        if needs_apache and shared_apache is None:
            raise SharedLicenseError(
                "Rust crates are used under the Apache License 2.0, but no component of this "
                "file carries that text to print once"
            )
        lines.extend(render_rust_crates(rust_crates, printed, terms_printed))
        apache_used = apache_used or needs_apache
    if apache_used and shared_apache is not None:
        lines.extend(
            [
                "",
                _RULE,
                SHARED_TEXTS_TITLE,
                _RULE,
                "License texts that several components above refer to are printed here once.",
                "",
                f"--- {APACHE_TITLE} ---",
                shared_apache,
            ]
        )
        printed[LicenseText(APACHE_TITLE, shared_apache).digest] = (
            f"the {APACHE_TITLE} under \"{SHARED_TEXTS_TITLE}\", above"
        )
    source_lines = copyleft_source_lines(packages, system_libraries, rust_crates)
    if source_lines:
        lines.extend(["", _RULE, COPYLEFT_TITLE, _RULE, *source_lines])
    if system_libraries is not None and system_libraries.libraries:
        lines.extend(
            render_system_libraries(
                system_libraries, printed, apache_printed=apache_used and shared_apache is not None
            )
        )
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
    platform: str | None = None,
) -> tuple[str, list[Package]]:
    """The notices text and every component in it: Python first, then the packages.

    *system_libraries* adds the Linux section (see collect_system_libraries()).
    *upstream_notice* defaults to the archived file (see render()).
    *platform* (default sys.platform) decides which components follow Python:
    libffi on "win32" and "darwin" (see LIBFFI_LICENSES, not on Linux), then the
    components CPython bundles (see PYTHON_BUNDLED_LICENSES).
    """
    platform = sys.platform if platform is None else platform
    components = [collect_python(python_dirs)]
    libffi = collect_libffi(platform)
    if libffi is not None:
        components.append(libffi)
    components.extend(collect_python_components(platform))
    components.extend(collect_packages(project, extras, build_tools))
    rust_crates = collect_rust_crates(collect_distributions(project, extras, build_tools))
    return render(components, system_libraries, upstream_notice, rust_crates), components


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
    except (
        ArchivedLicenseError,
        PackedLicenseFileError,
        SharedLicenseError,
        RustCratesError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        check_shared_texts(packages, text)
    except SharedLicenseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for package in packages:
        if not package.texts and not package.text_elsewhere:
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
