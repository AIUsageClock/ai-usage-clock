"""Tests for tools/write_third_party_notices.py.

Most tests build throwaway ``*.dist-info`` folders in a temporary directory and
put it on ``sys.path``, so each case controls exactly what the generator sees.
The last group runs against the real virtualenv: PyQt6 must be listed with its
GPL text, and nothing from the dev extras may leak in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.dist_info_factory import make_dist, site  # noqa: F401  (site is a fixture)
from tools import write_third_party_notices as notices


def names_of(packages) -> list[str]:
    return [package.name for package in packages]


def build(project: str, python_dirs: list[Path] | None = None):
    """build_notices for a fake project, looking for Python's license in *python_dirs* only."""
    return notices.build_notices(
        project, (), (), python_dirs=[] if python_dirs is None else python_dirs
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
    assert names_of(packages) == ["Python", "noticetest-alpha", "noticetest-zeta"]
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


def test_the_introduction_points_to_the_project_license(site):
    make_dist(site, "noticetest-app")

    text, _ = build("noticetest-app")

    assert text.startswith("THIRD-PARTY NOTICES\n")
    assert "MIT License; see the LICENSE file" in text
    assert notices.REPO_URL in text


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
    def fail():
        raise notices.MissingDependencies(["somepackage"])

    monkeypatch.setattr(notices, "build_notices", fail)
    output = tmp_path / "out" / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output)]) == 1

    assert "somepackage" in capsys.readouterr().err
    assert not output.exists()


def test_main_warns_about_packages_without_license_text(tmp_path, monkeypatch, capsys):
    bare = notices.Package(name="bare", version="2.0", declaration="MIT")
    monkeypatch.setattr(notices, "build_notices", lambda: ("text\n", [bare]))
    output = tmp_path / "THIRD_PARTY_NOTICES.txt"

    assert notices.main([str(output)]) == 0

    assert "no license text found for bare 2.0" in capsys.readouterr().err
    assert output.read_bytes() == b"text\n"


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
    # embedded in the executables; setuptools and packaging are kept out of
    # them by --exclude-module and checked by tools/check_bundled_notices.py.
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
