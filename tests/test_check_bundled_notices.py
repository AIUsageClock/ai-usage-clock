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
