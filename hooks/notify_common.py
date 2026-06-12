#!/usr/bin/env python3
"""Shared utilities for notify hook scripts."""

import os
import re
import subprocess
import sys
from datetime import datetime


def make_log_func(log_file: str):
    def _log(msg: str) -> None:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {msg}\n")
        except Exception:
            pass
    return _log


def bridge_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "slack_tmux_bridge.py")


def tmp_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "tmp")


def call_notify(payload_json: str, bridge: str, log_fn) -> None:
    try:
        result = subprocess.run(
            [sys.executable, bridge, "notify", "-"],
            input=payload_json,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        log_fn(f"notify returncode={result.returncode} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}")
    except Exception as e:
        log_fn(f"notify call error: {e}")


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[mGKHFJ]", "", text)


def _pane_snapshot_path(base_tmp_dir: str, pane_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", pane_id)
    return os.path.join(base_tmp_dir, f"pane_snapshot_{safe}.txt")


def _find_new_content(last: str, current: str) -> str:
    """Return the portion of current that follows the end of last."""
    if not last.strip():
        return current.strip()
    last_lines = [l for l in last.splitlines() if l.strip()]
    if not last_lines:
        return current.strip()
    anchor = "\n".join(last_lines[-min(10, len(last_lines)):])
    idx = current.rfind(anchor)
    if idx == -1:
        return current.strip()
    return current[idx + len(anchor):].strip()


def capture_pane_since_last(pane_id: str, base_tmp_dir: str, log_fn) -> str:
    """Capture new tmux pane content since the last snapshot. Updates snapshot."""
    if not pane_id:
        return ""
    snapshot_path = _pane_snapshot_path(base_tmp_dir, pane_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-S", "-1000", "-t", pane_id],
            capture_output=True, text=True, timeout=5,
        )
        current = _strip_ansi(result.stdout)
    except Exception as e:
        log_fn(f"capture_pane failed for {pane_id!r}: {e}")
        return ""
    last = ""
    if os.path.exists(snapshot_path):
        try:
            with open(snapshot_path, encoding="utf-8") as f:
                last = f.read()
        except Exception:
            pass
    new_content = _find_new_content(last, current)
    try:
        os.makedirs(base_tmp_dir, exist_ok=True)
        with open(snapshot_path, "w", encoding="utf-8") as f:
            f.write(current)
    except Exception as e:
        log_fn(f"snapshot save failed: {e}")
    log_fn(f"pane capture: {len(new_content)} new chars pane={pane_id!r}")
    return new_content


def save_pane_snapshot(pane_id: str, base_tmp_dir: str, log_fn) -> None:
    """Save current pane content as snapshot baseline without returning it."""
    if not pane_id:
        return
    snapshot_path = _pane_snapshot_path(base_tmp_dir, pane_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-S", "-1000", "-t", pane_id],
            capture_output=True, text=True, timeout=5,
        )
        current = _strip_ansi(result.stdout)
        os.makedirs(base_tmp_dir, exist_ok=True)
        with open(snapshot_path, "w", encoding="utf-8") as f:
            f.write(current)
        log_fn(f"pane snapshot saved pane={pane_id!r}")
    except Exception as e:
        log_fn(f"save_pane_snapshot failed: {e}")
