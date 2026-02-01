#!/bin/sh

# Use the first argument as the target, default to "0:0.0" if not provided
TMUX_TARGET="${1:-0:0.0}"
TMUX_BIN="${TMUX_BIN:-tmux}"

echo "[send_enter.sh] target=$TMUX_TARGET -> send Enter" >&2
"$TMUX_BIN" send-keys -t "$TMUX_TARGET" Enter
