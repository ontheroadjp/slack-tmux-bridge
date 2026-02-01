#!/bin/sh
#
# Simple launchd controller for slack_tmux_bridge.

set -euo pipefail

PLIST_NAME="com.slack_tmux_bridge.plist"
PLIST_SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SOURCE_PATH="$PLIST_SOURCE_DIR/$PLIST_NAME"
PLIST_DEST_DIR="$HOME/Library/LaunchAgents"
PLIST_DEST_PATH="$PLIST_DEST_DIR/$PLIST_NAME"

ensure_plist() {
  if [ ! -f "$PLIST_DEST_PATH" ]; then
    mkdir -p "$PLIST_DEST_DIR"
    cp "$PLIST_SOURCE_PATH" "$PLIST_DEST_PATH"
  fi
}

cmd="${1:-}"

case "$cmd" in
  install)
    mkdir -p "$PLIST_DEST_DIR"
    cp "$PLIST_SOURCE_PATH" "$PLIST_DEST_PATH"
    echo "installed: $PLIST_DEST_PATH"
    ;;
  start)
    ensure_plist
    if launchctl list | rg -q slack_tmux_bridge; then
      echo "already loaded: $PLIST_DEST_PATH"
      exit 0
    fi
    launchctl load "$PLIST_DEST_PATH"
    echo "started: $PLIST_DEST_PATH"
    ;;
  stop)
    if [ -f "$PLIST_DEST_PATH" ]; then
      if launchctl list | rg -q slack_tmux_bridge; then
        launchctl unload "$PLIST_DEST_PATH"
        echo "stopped: $PLIST_DEST_PATH"
      else
        echo "not loaded: $PLIST_DEST_PATH"
      fi
    fi
    ;;
  restart)
    if [ -f "$PLIST_DEST_PATH" ]; then
      launchctl unload "$PLIST_DEST_PATH"
    fi
    ensure_plist
    launchctl load "$PLIST_DEST_PATH"
    echo "restarted: $PLIST_DEST_PATH"
    ;;
  status)
    launchctl list | rg slack_tmux_bridge || true
    ;;
  log)
    tail -f "$HOME/Library/Logs/slack_tmux_bridge.log"
    ;;
  *)
    echo "usage: $0 {install|start|stop|restart|status|log}"
    exit 1
    ;;
esac
