#!/usr/bin/env python3
"""
Stop hook for Claude Code and Codex CLI.

Reads the hook payload from stdin and forwards the last assistant message
to slack_tmux_bridge notify ingress.

Claude Code (Stop hook):
  Payload contains `transcript_path` pointing to a JSONL transcript file.
  The script extracts the last assistant message from the transcript.

Codex CLI (notify):
  Payload already contains `last-assistant-message`.
  The script passes the payload through to slack_tmux_bridge notify directly.

Registration:

  Claude Code (~/.claude/settings.json):
    {
      "hooks": {
        "Stop": [{"matcher": "", "hooks": [{"type": "command",
          "command": "python3 /path/to/slack-tmux-bridge/hooks/notify_on_stop.py"}]}]
        ]
      }
    }

  Codex CLI (~/.codex/config.toml):
    notify = ["python3", "/path/to/slack-tmux-bridge/hooks/notify_on_stop.py"]
"""

import json
import os
import sys

from notify_common import bridge_path as _bridge_path
from notify_common import call_notify as _call_notify_impl
from notify_common import make_log_func
from notify_common import save_pane_snapshot
from notify_common import tmp_dir as _tmp_dir

_log = make_log_func(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp", "notify_on_stop.log"))


def _call_notify(payload_json: str, bridge: str) -> None:
    _call_notify_impl(payload_json, bridge, _log)


def _last_assistant_message(transcript_path: str) -> str:
    last = None
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Support both top-level role and wrapped {"message": {...}} format
                msg = entry if entry.get("role") else entry.get("message") or {}
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                content = msg.get("content", "")
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    texts = [
                        c.get("text", "")
                        for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    joined = "\n".join(t for t in texts if t)
                    if joined:
                        last = joined
    except Exception as e:
        _log(f"transcript read error: {e}")
    return last or ""


def main() -> None:
    _log("hook fired")
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception as e:
        _log(f"stdin parse error: {e}")
        sys.exit(0)

    _log(f"payload keys={sorted(payload.keys())} TMUX_PANE={os.environ.get('TMUX_PANE','')!r}")

    bridge = _bridge_path()
    if not os.path.isfile(bridge):
        _log(f"bridge not found: {bridge}")
        sys.exit(0)

    pane_id = os.environ.get("TMUX_PANE", "")

    transcript_path = payload.get("transcript_path", "")
    if transcript_path:
        # Claude Code mode: extract last assistant message from transcript
        msg = _last_assistant_message(transcript_path)
        _log(f"extracted msg length={len(msg)} transcript={transcript_path!r}")
        if not msg:
            _log("no assistant text message found in transcript, exit")
            sys.exit(0)
        notify_payload = json.dumps({"last-assistant-message": msg}, ensure_ascii=False)
        _call_notify(notify_payload, bridge)
    else:
        # Codex mode: payload already contains last-assistant-message
        if not payload.get("last-assistant-message"):
            _log("no last-assistant-message in payload, exit")
            sys.exit(0)
        _call_notify(raw.strip(), bridge)

    save_pane_snapshot(pane_id, _tmp_dir(), _log)
    sys.exit(0)


if __name__ == "__main__":
    main()
