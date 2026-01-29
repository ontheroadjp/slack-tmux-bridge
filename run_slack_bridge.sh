#!/bin/sh
#
# Wrapper to load environment variables and start the bridge from launchd.

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$BASE_DIR/.env" ]; then
  # Export variables defined in .env (excluding comments)
  set -a
  . "$BASE_DIR/.env"
  set +a
fi

cd "$BASE_DIR"

exec python slack_tmux_bridge.py
