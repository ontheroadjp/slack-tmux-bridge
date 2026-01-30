import os
import time

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

import slack_tmux_bridge as stb


def test_sessions_output_includes_channel_name(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    now = time.time()
    stb.LAST_EVENT_TS_BY_CHANNEL["C1"] = now - 5

    captured = {}

    def say(text):
        captured["text"] = text

    stb.handle_sessions_message({}, say)

    out = captured.get("text", "")
    assert "C1 (chan-a) -> 1:1.0 (/tmp/a)" in out


def test_dir_command_returns_directory(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["channel"] = channel
        sent["thread_ts"] = thread_ts
        sent["text"] = text

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "/dir", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert sent["channel"] == "C1"
    assert sent["thread_ts"] == "123.456"
    assert "/tmp/a" in sent["text"]
