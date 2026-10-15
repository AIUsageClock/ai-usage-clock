"""Tests for tools/check_bundled_notices.py.

The fakes are throwaway ``*.dist-info`` folders in a temporary site directory,
plus ``Analysis-00.toc`` files written the way PyInstaller writes them (a
pprint of a tuple), so each case controls what is installed, what got packed
and what the notices list. The last test runs against the real virtualenv.
"""

from __future__ import annotations

import importlib.util
import os
import pprint
import subprocess
import sys
from pathlib import Path

import pytest

from tests.dist_info_factory import make_dist, site  # noqa: F401  (site is a fixture)
from tools import check_bundled_notices as check
from tools import write_third_party_notices as notices


def normal(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def notices_text(*names: str) -> str:
    """A notices file that lists the given components."""
    return notices.render(
        [notices.Package(name=name, version="1.0", declaration="MIT") for name in names]
    )


def write_toc(path: Path, *, scripts=(), pure=(), binaries=(), datas=()) -> Path:
    """An Analysis-00.toc shaped like PyInstaller's: a pprint of the analysis tuple."""
    analysis = (
        ["entry.py"],
        ["/work"],
        [],
        [("/hooks", -1000)],
        {},
        ["PIL"],
        [],
        False,
        {},
        0,
        [],
        [],
        "3.12.0 (main)",
        list(scripts),
        list(pure),
        list(binaries),
        [],
        [],
        list(datas),
        [],
    )
    path.write_text(pprint.pformat(analysis), encoding="utf-8")
    return path


def packed(site_dir: Path, relative: str, name: str, typecode: str = "PYMODULE"):
    return (name, str(site_dir / relative), typecode)


def attribute(site_dir: Path, entries, module_owners=None):
    return check.attribute_entries(
        entries,
        check.installed_file_owners([str(site_dir)]),
        [normal(site_dir)],
        {} if module_owners is None else module_owners,
    )


# --- reading the analysis -----------------------------------------------------


def test_entries_are_found_anywhere_in_the_analysis_and_nothing_else():
    entry = ("pkg.mod", "/site/pkg/mod.py", "PYMODULE")
    analysis = (
        ["entry.py"],
        [("/hooks", -1000)],  # a (str, int) pair
        {"key": [entry]},
        [("only", "two")],
        [("a", "b", "lowercase")],  # third item is not a typecode
        [("a", "b", 3)],
        [["not", "a", "tuple"]],
        [("pkg.pre", "/site/pkg/pre.py", "PYMODULE-1")],
    )

    assert list(check.iter_toc_entries(analysis)) == [
        entry,
        ("pkg.pre", "/site/pkg/pre.py", "PYMODULE-1"),
    ]


def test_an_analysis_file_is_read_back_as_written(tmp_path):
    entries = [
        ("pkg", "C:\\site\\pkg\\__init__.py", "PYMODULE"),
        ("ext.pyd", "C:\\site\\ext.cp312-win_amd64.pyd", "EXTENSION"),
    ]
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=entries[:1], binaries=entries[1:])

    assert check.read_analysis_toc(toc) == entries


@pytest.mark.parametrize(
    "content",
    ["import os\n", "{unbalanced", "(['entry.py'], [], {})\n"],
    ids=["code", "syntax error", "no packed files"],
)
def test_an_unreadable_analysis_is_an_input_error(tmp_path, content):
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(content, encoding="utf-8")

    with pytest.raises(check.InputError):
        check.read_analysis_toc(toc)


def test_a_missing_analysis_is_an_input_error(tmp_path):
    with pytest.raises(check.InputError, match="cannot read"):
        check.read_analysis_toc(tmp_path / "absent.toc")


# --- attributing packed files to packages ---------------------------------------


def test_a_packed_file_belongs_to_the_distribution_that_lists_it(site):
    make_dist(site, "alpha-lib", site_files={"alphalib/__init__.py": b"", "alphalib/util.py": b""})

    result = attribute(
        site,
        [
            packed(site, "alphalib/__init__.py", "alphalib"),
            packed(site, "alphalib/util.py", "alphalib.util"),
        ],
    )

    assert result.distributions == {"alpha-lib": ["alphalib", "alphalib.util"]}
    assert result.unattributed == {}


