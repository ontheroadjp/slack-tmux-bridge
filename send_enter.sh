#!/bin/sh

# Use the first argument as the target, default to "0:0.0" if not provided
TMUX_TARGET="${1:-0:0.0}"

echo "[send_enter.sh] target=$TMUX_TARGET -> send Enter" >&2
tmux send-keys -t "$TMUX_TARGET" Enter