#!/usr/bin/env python3
"""Shared utilities for notify hook scripts."""

import os
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
