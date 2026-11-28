"""Tests for tools/write_third_party_notices.py.

Most tests build throwaway ``*.dist-info`` folders in a temporary directory and
put it on ``sys.path``, so each case controls exactly what the generator sees.
The last group runs against the real virtualenv: PyQt6 must be listed with its
GPL text, and nothing from the dev extras may leak in.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from aiusageclock import identity
from tests.dist_info_factory import make_dist, site  # noqa: F401  (site is a fixture)
from tools import pyinstaller_analysis as analysis
from tools import write_third_party_notices as notices


def names_of(packages) -> list[str]:
    return [package.name for package in packages]


def build(project: str, python_dirs: list[Path] | None = None):
    """build_notices for a fake project, looking for Python's license in *python_dirs* only."""
    return notices.build_notices(
        project,
        (),
        (),
        python_dirs=[] if python_dirs is None else python_dirs,
        platform="linux",
    )


# --- which packages are listed ---------------------------------------------


def test_runtime_requirements_are_followed_and_the_project_is_left_out(site):
    make_dist(
        site,
        "noticetest-app",
        requires=("noticetest-lib>=1", "noticetest-nope; sys_platform == 'no-such-os'"),
    )
    make_dist(site, "noticetest-lib", requires=("noticetest-deep",))
    make_dist(site, "noticetest-deep")
    make_dist(site, "noticetest-nope")

    packages = notices.collect_packages("noticetest-app", extras=(), build_tools=())

    assert names_of(packages) == ["noticetest-deep", "noticetest-lib"]


def test_extras_are_only_followed_when_asked_for(site):
    make_dist(
        site,
        "noticetest-app",
        requires=(
            "noticetest-lib",
            "noticetest-dev-tool; extra == 'dev'",
            "noticetest-shipped; extra == 'shipped'",
        ),
    )
    for name in ("noticetest-lib", "noticetest-dev-tool", "noticetest-shipped"):
        make_dist(site, name)

    runtime_only = notices.collect_packages("noticetest-app", extras=(), build_tools=())
    with_shipped = notices.collect_packages("noticetest-app", extras=("shipped",), build_tools=())

    assert names_of(runtime_only) == ["noticetest-lib"]
    assert names_of(with_shipped) == ["noticetest-lib", "noticetest-shipped"]


def test_extras_requested_by_a_requirement_pull_in_that_extras_dependencies(site):
    make_dist(site, "noticetest-app", requires=("noticetest-lib[speed]",))
    make_dist(
        site,
        "noticetest-lib",
        requires=("noticetest-fast; extra == 'speed'", "noticetest-slow; extra == 'other'"),
    )
    make_dist(site, "noticetest-fast")
    make_dist(site, "noticetest-slow")

    packages = notices.collect_packages("noticetest-app", extras=(), build_tools=())

    assert names_of(packages) == ["noticetest-fast", "noticetest-lib"]


def test_a_build_tool_is_listed_without_its_dependencies(site):
    make_dist(site, "noticetest-app")
    make_dist(site, "noticetest-tool", requires=("noticetest-tool-helper",))
    make_dist(site, "noticetest-tool-helper")

    packages = notices.collect_packages(
        "noticetest-app", extras=(), build_tools=("noticetest-tool",)
    )

    assert names_of(packages) == ["noticetest-tool"]


def test_a_missing_dependency_is_reported_instead_of_skipped(site):
    make_dist(site, "noticetest-app", requires=("noticetest-absent",))

    with pytest.raises(notices.MissingDependencies) as caught:
        notices.collect_packages("noticetest-app", extras=(), build_tools=())

    assert caught.value.names == ["noticetest-absent"]


def test_a_missing_build_tool_is_reported(site):
    make_dist(site, "noticetest-app")

    with pytest.raises(notices.MissingDependencies):
        notices.collect_packages("noticetest-app", extras=(), build_tools=("noticetest-absent",))


def test_an_uninstalled_project_is_reported(site):
    with pytest.raises(notices.metadata.PackageNotFoundError):
        notices.collect_packages("noticetest-absent", extras=(), build_tools=())


# --- what is said about each package ---------------------------------------


def test_declaration_prefers_the_expression_then_the_field_then_classifiers(site):
    make_dist(
        site,
        "noticetest-app",
        requires=("noticetest-a", "noticetest-b", "noticetest-c", "noticetest-d"),
    )
    make_dist(site, "noticetest-a", expression="MIT", license_field="Something else")
    make_dist(site, "noticetest-b", license_field="BSD-3-Clause")
    make_dist(
        site,
        "noticetest-c",
        classifiers=(
            "License :: OSI Approved",
            "License :: OSI Approved :: Apache Software License",
            "License :: OSI Approved :: MIT License",
            "Programming Language :: Python :: 3",
        ),
    )
    make_dist(site, "noticetest-d")

    packages = notices.collect_packages("noticetest-app", extras=(), build_tools=())

    assert {p.name: p.declaration for p in packages} == {
        "noticetest-a": "MIT",
        "noticetest-b": "BSD-3-Clause",
        "noticetest-c": "Apache Software License; MIT License",
        "noticetest-d": "not declared",
    }


def test_license_files_are_read_from_both_dist_info_layouts(site):
    make_dist(site, "noticetest-app", requires=("noticetest-old", "noticetest-new"))
    make_dist(site, "noticetest-old", files={"LICENSE": b"old layout text\n"})
    make_dist(
        site,
        "noticetest-new",
        license_file_entries=("LICENSE.txt",),
        files={
            "licenses/LICENSE.txt": b"new layout text\n",
            "licenses/vendor/COPYING": b"vendored text\n",
            "top_level.txt": b"not a license\n",
        },
    )

    packages = {p.name: p for p in notices.collect_packages("noticetest-app", (), ())}

    assert [t.name for t in packages["noticetest-old"].texts] == ["LICENSE"]
    assert [t.name for t in packages["noticetest-new"].texts] == [
        "LICENSE.txt",
        "vendor/COPYING",
    ]
    assert packages["noticetest-new"].texts[0].text == "new layout text"


def test_a_long_license_field_is_used_as_the_text_when_no_file_exists(site):
    make_dist(site, "noticetest-app", requires=("noticetest-inline",))
    make_dist(site, "noticetest-inline", license_field="Permission is granted. " + "x" * 300)

    (package,) = notices.collect_packages("noticetest-app", (), ())

    assert package.declaration == "see the license text below"
    assert package.texts[0].name == "License field"
    assert package.texts[0].text.startswith("Permission is granted.")


# --- the file that gets written --------------------------------------------


def test_text_is_utf8_with_lf_line_endings(site):
    make_dist(site, "noticetest-app", requires=("noticetest-lib",))
    make_dist(
        site,
        "noticetest-lib",
        expression="MIT",
        files={"licenses/LICENSE": "Copyright © 2026 Zoë\r\nSecond line\rThird line\r\n".encode()},
    )

    text, _ = build("noticetest-app")

    assert "Copyright © 2026 Zoë\nSecond line\nThird line" in text
    assert "\r" not in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_packages_are_sorted_and_the_output_is_reproducible(site):
    make_dist(site, "noticetest-app", requires=("noticetest-zeta", "noticetest-alpha"))
    make_dist(site, "noticetest-zeta", files={"LICENSE": b"zeta\n"})
    make_dist(site, "noticetest-alpha", files={"LICENSE": b"alpha\n"})

    first, packages = build("noticetest-app")
    second, _ = build("noticetest-app")

    assert first == second
    # The components CPython bundles (build() asks for Linux) come right after Python.
    assert [n.lower() for n in names_of(packages)[6:]] == ["noticetest-alpha", "noticetest-zeta"]
    assert names_of(packages)[0] == "Python"
    assert len(packages) == 1 + len(CPYTHON_COMPONENTS_BY_PLATFORM["linux"]) + 2
    assert first.index("noticetest-alpha 1.0\n=") < first.index("noticetest-zeta 1.0\n=")


def test_identical_license_texts_are_printed_once(site):
    make_dist(site, "noticetest-app", requires=("noticetest-one", "noticetest-two"))
    shared = b"The shared license text, long enough to notice.\n"
    make_dist(site, "noticetest-one", files={"LICENSE": shared})
    make_dist(site, "noticetest-two", files={"LICENSE": shared})

    text, _ = build("noticetest-app")

    assert text.count("The shared license text") == 1
    assert "same text as LICENSE of noticetest-one 1.0, above" in text


def test_a_package_without_license_text_says_so(site):
    make_dist(site, "noticetest-app", requires=("noticetest-bare",))
    make_dist(site, "noticetest-bare", expression="MIT")

    text, packages = build("noticetest-app")

    (bare,) = [package for package in packages if package.name == "noticetest-bare"]
    assert bare.texts == []
    assert "No license text is included in the installed package." in text


# --- licenses archived for wheels that ship none (winrt, pyobjc-core) --------

ARCHIVED_DIR = Path(__file__).resolve().parents[1] / "docs" / "legal" / "third-party"
# The files are the upstream texts word for word. Change a hash only together
# with the file, on purpose, after comparing it with the source URL in
# tools/write_third_party_notices.py.
ARCHIVED_LICENSE_SHA256 = {
    "pywinrt-LICENSE.txt": "6e898069e8b3c6d8d23dc70ac7067cc2b7c9db14c36df873026758db82c0891d",
    "pyobjc-core-License.txt": "0ca04b07928d4872b9d9bb22187ca0426dd8bfab08f26eada0999a71dc81aaff",
    # LICENSE of libffi v3.4.4 (commit f24180be...), 1132 bytes: the libffi that
    # CPython v3.14.10 ships on Windows (PCbuild/get_externals.bat).
    "libffi-3.4.4-LICENSE.txt": "2c9c2acb9743e6b007b91350475308aee44691d96aa20eacef8e199988c8c388",
    # LICENSE of Apple's libffi, tag libffi-40 (commit 72e95a49...), 1132 bytes;
    # tags libffi-30 to libffi-40 carry the same bytes.
    "libffi-apple-40-LICENSE.txt": "25d56871423a870487edee68000ef66b1a7ec44a7ab84838ceeb3ce07f734b74",
}


# The texts of the components inside CPython, byte for byte as the upstream
# sources hold them (CRLF line endings included: the repository stores them
# with -text). They were fetched from the source URLs in the entries of
# PYTHON_BUNDLED_LICENSES and match the hashes of the 2026-11-28 research.
CPYTHON_COMPONENT_SHA256 = {
    "expat-2.9.0-COPYING.txt": "31b15de82aa19a845156169a17a5488bf597e561b2c318d159ed583139b25e87",
    "mpdecimal-4.0.0-COPYRIGHT.txt": "2713324211652ce4a60e6e21e54f9dc3004299e591b0933a352f1a89c5fb53c2",
    "mpdecimal-2.5.1-LICENSE.txt": "b07528d8b1dbf1e2d2741052996f0876e23342ce2d30d0effa39c5457716c25a",
    "mimalloc-2.5.2-LICENSE.txt": "82ade5d7d9b029044b5fbbc326207fc47c2d44ee4dd71e8a559c36d728217de9",
    "hacl-star-8ba599b-LICENSE.txt": "998ce04fb8ad9dedb0bc1b44938f8c3dcf1089780fa105ce1c8c30fb5554d78c",
    # Sections of CPython v3.14.10's Doc/license.rst, copied word for word (CRLF,
    # as upstream); the upstream file is 8a7329b2...a6dd. Change a hash only
    # together with the file, after comparing it with the upstream sections.
    "cpython-3.14.10-incorporated-notices.txt": "4f9830368dad20857bc52820bacc8a9ed5cd97fdde1afb6bf0bb10517e55675f",
    "cpython-3.14.10-incorporated-notices-macos.txt": "bee62a91de9ee3b4cc42bdf2c72dd9470d90e7a159d9d72b3f01e6df747b34b7",
}
# What each platform's notices list after Python (and libffi), in order.
CPYTHON_COMPONENTS_BY_PLATFORM = {
    "win32": ["expat", "mpdecimal", "mimalloc", "hacl*", "cpython-incorporated-software"],
    "darwin": ["openssl", "expat", "mpdecimal", "hacl*", "cpython-incorporated-software"],
    "linux": ["expat", "mpdecimal", "mimalloc", "hacl*", "cpython-incorporated-software"],
}


def _archived(tmp_path: Path, content: bytes | None) -> tuple[dict, Path]:
    """An ARCHIVED_LICENSES-style mapping for "noticetest-bare" and its root folder."""
    entry = notices.ArchivedLicense(
        file="archive/bare-license.txt",
        project="bare-project",
        source_url="https://example.invalid/bare/LICENSE",
        ref="tag v9.9",
    )
    if content is not None:
        (tmp_path / "archive").mkdir()
        (tmp_path / "archive" / "bare-license.txt").write_bytes(content)
    return {"noticetest-bare": entry}, tmp_path


def test_the_archived_license_files_are_the_pinned_upstream_texts():
    for name, expected in ARCHIVED_LICENSE_SHA256.items():
        raw = (ARCHIVED_DIR / name).read_bytes()
        assert b"\r" not in raw, name
        assert b"Permission is hereby granted, free of charge" in raw, name
        assert hashlib.sha256(raw).hexdigest() == expected, name


def test_every_archived_license_points_at_an_existing_file_and_a_pinned_source():
    for canonical, entry in notices.ARCHIVED_LICENSES.items():
        assert canonical == canonical.lower()
        assert (Path(notices.REPO_ROOT) / entry.file).is_file(), canonical
        assert Path(entry.file).name in ARCHIVED_LICENSE_SHA256, canonical
        # A fixed commit, not a branch: the text is what that commit held.
        assert re.search(r"/blob/[0-9a-f]{40}/", entry.source_url), canonical
        assert entry.ref.startswith("tag v"), canonical


