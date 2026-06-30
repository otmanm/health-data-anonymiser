#!/bin/bash
set -euo pipefail

# Only run in Claude Code on the web (remote) sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# gh ships in Ubuntu's universe repo, so this needs no extra apt source.
if ! command -v gh >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y gh
fi