def test_a_package_folder_shared_by_two_distributions_blames_only_the_one_packed(site):
    # Namespace-style layout (jaraco.*, winrt.*): both distributions provide
    # the top-level "nsx", but only one of them has a file in the bundle.
    make_dist(site, "nsx-a", site_files={"nsx/a.py": b""})
    make_dist(site, "nsx-b", site_files={"nsx/b.py": b""})

    result = attribute(
        site,
        [packed(site, "nsx/a.py", "nsx.a")],
        module_owners={"nsx": ["nsx-a", "nsx-b"]},
    )

    assert list(result.distributions) == ["nsx-a"]


def test_metadata_folders_packed_as_data_belong_to_their_distribution(site):
    make_dist(site, "metaful", files={"LICENSE": b"text"})

    result = attribute(
        site, [packed(site, "metaful-1.0.dist-info/LICENSE", "metaful-1.0.dist-info/LICENSE", "DATA")]
    )

    assert list(result.distributions) == ["metaful"]


def test_a_file_no_record_lists_falls_back_to_the_module_name_providers(site):
    make_dist(site, "legacy-dist", top_level=("legacymod",), with_record=False)
    (site / "legacymod.py").write_bytes(b"")
    (site / "compiled.cp312-win_amd64.pyd").write_bytes(b"")
    make_dist(site, "native-dist", top_level=("compiled",), with_record=False)

    result = attribute(
        site,
        [
            packed(site, "legacymod.py", "legacymod"),
            packed(site, "compiled.cp312-win_amd64.pyd", "compiled", "EXTENSION"),
        ],
        module_owners=check.top_level_module_owners(),
    )

    assert sorted(result.distributions) == ["legacy-dist", "native-dist"]


def test_a_metadata_folder_of_an_unrecorded_distribution_is_still_recognised(site):
    _load_the_metadata_backport_if_installed()
    folder = site / "Some_Dist-2.0.dist-info"
    folder.mkdir()
    (folder / "METADATA").write_bytes(b"")

    result = attribute(
        site, [packed(site, "Some_Dist-2.0.dist-info/METADATA", "Some_Dist-2.0.dist-info/METADATA", "DATA")]
    )

    assert list(result.distributions) == ["some-dist"]


def test_a_file_in_site_packages_that_nothing_claims_is_reported_as_unattributed(site):
    (site / "orphan").mkdir()
    (site / "orphan" / "mod.py").write_bytes(b"")

    result = attribute(site, [packed(site, "orphan/mod.py", "orphan.mod")])

    assert result.distributions == {}
    assert result.unattributed == {"orphan": ["orphan.mod"]}


def test_files_outside_site_packages_are_not_third_party_packages(site, tmp_path):
    stdlib = tmp_path / "python" / "Lib"
    stdlib.mkdir(parents=True)
    (stdlib / "json.py").write_bytes(b"")
    entries = [
        ("json", str(stdlib / "json.py"), "PYMODULE"),
        ("aiusageclock", str(tmp_path / "repo" / "src" / "aiusageclock" / "app.py"), "PYMODULE"),
        ("namespace", "-", "PYMODULE"),
        ("nothing", "", "DATA"),
        ("Versions/Current", "A", "SYMLINK"),
    ]

    result = attribute(site, entries)

    assert result.distributions == {}
    assert result.unattributed == {}


def test_only_a_few_example_files_are_kept_per_distribution(site):
    files = {f"many/m{i}.py": b"" for i in range(6)}
    make_dist(site, "many", site_files=files)

    result = attribute(site, [packed(site, relative, relative) for relative in files])

    assert len(result.distributions["many"]) == 3


# --- comparing with the notices ---------------------------------------------------


def run_check(site_dir: Path, notice_names: tuple[str, ...], *labelled_entries):
    analyses = {f"toc{i}": entries for i, entries in enumerate(labelled_entries)}
    return check.check_bundles(
        notices_text(*notice_names),
        analyses,
        file_owners=check.installed_file_owners([str(site_dir)]),
        site_dirs=[normal(site_dir)],
        module_owners={},
    )


