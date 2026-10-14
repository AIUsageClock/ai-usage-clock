#!/usr/bin/env bash
# Build a standalone macOS .app or Linux folder using PyInstaller.
#
# Usage:
#   ./build.sh             # one-folder build (recommended)
#   ./build.sh --onefile   # single-file binary (slower first launch)
#
# Expects a virtualenv at .venv (created by `python -m venv .venv` and
# `.venv/bin/pip install -e .[dev]`).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "Virtualenv not found at .venv. Run:" >&2
    echo "  python3 -m venv .venv" >&2
    echo "  .venv/bin/pip install -e .[dev]" >&2
    exit 1
fi

ONEFILE=0
for arg in "$@"; do
    case "$arg" in
        --onefile|--one-file|-OneFile) ONEFILE=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

"$VENV_PY" -m pip install --quiet pyinstaller

PYINSTALLER_ARGS=(
    -m PyInstaller
    --noconfirm
    --clean
    --windowed
    --noupx
    --name ai-usage-clock
    # cffi (a cryptography dependency) imports setuptools lazily for its
    # compile-time features, which nothing here calls. Without these flags
    # setuptools, its vendored libraries and packaging end up in the bundle.
    --exclude-module setuptools
    --exclude-module pkg_resources
    --exclude-module _distutils_hack
    --paths src
    --collect-data aiusageclock
    --collect-all PyQt6.QtWebEngineWidgets
    --collect-all PyQt6.QtWebEngineCore
    pyinstaller_entry.py
)

if [ "$(uname -s)" = "Darwin" ]; then
    # Reverse-DNS bundle id; keeps Info.plist + LaunchServices happy.
    PYINSTALLER_ARGS+=(--osx-bundle-identifier com.aiusageclock.ai-usage-clock)
    PYINSTALLER_ARGS+=(--icon src/aiusageclock/assets/aiusageclockicon.icns)
else
    PYINSTALLER_ARGS+=(--icon src/aiusageclock/assets/aiusageclockicon.png)
fi

if [ "$ONEFILE" -eq 1 ]; then
    PYINSTALLER_ARGS+=(--onefile)
fi

"$VENV_PY" "${PYINSTALLER_ARGS[@]}"

# mcp pulls in httpx, whose optional CLI path reaches pygments, whose img
# formatter imports Pillow — ~13 MB of image codecs in a stdio JSON-RPC server
# that never renders anything. pygments is present because the build venv
# installs .[dev] (pytest needs it), so it is not a declared runtime dependency
# of anything the helper actually calls. A one-file payload is already
# compressed, so it does not shrink again inside the release archive; dropping
# these here is a straight ~8.6 MB off every platform's download.
#
# The same venv also leaks development and build-time packages through optional
# imports: anyio tries _pytest, uvicorn and pydantic-settings try yaml, and cffi
# tries setuptools. None of them is a runtime dependency of the helper, so they
# stay out of the executable and out of THIRD_PARTY_NOTICES.txt;
# tools/check_bundled_notices.py fails the build if one gets back in.
"$VENV_PY" -m PyInstaller \
    --noconfirm \
    --clean \
    --console \
    --onefile \
    --noupx \
    --name ai-usage-clock-mcp \
    --exclude-module PIL \
    --exclude-module pygments \
    --exclude-module _pytest \
    --exclude-module pytest \
    --exclude-module yaml \
    --exclude-module setuptools \
    --exclude-module pkg_resources \
    --exclude-module _distutils_hack \
    --paths src \
    pyinstaller_mcp_entry.py

# macOS ships the helper beside the .app because there is no folder bundle to
# put it in; every other layout nests it next to the GUI binary.
if [ "$(uname -s)" != "Darwin" ] && [ "$ONEFILE" -eq 0 ]; then
    mv dist/ai-usage-clock-mcp dist/ai-usage-clock/ai-usage-clock-mcp
    EXPECTED_MCP="dist/ai-usage-clock/ai-usage-clock-mcp"
else
    EXPECTED_MCP="dist/ai-usage-clock-mcp"
fi

# release.yml smoke-tests and packages the helper at a fixed path. Fail here,
# with the path named, rather than partway through a tag release.
if [ ! -f "$EXPECTED_MCP" ]; then
    echo "MCP helper missing at expected release path: $EXPECTED_MCP" >&2
    exit 1
fi

