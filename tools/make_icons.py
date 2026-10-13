#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyQt6>=6.7,<7"]
# ///
"""Build the AI Usage Clock app icons from a single vector design.

Usage:
    uv run tools/make_icons.py [OUTPUT_DIR]

OUTPUT_DIR defaults to src/aiusageclock/assets. Writes:
    aiusageclockicon.svg   vector source
    aiusageclockicon.png   1024x1024
    aiusageclockicon.ico   16-256 px, PNG-compressed frames
    aiusageclockicon.icns  16-1024 px, PNG-compressed frames

Every size is rendered from the same SVG (no simplified small-size artwork),
so the icon keeps one composition at every scale.
"""
from __future__ import annotations

import math
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

NAME = "aiusageclockicon"
ICO_SIZES = [16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128, 256]
ICNS_TYPES = [
    ("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256),
    ("ic09", 512), ("ic10", 1024), ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512),
]

C = 128.0  # centre of the 256x256 viewBox
GREEN, YELLOW, RED = (0x22, 0xC5, 0x5E), (0xEA, 0xB3, 0x08), (0xEF, 0x44, 0x44)


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _ramp(t: float) -> str:
    rgb = _lerp(GREEN, YELLOW, t / 0.5) if t <= 0.5 else _lerp(YELLOW, RED, (t - 0.5) / 0.5)
    return "#%02X%02X%02X" % rgb


def _pt(r: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return C + r * math.sin(rad), C - r * math.cos(rad)


def _arc(r: float, a1: float, a2: float, color: str, width: float) -> str:
    x1, y1 = _pt(r, a1)
    x2, y2 = _pt(r, a2)
    large = 1 if (a2 - a1) > 180 else 0
    return (
        f'<path d="M {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f}" '
        f'fill="none" stroke="{color}" stroke-width="{width}"/>'
    )


def _line(r1: float, r2: float, deg: float, color: str, width: float) -> str:
    x1, y1 = _pt(r1, deg)
    x2, y2 = _pt(r2, deg)
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
    )


def icon_svg() -> str:
    """Clock face inside a green-to-red usage ring; the minute hand marks the reset at 12."""
    steps, sweep = 36, 270.0
    parts = [
        '<rect x="8" y="8" width="240" height="240" rx="56" fill="#0F172A"/>',
        f'<circle cx="{C}" cy="{C}" r="92" fill="none" stroke="#334155" stroke-width="24"/>',
    ]
    for i in range(steps):
        a1 = i * sweep / steps
        a2 = (i + 1) * sweep / steps + (0.6 if i < steps - 1 else 0)
        parts.append(_arc(92, a1, a2, _ramp(i / (steps - 1)), 24))
    parts.append(f'<circle cx="{C}" cy="{C}" r="76" fill="#1E293B"/>')
    for i in range(12):
        major = i % 3 == 0
        parts.append(_line(70, 56 if major else 62, i * 30, "#CBD5E1", 7 if major else 4))
    parts += [
        _line(0, 54, 0, "#F8FAFC", 11),
        _line(0, 36, 120, "#F8FAFC", 13),
        f'<circle cx="{C}" cy="{C}" r="10" fill="#F8FAFC"/>',
    ]
    body = "\n".join(parts)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">\n'
        f"{body}\n</svg>\n"
    )


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, "PNG"):
        raise RuntimeError(f"PNG encode failed at {size}px")
    buf.close()
    return bytes(data)


def build_ico(frames: dict[int, bytes]) -> bytes:
    sizes = sorted(frames)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, payload = b"", b""
    for size in sizes:
        png = frames[size]
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    return header + entries + payload


def build_icns(frames: dict[int, bytes]) -> bytes:
    body = b"".join(
        kind.encode("ascii") + struct.pack(">I", 8 + len(frames[size])) + frames[size]
        for kind, size in ICNS_TYPES
    )
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def main(argv: list[str]) -> int:
    default = Path(__file__).resolve().parents[1] / "src" / "aiusageclock" / "assets"
    out = Path(argv[1]) if len(argv) > 1 else default
    out.mkdir(parents=True, exist_ok=True)

    app = QGuiApplication(argv[:1])  # noqa: F841 - QSvgRenderer needs a GUI app
    svg = icon_svg()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("SVG did not parse")

    needed = sorted(set(ICO_SIZES) | {size for _, size in ICNS_TYPES} | {1024})
    frames = {size: render_png(renderer, size) for size in needed}

    (out / f"{NAME}.svg").write_text(svg, encoding="utf-8", newline="\n")
    (out / f"{NAME}.png").write_bytes(frames[1024])
    (out / f"{NAME}.ico").write_bytes(build_ico({s: frames[s] for s in ICO_SIZES}))
    (out / f"{NAME}.icns").write_bytes(build_icns(frames))
    for suffix in ("svg", "png", "ico", "icns"):
        path = out / f"{NAME}.{suffix}"
        print(f"{path.name}: {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
