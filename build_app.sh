#!/bin/bash
# Build a double-clickable "NLM Scrubber.app" bundle in ./dist/.
# Requires Python 3 and pip (both ship with macOS Command Line Tools).
#
# Why py2app and not PyInstaller?  py2app produces a proper macOS .app with
# the right Info.plist for the OpenDocument Apple Event (drag-onto-Dock),
# which is how this app receives dropped files on stock macOS.

set -euo pipefail
cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This build script targets macOS. On other systems, just run 'python3 nlm_scrubber_mac_gui.py' directly."
    exit 1
fi

PYTHON="${PYTHON:-python3}"

echo "==> Cleaning previous build artifacts..."
rm -rf build dist

echo "==> Ensuring py2app is installed..."
"$PYTHON" -m pip install --user --upgrade py2app >/dev/null

echo "==> Building app bundle..."
"$PYTHON" setup.py py2app

echo
echo "Done.  App bundle: $(pwd)/dist/NLM Scrubber.app"
echo "Drag it into /Applications, then double-click to launch."