# On macOS, mark the bundle as a menu-bar-only agent so it doesn't show a
# Dock icon. Tradeoff: the floating-widget mode (off by default on Mac)
# also won't appear in Cmd-Tab while LSUIElement is set.
# PyInstaller mis-lays-out QtWebEngineCore.framework on macOS: it puts the
# Helpers directory and the WebEngine resource files at
# Versions/Resources/{Helpers,Resources} instead of Versions/A/{Helpers,Resources},
# so the top-level Helpers and Resources symlinks (which target
# Versions/Current/...) dangle and Qt can't find QtWebEngineProcess or
# icudtl.dat / *.pak.  Relocate them into the proper Versions/A layout.
if [ "$(uname -s)" = "Darwin" ] && [ "$ONEFILE" -eq 0 ]; then
    FWDIR="dist/ai-usage-clock.app/Contents/Frameworks/PyQt6/Qt6/lib/QtWebEngineCore.framework"
    STRAY="$FWDIR/Versions/Resources"
    if [ -d "$STRAY/Helpers" ] && [ ! -d "$FWDIR/Versions/A/Helpers" ]; then
        mv "$STRAY/Helpers" "$FWDIR/Versions/A/Helpers"
    fi
    if [ -d "$STRAY/Resources" ]; then
        cp -R "$STRAY/Resources/." "$FWDIR/Versions/A/Resources/"
    fi
    if [ -d "$STRAY" ]; then
        rm -rf "$STRAY"
    fi
fi

if [ "$(uname -s)" = "Darwin" ] && [ "$ONEFILE" -eq 0 ] \
        && [ -f "dist/ai-usage-clock.app/Contents/Info.plist" ]; then
    /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" \
        dist/ai-usage-clock.app/Contents/Info.plist 2>/dev/null \
        || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" \
            dist/ai-usage-clock.app/Contents/Info.plist
fi

# --collect-all on the WebEngine modules also drags in Chromium's debug
# resource packs, the DevTools front-end, and every Qt translation — ~140 MB
# the app never loads. Strip them before the folder is archived (issue #7).
# One-file builds are already packed by this point, so there is nothing to do.
if [ "$ONEFILE" -eq 0 ]; then
    if [ "$(uname -s)" = "Darwin" ]; then
        PRUNE_TARGET="dist/ai-usage-clock.app"
    else
        PRUNE_TARGET="dist/ai-usage-clock"
    fi
    echo
    echo "Pruning unused Qt/Chromium payload..."
    "$VENV_PY" "$SCRIPT_DIR/tools/prune_bundle.py" "$PRUNE_TARGET"
fi

# The MIT License requires its text to travel with every copy, and the bundled
# PyQt6/Qt/Chromium and the other dependencies each carry terms of their own.
# Ship LICENSE and THIRD_PARTY_NOTICES.txt with the build output: inside the
# folder on Linux, beside the .app and the MCP helper on macOS (and for
# one-file builds, which have no folder).
if [ "$(uname -s)" = "Darwin" ] || [ "$ONEFILE" -eq 1 ]; then
    NOTICE_DIR="dist"
else
    NOTICE_DIR="dist/ai-usage-clock"
fi
cp "$SCRIPT_DIR/LICENSE" "$NOTICE_DIR/LICENSE"
"$VENV_PY" "$SCRIPT_DIR/tools/write_third_party_notices.py" "$NOTICE_DIR/THIRD_PARTY_NOTICES.txt"
for NOTICE_FILE in LICENSE THIRD_PARTY_NOTICES.txt; do
    if [ ! -f "$NOTICE_DIR/$NOTICE_FILE" ]; then
        echo "$NOTICE_FILE missing from the build output: $NOTICE_DIR" >&2
        exit 1
    fi
done

# The notices are written from package metadata; what PyInstaller really packed
# can differ. Compare the two and fail on any package that ships unlisted.
"$VENV_PY" "$SCRIPT_DIR/tools/check_bundled_notices.py" \
    "$NOTICE_DIR/THIRD_PARTY_NOTICES.txt" \
    "$SCRIPT_DIR/build/ai-usage-clock/Analysis-00.toc" \
    "$SCRIPT_DIR/build/ai-usage-clock-mcp/Analysis-00.toc"

echo
echo "Build complete."
case "$(uname -s)" in
    Darwin)
        if [ "$ONEFILE" -eq 1 ]; then
            echo "Binary: dist/ai-usage-clock"
        else
            echo "Bundle: dist/ai-usage-clock.app"
        fi
        echo "MCP helper: dist/ai-usage-clock-mcp"
        ;;
    *)
        if [ "$ONEFILE" -eq 1 ]; then
            echo "Binary: dist/ai-usage-clock"
        else
            echo "Folder: dist/ai-usage-clock/  (run ./ai-usage-clock inside)"
            echo "MCP helper: dist/ai-usage-clock/ai-usage-clock-mcp"
        fi
        ;;
esac
