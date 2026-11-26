"""Tests for the "unused Qt modules" tier of tools/prune_bundle.py.

Each test builds a fake bundle tree with the file names the three platforms
use, so the name matching is checked without needing a real PyInstaller build.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools import prune_bundle as prune

# Modules the Qt WebEngine chain needs (or whose removal is not worth the risk).
KEPT_MODULES = [
    "Core", "Gui", "Widgets", "Network", "OpenGL", "PrintSupport", "Svg",
    "Positioning", "SerialPort", "DBus", "XcbQpa", "Qml", "QmlMeta",
    "QmlModels", "QmlWorkerScript", "Quick", "QuickWidgets", "WebChannel",
    "WebEngineCore", "WebEngineWidgets",
]  # fmt: skip

REMOVED_MODULES = [
    "Multimedia", "MultimediaQuick", "PositioningQuick", "QmlCore", "Quick3D",
    "Quick3DRuntimeRender", "Quick3DXr", "QuickControls2",
    "QuickControls2Material", "QuickDialogs2", "QuickEffects", "QuickLayouts",
    "QuickNativeStyle", "QuickParticles", "QuickShapes", "QuickTemplates2",
    "QuickTest", "QuickTimeline", "QuickTimelineBlendTrees",
    "QuickVectorImage", "RemoteObjects", "Sensors", "SensorsQuick",
    "ShaderTools", "SpatialAudio", "StateMachine", "StateMachineQml", "Test",
    "TextToSpeech", "WebChannelQuick", "WebEngineQuick",
    "WebEngineQuickDelegatesQml", "WebSockets",
]  # fmt: skip


def touch(path: Path, size: int = 8) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def run_prune(root: Path) -> list[tuple[Path, int]]:
    removed: list[tuple[Path, int]] = []
    prune.prune_unused_qt(root, removed)
    return removed


def test_no_pattern_can_reach_a_protected_module():
    for name in prune.PROTECTED_QT_MODULES:
        assert not prune.is_unused_qt_module(name), name
    for name in KEPT_MODULES:
        assert not prune.is_unused_qt_module(name), name
    for name in REMOVED_MODULES:
        assert prune.is_unused_qt_module(name), name


@pytest.mark.parametrize("name", ["Quick", "Qml", "QmlModels", "QmlMeta", "Positioning"])
def test_chain_modules_are_not_prefix_matched(name):
    # "Quick" is a prefix of Quick3D, QuickControls2 ... but must stay.
    assert not prune.is_unused_qt_module(name)


def test_windows_layout(tmp_path):
    bundle = tmp_path / "ai-usage-clock"
    qt = bundle / "_internal" / "PyQt6" / "Qt6"
    for module in KEPT_MODULES:
        touch(qt / "bin" / f"Qt6{module}.dll")
    for module in REMOVED_MODULES:
        touch(qt / "bin" / f"Qt6{module}.dll")
    touch(qt / "bin" / "opengl32sw.dll", 100)
    touch(qt / "bin" / "QtWebEngineProcess.exe")
    touch(qt / "bin" / "MSVCP140.dll")
    for plugin in ("platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll",
                   "imageformats/qsvg.dll", "tls/qschannelbackend.dll",
                   "iconengines/qsvgicon.dll", "networkinformation/qnetworklistmanager.dll",
                   "position/qtposition_winrt.dll", "generic/qtuiotouchplugin.dll"):  # fmt: skip
        touch(qt / "plugins" / plugin)
    for plugin in ("qmltooling/x.dll", "sceneparsers/y.dll", "geometryloaders/z.dll",
                   "renderers/r.dll", "multimedia/m.dll"):  # fmt: skip
        touch(qt / "plugins" / plugin)
    touch(qt / "qml" / "QtQuick" / "Controls" / "plugin.dll")
    touch(qt / "qml" / "QtQuick" / "qmldir")
    py = bundle / "_internal" / "PyQt6"
    for module in ("Core", "Gui", "Network", "Widgets", "PrintSupport",
                   "WebChannel", "WebEngineCore", "WebEngineWidgets"):  # fmt: skip
        touch(py / f"Qt{module}.pyd")
    for module in ("OpenGL", "Positioning", "Qml", "Quick", "QuickWidgets"):
        touch(py / f"Qt{module}.pyd")
    touch(py / "sip.cp314-win_amd64.pyd")
    touch(bundle / "_internal" / "python314.dll")
    touch(bundle / "ai-usage-clock.exe")

    removed = run_prune(bundle)
    left = {p.name for p in bundle.rglob("*") if p.is_file()}

    for module in KEPT_MODULES:
        assert f"Qt6{module}.dll" in left, module
    for module in REMOVED_MODULES:
        assert f"Qt6{module}.dll" not in left, module
    assert "opengl32sw.dll" in left
    assert {"QtWebEngineProcess.exe", "MSVCP140.dll", "python314.dll",
            "ai-usage-clock.exe", "sip.cp314-win_amd64.pyd"} <= left  # fmt: skip
    for kept in ("qwindows.dll", "qmodernwindowsstyle.dll", "qsvg.dll",
                 "qschannelbackend.dll", "qsvgicon.dll", "qnetworklistmanager.dll",
                 "qtposition_winrt.dll", "qtuiotouchplugin.dll"):  # fmt: skip
        assert kept in left, kept
    for gone in ("x.dll", "y.dll", "z.dll", "r.dll", "m.dll", "plugin.dll", "qmldir"):
        assert gone not in left, gone
    assert not (qt / "qml").exists()
    for module in ("Core", "Gui", "Network", "Widgets", "PrintSupport",
                   "WebChannel", "WebEngineCore", "WebEngineWidgets"):  # fmt: skip
        assert f"Qt{module}.pyd" in left, module
    for module in ("OpenGL", "Positioning", "Qml", "Quick", "QuickWidgets"):
        assert f"Qt{module}.pyd" not in left, module
    assert sum(size for _, size in removed) > 0


def test_linux_layout(tmp_path):
    bundle = tmp_path / "ai-usage-clock"
    qt = bundle / "_internal" / "PyQt6" / "Qt6"
    for module in KEPT_MODULES:
        touch(qt / "lib" / f"libQt6{module}.so.6")
    for module in REMOVED_MODULES:
        touch(qt / "lib" / f"libQt6{module}.so.6")
        touch(qt / "lib" / f"libQt6{module}.so.6.12.0")
    touch(qt / "plugins" / "platforms" / "libqxcb.so")
    touch(qt / "plugins" / "multimedia" / "libffmpegmediaplugin.so")
    touch(qt / "qml" / "QtQml" / "libqmlplugin.so")
    touch(bundle / "_internal" / "PyQt6" / "QtCore.abi3.so")
    touch(bundle / "_internal" / "PyQt6" / "QtQml.abi3.so")
    touch(bundle / "_internal" / "libpython3.14.so.1.0")
    touch(bundle / "_internal" / "libQt6Fake_notqt.txt")

    run_prune(bundle)
    left = {p.name for p in bundle.rglob("*") if p.is_file()}

    for module in KEPT_MODULES:
        assert f"libQt6{module}.so.6" in left, module
    for module in REMOVED_MODULES:
        assert f"libQt6{module}.so.6" not in left, module
        assert f"libQt6{module}.so.6.12.0" not in left, module
    assert {"libqxcb.so", "QtCore.abi3.so", "libpython3.14.so.1.0",
            "libQt6Fake_notqt.txt"} <= left  # fmt: skip
    assert "libffmpegmediaplugin.so" not in left
    assert "libqmlplugin.so" not in left
    assert "QtQml.abi3.so" not in left


def test_macos_layout_removes_frameworks_and_dangling_links(tmp_path):
    app = tmp_path / "ai-usage-clock.app"
    frameworks = app / "Contents" / "Frameworks"
    lib = frameworks / "PyQt6" / "Qt6" / "lib"
    for module in KEPT_MODULES + REMOVED_MODULES:
        touch(lib / f"Qt{module}.framework" / "Versions" / "A" / f"Qt{module}")
    touch(frameworks / "PyQt6" / "Qt6" / "plugins" / "platforms" / "libqcocoa.dylib")
    touch(frameworks / "PyQt6" / "Qt6" / "plugins" / "sceneparsers" / "libgltf.dylib")
    touch(frameworks / "PyQt6" / "QtCore.abi3.so")
    touch(frameworks / "PyQt6" / "QtQuick.abi3.so")
    touch(app / "Contents" / "MacOS" / "ai-usage-clock")

    link_note = ""
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True)
    try:
        # What PyInstaller does: a link at another location to a removed item.
        os.symlink(lib / "QtQuick3D.framework", resources / "QtQuick3D.framework")
        os.symlink(lib / "QtCore.framework", resources / "QtCore.framework")
        os.symlink(frameworks / "PyQt6" / "QtQuick.abi3.so", resources / "QtQuick.abi3.so")
    except (OSError, NotImplementedError):
        link_note = "symlinks unavailable"

    run_prune(app)

    for module in KEPT_MODULES:
        assert (lib / f"Qt{module}.framework").is_dir(), module
    for module in REMOVED_MODULES:
        assert not (lib / f"Qt{module}.framework").exists(), module
    assert (frameworks / "PyQt6" / "Qt6" / "plugins" / "platforms" / "libqcocoa.dylib").is_file()
    assert not (frameworks / "PyQt6" / "Qt6" / "plugins" / "sceneparsers").exists()
    assert (frameworks / "PyQt6" / "QtCore.abi3.so").is_file()
    assert not (frameworks / "PyQt6" / "QtQuick.abi3.so").exists()
    if not link_note:
        assert not os.path.lexists(resources / "QtQuick3D.framework")
        assert not os.path.lexists(resources / "QtQuick.abi3.so")
        assert (resources / "QtCore.framework").is_symlink()  # untouched, still valid


def test_preexisting_dangling_link_is_left_alone(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    link = bundle / "old-link"
    try:
        os.symlink(bundle / "nowhere", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    run_prune(bundle)
    assert os.path.lexists(link)


def test_main_reports_three_tiers_and_keeps_existing_behaviour(tmp_path, capsys):
    bundle = tmp_path / "ai-usage-clock"
    qt = bundle / "_internal" / "PyQt6" / "Qt6"
    touch(qt / "bin" / "Qt6Quick3D.dll", 2_000_000)
    touch(qt / "bin" / "Qt6Quick.dll", 2_000_000)
    touch(qt / "translations" / "qtbase_de.qm")
    touch(qt / "translations" / "qtbase_en.qm")
    touch(qt / "resources" / "qtwebengine_resources.debug.pak")

    assert prune.main.__module__ == "tools.prune_bundle"
    import sys

    argv = sys.argv
    sys.argv = ["prune_bundle.py", str(bundle)]
    try:
        assert prune.main() == 0
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "unreachable:" in out and "localisation:" in out and "unused Qt modules: 1 files" in out
    assert (qt / "bin" / "Qt6Quick.dll").exists()
    assert not (qt / "bin" / "Qt6Quick3D.dll").exists()
    assert (qt / "translations" / "qtbase_en.qm").exists()
    assert not (qt / "translations" / "qtbase_de.qm").exists()
