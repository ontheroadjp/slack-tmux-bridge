#!/usr/bin/env python3
"""
Notification hook for Claude Code.

Reads the Notification hook payload from stdin and forwards the message
to slack_tmux_bridge notify ingress so the user can see what Claude Code
needs and respond from Slack.

Registration (~/.claude/settings.json):
  {
    "hooks": {
      "Notification": [{"matcher": "", "hooks": [{"type": "command",
        "command": "python3 /path/to/slack-tmux-bridge/hooks/notify_on_wait.py"}]}]
    }
  }
"""

import json
import os
import subprocess
import sys
from datetime import datetime

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp", "notify_on_wait.log")


def _log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def _bridge_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "slack_tmux_bridge.py")


def _call_notify(payload_json: str, bridge: str) -> None:
    try:
        result = subprocess.run(
            [sys.executable, bridge, "notify", "-"],
            input=payload_json,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        _log(f"notify returncode={result.returncode} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}")
    except Exception as e:
        _log(f"notify call error: {e}")


def main() -> None:
    _log("hook fired")
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception as e:
        _log(f"stdin parse error: {e}")
        sys.exit(0)

    _log(f"payload keys={sorted(payload.keys())} TMUX_PANE={os.environ.get('TMUX_PANE', '')!r}")

    bridge = _bridge_path()
    if not os.path.isfile(bridge):
        _log(f"bridge not found: {bridge}")
        sys.exit(0)

    message = payload.get("message", "").strip()
    if not message:
        _log("no message in payload, exit")
        sys.exit(0)

    notify_payload = json.dumps(
        {"last-assistant-message": f"[permission/input needed]\n{message}"},
        ensure_ascii=False,
    )
    _call_notify(notify_payload, bridge)
    sys.exit(0)


if __name__ == "__main__":
    main()