def test_a_packed_package_that_the_notices_leave_out_is_reported(site):
    make_dist(site, "listed-lib", site_files={"listedlib.py": b""})
    make_dist(site, "forgotten-lib", site_files={"forgottenlib.py": b""})
    entries = [
        packed(site, "listedlib.py", "listedlib"),
        packed(site, "forgottenlib.py", "forgottenlib"),
    ]

    unlisted, unattributed = run_check(site, ("listed-lib",), entries)

    assert unlisted == {"toc0": {"forgotten-lib": ["forgottenlib"]}}
    assert unattributed == {}


def test_nothing_is_reported_when_every_packed_package_is_listed(site):
    make_dist(site, "listed-lib", site_files={"listedlib.py": b""})

    result = run_check(site, ("listed-lib",), [packed(site, "listedlib.py", "listedlib")])

    assert result == ({}, {})


def test_each_executable_is_reported_under_its_own_analysis(site):
    make_dist(site, "only-in-second", site_files={"second.py": b""})
    make_dist(site, "in-both", site_files={"both.py": b""})
    first = [packed(site, "both.py", "both")]
    second = [packed(site, "both.py", "both"), packed(site, "second.py", "second")]

    unlisted, _ = run_check(site, (), first, second)

    assert unlisted == {
        "toc0": {"in-both": ["both"]},
        "toc1": {"in-both": ["both"], "only-in-second": ["second"]},
    }


def test_the_project_itself_and_the_python_runtime_need_no_listing(site):
    make_dist(site, notices.PROJECT, site_files={"project_module.py": b""})
    entries = [packed(site, "project_module.py", "project_module")]

    assert run_check(site, (), entries) == ({}, {})


def test_listing_is_compared_by_canonical_name(site):
    make_dist(site, "Some.Odd_Name", site_files={"oddname.py": b""})

    result = run_check(site, ("some-odd-name",), [packed(site, "oddname.py", "oddname")])

    assert result == ({}, {})


def test_an_analysis_that_matches_no_installed_package_is_refused_not_passed(site, tmp_path):
    # All-clear on an analysis that was written for some other environment
    # (or whose paths do not line up with this one) would be a false all-clear.
    elsewhere = [("pkg", str(tmp_path / "elsewhere" / "pkg.py"), "PYMODULE")]

    with pytest.raises(check.InputError, match="belongs to an installed package"):
        run_check(site, (), elsewhere)


def test_a_symlinked_spelling_of_the_environment_still_matches(site, tmp_path):
    make_dist(site, "alpha-lib", site_files={"alphalib.py": b""})
    alias = tmp_path / "alias-of-site"
    try:
        alias.symlink_to(site, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows without the symlink privilege: a junction resolves the same way.
        if sys.platform != "win32":
            pytest.skip("symbolic links are not available here")
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(site)],
            capture_output=True,
            check=False,
        )
        if made.returncode != 0:
            pytest.skip("neither symbolic links nor junctions are available here")
    entries = [packed(alias, "alphalib.py", "alphalib")]

    through_the_alias = check.attribute_entries(
        entries,
        check.installed_file_owners([str(site)]),
        [normal(site)],
        {},
    )

    assert list(through_the_alias.distributions) == ["alpha-lib"]


def test_unclaimed_files_are_reported_even_when_all_packages_are_listed(site):
    (site / "orphan").mkdir()
    (site / "orphan" / "mod.py").write_bytes(b"")

    unlisted, unattributed = run_check(site, (), [packed(site, "orphan/mod.py", "orphan.mod")])

    assert unlisted == {}
    assert unattributed == {"toc0": {"orphan": ["orphan.mod"]}}


# --- the command line ----------------------------------------------------------------


@pytest.fixture
def isolated(site, monkeypatch):
    """main() sees only the fake site directory, not the real environment."""
    original = check.installed_file_owners
    monkeypatch.setattr(check, "installed_file_owners", lambda: original([str(site)]))
    monkeypatch.setattr(check, "default_site_dirs", lambda: [normal(site)])
    monkeypatch.setattr(check, "top_level_module_owners", lambda: {})
    return site