LIBFFI_SOURCES = {
    "win32": "https://github.com/libffi/libffi/blob/",
    "darwin": "https://github.com/apple-oss-distributions/libffi/blob/",
}


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_the_libffi_licenses_are_archived_with_a_pinned_source_and_match_their_hash(platform):
    entry = notices.LIBFFI_LICENSES[platform]
    assert (Path(notices.REPO_ROOT) / entry.file).is_file()
    assert Path(entry.file).name in ARCHIVED_LICENSE_SHA256
    assert re.search(r"/blob/[0-9a-f]{40}/LICENSE$", entry.source_url)
    assert entry.source_url.startswith(LIBFFI_SOURCES[platform])
    assert entry.ref.startswith("tag ")
    assert platform in notices.LIBFFI_NOTES
    assert entry.source_url in notices.LIBFFI_NOTES[platform]


def test_every_archived_file_is_used_by_an_entry():
    used = {Path(e.file).name for e in notices.ARCHIVED_LICENSES.values()}
    used |= {Path(e.file).name for e in notices.LIBFFI_LICENSES.values()}
    assert used == set(ARCHIVED_LICENSE_SHA256)
    # The licenses of the components inside CPython (PYTHON_BUNDLED_LICENSES) are
    # archived in the same folder, so the folder holds their files as well.
    cpython = {
        Path(entry.file).name
        for components in notices.PYTHON_BUNDLED_LICENSES.values()
        for component in components
        for entry in component.licenses
    }
    assert cpython == set(CPYTHON_COMPONENT_SHA256)
    # (the license texts of the Rust crates have a test of their own, below)
    assert {
        path.name for path in ARCHIVED_DIR.glob("*.txt") if not path.name.startswith("rust-")
    } == used | cpython


@pytest.mark.parametrize(
    ("platform", "file", "first_line"),
    [
        (
            "win32",
            "libffi-3.4.4-LICENSE.txt",
            "libffi - Copyright (c) 1996-2022  Anthony Green, Red Hat, Inc and others.",
        ),
        (
            "darwin",
            "libffi-apple-40-LICENSE.txt",
            "libffi - Copyright (c) 1996-2020  Anthony Green, Red Hat, Inc and others.",
        ),
    ],
)
def test_windows_and_macos_notices_list_libffi_with_its_full_license_text(
    site, platform, file, first_line
):
    make_dist(site, "noticetest-app")
    expected = notices._normalise_text((ARCHIVED_DIR / file).read_bytes())

    text, components = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], platform=platform
    )

    # Python, libffi, then what CPython itself bundles on that platform (the
    # list used to end at libffi, before PYTHON_BUNDLED_LICENSES existed).
    assert [c.name for c in components][:2] == ["Python", "libffi"]
    assert notices.listed_component_names(text) == [
        "python",
        "libffi",
        *CPYTHON_COMPONENTS_BY_PLATFORM[platform],
    ]
    assert "libffi (used-by-CPython-_ctypes) - MIT" in text
    assert "statically" not in text  # no claim about how a platform links it
    assert expected in text
    assert first_line in text
    assert notices.LIBFFI_LICENSES[platform].source_url in text
    # The other platform's text is not in this one.
    other = "darwin" if platform == "win32" else "win32"
    assert notices.LIBFFI_LICENSES[other].source_url not in text


def test_the_notes_say_what_each_platform_really_ships():
    assert "libffi-8.dll" in notices.LIBFFI_NOTES["win32"]
    assert "libffi 3.4.4" in notices.LIBFFI_NOTES["win32"]
    # python.org's macOS build links the system libffi; the note must not claim a bundle.
    assert "/usr/lib/libffi.dylib" in notices.LIBFFI_NOTES["darwin"]
    assert "instead of carrying its own copy" in notices.LIBFFI_NOTES["darwin"]


def test_linux_notices_have_no_libffi_component_of_their_own(site):
    make_dist(site, "noticetest-app")

    text, components = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], platform="linux"
    )

    # Python and what CPython itself bundles, but no libffi component (the list
    # used to be just Python before PYTHON_BUNDLED_LICENSES existed).
    assert components[0].name == "Python"
    assert "Anthony Green" not in text
    assert notices.listed_component_names(text) == [
        "python",
        *CPYTHON_COMPONENTS_BY_PLATFORM["linux"],
    ]
    assert notices.collect_libffi("linux") is None


# What Ubuntu 22.04 (jammy) ships as /usr/share/doc/libffi8/copyright (libffi
# 3.4.2-4): the permission notice of libffi between the list of copyright holders
# and the documentation terms. Shortened to the parts the test looks at.
JAMMY_LIBFFI8_COPYRIGHT = """\
This package was debianized by Matthias Klose <doko@debian.org>
on Mon, 10 Mar 2008 05:46:40 +0000.

License:

    libffi - Copyright (c) 1996-2010  Red Hat, Inc and others.
    See source files for details.

    Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    ``Software''), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions:

    The above copyright notice and this permission notice shall be included
    in all copies or substantial portions of the Software.
"""


@pytest.mark.parametrize("analysed", ["gui", "mcp"])
def test_a_linux_build_that_packs_libffi_so_carries_the_libffi_license_text(
    site, tmp_path, analysed
):
    write_copyright(tmp_path, "libffi8", JAMMY_LIBFFI8_COPYRIGHT)
    make_dist(site, "noticetest-app")
    owned = {f"{LIB_DIR}/libffi.so.8": ["libffi8"]}
    system = collect({analysed: [library("libffi.so.8")]}, owned, tmp_path)

    text, _ = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], system_libraries=system, platform="linux"
    )

    section = text[text.index(notices.SYSTEM_LIBRARIES_TITLE) :]
    assert notices.listed_system_library_names(text) == ["libffi.so.8"]
    assert "libffi8" in section
    assert "libffi - Copyright (c) 1996-2010  Red Hat, Inc and others." in section
    assert "``Software''), to deal in the Software" in section  # libffi's own wording


def test_a_linux_build_whose_libffi_copyright_file_is_missing_says_so(site, tmp_path):
    make_dist(site, "noticetest-app")
    owned = {f"{LIB_DIR}/libffi.so.8": ["libffi8"]}
    system = collect({"gui": [library("libffi.so.8")]}, owned, tmp_path)

    text, _ = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], system_libraries=system, platform="linux"
    )

    assert "libffi8" in text
    assert "Red Hat" not in text


def test_the_libffi_entries_fail_loudly_when_their_archived_file_is_unusable(tmp_path):
    for platform in ("win32", "darwin"):
        with pytest.raises(notices.ArchivedLicenseError, match="cannot read the archived license"):
            notices.collect_libffi(platform, tmp_path)


def test_the_winrt_and_pyobjc_core_dependencies_have_an_archived_license():
    import tomllib

    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    winrt = {
        str(canonicalize_name(Requirement(line).name))
        for line in dependencies
        if Requirement(line).name.lower().startswith("winrt-")
    }

    assert len(winrt) == 5
    assert winrt <= set(notices.ARCHIVED_LICENSES)
    # pyobjc-framework-Cocoa ships its own text; its dependency pyobjc-core does not.
    assert "pyobjc-core" in notices.ARCHIVED_LICENSES


def test_a_package_without_a_shipped_license_gets_the_archived_text_and_says_where_it_is_from(
    site, tmp_path
):
    make_dist(site, "noticetest-app", requires=("noticetest-bare",))
    make_dist(site, "noticetest-bare", expression="MIT")
    archived, root = _archived(tmp_path, b"\xef\xbb\xbfArchived MIT text\r\nsecond line\r\n")

    packages = notices.collect_packages(
        "noticetest-app", (), (), archived=archived, archive_root=root
    )

    (bare,) = packages
    assert [(t.name, t.text) for t in bare.texts] == [
        ("bare-project license (tag v9.9)", "Archived MIT text\nsecond line")
    ]
    assert "ships no license file" in bare.note
    assert "https://example.invalid/bare/LICENSE" in bare.note
    assert "bare-project, tag v9.9" in bare.note

    text = notices.render(
        [bare], upstream_notice="upstream"
    )
    assert "No license text is included in the installed package." not in text
    assert "Archived MIT text" in text
    assert "https://example.invalid/bare/LICENSE" in text


def test_a_license_that_the_wheel_ships_wins_over_the_archived_one(site, tmp_path):
    make_dist(site, "noticetest-app", requires=("noticetest-bare",))
    make_dist(site, "noticetest-bare", expression="MIT", files={"LICENSE": b"shipped text\n"})
    archived, root = _archived(tmp_path, b"Archived text\n")

    (bare,) = notices.collect_packages(
        "noticetest-app", (), (), archived=archived, archive_root=root
    )

    assert [t.text for t in bare.texts] == ["shipped text"]
    assert bare.note == ""


def test_packages_that_nothing_is_archived_for_still_say_they_have_no_text(site, tmp_path):
    make_dist(site, "noticetest-app", requires=("noticetest-other",))
    make_dist(site, "noticetest-other", expression="MIT")
    archived, root = _archived(tmp_path, b"Archived text\n")

    (other,) = notices.collect_packages(
        "noticetest-app", (), (), archived=archived, archive_root=root
    )

    assert other.texts == []
    assert other.note == ""


def test_the_real_winrt_and_pyobjc_core_texts_are_used_and_printed_once(site):
    make_dist(
        site,
        "noticetest-app",
        requires=("winrt-runtime", "winrt-windows-foundation", "pyobjc-core"),
    )
    make_dist(site, "winrt-runtime", "3.2.1", expression="MIT")
    make_dist(site, "winrt-windows-foundation", "3.2.1", expression="MIT")
    make_dist(site, "pyobjc-core", "12.2.2", license_field="MIT")

    text, packages = build("noticetest-app")

    # build() lists the bundled Python runtime first, then the components CPython
    # bundles; neither is a package here.
    cpython = {"python", *CPYTHON_COMPONENTS_BY_PLATFORM["linux"]}
    assert {
        p.canonical_name: bool(p.texts) for p in packages if p.canonical_name not in cpython
    } == {
        "pyobjc-core": True,
        "winrt-runtime": True,
        "winrt-windows-foundation": True,
    }
    assert "No license text is included in the installed package." not in text
    # The two winrt packages share one text: printed once, then pointed at.
    assert text.count("Copyright (c) Microsoft Corporation. All rights reserved.") == 1
    assert "same text as pywinrt license (tag v3.2.1) of winrt-runtime 3.2.1, above" in text
    assert "Copyright 2003-2025 - Ronald Oussoren" in text
    assert "https://github.com/pywinrt/pywinrt/blob/" in text
    assert "https://github.com/ronaldoussoren/pyobjc/blob/" in text


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (None, "cannot read the archived license"),
        (b"", "is empty"),
        (b"   \n\n", "is empty"),
        (b"\xff\xfeM\x00I\x00T\x00", "not valid UTF-8"),
        (b"MIT\x00text", "contains NUL"),
    ],
)
def test_an_unusable_archived_license_fails_loudly_with_its_path(site, tmp_path, content, reason):
    make_dist(site, "noticetest-app", requires=("noticetest-bare",))
    make_dist(site, "noticetest-bare", expression="MIT")
    archived, root = _archived(tmp_path, content)

    with pytest.raises(notices.ArchivedLicenseError) as excinfo:
        notices.collect_packages("noticetest-app", (), (), archived=archived, archive_root=root)

    message = str(excinfo.value)
    assert reason in message
    assert "bare-license.txt" in message


def test_main_reports_an_unusable_archived_license_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    def broken(**_options):
        raise notices.ArchivedLicenseError("cannot read the archived license x.txt: gone")

    monkeypatch.setattr(notices, "build_notices", broken)
    output = tmp_path / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output)]) == 1

    assert "cannot read the archived license x.txt" in capsys.readouterr().err
    assert not output.exists()


def test_the_introduction_points_to_the_project_license(site):
    make_dist(site, "noticetest-app")

    text, _ = build("noticetest-app")

    assert text.startswith("THIRD-PARTY NOTICES\n")
    assert "MIT License; see the LICENSE file" in text
    assert notices.REPO_URL in text


# --- the notice of the code the project is based on --------------------------

ARCHIVED_NOTICE = Path(__file__).resolve().parents[1] / "docs" / "legal" / "UPSTREAM-LICENSE.txt"
PROJECT_LICENSE = Path(__file__).resolve().parents[1] / "LICENSE"


def notice_section(text: str) -> str:
    """The upstream notice as written between its explanatory note and the component index."""
    start = text.index(notices.UPSTREAM_NOTICE_NOTE) + len(notices.UPSTREAM_NOTICE_NOTE)
    end = text.index("\nComponents (")
    return text[start:end].strip("\n")


def test_the_upstream_notice_sits_between_the_introduction_and_the_component_index(site):
    make_dist(site, "noticetest-app")

    text, _ = build("noticetest-app")

    lines = text.split("\n")
    title = lines.index(notices.UPSTREAM_NOTICE_TITLE)
    assert lines[title - 1] == lines[title + 1] == notices._RULE
    assert (
        text.index(notices.REPO_URL)
        < text.index(notices.UPSTREAM_NOTICE_TITLE + "\n")
        < text.index(notices.UPSTREAM_NOTICE_NOTE)
        < text.index("\nComponents (")
    )
    assert "MIT License" in notices.UPSTREAM_NOTICE_NOTE


def test_the_upstream_notice_is_the_archived_file_word_for_word(site):
    make_dist(site, "noticetest-app")
    expected = notices._normalise_text(ARCHIVED_NOTICE.read_bytes())

    text, _ = build("noticetest-app")

    assert notices.UPSTREAM_LICENSE_PATH == ARCHIVED_NOTICE
    assert expected.startswith("MIT License\n")
    assert "Permission is hereby granted, free of charge" in expected
    assert notice_section(text) == expected


def test_the_upstream_notice_is_read_from_the_file_not_copied_into_the_script(
    site, tmp_path, monkeypatch
):
    make_dist(site, "noticetest-app")
    archived = tmp_path / "notice.txt"
    archived.write_bytes("Sentinel notice ©\r\nsecond line\r\n".encode())
    monkeypatch.setattr(notices, "UPSTREAM_LICENSE_PATH", archived)

    text, _ = build("noticetest-app")

    assert notice_section(text) == "Sentinel notice ©\nsecond line"
    assert "\r" not in text


