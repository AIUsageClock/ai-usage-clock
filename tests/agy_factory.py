"""Fake ``agy`` files for tests that expect the path to be launchable."""

import os
from pathlib import Path


def make_fake_agy(path: Path, text: str = "") -> Path:
    """Create ``path`` as an executable file (mode 0o755) and return it.

    On macOS and Linux the app rejects a manually chosen agy path without the
    execute bit (AG-10), so a plain ``touch()`` file is "not executable" there.
    chmod is harmless on Windows, where the check is skipped.
    """
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o755)
    return path