def test_main_fails_and_names_the_package_a_build_would_ship_unlisted(isolated, tmp_path, capsys):
    site = isolated
    make_dist(site, "forgotten-lib", site_files={"forgottenlib.py": b""})
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(notices_text("something-else"), encoding="utf-8")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[packed(site, "forgottenlib.py", "forgottenlib")])

    assert check.main([str(notices_file), str(toc)]) == 1

    error = capsys.readouterr().err
    assert "forgotten-lib" in error
    assert str(toc) in error
    assert "--exclude-module" in error


def test_main_passes_once_the_package_is_listed(isolated, tmp_path, capsys):
    site = isolated
    make_dist(site, "forgotten-lib", site_files={"forgottenlib.py": b""})
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(notices_text("forgotten-lib"), encoding="utf-8")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[packed(site, "forgottenlib.py", "forgottenlib")])

    assert check.main([str(notices_file), str(toc)]) == 0

    assert "accounts for every package" in capsys.readouterr().out


def test_main_fails_on_files_that_no_package_claims(isolated, tmp_path, capsys):
    site = isolated
    (site / "orphan").mkdir()
    (site / "orphan" / "mod.py").write_bytes(b"")
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(notices_text(), encoding="utf-8")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[packed(site, "orphan/mod.py", "orphan.mod")])

    assert check.main([str(notices_file), str(toc)]) == 1

    assert "orphan" in capsys.readouterr().err


def test_main_refuses_an_analysis_that_matches_nothing_with_status_2(isolated, tmp_path, capsys):
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(notices_text(), encoding="utf-8")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[("m", "/elsewhere/m.py", "PYMODULE")])

    assert check.main([str(notices_file), str(toc)]) == 2

    assert "belongs to an installed package" in capsys.readouterr().err


def test_main_reports_unreadable_inputs_with_status_2(isolated, tmp_path, capsys):
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(notices_text(), encoding="utf-8")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[("m", "/elsewhere/m.py", "PYMODULE")])
    not_notices = tmp_path / "plain.txt"
    not_notices.write_text("just some text\n", encoding="utf-8")

    assert check.main([str(tmp_path / "absent.txt"), str(toc)]) == 2
    assert check.main([str(notices_file), str(tmp_path / "absent.toc")]) == 2
    assert check.main([str(not_notices), str(toc)]) == 2
    assert "error:" in capsys.readouterr().err


# --- distributions without a name ---------------------------------------------------


def make_nameless_dist(site: Path, top_level: str) -> None:
    """A dist-info whose METADATA has no Name header, claiming one top-level module."""
    folder = site / "nameless-1.0.dist-info"
    folder.mkdir()
    (folder / "METADATA").write_text("Metadata-Version: 2.1\nVersion: 1.0\n", encoding="utf-8")
    (folder / "top_level.txt").write_text(f"{top_level}\n", encoding="utf-8")


def test_a_distribution_without_a_name_is_left_out_of_the_module_owners():
    owners = check.top_level_module_owners(
        {"mixed": [None, "Real_Pkg", ""], "ghost": [None], "plain": ["Other"]}
    )

    assert owners == {"mixed": ["real-pkg"], "plain": ["other"]}


def test_a_nameless_distribution_in_the_environment_does_not_crash_the_fallback(site):
    make_nameless_dist(site, "ghostmod")
    (site / "ghostmod.py").write_bytes(b"")

    owners = check.top_level_module_owners()

    assert "ghostmod" not in owners
    # Nobody can be blamed for the file, so it is reported rather than crashing
    # or being waved through.
    result = attribute(site, [packed(site, "ghostmod.py", "ghostmod")], module_owners=owners)
    assert result.distributions == {}
    assert result.unattributed == {"ghostmod.py": ["ghostmod"]}
    assert check.installed_file_owners([str(site)]) == {}


class _UnreadableDist:
    """A distribution whose metadata read fails the way the importlib_metadata backport fails."""

    @property
    def metadata(self):
        raise FileNotFoundError("No package metadata was found.")


class _NamedDist:
    metadata = {"Name": "Real_Pkg"}


def test_a_distribution_whose_metadata_cannot_be_read_has_no_name():
    assert check._distribution_name(_UnreadableDist()) is None
    assert check._distribution_name(_NamedDist()) == "Real_Pkg"