@pytest.mark.parametrize(
    ("file_name", "content"),
    [
        ("absent-notice.txt", None),
        ("empty-notice.txt", b""),
        ("blank-notice.txt", b"\r\n\r\n"),
        ("utf16-notice.txt", "MIT License\n".encode("utf-16")),
        ("utf16-without-bom-notice.txt", "MIT License\n".encode("utf-16-le")),
        ("latin1-notice.txt", b"MIT Licen\xe9se\n"),
    ],
    ids=["missing", "empty", "blank", "utf-16", "utf-16-no-bom", "not-utf-8"],
)
def test_an_unusable_upstream_notice_fails_loudly_with_its_path(
    site, tmp_path, monkeypatch, capsys, file_name, content
):
    make_dist(site, "noticetest-app")
    archived = tmp_path / file_name
    if content is not None:
        archived.write_bytes(content)
    monkeypatch.setattr(notices, "UPSTREAM_LICENSE_PATH", archived)
    named = re.escape(file_name)

    with pytest.raises(notices.UpstreamNoticeError, match=named):
        build("noticetest-app")
    with pytest.raises(notices.UpstreamNoticeError, match=named):
        notices.render([])

    # main() reads the archive before it collects any package, so it fails early
    # without looking at the environment.
    def collected_anyway(**_options):
        raise AssertionError("packages were collected before the notice was read")

    monkeypatch.setattr(notices, "build_notices", collected_anyway)
    output = tmp_path / "out" / "THIRD_PARTY_NOTICES.txt"
    assert notices.main([str(output)]) == 1
    assert file_name in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("given", ["", "  \n\n", "\t\r\n"], ids=["empty", "spaces", "tab"])
def test_a_notice_handed_to_render_must_not_be_empty_either(given):
    with pytest.raises(notices.UpstreamNoticeError, match="empty"):
        notices.render([], upstream_notice=given)


def test_the_upstream_notice_is_decoded_strictly_not_with_replacement_characters(tmp_path):
    garbled = tmp_path / "utf16.txt"
    garbled.write_bytes("MIT License\n".encode("utf-16"))
    with pytest.raises(notices.UpstreamNoticeError, match="utf16.txt"):
        notices.read_upstream_notice(garbled)

    # A byte order mark in front of clean UTF-8 is fine and is dropped.
    clean = tmp_path / "utf8.txt"
    clean.write_bytes("\ufeffMIT License ©\r\n".encode())
    assert notices.read_upstream_notice(clean) == "MIT License ©"


# SHA-256 of the archived notice with LF line endings: the LICENSE file of the v1.0.0
# release, kept word for word because the MIT License requires the notice to travel
# with the software. Change it only together with the archived file, on purpose.
ARCHIVED_NOTICE_SHA256 = "e984396279a8ec685d67e6eeb16db6e2f4ddd06930e70138975d34bc5e24d74b"


def test_the_archived_notice_text_is_pinned():
    normalised = ARCHIVED_NOTICE.read_bytes().replace(b"\r\n", b"\n")

    assert hashlib.sha256(normalised).hexdigest() == ARCHIVED_NOTICE_SHA256


def test_the_archived_notice_matches_the_license_except_for_the_copyright_line():
    ours = notices._normalise_text(PROJECT_LICENSE.read_bytes()).split("\n")
    archived = notices._normalise_text(ARCHIVED_NOTICE.read_bytes()).split("\n")

    assert len(ours) == len(archived)
    for number, (ours_line, archived_line) in enumerate(zip(ours, archived), start=1):
        if ours_line.startswith("Copyright (c)"):
            assert archived_line.startswith("Copyright (c)"), f"line {number}"
        else:
            assert ours_line == archived_line, f"line {number} differs"
    ours_copyright = [line for line in ours if line.startswith("Copyright (c)")]
    archived_copyright = [line for line in archived if line.startswith("Copyright (c)")]
    assert len(ours_copyright) == len(archived_copyright) == 1
    assert ours_copyright != archived_copyright
    assert ours_copyright == [f"Copyright (c) 2026 {identity.PUBLISHER}"]


def test_the_upstream_notice_is_not_mistaken_for_a_component(site):
    make_dist(site, "noticetest-app", requires=("noticetest-lib",))
    make_dist(site, "noticetest-lib")
    package = notices.Package(name="odd", version="1.0", declaration="MIT")
    # A notice whose lines look like index entries must not leak into the index.
    lookalike = "Looks Like A 1.0 - MIT\nAnother Entry 2.0 - MIT"

    text, packages = build("noticetest-app")
    assert notices.listed_component_names(text) == [
        "python",
        *CPYTHON_COMPONENTS_BY_PLATFORM["linux"],
        "noticetest-lib",
    ]
    assert len(notices.listed_component_names(text)) == len(packages)

    with_lookalike = notices.render([package], upstream_notice=lookalike)
    assert lookalike in with_lookalike
    assert notices.listed_component_names(with_lookalike) == ["odd"]


# --- the bundled Python runtime --------------------------------------------


def test_python_is_listed_first_with_the_license_file_found(site, tmp_path):
    license_dir = tmp_path / "python-home"
    license_dir.mkdir()
    (license_dir / "LICENSE.txt").write_bytes("PSF terms © 2026\r\nsecond line\r\n".encode())
    make_dist(site, "noticetest-app", requires=("noticetest-lib",))
    make_dist(site, "noticetest-lib", files={"LICENSE": b"lib\n"})

    text, components = build("noticetest-app", [license_dir])

    python = components[0]
    assert python.name == "Python"
    assert python.version == sys.version.split()[0]
    assert python.declaration == (
        "PSF-2.0" if sys.implementation.name == "cpython" else "not declared"
    )
    assert [t.name for t in python.texts] == ["LICENSE.txt"]
    assert python.texts[0].text == "PSF terms © 2026\nsecond line"
    assert text.index(f"Python {python.version}\n=") < text.index("noticetest-lib 1.0\n=")
    assert "Interpreter: " in text
    assert notices._PYTHON_DOCS_LICENSE in text


def test_python_license_lookup_accepts_only_license_file_names(tmp_path):
    folder = tmp_path / "python-home"
    folder.mkdir()
    for name in ("LICENSE", "COPYING.txt", "NOTICE.md"):
        (folder / name).write_text(f"text of {name}", encoding="utf-8")
    for lookalike in ("license.py", "LICENSE.txt.bak", "licensing.txt", "LICENSE_notes.bin"):
        (folder / lookalike).write_text("not a license", encoding="utf-8")
    (folder / "LICENSES").mkdir()
    (folder / "NOTICE").mkdir()

    python = notices.collect_python([folder])

    assert [t.name for t in python.texts] == ["COPYING.txt", "LICENSE", "NOTICE.md"]


def test_python_license_is_searched_in_every_folder_and_the_first_wins(tmp_path):
    first, second = tmp_path / "root", tmp_path / "stdlib"
    first.mkdir()
    second.mkdir()
    (first / "LICENSE.txt").write_text("from the root", encoding="utf-8")
    (second / "LICENSE.txt").write_text("from the standard library", encoding="utf-8")
    (second / "COPYING").write_text("only in the second", encoding="utf-8")

    python = notices.collect_python([tmp_path / "does-not-exist", first, second])

    assert {t.name: t.text for t in python.texts} == {
        "LICENSE.txt": "from the root",
        "COPYING": "only in the second",
    }


def test_python_without_a_license_file_says_so(site, tmp_path):
    make_dist(site, "noticetest-app")

    text, components = build("noticetest-app", [tmp_path / "empty-python-home"])

    assert components[0].texts == []
    assert "No license file (LICENSE, COPYING or NOTICE) was found in the Python" in text
    assert "Declared license:" in text


def test_main_warns_when_python_has_no_license_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(notices, "python_license_dirs", lambda: [tmp_path / "nothing-here"])
    output = tmp_path / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output)]) == 0

    assert f"no license text found for Python {sys.version.split()[0]}" in capsys.readouterr().err
    assert "No license file (LICENSE, COPYING or NOTICE) was found" in output.read_text(
        encoding="utf-8"
    )


def test_the_real_python_is_described_and_its_license_found():
    python = notices.collect_python()

    assert python.version == sys.version.split()[0]
    assert python.detail.startswith(sys.implementation.name)
    # The lookup is verified on the Windows layout (LICENSE.txt in the
    # installation root); other layouts only have to produce a valid entry.
    if sys.platform == "win32":
        assert python.texts, "no license file found in the Python installation"
        assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in python.texts[0].text
    for license_text in python.texts:
        assert "\r" not in license_text.text


# --- reading a written file back ----------------------------------------------


def test_the_listed_components_are_read_back_from_a_rendered_file(site):
    make_dist(site, "noticetest-app", requires=("Noticetest.Lib", "noticetest-other"))
    make_dist(site, "Noticetest.Lib", version="2.5")
    make_dist(site, "noticetest-other")

    text, packages = build("noticetest-app")

    assert notices.listed_component_names(text) == [
        "python",
        *CPYTHON_COMPONENTS_BY_PLATFORM["linux"],
        "noticetest-lib",
        "noticetest-other",
    ]
    assert len(notices.listed_component_names(text)) == len(packages)


def test_a_license_declaration_containing_a_dash_does_not_confuse_the_reader():
    package = notices.Package(name="odd", version="1.0", declaration="MIT - with exceptions")

    assert notices.listed_component_names(notices.render([package])) == ["odd"]


@pytest.mark.parametrize(
    "broken",
    [
        "no index here\n",
        "Components (1)\nnot a rule\nodd 1.0 - MIT\n",
        "Components (2)\n" + "-" * 80 + "\nodd 1.0 - MIT\n",
        "Components (1)\n" + "-" * 80 + "\nnoversion - MIT\n",
    ],
    ids=["no index", "no rule", "wrong count", "no version"],
)
def test_a_file_that_is_not_a_notices_file_is_rejected(broken):
    with pytest.raises(ValueError):
        notices.listed_component_names(broken)


# --- command line ----------------------------------------------------------


def test_main_reports_missing_dependencies_and_writes_nothing(tmp_path, monkeypatch, capsys):
    def fail(**_options):
        raise notices.MissingDependencies(["somepackage"])

    monkeypatch.setattr(notices, "build_notices", fail)
    output = tmp_path / "out" / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output)]) == 1

    assert "somepackage" in capsys.readouterr().err
    assert not output.exists()


def test_main_warns_about_packages_without_license_text(tmp_path, monkeypatch, capsys):
    bare = notices.Package(name="bare", version="2.0", declaration="MIT")
    monkeypatch.setattr(notices, "build_notices", lambda **_options: ("text\n", [bare]))
    output = tmp_path / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output)]) == 0

    assert "no license text found for bare 2.0" in capsys.readouterr().err
    assert output.read_bytes() == b"text\n"


# --- system libraries of a Linux build -------------------------------------
#
# dpkg is not available where these tests usually run, and neither are the
# paths. A stand-in for subprocess.run answers ``dpkg -S`` from a dictionary,
# the library paths are POSIX strings that are only compared as text, and the
# "copyright files" live in a temporary folder. What really happens on Linux is
# up to the workflow_dispatch run of release.yml.

LIB_DIR = "/usr/lib/x86_64-linux-gnu"


def library(name, directory=LIB_DIR, typecode="BINARY"):
    """A toc entry for a library packed from *directory*."""
    return (name, f"{directory}/{name}", typecode)


def fake_dpkg(owned, calls=None, sources=None):
    """subprocess.run stand-in: answers ``dpkg -S`` from *owned* ({path: [packages]}).

    Like the real one it prints an owner line per known path, complains on
    stderr about the others and then exits with status 1. ``dpkg-query -W``
    (the source packages of copyleft libraries) is answered from *sources*
    ({binary package: (source package, source version)}; none by default).
    """

    def run(command, **_options):
        if command[0] == "dpkg-query":
            known = [(n, sources[n]) for n in command[4:] if n in (sources or {})]
            return subprocess.CompletedProcess(
                command,
                0 if len(known) == len(command[4:]) else 1,
                stdout="".join(f"{n}\t{s}\t{v}\n" for n, (s, v) in known),
                stderr="",
            )
        assert command[:2] == ["dpkg", "-S"], command
        paths = command[2:]
        if calls is not None:
            calls.append(paths)
        known = [path for path in paths if path in owned]
        unknown = [path for path in paths if path not in owned]
        return subprocess.CompletedProcess(
            command,
            1 if unknown else 0,
            stdout="".join(
                ", ".join(f"{package}:amd64" for package in owned[path]) + f": {path}\n"
                for path in known
            ),
            stderr="".join(f"dpkg-query: no path found matching pattern {p}\n" for p in unknown),
        )

    return run


def write_copyright(doc_root, package, text):
    folder = doc_root / package
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "copyright").write_text(text, encoding="utf-8", newline="")


# The tests of main() replace notices.collect_system_libraries; these helpers
# keep using the real one.
REAL_COLLECT = notices.collect_system_libraries


def collect(
    analyses,
    owned,
    doc_root,
    *,
    calls=None,
    realpath=lambda path: path,
    licenses_root=None,
    sources=None,
    os_release=None,
):
    """collect_system_libraries with nothing excluded, a fake dpkg and fake copyright files.

    *licenses_root* stands in for /usr/share/common-licenses; by default it is a
    folder that does not exist, so the machine running the tests is never read.
    """
    if licenses_root is None:
        licenses_root = doc_root / "no-such-common-licenses"
    return REAL_COLLECT(
        analyses,
        roots=[],
        run=fake_dpkg(owned, calls, sources),
        realpath=realpath,
        doc_root=doc_root,
        licenses_root=licenses_root,
        # a folder that does not exist: the machine running the tests is never read
        os_release=doc_root / "no-such-os-release" if os_release is None else os_release,
    )


def write_common_license(licenses_root, name, text):
    licenses_root.mkdir(parents=True, exist_ok=True)
    (licenses_root / name).write_text(text, encoding="utf-8", newline="")


