"""Throwaway ``*.dist-info`` folders for the third-party notice tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def make_dist(
    root: Path,
    name: str,
    version: str = "1.0",
    *,
    requires: tuple[str, ...] = (),
    expression: str | None = None,
    license_field: str | None = None,
    classifiers: tuple[str, ...] = (),
    license_file_entries: tuple[str, ...] = (),
    files: dict[str, bytes] | None = None,
    site_files: dict[str, bytes] | None = None,
    top_level: tuple[str, ...] = (),
    with_record: bool = True,
) -> Path:
    """Create ``<name>-<version>.dist-info`` under *root*.

    *files* are relative to the dist-info folder. *site_files* are the
    distribution's own files, relative to *root*, and are listed in RECORD.
    *top_level* writes top_level.txt; ``with_record=False`` leaves RECORD out.
    """
    folder = f"{name.replace('-', '_')}-{version}.dist-info"
    dist_info = root / folder
    dist_info.mkdir(parents=True)
    header = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if expression:
        header.append(f"License-Expression: {expression}")
    if license_field:
        header.append(f"License: {license_field}")
    header.extend(f"Classifier: {value}" for value in classifiers)
    header.extend(f"License-File: {value}" for value in license_file_entries)
    header.extend(f"Requires-Dist: {value}" for value in requires)
    (dist_info / "METADATA").write_text("\n".join(header) + "\n", encoding="utf-8")
    record = [f"{folder}/METADATA,,", f"{folder}/RECORD,,"]
    for relative, data in (files or {}).items():
        target = dist_info / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record.append(f"{folder}/{relative},,")
    for relative, data in (site_files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record.append(f"{relative},,")
    if top_level:
        (dist_info / "top_level.txt").write_text("\n".join(top_level) + "\n", encoding="utf-8")
    if with_record:
        (dist_info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")
    return dist_info


@pytest.fixture
def site(tmp_path, monkeypatch):
    """An empty site directory that importlib.metadata searches first."""
    root = tmp_path / "site"
    root.mkdir()
    monkeypatch.syspath_prepend(str(root))
    return root