def _load_the_metadata_backport_if_installed() -> None:
    """Import importlib_metadata the way keyring does on Python 3.11.

    Once imported, its finder also answers importlib.metadata.distributions() and
    raises MetadataNotFound for unreadable metadata. Importing it here keeps the
    test faithful to the build no matter which tests ran first.
    """
    try:
        import importlib_metadata  # noqa: F401
    except ImportError:
        pass


def test_a_distribution_with_a_record_but_empty_metadata_is_skipped(site):
    # On Python 3.11 the importlib_metadata backport raises for this folder from
    # inside importlib.metadata.distributions(); 3.12 just reports no Name.
    _load_the_metadata_backport_if_installed()
    broken = site / "broken_pkg-1.0.dist-info"
    broken.mkdir()
    (broken / "METADATA").write_bytes(b"")
    (broken / "RECORD").write_text(
        "brokenmod.py,,\nbroken_pkg-1.0.dist-info/METADATA,,\n", encoding="utf-8"
    )
    (site / "brokenmod.py").write_bytes(b"")
    make_dist(site, "good-pkg", site_files={"goodmod.py": b""})

    file_owners = check.installed_file_owners([str(site)])
    module_owners = check.top_level_module_owners()

    assert file_owners == {
        normal(site / "goodmod.py"): "good-pkg",
        normal(site / "good_pkg-1.0.dist-info" / "METADATA"): "good-pkg",
        normal(site / "good_pkg-1.0.dist-info" / "RECORD"): "good-pkg",
    }
    assert module_owners["goodmod"] == ["good-pkg"]
    assert "brokenmod" not in module_owners


def test_top_level_names_are_found_like_the_standard_library_finds_them(site):
    make_dist(site, "declared-pkg", top_level=("declared_a", "declared_b"),
              site_files={"declared_a/__init__.py": b""})
    make_dist(site, "inferred-pkg", site_files={
        "inferred_pkg/__init__.py": b"",
        "inferred_mod.py": b"",
        "inferred-1.0.data/notes.txt": b"",
    })
    ours = check._packages_distributions()

    import importlib.metadata as stdlib_metadata

    theirs = stdlib_metadata.packages_distributions()
    for top in ("declared_a", "declared_b", "inferred_pkg", "inferred_mod"):
        assert ours[top] == theirs[top], top
    # A top-level entry with a dot in it is not importable and is left out by both.
    assert "inferred-1.0.data" not in ours


def test_root_files_that_are_not_modules_and_empty_record_rows_are_ignored(site):
    dist_info = make_dist(site, "odd-pkg", site_files={"oddmod.py": b"", "LICENSE": b""})
    record = dist_info / "RECORD"
    record.write_text(record.read_text(encoding="utf-8") + ",,\n", encoding="utf-8")

    ours = check._packages_distributions()

    assert ours["oddmod"] == ["odd-pkg"]
    assert "LICENSE" not in ours
    assert "" not in ours


# --- system libraries -----------------------------------------------------------------
#
# Away from Linux the analyses hold no such files and nothing here applies; the
# fakes use POSIX paths that only ever get compared as text.

LIB_DIR = "/usr/lib/x86_64-linux-gnu"


def lib(name: str):
    return (name, f"{LIB_DIR}/{name}", "BINARY")


def notices_with_libraries(libraries=(), *packages: str) -> str:
    """A notices file whose system library section lists *libraries* (none: no section)."""
    system = (
        notices.SystemLibraries([notices.SystemLibrary(n, ("some-pkg",)) for n in libraries], [])
        if libraries
        else None
    )
    return notices.render(
        [notices.Package(name=name, version="1.0", declaration="MIT") for name in packages],
        system,
    )


def library_report(text, analyses, *, enforce):
    return check.check_system_libraries(text, analyses, roots=[], enforce=enforce)


def test_packed_libraries_are_reported_per_analysis_apart_from_the_python_environment(tmp_path):
    python_home = tmp_path / "python"
    inside = ("libpython3.12.so", str(python_home / "libpython3.12.so"), "BINARY")
    analyses = {
        "gui": [lib("libnss3.so"), lib("libasound.so.2"), inside],
        "helper": [lib("libnss3.so"), ("json", f"{LIB_DIR}/json.py", "PYMODULE")],
        "bare": [inside],
    }

    report = check.check_system_libraries(
        notices_with_libraries(), analyses, roots=[str(python_home)], enforce=False
    )

    assert report.packed == {"gui": ["libasound.so.2", "libnss3.so"], "helper": ["libnss3.so"]}