def test_only_shared_libraries_from_outside_the_environment_are_system_libraries(tmp_path):
    python_home = tmp_path / "python"
    site_dir = tmp_path / "venv" / "site-packages"
    extension = library("_ssl.cpython-312-x86_64-linux-gnu.so", "/usr/lib/python3.12", "EXTENSION")
    entries = [
        library("libnss3.so"),
        extension,
        ("libpython3.12.so.1.0", str(python_home / "lib" / "libpython3.12.so.1.0"), "BINARY"),
        (
            "PyQt6/Qt6/lib/libQt6Core.so.6",
            str(site_dir / "PyQt6" / "Qt6" / "lib" / "libQt6Core.so.6"),
            "BINARY",
        ),
        ("namespace", "-", "BINARY"),
        ("nothing", "", "BINARY"),
    ]

    found = notices.bundled_system_libraries(entries, roots=[str(python_home), str(site_dir)])

    assert found == {"libnss3.so": f"{LIB_DIR}/libnss3.so", extension[0]: extension[1]}


def test_a_library_that_sits_inside_a_root_is_left_out_but_a_lookalike_folder_is_not(tmp_path):
    python_home = tmp_path / "python"
    inside = ("libinside.so", str(python_home / "lib" / "libinside.so"), "BINARY")
    beside = ("libbeside.so", str(tmp_path / "python-extra" / "libbeside.so"), "BINARY")

    found = notices.bundled_system_libraries([inside, beside], roots=[str(python_home)])

    assert list(found) == ["libbeside.so"]


@pytest.mark.parametrize("typecode", ["PYMODULE", "PYSOURCE", "DATA", "SYMLINK"])
def test_packed_files_that_are_not_libraries_are_not_system_libraries(typecode):
    entry = ("something", f"{LIB_DIR}/something", typecode)

    assert notices.bundled_system_libraries([entry], roots=[]) == {}
    assert notices.bundled_system_libraries([("something", entry[1], "BINARY")], roots=[]) != {}


def test_the_environment_roots_cover_python_the_virtualenv_and_the_repository(monkeypatch, tmp_path):
    python_home = tmp_path / "python-home"
    monkeypatch.setattr(sys, "base_prefix", str(python_home))
    monkeypatch.setattr(sys, "base_exec_prefix", str(python_home))

    roots = notices.environment_roots()

    assert analysis.normal_path(python_home) in roots
    assert analysis.normal_path(sys.prefix) in roots
    assert analysis.normal_path(Path(__file__).resolve().parents[1]) in roots


def python_prefix(monkeypatch, prefix):
    monkeypatch.setattr(sys, "base_prefix", prefix)
    monkeypatch.setattr(sys, "base_exec_prefix", prefix)


@pytest.mark.parametrize("prefix", ["/usr", "/usr/local", "/opt"])
def test_a_python_prefix_that_holds_much_more_than_python_does_not_make_the_system_look_like_python(
    monkeypatch, prefix
):
    python_prefix(monkeypatch, prefix)

    roots = notices.environment_roots()

    assert analysis.normal_path(prefix) not in roots
    assert analysis.normal_path("/") not in roots
    assert analysis.normal_path(sys.prefix) in roots  # the other roots stay


def test_a_python_installed_under_a_prefix_of_its_own_is_a_root(monkeypatch):
    prefix = "/opt/hostedtoolcache/Python/3.11.9/x64"  # actions/setup-python
    python_prefix(monkeypatch, prefix)

    assert analysis.normal_path(prefix) in notices.environment_roots()


@pytest.mark.parametrize("prefix", ["/usr/local", "/opt"])
def test_libraries_beside_a_python_under_usr_local_or_opt_are_listed_not_swallowed(
    monkeypatch, prefix
):
    python_prefix(monkeypatch, prefix)
    unrelated = ("libfoo.so.1", f"{prefix}/lib/libfoo.so.1", "BINARY")
    libpython = ("libpython3.12.so.1.0", f"{prefix}/lib/libpython3.12.so.1.0", "BINARY")

    found = notices.bundled_system_libraries([unrelated, libpython])

    # libpython comes out too, as a file no Debian package owns: a person decides
    # about that, whereas a library left out here would go unnoticed.
    assert set(found) == {"libfoo.so.1", "libpython3.12.so.1.0"}


def test_a_python_with_a_prefix_of_its_own_keeps_its_own_libraries_out_but_not_its_neighbours(
    monkeypatch,
):
    prefix = "/opt/hostedtoolcache/Python/3.11.9/x64"
    python_prefix(monkeypatch, prefix)
    own = [
        ("libpython3.11.so.1.0", f"{prefix}/lib/libpython3.11.so.1.0", "BINARY"),
        ("_ssl.so", f"{prefix}/lib/python3.11/lib-dynload/_ssl.so", "EXTENSION"),
    ]
    neighbours = [library("libnss3.so"), ("libother.so", "/opt/other/libother.so", "BINARY")]

    found = notices.bundled_system_libraries(own + neighbours)

    assert set(found) == {"libnss3.so", "libother.so"}


def test_dpkg_answers_are_read_with_architecture_qualifiers_and_several_owners():
    output = (
        "libnss3:amd64: /usr/lib/x86_64-linux-gnu/libnss3.so\n"
        "libglib2.0-0:amd64, libglib2.0-0-dbg:amd64: /usr/lib/x86_64-linux-gnu/libglib-2.0.so.0\n"
        "diversion by libc6 from: /lib/x86_64-linux-gnu/libfoo.so\n"
        "dpkg-query: no path found matching pattern /usr/lib/x\n"
        "zlib1g: /lib/x86_64-linux-gnu/libz.so.1\n"
        "\n"
    )

    assert notices.parse_dpkg_search(output) == {
        "/usr/lib/x86_64-linux-gnu/libnss3.so": {"libnss3"},
        "/usr/lib/x86_64-linux-gnu/libglib-2.0.so.0": {"libglib2.0-0", "libglib2.0-0-dbg"},
        "/lib/x86_64-linux-gnu/libz.so.1": {"zlib1g"},
    }
    assert notices.parse_dpkg_search("dpkg-query: no path found matching pattern /x\n") == {}


def test_local_diversion_notices_are_not_taken_for_package_names():
    output = (
        "local diversion from: /usr/lib/x86_64-linux-gnu/libfoo.so\n"
        "local diversion to: /usr/lib/x86_64-linux-gnu/libfoo.so.distrib\n"
        "diversion by libc6 to: /lib/x86_64-linux-gnu/libbar.so\n"
        "Some Notice: /usr/lib/x86_64-linux-gnu/libodd.so\n"
        "libnss3:amd64: /usr/lib/x86_64-linux-gnu/libnss3.so\n"
    )

    assert notices.parse_dpkg_search(output) == {
        "/usr/lib/x86_64-linux-gnu/libnss3.so": {"libnss3"}
    }
    # Counterpart: a real package whose name starts like the notice is an owner.
    assert notices.parse_dpkg_search("local-tools:amd64: /usr/bin/x\n") == {
        "/usr/bin/x": {"local-tools"}
    }
    assert notices.parse_dpkg_search("local diversion from: /usr/bin/x\n") == {}


def test_dpkg_is_asked_in_batches_and_unknown_paths_are_simply_absent():
    paths = [f"{LIB_DIR}/lib{i:03}.so" for i in range(250)]
    owned = {path: ["pkg"] for path in paths[:10]}
    calls = []

    owners = notices.dpkg_owners(paths + paths[:5], fake_dpkg(owned, calls))

    assert [len(batch) for batch in calls] == [100, 100, 50]  # duplicates asked once
    assert sorted(owners) == sorted(owned)
    assert notices.dpkg_owners([], fake_dpkg(owned, calls)) == {}
    assert len(calls) == 3  # nothing to ask, nothing run


def test_a_dpkg_that_cannot_run_or_fails_is_reported_not_mistaken_for_no_owners():
    def missing(command, **_options):
        raise FileNotFoundError(2, "No such file or directory: 'dpkg'")

    def broken(command, **_options):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="dpkg: error: bad\nmore\n")

    def slow(command, **_options):
        raise subprocess.TimeoutExpired(command, 300)

    with pytest.raises(notices.DpkgUnavailable, match="could not be run"):
        notices.dpkg_owners(["/usr/lib/libx.so"], missing)
    with pytest.raises(notices.DpkgUnavailable, match="status 2: dpkg: error: bad"):
        notices.dpkg_owners(["/usr/lib/libx.so"], broken)
    with pytest.raises(notices.DpkgUnavailable):
        notices.dpkg_owners(["/usr/lib/libx.so"], slow)


def test_lookup_spellings_try_the_resolved_file_first_and_both_spellings_of_a_merged_usr():
    def realpath(path):
        return path.replace("libz.so.1", "libz.so.1.2.11")

    spellings = notices._lookup_spellings("/lib/x86_64-linux-gnu/libz.so.1", realpath)

    assert spellings == [
        "/lib/x86_64-linux-gnu/libz.so.1.2.11",
        "/usr/lib/x86_64-linux-gnu/libz.so.1.2.11",
        "/lib/x86_64-linux-gnu/libz.so.1",
        "/usr/lib/x86_64-linux-gnu/libz.so.1",
    ]
    # Not a path dpkg could match exactly: never asked (it would read a substring).
    assert notices._lookup_spellings("relative/libx.so", lambda path: path) == []
    # A file that is not under a merged directory has only its own spellings.
    assert notices._lookup_spellings("/opt/x/libx.so", lambda path: path) == ["/opt/x/libx.so"]


def test_each_library_is_listed_with_its_debian_package_and_that_packages_copyright(tmp_path):
    write_copyright(tmp_path, "libnss3", "NSS is MPL-2.0\r\nsecond line\r\n")
    write_copyright(tmp_path, "libasound2", "ALSA is LGPL-2.1+")
    owned = {
        f"{LIB_DIR}/libnss3.so": ["libnss3"],
        f"{LIB_DIR}/libasound.so.2": ["libasound2"],
    }

    system = collect(
        {"gui": [library("libnss3.so"), library("libasound.so.2")]}, owned, tmp_path
    )

    assert system.dpkg_problem == ""
    assert [(lib.name, lib.packages) for lib in system.libraries] == [
        ("libasound.so.2", ("libasound2",)),
        ("libnss3.so", ("libnss3",)),
    ]
    assert [(p.name, p.libraries, p.copyright_text) for p in system.packages] == [
        ("libasound2", ["libasound.so.2"], "ALSA is LGPL-2.1+"),
        ("libnss3", ["libnss3.so"], "NSS is MPL-2.0\nsecond line"),
    ]


def test_several_libraries_of_one_package_share_one_copyright_block(tmp_path):
    write_copyright(tmp_path, "libnss3", "NSS licence text")
    write_copyright(tmp_path, "libglib2.0-0", "GLib licence text")
    owned = {
        f"{LIB_DIR}/libnss3.so": ["libnss3"],
        f"{LIB_DIR}/libnssutil3.so": ["libnss3"],
        f"{LIB_DIR}/libsmime3.so": ["libnss3"],
        f"{LIB_DIR}/libglib-2.0.so.0": ["libglib2.0-0"],
    }
    entries = [library(name) for name in ("libnss3.so", "libnssutil3.so", "libsmime3.so", "libglib-2.0.so.0")]

    system = collect({"gui": entries, "helper": entries[:2]}, owned, tmp_path)
    text = notices.render([], system)

    assert [p.name for p in system.packages] == ["libglib2.0-0", "libnss3"]
    assert system.packages[1].libraries == ["libnss3.so", "libnssutil3.so", "libsmime3.so"]
    assert text.count("NSS licence text") == 1
    assert text.count("libnss3 (Debian package)") == 1
    assert "Bundled files: libnss3.so, libnssutil3.so, libsmime3.so" in text
    # Counterpart: two packages do get two blocks.
    assert text.count("GLib licence text") == 1 and text.count("(Debian package)") == 2


XCB_SAME_TEXT = "Copyright (C) the X.Org Foundation\nPermission is hereby granted, free of charge"


def xcb_packages(tmp_path, texts):
    """Three binary packages built from one source, with the copyright text in *texts*."""
    owned = {}
    entries = []
    for package, library_name in (
        ("libxcb-shm0", "libxcb-shm.so.0"),
        ("libxcb-randr0", "libxcb-randr.so.0"),
        ("libxcb-xkb1", "libxcb-xkb.so.1"),
        ("libnss3", "libnss3.so"),
    ):
        owned[f"{LIB_DIR}/{library_name}"] = [package]
        entries.append(library(library_name))
        if package in texts:
            write_copyright(tmp_path, package, texts[package])
    return collect({"gui": entries}, owned, tmp_path), entries


def test_binary_packages_with_the_same_copyright_text_print_it_once_and_point_back(tmp_path):
    texts = {name: XCB_SAME_TEXT for name in ("libxcb-shm0", "libxcb-randr0", "libxcb-xkb1")}
    texts["libnss3"] = "NSS licence text"
    system, _ = xcb_packages(tmp_path, texts)

    text = notices.render([], system)

    base = tmp_path.as_posix()
    first = f"{base}/libxcb-randr0/copyright"  # the first of the three by name
    assert text.count("Copyright (C) the X.Org Foundation") == 1
    assert f"--- {first} ---\n{XCB_SAME_TEXT}" in text
    for later in ("libxcb-shm0", "libxcb-xkb1"):
        assert f"--- {base}/{later}/copyright (same text as {first}, above) ---" in text
    # Every package keeps its own block and its bundled files.
    assert text.count("(Debian package)") == 4
    assert "Bundled files: libxcb-shm.so.0\n" in text
    assert "Bundled files: libxcb-xkb.so.1\n" in text
    # Counterpart: a text that differs is printed in full.
    assert text.count("NSS licence text") == 1
    assert f"--- {base}/libnss3/copyright ---\nNSS licence text" in text


def test_copyright_texts_that_differ_are_all_printed_in_full(tmp_path):
    texts = {
        "libxcb-shm0": XCB_SAME_TEXT,
        "libxcb-randr0": XCB_SAME_TEXT + " (with a difference)",
        "libxcb-xkb1": XCB_SAME_TEXT + "\nand a third wording",
        "libnss3": "NSS licence text",
    }
    system, _ = xcb_packages(tmp_path, texts)

    text = notices.render([], system)

    assert "same text as" not in text
    assert text.count("Copyright (C) the X.Org Foundation") == 3


