"""Reading PyInstaller's analysis file and comparing the paths in it.

``build/<name>/Analysis-00.toc`` lists every file PyInstaller packed into an
executable. Two build tools read it: tools/check_bundled_notices.py compares it
with THIRD_PARTY_NOTICES.txt, and tools/write_third_party_notices.py uses it to
find the system libraries a Linux build carries. This module is the part they
share: it only knows how to read the file and how to spell a path so that two
spellings of the same file compare equal.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path

# PYMODULE, PYMODULE-1, PYSOURCE, EXTENSION, BINARY, DATA, SYMLINK, ...
_TYPECODE = re.compile(r"^[A-Z][A-Z0-9]*(-[0-9]+)?$")

TocEntry = tuple[str, str, str]


class InputError(Exception):
    """A file the check needs cannot be read or does not look as expected."""


def iter_toc_entries(node: object) -> Iterator[TocEntry]:
    """Every ``(name, source path, typecode)`` triple in a parsed analysis.

    Analysis-00.toc is a pprint of PyInstaller's analysis state. The fields are
    positional and have been added to over the releases, so this walks the
    whole structure for the triple shape instead of indexing into it. That also
    covers the files the build was told to collect (the ``datas`` and
    ``binaries`` inputs), not only the ones PyInstaller found.
    """
    if (
        isinstance(node, tuple)
        and len(node) == 3
        and all(isinstance(value, str) for value in node)
        and _TYPECODE.match(node[2])
    ):
        yield node
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from iter_toc_entries(child)
    elif isinstance(node, dict):
        for child in node.values():
            yield from iter_toc_entries(child)


def read_analysis_toc(path: Path) -> list[TocEntry]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read the PyInstaller analysis {path}: {exc}") from exc
    try:
        data = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError) as exc:
        raise InputError(f"{path} is not a PyInstaller Analysis-00.toc: {exc}") from exc
    entries = list(iter_toc_entries(data))
    if not entries:
        raise InputError(f"{path} lists no packed files; is it an Analysis-00.toc?")
    return entries


def normal_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(path))


def path_spellings(path: str | os.PathLike[str]) -> list[str]:
    """The path as given and with symlinks resolved, normalised; one when they agree.

    A virtualenv reached through a symlink can show up under either spelling,
    depending on whether PyInstaller or the package metadata recorded it.
    """
    plain = normal_path(path)
    resolved = os.path.normcase(os.path.realpath(path))
    return [plain] if resolved == plain else [plain, resolved]