def test_on_linux_the_notices_must_list_exactly_the_libraries_that_were_packed():
    analyses = {"gui": [lib("libnss3.so"), lib("libasound.so.2")], "helper": [lib("libnss3.so")]}

    exact = library_report(notices_with_libraries(["libasound.so.2", "libnss3.so"]), analyses, enforce=True)
    forgotten = library_report(notices_with_libraries(["libnss3.so"]), analyses, enforce=True)
    stale = library_report(
        notices_with_libraries(["libasound.so.2", "libgone.so", "libnss3.so"]), analyses, enforce=True
    )

    assert exact.listed == ["libasound.so.2", "libnss3.so"] and not exact.mismatch
    assert forgotten.unlisted == ["libasound.so.2"] and forgotten.not_packed == []
    assert forgotten.mismatch
    assert stale.not_packed == ["libgone.so"] and stale.unlisted == []
    assert stale.mismatch


def test_on_linux_libraries_packed_without_any_section_are_a_mismatch_but_none_is_fine():
    packed_some = library_report(notices_with_libraries(), {"gui": [lib("libnss3.so")]}, enforce=True)
    packed_none = library_report(notices_with_libraries(), {"gui": []}, enforce=True)

    assert packed_some.listed is None and packed_some.unlisted == ["libnss3.so"]
    assert packed_some.mismatch
    assert packed_none.listed is None and not packed_none.mismatch


def test_away_from_linux_the_libraries_are_information_only():
    analyses = {"gui": [lib("libnss3.so")]}

    no_section = library_report(notices_with_libraries(), analyses, enforce=False)
    different = library_report(notices_with_libraries(["libother.so"]), analyses, enforce=False)

    assert no_section.packed == {"gui": ["libnss3.so"]} and not no_section.mismatch
    assert different.packed == {"gui": ["libnss3.so"]} and not different.mismatch
    assert different.unlisted == [] and different.not_packed == []


def test_whether_the_notices_are_held_to_the_libraries_follows_the_platform(monkeypatch):
    analyses = {"gui": [lib("libnss3.so")]}
    text = notices_with_libraries()

    monkeypatch.setattr(notices, "is_linux", lambda: True)
    on_linux = check.check_system_libraries(text, analyses, roots=[])
    monkeypatch.setattr(notices, "is_linux", lambda: False)
    elsewhere = check.check_system_libraries(text, analyses, roots=[])

    assert on_linux.mismatch and not elsewhere.mismatch


def run_main(isolated, tmp_path, *, libraries, section, extra_notices=(), packed_libraries=("libnss3.so",)):
    """main() on a fake bundle that packs *packed_libraries* and a Python package."""
    site = isolated
    if not (site / "listedlib.py").exists():
        make_dist(site, "listed-lib", site_files={"listedlib.py": b""})
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(
        notices_with_libraries(libraries if section else (), "listed-lib", *extra_notices),
        encoding="utf-8",
    )
    toc = write_toc(
        tmp_path / "Analysis-00.toc",
        pure=[packed(site, "listedlib.py", "listedlib")],
        binaries=[lib(name) for name in packed_libraries],
    )
    return check.main([str(notices_file), str(toc)])


