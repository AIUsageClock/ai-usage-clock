from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QIcon


def app_icon_path(extension: str = "png") -> Path:
    """Return the packaged AI Usage Clock application-icon asset."""
    return Path(__file__).resolve().parent / "assets" / f"aiusageclockicon.{extension}"


def app_icon() -> QIcon:
    """Load the canonical icon used by application windows and dialogs."""
    return QIcon(str(app_icon_path()))
