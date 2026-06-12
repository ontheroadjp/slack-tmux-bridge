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
import sys

from notify_common import bridge_path as _bridge_path
from notify_common import call_notify as _call_notify_impl
from notify_common import make_log_func

_log = make_log_func(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp", "notify_on_wait.log"))


def _call_notify(payload_json: str, bridge: str) -> None:
    _call_notify_impl(payload_json, bridge, _log)


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