def test_a_missing_copyright_file_is_not_mistaken_for_a_repeat(tmp_path):
    texts = {"libxcb-shm0": XCB_SAME_TEXT, "libxcb-randr0": XCB_SAME_TEXT, "libnss3": "NSS"}
    system, _ = xcb_packages(tmp_path, texts)  # libxcb-xkb1 has no file

    text = notices.render([], system)

    base = tmp_path.as_posix()
    assert f"No copyright text was found at {base}/libxcb-xkb1/copyright." in text
    assert text.count("same text as") == 1  # only libxcb-shm0 pointing at libxcb-randr0


def test_the_copyright_repeats_do_not_depend_on_the_order_of_the_libraries(tmp_path):
    texts = {name: XCB_SAME_TEXT for name in ("libxcb-shm0", "libxcb-randr0", "libxcb-xkb1")}
    texts["libnss3"] = "NSS licence text"
    system, entries = xcb_packages(tmp_path, texts)
    owned = {f"{LIB_DIR}/{name}": [package] for name, package in (
        ("libxcb-shm.so.0", "libxcb-shm0"),
        ("libxcb-randr.so.0", "libxcb-randr0"),
        ("libxcb-xkb.so.1", "libxcb-xkb1"),
        ("libnss3.so", "libnss3"),
    )}

    shuffled = collect({"helper": entries[::-1]}, owned, tmp_path)

    assert notices.render([], system) == notices.render([], shuffled)


def test_a_copyright_text_equal_to_a_python_license_text_points_at_it(site, tmp_path):
    shared = "The shared license text, long enough to notice."
    make_dist(site, "noticetest-app", requires=("noticetest-lib",))
    make_dist(site, "noticetest-lib", files={"LICENSE": (shared + "\n").encode()})
    write_copyright(tmp_path, "libnss3", shared)
    system = collect(
        {"gui": [library("libnss3.so")]}, {f"{LIB_DIR}/libnss3.so": ["libnss3"]}, tmp_path
    )

    text, _ = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], system_libraries=system, platform="linux"
    )

    assert text.count(shared) == 1
    base = tmp_path.as_posix()
    assert (
        f"--- {base}/libnss3/copyright (same text as LICENSE of noticetest-lib 1.0, above) ---"
        in text
    )


def test_a_library_no_package_owns_is_said_to_be_unowned_and_gets_no_invented_package(tmp_path):
    write_copyright(tmp_path, "libnss3", "NSS licence text")
    owned = {f"{LIB_DIR}/libnss3.so": ["libnss3"]}

    system = collect({"gui": [library("libnss3.so"), library("libodd.so.1")]}, owned, tmp_path)
    text = notices.render([], system)

    assert dict((lib.name, lib.packages) for lib in system.libraries)["libodd.so.1"] == ()
    assert [p.name for p in system.packages] == ["libnss3"]
    assert "libodd.so.1 - no Debian package owns this file" in text
    assert "libnss3.so - libnss3\n" in text


def test_a_missing_copyright_file_is_reported_instead_of_papered_over(tmp_path):
    write_copyright(tmp_path, "libnss3", "NSS licence text")
    owned = {f"{LIB_DIR}/libnss3.so": ["libnss3"], f"{LIB_DIR}/libx.so": ["libgone"]}

    system = collect({"gui": [library("libnss3.so"), library("libx.so")]}, owned, tmp_path)
    text = notices.render([], system)

    gone = {p.name: p for p in system.packages}["libgone"]
    assert gone.copyright_text is None
    assert f"No copyright text was found at {tmp_path.as_posix()}/libgone/copyright." in text
    assert "NSS licence text" in text  # the package that has one is unaffected


def test_a_package_name_that_could_leave_the_doc_folder_is_never_read(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    write_copyright(tmp_path, "secret", "not a copyright file")  # doc/../secret/copyright
    owned = {f"{LIB_DIR}/libx.so": ["../secret"]}

    system = collect({"gui": [library("libx.so")]}, owned, doc)

    assert (doc / ".." / "secret" / "copyright").is_file()
    # Two layers refuse it: the reading of dpkg's answer does not accept the
    # name as a package, and the reading of the file would not follow it either.
    assert notices.parse_dpkg_search("../secret:amd64: /usr/lib/libx.so\n") == {}
    assert system.packages == []
    assert notices.read_debian_copyright("../secret", doc)[1] is None
    # Counterpart: a plain package name is read from the same kind of place.
    assert notices.read_debian_copyright("secret", tmp_path)[1] == "not a copyright file"


# --- the standard license texts that copyright files point to ----------------

OWNED_BY_GLIB_AND_ALSA = {
    f"{LIB_DIR}/libglib-2.0.so.0": ["libglib2.0-0"],
    f"{LIB_DIR}/libasound.so.2": ["libasound2"],
}


def glib_and_alsa(tmp_path, glib_text, alsa_text, licenses_root):
    write_copyright(tmp_path, "libglib2.0-0", glib_text)
    write_copyright(tmp_path, "libasound2", alsa_text)
    entries = [library("libglib-2.0.so.0"), library("libasound.so.2")]
    return collect(
        {"gui": entries}, OWNED_BY_GLIB_AND_ALSA, tmp_path, licenses_root=licenses_root
    )


def test_references_to_common_licenses_are_found_by_their_plain_file_name():
    text = (
        "On Debian systems the full text of the GNU Lesser General Public License\n"
        "can be found in /usr/share/common-licenses/LGPL-2.1.\n"
        "See also '/usr/share/common-licenses/GPL-3' and (/usr/share/common-licenses/Apache-2.0),\n"
        "/usr/share/common-licenses/GPL-3 again, /usr/share/common-licenses/MPL-2.0;\n"
        "and /usr/share/common-licenses/BSD."
    )

    assert notices.common_license_references(text) == [
        "Apache-2.0",
        "BSD",
        "GPL-3",
        "LGPL-2.1",
        "MPL-2.0",
    ]
    assert notices.common_license_references("no reference in this text") == []


@pytest.mark.parametrize(
    "text",
    [
        "/usr/share/common-licenses/../../etc/passwd",
        "/usr/share/common-licenses/..",
        "/usr/share/common-licenses/.hidden",
        "/usr/share/common-licenses/sub/dir/GPL-3",
        "/usr/share/common-licenses/",
        "/usr/share/common-licenses",
        "/usr/share/other-licenses/GPL-3",
    ],
    ids=["parent folders", "parent", "dot file", "sub folder", "no name", "no slash", "other folder"],
)
def test_text_that_is_not_a_plain_file_name_under_the_folder_is_not_a_reference(text):
    assert notices.common_license_references(text) == []
    # Counterpart: the same folder with a plain name is a reference.
    assert notices.common_license_references(text + "\nsee /usr/share/common-licenses/GPL-3") == [
        "GPL-3"
    ]


def test_a_license_name_that_is_not_a_plain_file_name_is_never_read(tmp_path):
    root = tmp_path / "licenses"
    write_common_license(root, "GPL-3", "GPL text")
    write_common_license(root, ".secret", "secret in the folder")
    write_common_license(root / "sub", "GPL-3", "secret in a sub folder")
    (tmp_path / "secret").write_text("secret beside the folder", encoding="utf-8")

    for unsafe in ("../secret", "sub/GPL-3", "..", ".", "", ".secret", "GPL-3/../../secret"):
        assert notices.read_common_license(unsafe, root).text is None, unsafe
    # Counterpart: the files exist and a plain name reads fine.
    assert (root / ".." / "secret").is_file() and (root / "sub" / "GPL-3").is_file()
    assert notices.read_common_license("GPL-3", root).text == "GPL text"


def test_each_referenced_license_text_is_copied_once_after_the_packages_sorted_by_name(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "LGPL-2.1", "Full LGPL 2.1 text\r\nsecond line\r\n")
    write_common_license(licenses, "GPL-3", "Full GPL 3 text")
    system = glib_and_alsa(
        tmp_path,
        "GLib: see /usr/share/common-licenses/LGPL-2.1 and /usr/share/common-licenses/GPL-3.",
        "ALSA: see /usr/share/common-licenses/LGPL-2.1.",
        licenses,
    )

    text = notices.render([], system)

    assert [(lic.name, lic.text) for lic in system.licenses] == [
        ("GPL-3", "Full GPL 3 text"),
        ("LGPL-2.1", "Full LGPL 2.1 text\nsecond line"),
    ]
    assert text.count("Full LGPL 2.1 text") == 1 and text.count("Full GPL 3 text") == 1
    assert "\r" not in text
    base = licenses.as_posix()
    assert (
        text.index("libasound2 (Debian package)")
        < text.index("libglib2.0-0 (Debian package)")
        < text.index(notices.REFERENCED_LICENSES_TITLE + "\n")
        < text.index(f"--- {base}/GPL-3 ---")
        < text.index(f"--- {base}/LGPL-2.1 ---")
    )


def test_without_references_there_is_no_referenced_licenses_subsection(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "GPL-3", "Full GPL 3 text")
    system = glib_and_alsa(tmp_path, "GLib: no reference here", "ALSA: none either", licenses)

    text = notices.render([], system)

    assert system.licenses == []
    assert notices.REFERENCED_LICENSES_TITLE not in text.split("\n")
    assert "Full GPL 3 text" not in text  # present on disk, but nobody asked for it


def test_a_referenced_license_text_that_is_not_there_is_reported_not_invented(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "GPL-3", "Full GPL 3 text")
    system = glib_and_alsa(
        tmp_path,
        "GLib: see /usr/share/common-licenses/LGPL-2.1 and /usr/share/common-licenses/GPL-3.",
        "ALSA: nothing",
        licenses,
    )

    text = notices.render([], system)

    assert {lic.name: lic.text for lic in system.licenses} == {
        "GPL-3": "Full GPL 3 text",
        "LGPL-2.1": None,
    }
    assert f"Not found at {licenses.as_posix()}/LGPL-2.1." in text
    assert "Full GPL 3 text" in text  # the one that exists is unaffected


def test_a_dot_zero_reference_falls_back_to_the_file_without_it(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "GPL-2", "Full GPL 2 text")
    write_common_license(licenses, "GPL-3", "Full GPL 3 text")
    write_common_license(licenses, "LGPL-2.1", "Full LGPL 2.1 text")
    system = glib_and_alsa(
        tmp_path,
        "Pango: /usr/share/common-licenses/GPL-2.0 and /usr/share/common-licenses/GPL-3.0",
        "ALSA: /usr/share/common-licenses/LGPL-2.1",
        licenses,
    )

    text = notices.render([], system)

    assert {lic.name: lic.text for lic in system.licenses} == {
        "GPL-2.0": "Full GPL 2 text",
        "GPL-3.0": "Full GPL 3 text",
        "LGPL-2.1": "Full LGPL 2.1 text",
    }
    base = licenses.as_posix()
    assert f"--- {base}/GPL-2 ---" in text and f"--- {base}/GPL-3 ---" in text
    assert "Not found" not in text


def test_the_dot_zero_fallback_prefers_the_exact_name_and_does_not_hide_a_missing_text(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "Apache-2.0", "Apache text")
    write_common_license(licenses, "Apache-2", "wrong file")
    write_common_license(licenses, "LGPL-2", "must not stand in for LGPL-2.1")

    assert notices.read_common_license("Apache-2.0", licenses).text == "Apache text"
    missing = notices.read_common_license("GPL-2.0", licenses)
    assert missing.text is None
    assert missing.path == f"{licenses.as_posix()}/GPL-2.0"
    # Only a trailing ".0" is dropped: LGPL-2.1 has no fallback.
    assert notices.read_common_license("LGPL-2.1", licenses).text is None


def test_a_reference_that_climbs_out_of_the_folder_is_ignored_even_when_the_target_exists(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "GPL-3", "Full GPL 3 text")
    (tmp_path / "secret").write_text("text that must not be copied", encoding="utf-8")
    system = glib_and_alsa(
        tmp_path,
        "GLib: /usr/share/common-licenses/../secret and /usr/share/common-licenses/GPL-3",
        "ALSA: nothing",
        licenses,
    )

    text = notices.render([], system)

    assert (licenses / ".." / "secret").is_file()
    assert [lic.name for lic in system.licenses] == ["GPL-3"]
    assert "must not be copied" not in text


def test_a_referenced_text_equal_to_one_printed_earlier_is_not_repeated(site, tmp_path):
    shared = "The shared license text, long enough to notice."
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "GPL", shared)  # the link to GPL-3 reads the same
    write_common_license(licenses, "GPL-3", shared)
    write_common_license(licenses, "Zlib", "A different license text")
    make_dist(site, "noticetest-app", requires=("noticetest-lib",))
    make_dist(site, "noticetest-lib", files={"LICENSE": (shared + "\n").encode()})
    system = glib_and_alsa(
        tmp_path,
        "GLib: /usr/share/common-licenses/GPL, /usr/share/common-licenses/GPL-3",
        "ALSA: /usr/share/common-licenses/Zlib",
        licenses,
    )

    text, _ = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], system_libraries=system, platform="linux"
    )

    base = licenses.as_posix()
    assert text.count(shared) == 1  # printed with the package, nowhere else
    assert f"--- {base}/GPL (same text as LICENSE of noticetest-lib 1.0, above) ---" in text
    assert f"--- {base}/GPL-3 (same text as LICENSE of noticetest-lib 1.0, above) ---" in text
    assert text.count("A different license text") == 1  # different text is printed in full


def test_two_referenced_texts_that_are_equal_to_each_other_are_printed_once(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "GPL", "Same words in both files")
    write_common_license(licenses, "GPL-3", "Same words in both files")
    write_common_license(licenses, "LGPL-3", "Other words entirely")
    system = glib_and_alsa(
        tmp_path,
        "GLib: /usr/share/common-licenses/GPL, /usr/share/common-licenses/GPL-3",
        "ALSA: /usr/share/common-licenses/LGPL-3",
        licenses,
    )

    text = notices.render([], system)

    base = licenses.as_posix()
    assert text.count("Same words in both files") == 1
    assert f"--- {base}/GPL-3 (same text as {base}/GPL, above) ---" in text
    assert text.count("Other words entirely") == 1


