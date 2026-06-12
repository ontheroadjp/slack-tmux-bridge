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
import subprocess
import sys


def _bridge_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "slack_tmux_bridge.py")


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
    except Exception:
        pass
    return last or ""


def _call_notify(payload_json: str, bridge: str) -> None:
    try:
        subprocess.run(
            [sys.executable, bridge, "notify", "-"],
            input=payload_json,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        pass


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    bridge = _bridge_path()
    if not os.path.isfile(bridge):
        sys.exit(0)

    transcript_path = payload.get("transcript_path", "")
    if transcript_path:
        # Claude Code mode: extract last assistant message from transcript
        msg = _last_assistant_message(transcript_path)
        if not msg:
            sys.exit(0)
        notify_payload = json.dumps({"last-assistant-message": msg}, ensure_ascii=False)
        _call_notify(notify_payload, bridge)
    else:
        # Codex mode: payload already contains last-assistant-message
        if not payload.get("last-assistant-message"):
            sys.exit(0)
        _call_notify(raw.strip(), bridge)

    sys.exit(0)


if __name__ == "__main__":
    main()