def test_main_lists_the_packed_libraries_and_passes_when_the_notices_name_them(
    isolated, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(notices, "is_linux", lambda: True)

    status = run_main(isolated, tmp_path, libraries=["libnss3.so"], section=True)

    out = capsys.readouterr()
    assert status == 0
    assert out.out.startswith("info: ") or "\ninfo: " in out.out
    assert "libnss3.so" in out.out and "Analysis-00.toc (1)" in out.out
    assert "accounts for every package" in out.out
    assert out.err == ""


def test_main_fails_on_linux_when_the_section_and_the_packed_libraries_differ(
    isolated, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(notices, "is_linux", lambda: True)

    status = run_main(isolated, tmp_path, libraries=["libother.so"], section=True)

    err = capsys.readouterr().err
    assert status == 1
    assert "libnss3.so" in err and "not listed in the 'System libraries bundled on Linux'" in err
    assert "libother.so" in err and "not packed into any executable" in err
    assert "does not match this build" in err


def test_main_fails_on_linux_when_the_notices_have_no_section_at_all(
    isolated, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(notices, "is_linux", lambda: True)

    status = run_main(isolated, tmp_path, libraries=[], section=False)

    err = capsys.readouterr().err
    assert status == 1
    assert "has no 'System libraries bundled on Linux' section" in err
    assert "libnss3.so" in err


def test_main_only_informs_away_from_linux_even_when_the_notices_do_not_match(
    isolated, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(notices, "is_linux", lambda: False)

    status = run_main(isolated, tmp_path, libraries=[], section=False)

    out = capsys.readouterr()
    assert status == 0
    assert "info: " in out.out and "libnss3.so" in out.out
    assert out.err == ""


def test_main_says_nothing_about_libraries_when_none_were_packed(
    isolated, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(notices, "is_linux", lambda: True)

    status = run_main(isolated, tmp_path, libraries=[], section=False, packed_libraries=())

    out = capsys.readouterr()
    assert status == 0
    assert "info:" not in out.out and out.err == ""


def test_main_reports_a_package_problem_and_a_library_problem_together(
    isolated, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(notices, "is_linux", lambda: True)
    make_dist(isolated, "forgotten-lib", site_files={"forgottenlib.py": b""})
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(notices_with_libraries(["libother.so"], "something-else"), encoding="utf-8")
    toc = write_toc(
        tmp_path / "Analysis-00.toc",
        pure=[packed(isolated, "forgottenlib.py", "forgottenlib")],
        binaries=[lib("libnss3.so")],
    )

    assert check.main([str(notices_file), str(toc)]) == 1

    err = capsys.readouterr().err
    assert "forgotten-lib" in err and "libnss3.so" in err and "libother.so" in err


def test_main_refuses_a_damaged_system_library_section_with_status_2(
    isolated, tmp_path, capsys
):
    make_dist(isolated, "listed-lib", site_files={"listedlib.py": b""})
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    damaged = notices_with_libraries(["libnss3.so"], "listed-lib").replace("System libraries (1)", "System libraries (7)")
    notices_file.write_text(damaged, encoding="utf-8")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[packed(isolated, "listedlib.py", "listedlib")])

    assert check.main([str(notices_file), str(toc)]) == 2

    assert "announces 7 system libraries" in capsys.readouterr().err


def test_main_reports_a_notices_file_that_is_not_utf8_with_status_2(isolated, tmp_path, capsys):
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_bytes("Components (0)\n".encode("utf-8") + b"\xff\xfe broken \x80")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[("m", "/elsewhere/m.py", "PYMODULE")])

    assert check.main([str(notices_file), str(toc)]) == 2

    assert "cannot read" in capsys.readouterr().err


def test_the_failure_advice_points_at_the_files_that_really_decide_what_is_listed(
    isolated, tmp_path, capsys
):
    make_dist(isolated, "forgotten-lib", site_files={"forgottenlib.py": b""})
    notices_file = tmp_path / "THIRD_PARTY_NOTICES.txt"
    notices_file.write_text(notices_text("something-else"), encoding="utf-8")
    toc = write_toc(tmp_path / "Analysis-00.toc", pure=[packed(isolated, "forgottenlib.py", "forgottenlib")])

    assert check.main([str(notices_file), str(toc)]) == 1

    err = capsys.readouterr().err
    assert "--exclude-module" in err
    assert "pyproject.toml" in err and "EMBEDDED_BUILD_TOOLS" in err


# --- the real environment --------------------------------------------------------


def test_files_of_the_real_environment_are_attributed_to_their_packages():
    origins = {}
    for module in ("keyring", "_pytest", "PyQt6"):
        spec = importlib.util.find_spec(module)
        assert spec is not None and spec.origin, module
        origins[module] = spec.origin
    entries = [(module, origin, "PYMODULE") for module, origin in origins.items()]

    result = check.attribute_entries(
        entries,
        check.installed_file_owners(),
        check.default_site_dirs(),
        check.top_level_module_owners(),
    )

    assert set(result.distributions) == {"keyring", "pytest", "pyqt6"}
    assert result.unattributed == {}