def test_the_referenced_licenses_do_not_depend_on_the_order_of_references_or_packages(tmp_path):
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "GPL-3", "Full GPL 3 text")
    write_common_license(licenses, "LGPL-2.1", "Full LGPL 2.1 text")
    refs = "/usr/share/common-licenses/GPL-3 /usr/share/common-licenses/LGPL-2.1"
    reversed_refs = "/usr/share/common-licenses/LGPL-2.1 /usr/share/common-licenses/GPL-3"

    def referenced_part(system):
        text = notices.render([], system)
        return text[text.index(notices.REFERENCED_LICENSES_TITLE + "\n") :]

    forward = glib_and_alsa(tmp_path, f"GLib: {refs}", "ALSA: nothing", licenses)
    again = glib_and_alsa(tmp_path, f"GLib: {refs}", "ALSA: nothing", licenses)
    # The references sit in another package, in another order.
    backward = glib_and_alsa(tmp_path, "GLib: nothing", f"ALSA: {reversed_refs}", licenses)
    write_common_license(licenses, "GPL-3", "Edited GPL 3 text")
    edited = glib_and_alsa(tmp_path, f"GLib: {refs}", "ALSA: nothing", licenses)

    assert notices.render([], forward) == notices.render([], again)
    assert referenced_part(forward) == referenced_part(backward)
    assert referenced_part(forward) != referenced_part(edited)


def test_the_owner_is_found_under_the_other_spelling_of_a_merged_usr_and_through_symlinks(tmp_path):
    write_copyright(tmp_path, "zlib1g", "zlib licence")
    # The loader reported the symlink under /lib; dpkg lists the real file
    # under /usr/lib.
    owned = {f"{LIB_DIR}/libz.so.1.2.11": ["zlib1g"]}
    entry = ("libz.so.1", "/lib/x86_64-linux-gnu/libz.so.1", "BINARY")

    def realpath(path):
        return path.replace("/lib/x86_64-linux-gnu/libz.so.1", "/lib/x86_64-linux-gnu/libz.so.1.2.11")

    found = collect({"gui": [entry]}, owned, tmp_path, realpath=realpath)
    unknown = collect({"gui": [entry]}, {f"{LIB_DIR}/libother.so": ["other"]}, tmp_path)

    assert found.libraries == [notices.SystemLibrary("libz.so.1", ("zlib1g",))]
    assert unknown.libraries == [notices.SystemLibrary("libz.so.1", ())]


def test_without_dpkg_the_libraries_are_still_listed_and_the_text_says_why_no_package_is_known(
    tmp_path,
):
    def no_dpkg(command, **_options):
        raise FileNotFoundError(2, "No such file or directory: 'dpkg'")

    system = REAL_COLLECT(
        {"gui": [library("libnss3.so")]},
        roots=[],
        run=no_dpkg,
        realpath=lambda path: path,
        doc_root=tmp_path,
    )
    text = notices.render([], system)

    assert [lib.name for lib in system.libraries] == ["libnss3.so"]
    assert system.packages == []
    assert "dpkg could not be run" in system.dpkg_problem
    assert "The owning packages could not be determined: dpkg could not be run" in text
    assert "libnss3.so - package unknown (dpkg could not be used on the build machine)" in text
    assert "no Debian package owns this file" not in text  # nobody checked, so nobody says it


def test_the_result_does_not_depend_on_the_order_of_the_analyses_or_their_entries(tmp_path):
    write_copyright(tmp_path, "libnss3", "NSS licence text")
    # The helper packs libnss3 from another place, owned by another package;
    # the smaller path must win whichever analysis is read first.
    owned = {
        f"{LIB_DIR}/libnss3.so": ["libnss3"],
        "/opt/lib/libnss3.so": ["libnss3-opt"],
        f"{LIB_DIR}/libz.so.1": ["zlib1g"],
    }
    first = [library("libnss3.so"), library("libz.so.1")]
    second = [library("libz.so.1"), library("libnss3.so", "/opt/lib")]

    forward = collect({"gui": first, "helper": second}, owned, tmp_path)
    backward = collect({"helper": second[::-1], "gui": first[::-1]}, owned, tmp_path)
    different = collect({"gui": first[:1]}, owned, tmp_path)

    assert notices.render([], forward) == notices.render([], backward)
    assert notices.render([], forward) != notices.render([], different)
    assert [lib.name for lib in forward.libraries] == ["libnss3.so", "libz.so.1"]
    assert forward.libraries[0].packages == ("libnss3-opt",)
    assert different.libraries[0].packages == ("libnss3",)


def test_a_name_packed_from_two_places_in_one_analysis_resolves_to_the_smaller_path():
    entries = [
        ("libx.so", "/b/libx.so", "BINARY"),
        ("libx.so", "/a/libx.so", "BINARY"),
    ]

    assert notices.bundled_system_libraries(entries, roots=[]) == {"libx.so": "/a/libx.so"}
    assert notices.bundled_system_libraries(entries[::-1], roots=[]) == {"libx.so": "/a/libx.so"}


def test_the_system_libraries_section_is_written_after_the_packages_and_read_back(site, tmp_path):
    write_copyright(tmp_path, "libnss3", "NSS licence text")
    make_dist(site, "noticetest-app", requires=("noticetest-lib",))
    make_dist(site, "noticetest-lib", files={"LICENSE": b"lib\n"})
    owned = {f"{LIB_DIR}/libnss3.so": ["libnss3"]}
    system = collect({"gui": [library("libnss3.so"), library("libodd.so")]}, owned, tmp_path)

    text, _ = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], system_libraries=system, platform="linux"
    )

    assert text.index("noticetest-lib 1.0\n=") < text.index(notices.SYSTEM_LIBRARIES_TITLE)
    assert notices.listed_component_names(text) == [
        "python",
        *CPYTHON_COMPONENTS_BY_PLATFORM["linux"],
        "noticetest-lib",
    ]
    assert notices.listed_system_library_names(text) == ["libnss3.so", "libodd.so"]
    assert "\r" not in text and text.endswith("\n") and not text.endswith("\n\n")


def test_no_section_is_written_without_system_libraries(site):
    make_dist(site, "noticetest-app")

    plain, _ = build("noticetest-app")
    empty, _ = notices.build_notices(
        "noticetest-app",
        (),
        (),
        python_dirs=[],
        system_libraries=notices.SystemLibraries([], []),
        platform="linux",
    )
    with_one, _ = notices.build_notices(
        "noticetest-app",
        (),
        (),
        python_dirs=[],
        system_libraries=notices.SystemLibraries([notices.SystemLibrary("libx.so")], []),
    )

    assert notices.SYSTEM_LIBRARIES_TITLE not in plain
    assert empty == plain
    assert notices.SYSTEM_LIBRARIES_TITLE in with_one
    assert notices.listed_system_library_names(plain) is None


@pytest.mark.parametrize(
    "broken",
    [
        notices.SYSTEM_LIBRARIES_TITLE + "\nno index here\n",
        notices.SYSTEM_LIBRARIES_TITLE + "\nSystem libraries (1)\nnot a rule\nlibx.so - pkg\n",
        notices.SYSTEM_LIBRARIES_TITLE + "\nSystem libraries (2)\n" + "-" * 80 + "\nlibx.so - pkg\n",
        notices.SYSTEM_LIBRARIES_TITLE + "\nSystem libraries (1)\n" + "-" * 80 + "\nlibx.so\n",
    ],
    ids=["no index", "no rule", "wrong count", "no reason"],
)
def test_a_damaged_system_libraries_section_is_rejected(broken):
    with pytest.raises(ValueError):
        notices.listed_system_library_names(broken)


def test_main_adds_the_section_on_linux_and_writes_the_same_bytes_twice(tmp_path, monkeypatch):
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(repr(([library("libnss3.so")],)), encoding="utf-8")
    write_copyright(
        tmp_path / "doc", "libnss3", "NSS licence text, see /usr/share/common-licenses/MPL-2.0."
    )
    licenses = tmp_path / "common-licenses"
    write_common_license(licenses, "MPL-2.0", "Mozilla Public License text")
    seen = []

    def collect_fake(analyses):
        seen.append(analyses)
        return collect(
            analyses,
            {f"{LIB_DIR}/libnss3.so": ["libnss3"]},
            tmp_path / "doc",
            licenses_root=licenses,
        )

    monkeypatch.setattr(notices, "is_linux", lambda: True)
    monkeypatch.setattr(notices, "collect_system_libraries", collect_fake)
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"

    assert notices.main([str(first), str(toc)]) == 0
    assert notices.main([str(second), str(toc)]) == 0

    text = first.read_text(encoding="utf-8")
    assert first.read_bytes() == second.read_bytes()
    assert b"\r" not in first.read_bytes()
    assert notices.listed_system_library_names(text) == ["libnss3.so"]
    assert "NSS licence text" in text
    assert "Mozilla Public License text" in text
    assert [list(analyses) for analyses in seen] == [[str(toc)], [str(toc)]]


def test_main_does_not_add_the_section_away_from_linux_or_without_the_analyses(
    tmp_path, monkeypatch
):
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(repr(([library("libnss3.so")],)), encoding="utf-8")
    asked = []

    def collect_fake(analyses):
        asked.append(analyses)
        return collect(analyses, {f"{LIB_DIR}/libnss3.so": ["libnss3"]}, tmp_path / "doc")

    monkeypatch.setattr(notices, "collect_system_libraries", collect_fake)

    monkeypatch.setattr(notices, "is_linux", lambda: False)
    other = tmp_path / "other-os.txt"
    assert notices.main([str(other), str(toc)]) == 0
    monkeypatch.setattr(notices, "is_linux", lambda: True)
    no_analyses = tmp_path / "no-analyses.txt"
    assert notices.main([str(no_analyses)]) == 0

    assert asked == []
    for written in (other, no_analyses):
        lines = written.read_text(encoding="utf-8").split("\n")
        assert notices.SYSTEM_LIBRARIES_TITLE not in lines
        assert notices.REFERENCED_LICENSES_TITLE not in lines
    # Counterpart: on Linux, given the analysis, the collector is asked and the
    # section appears.
    linux = tmp_path / "linux.txt"
    assert notices.main([str(linux), str(toc)]) == 0
    assert len(asked) == 1
    assert notices.SYSTEM_LIBRARIES_TITLE in linux.read_text(encoding="utf-8")


def test_main_fails_without_writing_when_an_analysis_cannot_be_read_on_linux(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(notices, "is_linux", lambda: True)
    output = tmp_path / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output), str(tmp_path / "absent.toc")]) == 1

    assert "cannot read the PyInstaller analysis" in capsys.readouterr().err
    assert not output.exists()


def test_main_warns_but_succeeds_when_dpkg_could_not_be_used(tmp_path, monkeypatch, capsys):
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(repr(([library("libnss3.so")],)), encoding="utf-8")

    def no_dpkg(command, **_options):
        raise FileNotFoundError(2, "No such file or directory: 'dpkg'")

    monkeypatch.setattr(notices, "is_linux", lambda: True)
    monkeypatch.setattr(
        notices,
        "collect_system_libraries",
        lambda analyses: REAL_COLLECT(
            analyses, roots=[], run=no_dpkg, realpath=lambda path: path, doc_root=tmp_path
        ),
    )
    output = tmp_path / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output), str(toc)]) == 0

    assert "the Debian packages of the system libraries are unknown" in capsys.readouterr().err
    assert "libnss3.so - package unknown" in output.read_text(encoding="utf-8")


# --- the real environment --------------------------------------------------


@pytest.fixture(scope="module")
def real_packages():
    return {package.canonical_name: package for package in notices.collect_packages()}


def test_pyqt6_is_listed_with_its_gpl_text(real_packages):
    for name in ("pyqt6", "pyqt6-webengine", "pyqt6-qt6", "pyqt6-webengine-qt6"):
        assert name in real_packages, name

    pyqt6 = real_packages["pyqt6"]
    # Metadata spelling varies between PyQt6 releases (SPDX id or classifier).
    assert "GPL" in pyqt6.declaration
    assert "GNU GENERAL PUBLIC LICENSE" in pyqt6.texts[0].text
    assert "Version 3, 29 June 2007" in pyqt6.texts[0].text
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in real_packages["pyqt6-qt6"].texts[0].text


def test_the_embedded_build_tools_are_listed_but_the_project_and_dev_tools_are_not(real_packages):
    # PyInstaller's bootloader and runtime hooks, and the contrib hooks, are
    # embedded in the executables. setuptools is kept out of them by
    # --exclude-module, and packaging stays out together with it (neither build
    # script excludes packaging on its own); tools/check_bundled_notices.py
    # fails the build if either gets in.
    for build_tool in ("pyinstaller", "pyinstaller-hooks-contrib"):
        assert build_tool in real_packages, build_tool
    assert notices.PROJECT not in real_packages
    for dev_only in ("pytest", "pytest-qt", "responses"):
        assert dev_only not in real_packages, dev_only


def test_asking_for_the_dev_extra_would_be_noticed():
    # The check above is only meaningful if the dev extra really does pull
    # these in; this is the deliberately broken configuration.
    with_dev = {p.canonical_name for p in notices.collect_packages(extras=("dev",))}

    assert "pytest" in with_dev
    assert "dev" not in notices.SHIPPED_EXTRAS


def test_the_real_notices_text_has_no_entry_for_the_project_and_has_the_upstream_notice():
    text, _ = notices.build_notices()

    assert notices.PROJECT not in notices.listed_component_names(text)
    assert notices.UPSTREAM_NOTICE_TITLE in text


def test_main_writes_utf8_lf_and_the_same_bytes_twice(tmp_path):
    first = tmp_path / "first" / "THIRD_PARTY_NOTICES.txt"
    second = tmp_path / "second.txt"

    assert notices.main([str(first)]) == 0
    assert notices.main([str(second)]) == 0

    data = first.read_bytes()
    assert data == second.read_bytes()
    data.decode("utf-8")
    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in data
    assert data.endswith(b"\n")
    assert b"PyQt6 " in data and b"GNU GENERAL PUBLIC LICENSE" in data
    assert f"Python {sys.version.split()[0]} - ".encode() in data


# --- the components CPython bundles (expat, libmpdec, mimalloc, HACL*, OpenSSL) ---


