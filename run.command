#!/bin/bash
# Double-click this file in Finder to launch the NLM Scrubber GUI.
# No installation required — uses the python3 that ships with macOS.
#
# If macOS refuses to run it ("can't be opened because Apple cannot check..."),
# right-click the file and choose Open, then click Open in the dialog.

set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    osascript -e 'display alert "Python 3 not found" message "Install Python 3 from python.org or run: xcode-select --install"'
    exit 1
fi

exec python3 nlm_scrubber_mac_gui.py
