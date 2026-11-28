"""Tests for the second half of tools/write_third_party_notices.py's minimum-obligation work.

Three parts: the trimming of Debian copyright files (DEP-5) and the copyleft
source offer of the Linux system libraries, both exercised with real Debian
copyright files from Ubuntu 22.04 (tests/fixtures/debian-copyright) and with
small hand-written ones; and the Rust crates that the cryptography,
pydantic_core and rpds-py wheels link in (docs/legal/third-party/rust-crates.json).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tests.dist_info_factory import make_dist, site  # noqa: F401  (site is a fixture)
from tests.test_third_party_notices import (  # noqa: F401  (helpers of the first test module)
    LIB_DIR,
    collect,
    fake_dpkg,
    library,
    write_common_license,
    write_copyright,
)
from tools import write_third_party_notices as notices

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "debian-copyright"
DEP5 = ("xz-utils", "libpng1.6", "p11-kit", "ncurses", "libzstd", "libcap2", "util-linux", "nettle")
NOT_DEP5 = ("glib2.0", "libxext")


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.copyright").read_text(encoding="utf-8").strip("\n")


def paragraphs(text: str) -> list[str]:
    return notices._PARAGRAPH_BREAK.split(text)


def patterns_of(paragraph: str) -> list[str]:
    value = notices._field_value(paragraph, "Files")
    return [] if value is None else value.split()


def dep5(*parts: str) -> str:
    return "\n\n".join(("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/", *parts))


LONG_TEXT = " ".join(f"word{index}" for index in range(120))  # well over the minimum for a pointer


def license_paragraph(name: str, text: str = LONG_TEXT) -> str:
    return f"License: {name}\n " + "\n ".join(text[i : i + 60] for i in range(0, len(text), 60))


# --- Debian copyright files: what is left out --------------------------------


@pytest.mark.parametrize("name", DEP5)
def test_the_files_star_paragraph_of_a_real_file_is_always_kept(name):
    text = fixture_text(name)
    trimmed, _ = notices.trim_debian_copyright(text)

    assert any(patterns_of(paragraph) == ["*"] for paragraph in paragraphs(trimmed))


@pytest.mark.parametrize("name", DEP5)
def test_nothing_that_only_covers_debian_or_non_binaries_is_left_in_a_real_file(name):
    trimmed, _ = notices.trim_debian_copyright(fixture_text(name))

    for paragraph in paragraphs(trimmed):
        patterns = patterns_of(paragraph)
        if patterns:
            assert not notices._only_for_the_packaging_or_non_binaries(patterns), patterns


@pytest.mark.parametrize("name", DEP5)
def test_every_paragraph_that_goes_is_one_of_the_two_kinds_and_the_rest_stays_word_for_word(name):
    text = fixture_text(name)
    trimmed, _ = notices.trim_debian_copyright(text)
    before, after = paragraphs(text), paragraphs(trimmed)

    assert [paragraph for paragraph in before if paragraph in after] == after  # order, no edits
    for gone in (paragraph for paragraph in before if paragraph not in after):
        patterns = patterns_of(gone)
        assert patterns and notices._only_for_the_packaging_or_non_binaries(patterns)


def test_the_real_files_shrink_and_the_known_cases_are_trimmed():
    sizes = {name: notices.trim_debian_copyright(fixture_text(name))[0] for name in DEP5}

    assert sum(len(text) for text in sizes.values()) < sum(len(fixture_text(n)) for n in DEP5)
    assert "debian/*" not in "\n".join(patterns_of(p)[0] for p in paragraphs(sizes["libpng1.6"]) if patterns_of(p))
    assert "po/de.po" not in sizes["p11-kit"]
    assert "testsuite/ccm-test.c" not in sizes["nettle"]
    assert "m4/acx_pthread.m4" not in sizes["xz-utils"]


@pytest.mark.parametrize("name", NOT_DEP5)
def test_a_file_that_is_not_in_the_machine_readable_format_is_never_changed(name):
    text = fixture_text(name)

    assert not text.startswith("Format:")
    assert notices.trim_debian_copyright(text) == (text, False)
    seen: dict = {}
    assert notices.point_at_repeated_licenses(text, "pkg", seen) == text
    assert seen == {}


def test_a_paragraph_goes_only_when_every_pattern_is_of_the_two_kinds():
    keep_mixed = "Files: debian/* src/main.c\nCopyright: 2020 A\nLicense: MIT"
    keep_mixed_doc = "Files: doc/* lib/core.c\nCopyright: 2020 B\nLicense: MIT"
    drop_debian = "Files: debian/*\nCopyright: 2020 C\nLicense: MIT"
    drop_docs = "Files: doc/*\n tests/*\n examples/*\nCopyright: 2020 D\nLicense: MIT"
    drop_build = (
        "Files: config.guess config.sub install-sh Makefile.in src/Makefile.am po/*\n"
        "Copyright: 2020 E\nLicense: MIT"
    )
    everything = "Files: *\nCopyright: 2020 F\nLicense: MIT"
    text = dep5(keep_mixed, keep_mixed_doc, drop_debian, drop_docs, drop_build, everything)

    trimmed, nothing_left = notices.trim_debian_copyright(text)

    assert nothing_left is False
    assert paragraphs(trimmed)[1:] == [keep_mixed, keep_mixed_doc, everything]


def test_a_pattern_that_cannot_be_told_keeps_its_paragraph():
    odd = "Files: src/data/*.bin\nCopyright: 2020 A\nLicense: MIT"
    trimmed, _ = notices.trim_debian_copyright(dep5(odd, "Files: debian/*\nCopyright: x\nLicense: MIT"))

    assert odd in trimmed


def test_a_file_with_only_packaging_paragraphs_says_so_in_the_output(tmp_path):
    only_debian = dep5("Files: debian/*\nCopyright: 2020 A\nLicense: GPL-2+")
    write_copyright(tmp_path, "libonly1", only_debian)
    system = collect({"a": [library("libonly1.so")]}, {f"{LIB_DIR}/libonly1.so": ["libonly1"]}, tmp_path)

    assert system.packages[0].nothing_left is True
    text = "\n".join(notices.render_system_libraries(system))
    assert "libonly1.so - libonly1" in text  # still in the index
    assert "libonly1 (Debian package)" in text  # and has its own block
    assert "covers only the Debian packaging" in text
    assert "debian/*" not in text.split("covers only")[0].split("Bundled files")[1]


def test_a_license_text_that_only_a_left_out_paragraph_holds_is_put_back():
    gpl_body = " ".join(["Terms of this license."] * 30)
    full_text_here = f"Files: debian/*\nCopyright: 2020 A\n{license_paragraph('Special-1', gpl_body)}"
    uses_name_only = "Files: src/*\nCopyright: 2020 B\nLicense: Special-1"
    text = dep5(uses_name_only, full_text_here)

    trimmed, _ = notices.trim_debian_copyright(text)

    assert full_text_here in trimmed

    # With a license paragraph that has the text, the debian one can go.
    standalone = license_paragraph("Special-1", gpl_body)
    again, _ = notices.trim_debian_copyright(dep5(uses_name_only, full_text_here, standalone))
    assert full_text_here not in again
    assert standalone in again


def test_a_stand_alone_license_with_the_same_text_is_printed_once_across_packages():
    seen: dict = {}
    first = dep5("Files: *\nCopyright: 2020 A\nLicense: MIT", license_paragraph("MIT"))
    second = dep5("Files: *\nCopyright: 2020 B\nLicense: Expat", license_paragraph("Expat"))
    third = dep5("Files: *\nCopyright: 2020 C\nLicense: MIT", license_paragraph("MIT", LONG_TEXT + " extra"))

    one = notices.point_at_repeated_licenses(first, "libone", seen)
    two = notices.point_at_repeated_licenses(second, "libtwo", seen)
    three = notices.point_at_repeated_licenses(third, "libthree", seen)

    assert one == first  # the first one keeps its text
    assert "word50" not in two
    assert 'word for word the one of "MIT", in the copyright file of libone, above' in two
    assert "License: Expat" in two  # the paragraph still names its license
    assert "Files: *\nCopyright: 2020 B" in two  # nothing else changes
    assert three.count("word50") == 1  # a different wording is not a repeat
    # the pointer's target is really printed (here: in the first file)
    assert "word50" in one


def test_a_short_license_text_and_a_paragraph_with_files_are_not_replaced():
    short = license_paragraph("Short", "Do as you like.")
    with_files = "Files: *\nCopyright: x\n" + license_paragraph("Big").replace("License:", "License:", 1)
    seen: dict = {}
    text = dep5(short, with_files)

    assert notices.point_at_repeated_licenses(text, "a", seen) == text
    assert notices.point_at_repeated_licenses(dep5(short), "b", seen) == dep5(short)


def test_a_repeat_inside_one_file_points_back_in_the_same_file():
    text = dep5(license_paragraph("A"), license_paragraph("B"))

    result = notices.point_at_repeated_licenses(text, "libx", {})

    assert 'word for word the one of "A", above.' in result


def test_the_references_are_counted_again_after_the_trimming(tmp_path):
    licenses = tmp_path / "common"
    for name in ("GPL-2", "GPL-3", "GFDL-1.3", "CC0-1.0", "Artistic"):
        write_common_license(licenses, name, f"text of {name}")
    kept = "Files: *\nCopyright: 2020 A\nLicense: GPL-2+\n On Debian see /usr/share/common-licenses/GPL-2."
    only_in_debian = (
        "Files: debian/*\nCopyright: 2020 B\nLicense: GPL-3+\n See /usr/share/common-licenses/GPL-3."
    )
    only_in_docs = (
        "Files: doc/*\nCopyright: 2020 C\nLicense: GFDL-1.3\n See /usr/share/common-licenses/GFDL-1.3."
    )
    candidate = (
        "Files: lib/*\nCopyright: 2020 D\nLicense: CC0-1.0\n See /usr/share/common-licenses/CC0-1.0."
    )
    write_copyright(tmp_path, "libref1", dep5(kept, only_in_debian, only_in_docs, candidate))
    system = collect(
        {"a": [library("libref1.so")]},
        {f"{LIB_DIR}/libref1.so": ["libref1"]},
        tmp_path,
        licenses_root=licenses,
    )

    names = [referenced.name for referenced in system.licenses]

    assert names == ["CC0-1.0", "GPL-2"]  # the candidate stays, GPL-3 and GFDL-1.3 go
    assert all(referenced.text for referenced in system.licenses)


def test_a_reference_that_stays_with_a_restored_paragraph_is_counted(tmp_path):
    licenses = tmp_path / "common"
    write_common_license(licenses, "GPL-3", "text of GPL-3")
    body = "\n ".join(["See /usr/share/common-licenses/GPL-3 for the terms."] * 12)
    holds_text = f"Files: debian/*\nCopyright: 2020 B\nLicense: GPL-3+\n {body}"
    uses = "Files: *\nCopyright: 2020 A\nLicense: GPL-3+"
    write_copyright(tmp_path, "librestore1", dep5(uses, holds_text))
    system = collect(
        {"a": [library("librestore1.so")]},
        {f"{LIB_DIR}/librestore1.so": ["librestore1"]},
        tmp_path,
        licenses_root=licenses,
    )

    assert [referenced.name for referenced in system.licenses] == ["GPL-3"]


def test_a_dot_zero_alias_in_a_kept_paragraph_still_finds_its_text(tmp_path):
    licenses = tmp_path / "common"
    write_common_license(licenses, "GPL-2", "text of GPL-2")
    text = dep5("Files: *\nCopyright: x\nLicense: GPL-2\n See /usr/share/common-licenses/GPL-2.0")
    write_copyright(tmp_path, "libalias1", text)
    system = collect(
        {"a": [library("libalias1.so")]},
        {f"{LIB_DIR}/libalias1.so": ["libalias1"]},
        tmp_path,
        licenses_root=licenses,
    )

    assert [(r.name, r.text) for r in system.licenses] == [("GPL-2.0", "text of GPL-2")]


def test_every_library_keeps_its_own_block_and_the_index_does_not_change(tmp_path):
    write_copyright(tmp_path, "libone1", dep5("Files: *\nCopyright: x\nLicense: MIT", license_paragraph("MIT")))
    write_copyright(tmp_path, "libtwo1", dep5("Files: *\nCopyright: y\nLicense: MIT", license_paragraph("MIT")))
    owned = {f"{LIB_DIR}/libone1.so": ["libone1"], f"{LIB_DIR}/libtwo1.so": ["libtwo1"]}
    system = collect({"a": [library("libone1.so"), library("libtwo1.so")]}, owned, tmp_path)

    text = "\n".join(notices.render_system_libraries(system))

    assert "System libraries (2)" in text
    assert "libone1 (Debian package)" in text and "libtwo1 (Debian package)" in text
    assert notices.listed_system_library_names("\n".join(["", notices.SYSTEM_LIBRARIES_TITLE, *text.split("\n")])) == [
        "libone1.so",
        "libtwo1.so",
    ]
    assert text.count("word50") == 1


def test_two_packages_with_the_same_trimmed_text_still_point_at_each_other_as_a_whole(tmp_path):
    same = dep5("Files: *\nCopyright: x\nLicense: MIT", license_paragraph("MIT"))
    write_copyright(tmp_path, "liba1", same + "\n\nFiles: debian/*\nCopyright: a\nLicense: MIT")
    write_copyright(tmp_path, "libb1", same + "\n\nFiles: debian/*\nCopyright: b\nLicense: MIT")
    owned = {f"{LIB_DIR}/liba1.so": ["liba1"], f"{LIB_DIR}/libb1.so": ["libb1"]}
    system = collect({"a": [library("liba1.so"), library("libb1.so")]}, owned, tmp_path)

    text = "\n".join(notices.render_system_libraries(system))

    assert "libb1/copyright (same text as /usr/share/doc/liba1/copyright, above)" in text.replace(
        str(tmp_path).replace("\\", "/"), "/usr/share/doc"
    ) or "(same text as" in text
    assert text.count("word50") == 1


def test_a_referenced_apache_text_that_is_the_shared_one_is_not_repeated():
    shared, _ = notices.build_notices, None  # (the real shared text comes from the installed packages)
    components = notices.collect_packages()
    apache = notices.find_shared_apache_text(components)
    assert apache is not None
    debian_apache = "Apache License\nVersion 2.0, January 2004\nhttp://www.apache.org/licenses/\n\n" + apache.split(
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION", 1
    )[0].replace("Apache License", "", 1)[:0] + "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" + apache.split(
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION", 1
    )[1]
    assert notices.is_apache_license_file(debian_apache)
    assert debian_apache != apache
    system = notices.SystemLibraries(
        libraries=[notices.SystemLibrary("libx.so", ("libx1",))],
        packages=[notices.DebianPackage("libx1", ["libx.so"], "/usr/share/doc/libx1/copyright", "see Apache-2.0")],
        licenses=[
            notices.ReferencedLicense("Apache-2.0", "/usr/share/common-licenses/Apache-2.0", debian_apache),
            notices.ReferencedLicense("GPL-3", "/usr/share/common-licenses/GPL-3", "GPL text"),
        ],
    )

    with_shared = "\n".join(notices.render_system_libraries(system, {}, apache_printed=True))
    without = "\n".join(notices.render_system_libraries(system, {}, apache_printed=False))

    assert "TERMS AND CONDITIONS" not in with_shared
    assert "printed once under \"Shared license texts\", above" in with_shared
    assert "GPL text" in with_shared
    assert "TERMS AND CONDITIONS" in without


# --- the source of the copyleft system libraries ----------------------------


GPL_COPYRIGHT = dep5("Files: *\nCopyright: 2020 A\nLicense: LGPL-2.1+\n See /usr/share/common-licenses/LGPL-2.1.")
BSD_COPYRIGHT = dep5("Files: *\nCopyright: 2020 B\nLicense: BSD-3-clause\n Redistribution and use are permitted.")
UBUNTU = 'NAME="Ubuntu"\nVERSION_ID="22.04"\nVERSION_CODENAME=jammy\nID=ubuntu\n'


def linux_system(tmp_path, *, sources, copyrights=None, os_release=UBUNTU):
    texts = copyrights or {"libglib2.0-0": GPL_COPYRIGHT, "libbsd1": BSD_COPYRIGHT}
    for package, text in texts.items():
        write_copyright(tmp_path, package, text)
    release = tmp_path / "os-release"
    if os_release is not None:
        release.write_text(os_release, encoding="utf-8")
    owned = {f"{LIB_DIR}/{package}.so": [package] for package in texts}
    return collect(
        {"a": [library(f"{package}.so") for package in texts]},
        owned,
        tmp_path,
        sources=sources,
        os_release=release,
    )


def test_a_copyleft_library_gets_its_source_package_and_version_from_dpkg_query(tmp_path):
    system = linux_system(
        tmp_path,
        sources={"libglib2.0-0": ("glib2.0", "2.72.4-0ubuntu2.6"), "libbsd1": ("libbsd", "0.11.5-1")},
    )

    assert system.distribution == "Ubuntu 22.04 (jammy)"
    assert system.distribution_id == "ubuntu"
    assert [(s.name, s.version, s.packages) for s in system.copyleft_sources] == [
        ("glib2.0", "2.72.4-0ubuntu2.6", ("libglib2.0-0",))
    ]  # the BSD library names no copyleft license: not listed
    lines = "\n".join(notices.linux_source_lines(system))
    assert "glib2.0 2.72.4-0ubuntu2.6 - Debian package(s): libglib2.0-0" in lines
    assert "apt-get source <source>=<version>" in " ".join(lines.split())
    assert "https://launchpad.net/ubuntu/+source/<source>/<version>" in lines
    assert "Ubuntu 22.04 (jammy)" in " ".join(lines.split())
    assert "libbsd" not in lines


def test_binary_packages_of_one_source_are_listed_together(tmp_path):
    texts = {"libnettle8": GPL_COPYRIGHT, "libhogweed6": GPL_COPYRIGHT}
    system = linux_system(
        tmp_path,
        sources={name: ("nettle", "3.7.3-1build2") for name in texts},
        copyrights=texts,
    )

    assert [(s.name, s.packages) for s in system.copyleft_sources] == [
        ("nettle", ("libhogweed6", "libnettle8"))
    ]


def test_without_dpkg_query_the_version_is_said_to_be_unknown_not_guessed(tmp_path):
    system = linux_system(tmp_path, sources={})  # dpkg-query knows nothing

    assert [(s.name, s.version) for s in system.copyleft_sources] == [("libglib2.0-0", None)]
    lines = "\n".join(notices.linux_source_lines(system))
    assert "libglib2.0-0 - version unknown" in lines
    assert "glib2.0 " not in lines  # no source name was invented


def test_when_dpkg_cannot_name_the_owners_the_section_says_so(tmp_path):
    write_copyright(tmp_path, "libglib2.0-0", GPL_COPYRIGHT)

    def broken(command, **options):
        raise OSError("no dpkg here")

    system = notices.collect_system_libraries(
        {"a": [library("libglib2.0-0.so")]},
        roots=[],
        run=broken,
        doc_root=tmp_path,
        licenses_root=tmp_path / "none",
        os_release=tmp_path / "none",
    )

    assert system.copyleft_sources == []
    assert "could not be determined" in " ".join(notices.linux_source_lines(system))


def test_a_distribution_that_is_not_ubuntu_gets_no_launchpad_address(tmp_path):
    system = linux_system(
        tmp_path,
        sources={"libglib2.0-0": ("glib2.0", "2.74.6-2")},
        os_release='NAME="Debian GNU/Linux"\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\nID=debian\n',
    )

    lines = "\n".join(notices.linux_source_lines(system))
    assert "Debian GNU/Linux 12 (bookworm)" in " ".join(lines.split())
    assert "launchpad" not in lines


def test_an_unreadable_os_release_is_called_by_its_plain_name(tmp_path):
    system = linux_system(
        tmp_path, sources={"libglib2.0-0": ("glib2.0", "2.72.4-0ubuntu2.6")}, os_release=None
    )

    assert system.distribution == ""
    assert "the Linux distribution of the build machine" in " ".join(
        "\n".join(notices.linux_source_lines(system)).split()
    )


def test_the_linux_source_lines_are_part_of_the_copyleft_section(site, tmp_path):
    make_dist(site, "noticetest-app", requires=("certifi",))
    make_dist(site, "certifi", "2030.1.1", license_field="MPL-2.0")
    system = linux_system(tmp_path, sources={"libglib2.0-0": ("glib2.0", "2.72.4-0ubuntu2.6")})
    components = notices.collect_packages("noticetest-app", (), ())

    text = notices.render(components, system, "upstream notice", [])

    section = text.split(f"\n{notices.COPYLEFT_TITLE}\n", 1)[1].split("\nSystem libraries bundled on Linux")[0]
    assert "certifi-2030.1.1.tar.gz" in section
    assert "System libraries of the Linux build" in section
    assert "glib2.0 2.72.4-0ubuntu2.6" in section
    assert text.index(notices.COPYLEFT_TITLE) < text.index(notices.SYSTEM_LIBRARIES_TITLE)


def test_a_fake_dpkg_without_a_query_answer_is_not_mistaken_for_the_real_one():
    assert fake_dpkg({}) is not None  # the stand-in of the first module understands dpkg-query


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("License: GPL-2+", True),
        ("License: LGPL-2.1", True),
        ("License: MPL-2.0", True),
        ("under the GNU General Public License", True),
        ("the Mozilla Public License", True),
        ("License: BSD-3-clause", False),
        ("License: Expat\n permission is hereby granted", False),
    ],
)
def test_the_copyleft_test_looks_for_the_gnu_and_mozilla_licenses(text, expected):
    assert notices.names_a_copyleft_license(text) is expected


def test_the_linux_output_of_the_real_files_stays_under_its_estimated_budget(tmp_path):
    """An estimate: the 10 real files, printed as the section prints them (not a Linux build)."""
    total_before = 0
    texts = {}
    for name in DEP5 + NOT_DEP5:
        text = fixture_text(name)
        total_before += len(text.encode())
        write_copyright(tmp_path, name, text)
        texts[name] = [f"{LIB_DIR}/{name}.so"]
    owned = {path[0]: [name] for name, path in texts.items()}
    system = collect({"a": [library(f"{name}.so") for name in texts]}, owned, tmp_path)

    printed = "\n".join(notices.render_system_libraries(system)).encode("utf-8")

    assert len(printed) < total_before  # the trimming only ever takes things out
    assert len(printed) <= 100_000  # measured about 93,000


# --- Rust crates --------------------------------------------------------------

MIT_TEXT = (
    "{copyright}\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this "
    "software and associated documentation files (the \"Software\"), to deal in the Software without "
    "restriction, including without limitation the rights to use, copy, modify, merge, publish, "
    "distribute, sublicense, and/or sell copies of the Software, subject to the following conditions: "
    "The above copyright notice and this permission notice shall be included in all copies or "
    "substantial portions of the Software. THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY "
    "KIND."
)


def crate_entry(name, version, obligation, **extra):
    entry = {
        "name": name,
        "version": version,
        "obligation": obligation,
        "chosen": {"none": "Unlicense", "shared-apache": "Apache-2.0", "text": "MIT"}.get(
            obligation, "MPL-2.0"
        ),
        "copyright_lines": [],
        "source_url": f"https://docs.rs/crate/{name}/{version}/source/",
    }
    entry.update(extra)
    return entry


def write_rust_data(root: Path, crates: list[dict], texts: dict[str, str] | None = None) -> Path:
    folder = root / "docs" / "legal" / "third-party"
    folder.mkdir(parents=True, exist_ok=True)
    table = {}
    for name, content in (texts or {}).items():
        raw = content.encode("utf-8")
        (folder / name).write_bytes(raw)
        table[name] = {"sha256": hashlib.sha256(raw).hexdigest()}
    (folder / "rust-crates.json").write_text(
        json.dumps({"schema": 1, "texts": table, "crates": crates}), encoding="utf-8"
    )
    return root


def wheel_with(
    site_dir: Path,
    name: str,
    crates: list[tuple[str, str]],
    version: str = "1.0",
    generic: tuple[tuple[str, str], ...] = (),
):
    sbom = {
        "bomFormat": "CycloneDX",
        "components": [
            {"type": "library", "name": n, "version": v, "purl": f"pkg:cargo/{n}@{v}"}
            for n, v in crates
        ]
        + [
            {"type": "library", "name": n, "version": v, "purl": f"pkg:generic/{n}@{v}"}
            for n, v in generic
        ],
    }
    return make_dist(
        site_dir,
        name,
        version,
        files={"sboms/x.cyclonedx.json": json.dumps(sbom).encode()},
    )


def dists(*names: str):
    from importlib import metadata

    return [metadata.distribution(name) for name in names]


def test_each_obligation_is_written_the_way_it_is_defined(site, tmp_path):
    wheel_with(
        site,
        "wheel-one",
        [("aaa", "1.0"), ("bbb", "2.0"), ("ccc", "3.0"), ("ddd", "4.0"), ("eee", "5.0")],
    )
    root = write_rust_data(
        tmp_path,
        [
            crate_entry("aaa", "1.0", "none"),
            crate_entry("bbb", "2.0", "shared-apache", notice="bbb NOTICE: made by B"),
            crate_entry(
                "ccc",
                "3.0",
                "text",
                copyright_lines=["Copyright (c) 2020 Carol"],
                license_text_file="rust-ccc-LICENSE.txt",
            ),
            crate_entry("ddd", "4.0", "source-offer", source_url="https://example.org/ddd-4.0.tar.gz"),
            crate_entry("eee", "5.0", "shared-apache"),
        ],
        {"rust-ccc-LICENSE.txt": MIT_TEXT.format(copyright="Copyright (c) 2020 Carol")},
    )

    crates = notices.collect_rust_crates(dists("wheel-one"), root)

    assert [(c.name, c.obligation) for c in crates] == [
        ("bbb", "shared-apache"),
        ("ccc", "text"),
        ("ddd", "source-offer"),
        ("eee", "shared-apache"),
    ]  # "none" is not listed, and the generic SBOM component is no crate
    assert crates[0].notice == "bbb NOTICE: made by B"
    assert "Copyright (c) 2020 Carol" in (crates[1].text or "")


def render_with_rust(site, tmp_path, crates, apache=True):
    make_dist(site, "noticetest-app", requires=("noticetest-apache",) if apache else ())
    if apache:
        make_dist(
            site,
            "noticetest-apache",
            expression="Apache-2.0",
            files={"licenses/LICENSE": notices.find_shared_apache_text(notices.collect_packages()).encode()},
            license_file_entries=("licenses/LICENSE",),
        )
    components = notices.collect_packages("noticetest-app", (), ())
    return notices.render(components, None, "upstream notice", crates), components


def test_the_rust_section_lists_apache_crates_by_name_and_prints_text_crates_with_their_copyright(
    site, tmp_path
):
    wheel_with(site, "wheel-one", [("bbb", "2.0"), ("ccc", "3.0"), ("ccd", "3.1"), ("eee", "5.0")])
    root = write_rust_data(
        tmp_path,
        [
            crate_entry("bbb", "2.0", "shared-apache", notice="bbb NOTICE: made by B"),
            crate_entry("ccc", "3.0", "text", copyright_lines=["Copyright (c) 2020 Carol"], license_text_file="c.txt"),
            crate_entry("ccd", "3.1", "text", copyright_lines=["Copyright (c) 2021 Dave"], license_text_file="d.txt"),
            crate_entry("eee", "5.0", "shared-apache"),
        ],
        {
            "c.txt": MIT_TEXT.format(copyright="Copyright (c) 2020 Carol"),
            "d.txt": MIT_TEXT.format(copyright="Copyright (c) 2021 Dave"),
        },
    )
    crates = notices.collect_rust_crates(dists("wheel-one"), root)

    text, _ = render_with_rust(site, tmp_path, crates)

    section = text.split(f"\n{notices.RUST_CRATES_TITLE}\n", 1)[1].split(f"\n{notices.SHARED_TEXTS_TITLE}\n")[0]
    assert "bbb 2.0" in section and "eee 5.0" in section
    assert "NOTICE of bbb 2.0:\nbbb NOTICE: made by B" in section
    assert "TERMS AND CONDITIONS" not in section  # the Apache text is not repeated here
    assert text.count("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION") == 1
    assert "Copyright (c) 2020 Carol" in section and "Copyright (c) 2021 Dave" in section
    assert section.count("Permission is hereby granted") == 1  # the second has the same wording
    assert "only the copyright notice differs" in section
    assert text.index(notices.RUST_CRATES_TITLE) < text.index(f"\n{notices.SHARED_TEXTS_TITLE}\n")


def test_crates_with_the_same_text_share_one_heading_and_one_copy(site, tmp_path):
    wheel_with(site, "wheel-one", [("one", "1.0"), ("two", "1.0")])
    root = write_rust_data(
        tmp_path,
        [
            crate_entry("one", "1.0", "text", copyright_lines=["Copyright (c) 2020 Carol"], license_text_file="c.txt"),
            crate_entry("two", "1.0", "text", copyright_lines=["Copyright (c) 2020 Carol"], license_text_file="c.txt"),
        ],
        {"c.txt": MIT_TEXT.format(copyright="Copyright (c) 2020 Carol")},
    )
    crates = notices.collect_rust_crates(dists("wheel-one"), root)

    text, _ = render_with_rust(site, tmp_path, crates, apache=False)

    assert "one 1.0 (wheel-one), two 1.0 (wheel-one)" in text
    assert text.count("Copyright (c) 2020 Carol") == 1


def test_a_copyright_line_that_the_text_lacks_is_printed_with_where_it_comes_from(site, tmp_path):
    wheel_with(site, "wheel-one", [("zed", "1.0")])
    root = write_rust_data(
        tmp_path,
        [
            crate_entry(
                "zed",
                "1.0",
                "text",
                copyright_lines=["Jane Roe <jane@example.org>"],
                license_text_file="z.txt",
                copyright_note="LICENSE-MIT has no Copyright line; name taken from Cargo.toml authors",
            )
        ],
        {"z.txt": MIT_TEXT.format(copyright="")},
    )
    crates = notices.collect_rust_crates(dists("wheel-one"), root)

    text, _ = render_with_rust(site, tmp_path, crates, apache=False)

    assert "Copyright: Jane Roe <jane@example.org>\n(LICENSE-MIT has no Copyright line; name taken from Cargo.toml authors.)" in text


def test_a_source_offer_crate_goes_into_the_copyleft_section(site, tmp_path):
    wheel_with(site, "wheel-one", [("ddd", "4.0")])
    root = write_rust_data(
        tmp_path,
        [crate_entry("ddd", "4.0", "source-offer", source_url="https://example.org/ddd-4.0.tar.gz")],
    )
    crates = notices.collect_rust_crates(dists("wheel-one"), root)

    text, _ = render_with_rust(site, tmp_path, crates, apache=False)

    section = text.split(f"\n{notices.COPYLEFT_TITLE}\n", 1)[1]
    assert "ddd 4.0 (wheel-one) (MPL-2.0), Rust crate\n  https://example.org/ddd-4.0.tar.gz" in section


def test_a_crate_that_the_data_does_not_know_stops_the_build_with_instructions(site, tmp_path):
    wheel_with(site, "wheel-one", [("known", "1.0"), ("brand-new", "9.9")])
    root = write_rust_data(tmp_path, [crate_entry("known", "1.0", "none")])

    with pytest.raises(notices.RustCratesError) as error:
        notices.collect_rust_crates(dists("wheel-one"), root)

    message = str(error.value)
    assert "brand-new 9.9 (wheel-one)" in message
    assert "known 1.0" not in message
    assert "rust-crates.json" in message
    assert "research" in message and "upgraded" in message


def test_a_version_that_the_data_does_not_have_is_unknown_too(site, tmp_path):
    wheel_with(site, "wheel-one", [("known", "2.0")])
    root = write_rust_data(tmp_path, [crate_entry("known", "1.0", "none")])

    with pytest.raises(notices.RustCratesError, match=r"known 2\.0"):
        notices.collect_rust_crates(dists("wheel-one"), root)


def test_build_notices_and_main_fail_for_an_unknown_crate_and_write_nothing(site, tmp_path, capsys):
    make_dist(site, "noticetest-app", requires=("wheel-new",))
    wheel_with(site, "wheel-new", [("brand-new", "9.9")])

    with pytest.raises(notices.RustCratesError, match="brand-new 9.9"):
        notices.build_notices("noticetest-app", (), (), python_dirs=[], platform="linux")

    # the same through main(), with the project's own name patched in
    output = tmp_path / "out.txt"
    original = notices.build_notices
    try:
        notices.build_notices = lambda **kw: original(
            "noticetest-app", (), (), python_dirs=[], platform="linux", **kw
        )
        assert notices.main([str(output)]) == 1
    finally:
        notices.build_notices = original
    assert "brand-new 9.9" in capsys.readouterr().err
    assert not output.exists()


def test_each_wheel_lists_only_the_crates_of_its_own_sbom(site, tmp_path):
    wheel_with(site, "wheel-one", [("both", "1.0"), ("only-one", "1.0")])
    wheel_with(site, "wheel-two", [("both", "1.0"), ("only-two", "1.0")])
    wheel_with(site, "wheel-three", [("only-three", "1.0")])
    entries = [crate_entry(n, "1.0", "shared-apache") for n in ("both", "only-one", "only-two", "only-three", "unused")]
    root = write_rust_data(tmp_path, entries)

    everything = notices.collect_rust_crates(dists("wheel-one", "wheel-two", "wheel-three"), root)
    second_only = notices.collect_rust_crates(dists("wheel-two"), root)

    assert {(c.name, c.wheels) for c in everything} == {
        ("both", ("wheel-one", "wheel-two")),
        ("only-one", ("wheel-one",)),
        ("only-two", ("wheel-two",)),
        ("only-three", ("wheel-three",)),
    }  # "unused" is in the data but in no wheel: not listed
    assert [c.name for c in second_only] == ["both", "only-two"]


def test_a_wheel_without_an_sbom_adds_no_crates_and_needs_no_data_file(site, tmp_path):
    make_dist(site, "wheel-plain")

    assert notices.collect_rust_crates(dists("wheel-plain"), tmp_path / "no-data-here") == []


def test_a_text_that_does_not_match_its_pinned_hash_stops_the_build(site, tmp_path):
    wheel_with(site, "wheel-one", [("ccc", "3.0")])
    root = write_rust_data(
        tmp_path,
        [crate_entry("ccc", "3.0", "text", license_text_file="c.txt")],
        {"c.txt": MIT_TEXT.format(copyright="Copyright (c) 2020 Carol")},
    )
    (root / "docs/legal/third-party/c.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(notices.RustCratesError, match="sha256"):
        notices.collect_rust_crates(dists("wheel-one"), root)


def test_a_text_crate_without_its_text_or_a_damaged_data_file_stops_the_build(site, tmp_path):
    wheel_with(site, "wheel-one", [("ccc", "3.0")])
    root = write_rust_data(tmp_path, [crate_entry("ccc", "3.0", "text", license_text_file="gone.txt")])
    with pytest.raises(notices.RustCratesError, match="texts"):
        notices.collect_rust_crates(dists("wheel-one"), root)

    (root / "docs/legal/third-party/rust-crates.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(notices.RustCratesError, match="cannot read"):
        notices.collect_rust_crates(dists("wheel-one"), root)

    bad = write_rust_data(tmp_path / "bad", [crate_entry("ccc", "3.0", "maybe")])
    with pytest.raises(notices.RustCratesError, match="obligation"):
        notices.collect_rust_crates(dists("wheel-one"), bad)


def test_apache_crates_need_the_shared_text_to_exist(site, tmp_path):
    wheel_with(site, "wheel-one", [("eee", "5.0")])
    root = write_rust_data(tmp_path, [crate_entry("eee", "5.0", "shared-apache")])
    crates = notices.collect_rust_crates(dists("wheel-one"), root)

    with pytest.raises(notices.SharedLicenseError, match="Apache"):
        render_with_rust(site, tmp_path, crates, apache=False)


# --- the real data file ---------------------------------------------------------

DATA_DIR = Path(notices.REPO_ROOT) / "docs" / "legal" / "third-party"


@pytest.fixture(scope="module")
def real_rust_data():
    return notices.load_rust_crate_data()


def test_every_text_of_the_data_file_is_pinned_and_every_pinned_text_is_used():
    document = json.loads((DATA_DIR / "rust-crates.json").read_text(encoding="utf-8"))

    used = {c["license_text_file"] for c in document["crates"] if c.get("license_text_file")}
    assert set(document["texts"]) == used
    for name, pinned in document["texts"].items():
        raw = (DATA_DIR / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == pinned["sha256"], name
        assert b"\r" not in raw and raw.decode("utf-8")
    on_disk = {path.name for path in DATA_DIR.glob("rust-*.txt")}
    assert on_disk == used
    assert "as published on crates.io" in document["text_note"]


def test_every_entry_of_the_data_file_is_complete(real_rust_data):
    for (name, version), entry in real_rust_data.items():
        assert entry["obligation"] in notices._RUST_OBLIGATIONS, (name, version)
        assert entry["spdx"] and entry["chosen"] and entry["source_url"], (name, version)
        if entry["obligation"] == "text":
            text = entry["text"]
            assert text.strip() and entry["copyright_lines"], (name, version)
            for line in entry["copyright_lines"]:
                assert line in text or entry.get("copyright_note"), (name, version, line)
        if entry["obligation"] == "shared-apache":
            assert "Apache-2.0" in entry["chosen"], (name, version)
        if entry.get("build_time_only"):
            assert entry["obligation"] == "none" and entry["build_time_evidence"], (name, version)


def test_the_ten_crates_named_by_the_research_are_proven_build_time_only(real_rust_data):
    named = {
        ("asn1_derive", "0.24.1"),
        ("strum_macros", "0.28.0"),
        ("synstructure", "0.13.1"),
        ("icu_provider_macros", "1.5.0"),
        ("yoke-derive", "0.7.4"),
        ("zerofrom-derive", "0.1.4"),
        ("zerovec-derive", "0.10.3"),
        ("unicode-ident", "1.0.12"),
        ("unicode-ident", "1.0.22"),
        ("unicode-ident", "1.0.24"),
    }

    for key in named:
        entry = real_rust_data[key]
        assert entry["build_time_only"] is True and entry["obligation"] == "none", key
        assert entry["obligation_before_build_time_check"] == "text", key
        assert "proc-macro" in entry["build_time_evidence"], key
    # a crate that was not proven keeps its duty
    assert real_rust_data[("cc", "1.4.0")]["obligation"] == "shared-apache"
    assert "build_time_only" not in real_rust_data[("cc", "1.4.0")]


def test_zmij_says_where_its_copyright_line_comes_from(real_rust_data):
    entry = real_rust_data[("zmij", "1.0.6")]

    assert entry["copyright_lines"] == ["David Tolnay <dtolnay@gmail.com>"]
    assert "Cargo.toml" in entry["copyright_note"]
    assert "David Tolnay" not in entry["text"]


def test_portable_atomic_of_the_lock_file_is_not_in_the_data(real_rust_data):
    assert not [key for key in real_rust_data if key[0] == "portable-atomic" and key[1] == "1.11.1"]


def test_the_real_environment_builds_and_lists_the_crates_of_its_own_sboms():
    from importlib import metadata

    crates = notices.collect_rust_crates(notices.collect_distributions())
    listed = {c.name for c in crates}

    assert crates, "cryptography, pydantic_core and rpds-py are installed with SBOMs"
    assert {"asn1", "jiter", "zmij", "bitvec"} <= listed
    assert not listed & {"unicode-ident", "synstructure", "asn1_derive", "strum_macros"}
    names = {dist.metadata["Name"] for dist in notices.collect_distributions()}
    assert {wheel for c in crates for wheel in c.wheels} <= names
    assert metadata.version("cryptography")


def test_the_real_notices_carry_the_rust_section_once_and_no_build_time_crate():
    text, _ = notices.build_notices()

    assert text.count(f"\n{notices.RUST_CRATES_TITLE}\n") == 1
    section = text.split(f"\n{notices.RUST_CRATES_TITLE}\n", 1)[1].split(f"\n{notices.SHARED_TEXTS_TITLE}\n")[0]
    assert "Copyright: David Tolnay <dtolnay@gmail.com>" in section
    assert "Cargo.toml authors" in section
    assert "Copyright © 2020-2024 Unicode, Inc." in section
    for build_time in ("synstructure", "unicode-ident", "asn1_derive", "yoke-derive"):
        assert build_time not in section
    assert text.count("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION") == 1
    # each listed text crate keeps its recorded copyright lines in the section
    data = notices.load_rust_crate_data()
    listed = notices.collect_rust_crates(notices.collect_distributions())
    for crate in listed:
        if crate.obligation == "text":
            for line in data[(crate.name, crate.version)]["copyright_lines"]:
                assert line in section, (crate.title, line)
    assert re.search(r"^Crates used under the Apache License 2\.0 \(\d+\)$", section, re.M)


# --- non-crate components of an SBOM (pkg:generic) ------------------------------


GENERIC_OPENSSL = {
    "name": "openssl",
    "version": "4.0.3",
    "role": "statically linked into the cryptography package",
    "chosen": "Apache-2.0",
    "obligation": "shared-apache",
    "notice": None,
}


def add_generic(root: Path, *entries: dict) -> None:
    path = root / "docs/legal/third-party/rust-crates.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["generic_components"] = list(entries)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_a_generic_openssl_is_listed_and_the_same_output_has_the_apache_text(site, tmp_path):
    wheel_with(site, "wheel-one", [("eee", "5.0")], generic=(("openssl", "4.0.3"),))
    root = write_rust_data(tmp_path, [crate_entry("eee", "5.0", "shared-apache")])
    add_generic(root, GENERIC_OPENSSL)
    crates = notices.collect_rust_crates(dists("wheel-one"), root)

    text, _ = render_with_rust(site, tmp_path, crates)

    assert [(c.name, c.role) for c in crates if c.role] == [
        ("openssl", "statically linked into the cryptography package")
    ]
    assert (
        "openssl 4.0.3 (wheel-one): statically linked into the cryptography package. "
        "License: Apache-2.0, see above." in text
    )
    assert text.count("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION") == 1


def test_a_generic_component_that_the_table_does_not_know_stops_the_build(site, tmp_path):
    wheel_with(site, "wheel-one", [], generic=(("zlib", "1.3"), ("openssl", "4.0.3")))
    root = write_rust_data(tmp_path, [])
    add_generic(root, GENERIC_OPENSSL)

    with pytest.raises(notices.RustCratesError, match=r"zlib 1\.3 \(wheel-one\)") as error:
        notices.collect_rust_crates(dists("wheel-one"), root)
    assert "openssl" not in str(error.value).split(":", 1)[1].split(".")[0]

    # another version of a known component is unknown too: its NOTICE has to be looked at again
    wheel_with(site, "wheel-two", [], generic=(("openssl", "4.1.0"),))
    with pytest.raises(notices.RustCratesError, match=r"openssl 4\.1\.0"):
        notices.collect_rust_crates(dists("wheel-two"), root)


def test_the_real_cryptography_wheel_lists_its_openssl(real_rust_data):
    crates = notices.collect_rust_crates(notices.collect_distributions())
    openssl = [c for c in crates if c.name == "openssl" and c.role]

    assert [(c.version, c.wheels, c.obligation) for c in openssl] == [
        ("4.0.3", ("cryptography",), "shared-apache")
    ]
    text, _ = notices.build_notices()
    assert "openssl 4.0.3 (cryptography): statically linked into the cryptography package." in text