def test_the_cpython_component_files_are_the_pinned_upstream_bytes():
    for name, expected in CPYTHON_COMPONENT_SHA256.items():
        raw = (ARCHIVED_DIR / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected, name
        raw.decode("utf-8")  # clean UTF-8, as archived_license_for() demands
        assert b"\0" not in raw, name


@pytest.mark.parametrize("platform", sorted(notices.PYTHON_BUNDLED_LICENSES))
def test_every_cpython_component_entry_has_a_pinned_source_and_a_role_label(platform):
    for component in notices.PYTHON_BUNDLED_LICENSES[platform]:
        for entry in component.licenses:
            assert Path(entry.file).name in CPYTHON_COMPONENT_SHA256, component.name
            assert (Path(notices.REPO_ROOT) / entry.file).is_file(), component.name
            # A fixed commit, not a branch or a movable tag.
            assert re.search(r"/blob/[0-9a-f]{40}/", entry.source_url), component.name
        # Only a component without an archived text of its own (OpenSSL) has no URL.
        assert ("{url}" in component.note) == (component.license is not None), component.name
        # The label names a role: a version belongs in the note and the URL only.
        assert component.version_label.startswith(("(used-by-CPython-", "(Doc-license"))
        assert not re.search(r"\d", component.version_label), component.name


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_each_platform_lists_its_cpython_components_with_their_full_license_texts(site, platform):
    make_dist(site, "noticetest-app")

    text, _ = notices.build_notices("noticetest-app", (), (), python_dirs=[], platform=platform)

    for component in notices.PYTHON_BUNDLED_LICENSES[platform]:
        for entry in component.licenses:
            raw = (Path(notices.REPO_ROOT) / entry.file).read_bytes()
            assert notices._normalise_text(raw) in text, component.name
            assert entry.source_url in text, component.name
    assert "expat (used-by-CPython-pyexpat) - MIT" in text
    assert "mpdecimal (used-by-CPython-_decimal) - BSD-2-Clause" in text
    assert "HACL* (used-by-CPython-hashlib) - MIT" in text
    assert "CPython-incorporated-software (Doc-license.rst) - various, see text" in text


def test_a_platform_carries_only_its_own_cpython_components(site):
    make_dist(site, "noticetest-app")
    texts = {
        platform: notices.build_notices(
            "noticetest-app", (), (), python_dirs=[], platform=platform
        )[0]
        for platform in ("win32", "darwin", "linux")
    }
    bundled = notices.PYTHON_BUNDLED_LICENSES
    mimalloc = bundled["win32"][2].license.source_url
    mpdecimal_400 = bundled["win32"][1].license.source_url
    mpdecimal_251 = bundled["linux"][1].license.source_url

    # macOS builds CPython with --with-mimalloc=no; only macOS ships OpenSSL itself.
    assert mimalloc in texts["win32"] and mimalloc in texts["linux"]
    assert mimalloc not in texts["darwin"]
    assert "mimalloc (used-by" not in texts["darwin"]
    assert "OpenSSL (used-by-CPython-ssl-and-hashlib) - Apache-2.0" in texts["darwin"]
    assert "OpenSSL (used-by" not in texts["win32"]
    assert "OpenSSL (used-by" not in texts["linux"]
    # Linux carries libmpdec 2.5.1, the others the 4.0.0 text.
    assert mpdecimal_251 in texts["linux"]
    assert mpdecimal_251 not in texts["win32"] and mpdecimal_251 not in texts["darwin"]
    assert mpdecimal_400 in texts["win32"] and mpdecimal_400 in texts["darwin"]
    assert mpdecimal_400 not in texts["linux"]
    assert "Anthony Green" not in texts["linux"]  # still no libffi text on Linux
    # The kqueue notice (code compiled only on macOS) is macOS's alone; the
    # others of CPython's own incorporated code are in all three.
    assert "Copyright (c) 2000 Doug White" in texts["darwin"]
    assert "Doug White" not in texts["win32"] and "Doug White" not in texts["linux"]
    for text in texts.values():
        assert "Copyright (C) 1997 - 2002, Makoto Matsumoto" in text  # Mersenne Twister
        assert "UNICODE LICENSE V3" in text
    # Sections for code that is not shipped, or that asks nothing, are not there.
    for text in texts.values():
        assert "Twisted Matrix" not in text  # test_epoll
        assert "WIDE Project" not in text  # getaddrinfo.c, not compiled
        assert "Sam Rushing" not in text  # test.support
        assert "Autonomous Zones" not in text  # trace, not in the bundle
        assert "W3C(R)" not in text  # the C14N test data


def test_the_openssl_entry_is_backed_by_the_apache_license_text_in_the_same_file():
    # The entry has no text of its own and points at the Apache-2.0 text printed
    # under other components, so the real notices of this environment (made of
    # the real dependencies) must carry it whenever the entry is there. A
    # dependency change that dropped the last Apache-2.0 package would fail here.
    text, _ = notices.build_notices(platform="darwin")

    assert "OpenSSL (used-by-CPython-ssl-and-hashlib) - Apache-2.0" in text
    assert "Apache License\n                           Version 2.0, January 2004" in text
    assert "has no NOTICE file" in text


def test_the_macos_libmpdec_note_does_not_claim_the_texts_are_identical():
    note = " ".join(notices.PYTHON_BUNDLED_LICENSES["darwin"][2].note.split())
    assert "uses libmpdec 4.0.1" in note
    assert "is the text of libmpdec 4.0.0" in note
    assert "does not claim that the two texts are identical" in note


def test_the_python_note_points_at_the_components_below_not_only_at_the_docs():
    note = " ".join(notices.PYTHON_NOTE.split())
    assert "are listed as components of their own below" in note
    assert notices._PYTHON_DOCS_LICENSE in note


def test_a_platform_without_an_entry_gets_no_cpython_components():
    assert notices.collect_python_components("freebsd14") == []


def test_the_cpython_components_fail_loudly_when_an_archived_file_is_unusable(tmp_path):
    with pytest.raises(notices.ArchivedLicenseError, match="cannot read the archived license"):
        notices.collect_python_components("linux", root=tmp_path)


# --- the minimum the licenses ask for (2026-11-28) -----------------------------
# One Apache License text, one copy of each MIT/BSD wording, no GPL text that a
# file only reproduces, no history of Python, and the copyleft source offer.

BYTE_BUDGET = 200_000  # the Windows output was 321,185 bytes before, 168,980 after


@pytest.fixture(scope="module")
def real_notices():
    """The notices of this environment: ``(text, components)``."""
    return notices.build_notices()


@pytest.fixture(scope="module")
def apache_text(real_notices):
    """A real Apache License 2.0 file from the installed packages (its body is pinned)."""
    _, components = real_notices
    found = notices.find_shared_apache_text(components)
    assert found is not None, "no installed package ships the Apache License 2.0"
    return found


def dist_text(site, name: str, files: dict[str, str], **kwargs):
    make_dist(
        site,
        name,
        files={path: body.encode("utf-8") for path, body in files.items()},
        **kwargs,
    )


def test_the_pinned_apache_body_digest_matches_the_installed_licenses(apache_text):
    assert notices.apache_body_digest(apache_text) == notices.APACHE_BODY_SHA256
    assert notices.is_apache_license_file(apache_text)
    assert not notices.is_apache_license_file("Apache License\nsomething else entirely")
    changed = apache_text.replace("Grant of Copyright License", "Grant of Copyleft License")
    assert not notices.is_apache_license_file(changed)


def test_the_real_notices_carry_the_apache_license_exactly_once(real_notices):
    text, _ = real_notices

    assert text.count("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION") == 1
    assert text.count(f"--- {notices.APACHE_TITLE} ---") == 1
    assert f"\n{notices.SHARED_TEXTS_TITLE}\n" in text


def test_every_apache_component_keeps_its_copyright_lines_and_its_notice(site, apache_text):
    make_dist(site, "noticetest-app", requires=("noticetest-one", "noticetest-two"))
    dist_text(
        site,
        "noticetest-one",
        {
            "licenses/LICENSE": apache_text + "\n\n   Copyright 2026 Example Person\n",
            "licenses/NOTICE": "Example One\nCopyright 2019 Someone Else\n",
        },
        license_file_entries=("LICENSE",),
        expression="Apache-2.0",
    )
    dist_text(site, "noticetest-two", {"licenses/LICENSE": apache_text}, expression="Apache-2.0")

    text, _ = build("noticetest-app")

    assert text.count("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION") == 1
    assert "   Copyright 2026 Example Person" in text
    assert "Example One\nCopyright 2019 Someone Else" in text
    # Both entries point at the shared text.
    assert text.count(notices.APACHE_POINTER) == 2


def test_an_apache_text_whose_body_differs_is_kept_whole(site, apache_text):
    make_dist(site, "noticetest-app", requires=("noticetest-std", "noticetest-odd"))
    dist_text(site, "noticetest-std", {"licenses/LICENSE": apache_text}, expression="Apache-2.0")
    odd = apache_text.replace("Grant of Patent License", "Grant of Patents License")
    assert odd != apache_text
    dist_text(site, "noticetest-odd", {"licenses/LICENSE": odd}, expression="Apache-2.0")

    text, _ = build("noticetest-app")

    # The standard one is printed once (shared), the odd one in full.
    assert text.count("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION") == 2
    assert "Grant of Patents License" in text


def test_a_file_that_looks_like_apache_but_is_not_the_standard_text_is_not_shortened(site):
    make_dist(site, "noticetest-app", requires=("noticetest-fake",))
    fake = "Apache License\n\nTERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION\nmine\n"
    dist_text(site, "noticetest-fake", {"licenses/LICENSE": fake}, expression="Apache-2.0")

    text, _ = build("noticetest-app")

    assert "\nmine\n" in text
    assert f"\n{notices.SHARED_TEXTS_TITLE}\n" not in text


def test_the_shared_section_is_absent_when_no_component_uses_it(site):
    make_dist(site, "noticetest-app", requires=("noticetest-one",))
    dist_text(site, "noticetest-one", {"licenses/LICENSE": "Some license text.\n"})

    text, _ = build("noticetest-app")

    assert f"\n{notices.SHARED_TEXTS_TITLE}\n" not in text


def test_an_entry_that_needs_the_shared_apache_text_fails_without_it(site):
    make_dist(site, "noticetest-app", requires=("noticetest-one",))
    dist_text(site, "noticetest-one", {"licenses/LICENSE": "Some license text.\n"})
    text, packages = notices.build_notices(
        "noticetest-app", (), (), python_dirs=[], platform="darwin"
    )

    with pytest.raises(notices.SharedLicenseError, match="OpenSSL"):
        notices.check_shared_texts(packages, text)


def test_the_openssl_entry_passes_the_shared_text_check_in_the_real_environment():
    text, packages = notices.build_notices(platform="darwin")

    notices.check_shared_texts(packages, text)
    assert "OpenSSL (used-by-CPython-ssl-and-hashlib) - Apache-2.0" in text


MIT_TEXT = (
    "MIT License\n\n{copyright}\n\nPermission is hereby granted, free of charge, to any "
    "person obtaining a copy\nof this noticetest software and associated documentation files (the "
    '"Software"), to deal\nin the Software without restriction, including without limitation '
    "the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
    "copies of the Software, and to permit persons to whom the Software is\nfurnished to do so, "
    "subject to the following conditions:\n\nThe above copyright notice and this permission "
    "notice shall be included in all\ncopies or substantial portions of the Software.\n"
)


def test_texts_that_differ_only_in_the_copyright_line_share_one_wording(site):
    make_dist(site, "noticetest-app", requires=("noticetest-a", "noticetest-b", "noticetest-c"))
    for name, holder in (("a", "Alice"), ("b", "Bob"), ("c", "Carol")):
        text = MIT_TEXT.format(copyright=f"Copyright (c) 2020 {holder}")
        dist_text(site, f"noticetest-{name}", {"licenses/LICENSE": text}, expression="MIT")

    text, _ = build("noticetest-app")

    assert text.count("of this noticetest software") == 1
    for holder in ("Alice", "Bob", "Carol"):
        assert f"Copyright (c) 2020 {holder}" in text
    assert text.count("only the copyright notice differs") == 2
    assert "LICENSE of noticetest-a 1.0, above" in text


def test_a_wording_that_differs_is_not_merged(site):
    make_dist(site, "noticetest-app", requires=("noticetest-a", "noticetest-b"))
    dist_text(
        site,
        "noticetest-a",
        {"licenses/LICENSE": MIT_TEXT.format(copyright="Copyright (c) 2020 Alice")},
        expression="MIT",
    )
    other = MIT_TEXT.format(copyright="Copyright (c) 2020 Bob").replace("sublicense", "relicense")
    dist_text(site, "noticetest-b", {"licenses/LICENSE": other}, expression="MIT")

    text, _ = build("noticetest-app")

    assert text.count("of this noticetest software") == 2
    assert "only the copyright notice differs" not in text


def test_a_short_text_or_one_without_a_copyright_line_is_not_merged(site):
    make_dist(site, "noticetest-app", requires=("noticetest-a", "noticetest-b", "noticetest-c"))
    short = "Copyright (c) 2020 Alice\nDo what you like.\n"
    dist_text(site, "noticetest-a", {"licenses/LICENSE": short})
    dist_text(site, "noticetest-b", {"licenses/LICENSE": short.replace("Alice", "Bob")})
    body = MIT_TEXT.format(copyright="")
    dist_text(site, "noticetest-c", {"licenses/LICENSE": body})

    text, _ = build("noticetest-app")

    assert text.count("Do what you like.") == 2
    assert text.count("of this noticetest software") == 1


def test_a_sentence_about_the_copyright_notice_is_not_a_copyright_line():
    sentence = "The above copyright notice and this permission notice shall be included"
    assert notices.copyright_lines(sentence) == []
    assert notices.copyright_lines("Copyright (c) 2020 Alice") == ["Copyright (c) 2020 Alice"]
    assert notices.copyright_lines("Copyright © 2019, Encode OSS Ltd.") != []
    assert notices.copyright_lines("Copyright 2019 Kenneth Reitz") != []
    assert notices.copyright_lines("(c) 2008 Somebody") != []
    assert notices.copyright_lines("All rights reserved.") != []
    assert notices.copyright_lines("Copyright [yyyy] [name of copyright owner]") == []


def test_the_real_notices_keep_every_copyright_line_of_every_component(real_notices):
    text, components = real_notices
    # These four lose parts of their files on purpose (the GPL and Apache texts a
    # file reproduces, the history of Python); their lines are checked below.
    trimmed = {"pyinstaller", "pyinstaller-hooks-contrib", "python", "typing-extensions"}
    missing = []
    for package in components:
        if package.canonical_name in trimmed:
            continue
        for license_text in package.texts:
            for line in notices.copyright_lines(license_text.text):
                if line.rstrip() not in text:
                    missing.append((package.title, line))
    assert missing == []
    for package in components:
        section = text.split(f"\n{package.title}\n{notices._RULE}\n", 1)[1]
        assert section.startswith(f"Declared license: {package.declaration}\n"), package.title


def test_the_real_notices_still_list_every_component_that_ships(real_notices):
    # The components of the lock file for this platform, followed from the
    # project itself (its runtime requirements and the "mcp" extra), must all
    # be in the index of the file.
    import tomllib

    from packaging.markers import Marker
    from packaging.utils import canonicalize_name

    lock = tomllib.loads((Path(__file__).resolve().parents[1] / "uv.lock").read_text("utf-8"))
    entries = {canonicalize_name(entry["name"]): entry for entry in lock["package"]}
    root = canonicalize_name(notices.PROJECT)

    def requirements(entry, extra):
        found = list(entry.get("dependencies", ()))
        if extra:
            found += entry.get("optional-dependencies", {}).get(extra, ())
        return found

    wanted: set[str] = set()
    pending = [(root, extra) for extra in ("", *notices.SHIPPED_EXTRAS)]
    seen = set()
    while pending:
        name, extra = pending.pop()
        if (name, extra) in seen:
            continue
        seen.add((name, extra))
        for dependency in requirements(entries[name], extra):
            marker = dependency.get("marker")
            if marker and not Marker(marker).evaluate():
                continue
            dep_name = canonicalize_name(dependency["name"])
            wanted.add(dep_name)
            pending.append((dep_name, ""))
            for dep_extra in dependency.get("extra", ()):
                pending.append((dep_name, dep_extra))
    wanted.discard(root)

    text, _ = real_notices
    listed = set(notices.listed_component_names(text))
    assert wanted - listed == set()
    assert {"pyqt6", "pyqt6-qt6", "requests", "keyring"} <= wanted  # the walk found something


def test_the_real_notices_index_keeps_its_format(real_notices):
    text, components = real_notices

    assert len(notices.listed_component_names(text)) == len(components)
    assert f"Components ({len(components)})\n{notices._THIN_RULE}\n" in text


def test_the_real_notices_stay_under_the_byte_budget(real_notices):
    text, _ = real_notices

    assert len(text.encode("utf-8")) <= BYTE_BUDGET


PACKED_FILES = {
    "licenses/win32/License.txt": "Copyright (c) 1994-2008, Mark Hammond\nwin32 terms\n",
    "licenses/adodbapi/license.txt": "LGPL text for adodbapi\n",
    "licenses/pythonwin/pywin/idle/LICENSE.txt": "PSF text for IDLE\n",
}


def test_pywin32_keeps_only_the_license_of_its_win32_folder(site):
    make_dist(site, "noticetest-app", requires=("pywin32",))
    dist_text(
        site,
        "pywin32",
        PACKED_FILES,
        expression="PSF",
        license_file_entries=("win32/License.txt", "adodbapi/license.txt"),
    )

    text, packages = build("noticetest-app")

    (pywin32,) = [package for package in packages if package.name == "pywin32"]
    assert [license_text.name for license_text in pywin32.texts] == ["win32/License.txt"]
    assert "win32 terms" in text
    assert "LGPL text for adodbapi" not in text and "PSF text for IDLE" not in text


def test_a_listed_license_file_that_is_missing_is_an_error_not_a_skip(site):
    make_dist(site, "noticetest-app", requires=("pywin32",))
    dist_text(site, "pywin32", {"licenses/adodbapi/license.txt": "LGPL\n"}, expression="PSF")

    with pytest.raises(notices.PackedLicenseFileError, match=r"win32/License\.txt"):
        build("noticetest-app")


def test_cryptography_keeps_the_apache_license_and_not_the_bsd_one(site, apache_text):
    make_dist(site, "noticetest-app", requires=("cryptography",))
    dist_text(
        site,
        "cryptography",
        {
            "licenses/LICENSE": "Either of LICENSE.APACHE or LICENSE.BSD.\n",
            "licenses/LICENSE.APACHE": apache_text,
            "licenses/LICENSE.BSD": "Copyright (c) Individual contributors. BSD wording here\n",
        },
        expression="Apache-2.0 OR BSD-3-Clause",
    )

    text, packages = build("noticetest-app")

    (crypto,) = [package for package in packages if package.name == "cryptography"]
    assert [license_text.name for license_text in crypto.texts] == ["LICENSE", "LICENSE.APACHE"]
    assert "BSD wording here" not in text
    assert "uses it under the Apache License 2.0" in " ".join(text.split())


def test_the_filter_table_is_applied_only_to_the_packages_it_names():
    texts = [notices.LicenseText("A", "a"), notices.LicenseText("B", "b")]

    assert notices.packed_license_texts("other", texts) == texts
    assert notices.packed_license_texts("x", texts, {"x": ("B",)}) == [texts[1]]
    with pytest.raises(notices.PackedLicenseFileError, match="C"):
        notices.packed_license_texts("x", texts, {"x": ("C",)})


def test_the_real_pyinstaller_entries_keep_the_exception_and_drop_the_gpl_text(real_notices):
    text, _ = real_notices

    assert (
        "In addition to the permissions in the GNU General Public License, the\n"
        "authors give you unlimited permission to link or embed compiled bootloader\n"
        "and related files into combinations with other programs, and to distribute\n"
        "those combinations without any restriction coming from the use of those\n"
        "files."
    ) in text
    assert "Copyright (c) 2010-2023, PyInstaller Development Team" in text
    assert (
        "The PyInstaller Community Hooks are licensed under the terms of the GNU General\n"
        "Public License"
    ) in text
    # The GPL 2 text is gone: its title, preamble and terms.
    assert "Version 2, June 1991" not in text
    assert "TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION" not in text
    assert text.count("[The full text of the GNU General Public License, version 2") == 2
    assert text.count("[The Apache License 2.0 that follows here in the original file") == 2


PYINSTALLER_LIKE = (
    "Head\nCopyright (c) 2010 Team\n\n================================\nGNU General Public License\n"
    "================================\n\nGPL words\n\t\t     END OF TERMS AND CONDITIONS\n\nTail\n"
)


def test_a_cut_replaces_only_the_part_between_its_points(site):
    make_dist(site, "noticetest-app", requires=("pyinstaller",))
    dist_text(site, "pyinstaller", {"licenses/COPYING.txt": PYINSTALLER_LIKE}, expression="GPL")

    text, _ = build("noticetest-app")

    assert "Head\nCopyright (c) 2010 Team" in text
    assert "GPL words" not in text
    assert "is not reproduced in this copy.]\n\nTail" in text


def test_a_file_without_the_cut_points_is_printed_whole_with_a_warning(site, capsys):
    make_dist(site, "noticetest-app", requires=("pyinstaller",))
    changed = PYINSTALLER_LIKE.replace("GNU General Public License", "GNU Public License")
    dist_text(site, "pyinstaller", {"licenses/COPYING.txt": changed}, expression="GPL")

    text, _ = build("noticetest-app")

    assert "GPL words" in text
    assert "cannot find the cut points" in capsys.readouterr().err


def test_an_apache_part_that_is_not_the_standard_text_is_not_cut(site, apache_text):
    make_dist(site, "noticetest-app", requires=("pyinstaller", "noticetest-std"))
    dist_text(site, "noticetest-std", {"licenses/LICENSE": apache_text}, expression="Apache-2.0")
    head = "Head\n================================\nApache License 2.0\n"
    head += "================================\n"
    other = head + apache_text.replace("Grant of Patent", "Grant of Patents")
    other += "\n   limitations under the License.\n\nTail\n"
    dist_text(site, "pyinstaller", {"licenses/COPYING.txt": other}, expression="GPL")

    text, _ = build("noticetest-app")

    assert "Grant of Patents License" in text


PSF_TEXT = (
    "A. HISTORY OF THE SOFTWARE\n==========================\n\nPython was created in 1990.\n\n"
    "B. TERMS AND CONDITIONS FOR ACCESSING OR OTHERWISE USING PYTHON\n"
    "===============================================================\n\n"
    "Copyright (c) 2001 Python Software Foundation; All Rights Reserved\n\nPSF terms.\n"
)


def test_the_history_of_python_is_dropped_and_the_psf_terms_stay(site):
    make_dist(site, "noticetest-app", requires=("typing-extensions",))
    dist_text(site, "typing-extensions", {"licenses/LICENSE": PSF_TEXT}, expression="PSF-2.0")

    text, _ = build("noticetest-app")

    assert "Python was created in 1990." not in text
    assert "A. HISTORY OF THE SOFTWARE\n=" not in text
    assert "B. TERMS AND CONDITIONS FOR ACCESSING OR OTHERWISE USING PYTHON" in text
    assert "Copyright (c) 2001 Python Software Foundation; All Rights Reserved" in text
    assert "PSF terms." in text


def test_the_python_license_loses_its_history_too(tmp_path):
    (tmp_path / "LICENSE.txt").write_text(PSF_TEXT, encoding="utf-8")

    package = notices.collect_python([tmp_path])
    text = notices.render([package], upstream_notice="x")

    assert "Python was created in 1990." not in text
    assert "PSF terms." in text


def test_a_psf_text_without_the_section_headings_is_kept_whole_with_a_warning(site, capsys):
    make_dist(site, "noticetest-app", requires=("typing-extensions",))
    dist_text(site, "typing-extensions", {"licenses/LICENSE": "Some other wording.\n"})

    text, _ = build("noticetest-app")

    assert "Some other wording." in text
    assert "cannot find the cut points" in capsys.readouterr().err


def test_the_real_python_licenses_have_no_history_but_all_their_terms(real_notices):
    text, components = real_notices

    assert "A. HISTORY OF THE SOFTWARE\n=" not in text
    assert "Python was created in the early 1990s" not in text
    marker = "B. TERMS AND CONDITIONS FOR ACCESSING OR OTHERWISE USING PYTHON"
    shared = notices.find_shared_apache_text(components)
    checked = 0
    for package in components:
        if package.canonical_name not in {"python", "typing-extensions"}:
            continue
        for license_text in package.texts:
            raw = license_text.text
            if marker not in raw:
                continue
            kept = raw[raw.index(marker) :]
            # An Apache License inside the file (OpenSSL's, at the end of python.org's
            # Windows LICENSE.txt) is printed once in the shared section instead;
            # everything else from B. on stays word for word.
            if shared is not None:
                kept = notices.shrink_embedded_apache(kept, shared) or kept
            assert kept in text, package.title
            checked += 1
    assert checked >= 1  # typing_extensions at least


def test_the_introduction_says_the_program_contains_gpl_and_lgpl_components():
    intro = " ".join(notices.INTRO.split())

    assert (
        "The packaged program also contains components under the GNU GPL and LGPL, "
        "among them PyQt6 (GPL-3.0); the package as a whole is distributed under the "
        "terms those licenses require. Where to get their source code is listed under "
        '"Source code of copyleft components".'
    ) in intro
    assert intro.index("licensed under the MIT License") < intro.index("also contains")


def test_the_real_notices_say_where_the_source_of_each_copyleft_component_is(real_notices):
    text, components = real_notices
    section = text.split(f"\n{notices.COPYLEFT_TITLE}\n", 1)[1]
    versions = {package.canonical_name: package.version for package in components}

    for name in ("pyqt6", "pyqt6-webengine", "pyqt6-qt6", "pyqt6-webengine-qt6", "certifi"):
        assert name in versions, name
    qt = versions["pyqt6-qt6"]
    qt_series = ".".join(qt.split(".")[:2])
    webengine = versions["pyqt6-webengine-qt6"]
    webengine_series = ".".join(webengine.split(".")[:2])
    assert f"/source/P/PyQt6/pyqt6-{versions['pyqt6']}.tar.gz" in section
    assert (
        f"/source/P/PyQt6-WebEngine/pyqt6_webengine-{versions['pyqt6-webengine']}.tar.gz"
        in section
    )
    assert f"https://download.qt.io/archive/qt/{qt_series}/{qt}/single/" in section
    assert f"https://download.qt.io/archive/qt/{qt_series}/{qt}/submodules/" in section
    assert (
        f"https://download.qt.io/archive/qtwebengine/{webengine_series}/{webengine}/src/"
        in section
    )
    assert f"/source/c/certifi/certifi-{versions['certifi']}.tar.gz" in section
    # The section follows the shared texts and names no BSD-licensed PyQt6 part.
    shared = text.index(f"\n{notices.SHARED_TEXTS_TITLE}\n")
    assert shared < text.index(f"\n{notices.COPYLEFT_TITLE}\n")
    assert "PyQt6_sip" not in section


def test_the_source_section_is_derived_from_the_installed_versions(site):
    make_dist(site, "noticetest-app", requires=("PyQt6-Qt6", "certifi"))
    make_dist(site, "PyQt6-Qt6", "7.1.2", expression="LGPL-3.0-only")
    make_dist(site, "certifi", "2030.1.1", license_field="MPL-2.0")

    text, _ = build("noticetest-app")

    assert "https://download.qt.io/archive/qt/7.1/7.1.2/single/" in text
    assert "certifi-2030.1.1.tar.gz" in text
    assert "PyQt6 (" not in text.split(notices.COPYLEFT_TITLE)[-1]


def test_without_copyleft_components_there_is_no_source_section(site):
    make_dist(site, "noticetest-app", requires=("noticetest-one",))
    dist_text(site, "noticetest-one", {"licenses/LICENSE": "Some license text.\n"})

    text, _ = build("noticetest-app")

    assert f"\n{notices.COPYLEFT_TITLE}\n" not in text
