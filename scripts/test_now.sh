#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT_DIR/venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "venv python not found at $VENV_PY" >&2
  exit 1
fi

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo ".env not found at $ROOT_DIR/.env" >&2
  exit 1
fi

set -a
source "$ROOT_DIR/.env"
set +a

exec "$VENV_PY" -m pytest "$ROOT_DIR/test/test_slack_bridge_sessions.py" -k now "$@"
