#!/bin/bash
# Standalone Docker launcher for NLM Scrubber.
# Use this when the native scrubber binary won't run on your OS (e.g. macOS Apple Silicon).
#
# Usage:
#   ./run_in_docker.sh <input_dir_or_file> <output_dir>
#
# Prerequisites: Docker Desktop running, NLM Scrubber already downloaded by the GUI
#   (or manually placed in ~/.nlm_scrubber/).

set -euo pipefail

SCRUBBER_DIR="${HOME}/.nlm_scrubber"
BIN="${SCRUBBER_DIR}/scrubber.lnx"

if [[ ! -f "$BIN" ]]; then
    echo "Error: $BIN not found. Run the GUI at least once to download NLM Scrubber." >&2
    exit 1
fi

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <input_dir_or_file> <output_dir>" >&2
    exit 1
fi

INPUT=$(realpath "$1")
OUTPUT=$(realpath "$2")
mkdir -p "$OUTPUT"

# If input is a file, wrap it in a temp dir.
CLEANUP_INPUT=0
if [[ -f "$INPUT" ]]; then
    TMP_INPUT=$(mktemp -d)
    cp "$INPUT" "$TMP_INPUT/"
    INPUT="$TMP_INPUT"
    CLEANUP_INPUT=1
fi

# Write a config for the container-internal paths.
cat > "${SCRUBBER_DIR}/config_docker.txt" <<EOF
input_dir=/input
output_dir=/output
input_type=txt
output_type=txt
find_date=yes
find_patient=yes
find_doctor=yes
find_hospital=yes
find_unique_id=yes
find_phone=yes
find_email=yes
find_age=yes
find_url=yes
find_state=yes
find_city=yes
find_rated_number=no
use_surrogates=no
EOF

echo "Running NLM Scrubber via Docker..."
docker run --rm \
    -v "${SCRUBBER_DIR}:/scrubber" \
    -v "${INPUT}:/input:ro" \
    -v "${OUTPUT}:/output" \
    ubuntu:22.04 \
    /scrubber/scrubber.lnx /scrubber/config_docker.txt

echo "Done. Output: $OUTPUT"

if [[ $CLEANUP_INPUT -eq 1 ]]; then
    rm -rf "$TMP_INPUT"
fi
