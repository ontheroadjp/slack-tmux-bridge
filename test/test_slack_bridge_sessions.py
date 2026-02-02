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

    out = stb._build_sessions_output()
    assert "- chan-a → /tmp/a" in out


def test_sessions_output_includes_age(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    out = stb._build_sessions_output()
    assert "- chan-a → /tmp/a" in out


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


def test_dir_command_uses_parent_thread_ts(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["thread_ts"] = thread_ts
        sent["text"] = text

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "child-ts", "thread_ts": "parent-ts", "text": "/dir", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert sent["thread_ts"] == "parent-ts"
    assert "/tmp/a" in sent["text"]


def test_bye_command_removes_session(tmp_path, monkeypatch):
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

    event = {"channel": "C1", "ts": "123.456", "text": "/bye", "user": "U1"}
    stb.handle_message(event, stb.logger)

    sessions = stb._load_active_sessions()
    assert "C1" not in sessions
    assert sent["channel"] == "C1"
    assert "解除" in sent["text"]
    assert sent["thread_ts"] == "123.456"


def test_escaped_slash_dir_command(tmp_path, monkeypatch):
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

    event = {"channel": "C1", "ts": "123.456", "text": "\\/dir", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert sent["channel"] == "C1"
    assert "/tmp/a" in sent["text"]


def test_escaped_slash_bye_command(tmp_path, monkeypatch):
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

    event = {"channel": "C1", "ts": "123.456", "text": "\\/bye", "user": "U1"}
    stb.handle_message(event, stb.logger)

    sessions = stb._load_active_sessions()
    assert "C1" not in sessions
    assert sent["channel"] == "C1"
    assert "解除" in sent["text"]
    assert sent["thread_ts"] == "123.456"


def test_dedupe_active_sessions_keeps_latest(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
        "C2": {"pane": "1:1.0", "dir": "/tmp/b", "name": "chan-b"},
    })

    now = time.time()
    stb.LAST_EVENT_TS_BY_CHANNEL["C1"] = now - 10
    stb.LAST_EVENT_TS_BY_CHANNEL["C2"] = now - 1

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append((ch, text)))

    stb._dedupe_active_sessions()

    sessions = stb._load_active_sessions()
    assert "C2" in sessions
    assert "C1" not in sessions
    assert messages


def test_dedupe_prefers_channel_with_name_when_timestamps_equal(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": None},
        "C2": {"pane": "1:1.0", "dir": "/tmp/b", "name": "chan-b"},
    })

    now = time.time()
    stb.LAST_EVENT_TS_BY_CHANNEL["C1"] = now
    stb.LAST_EVENT_TS_BY_CHANNEL["C2"] = now

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append((ch, text)))

    stb._dedupe_active_sessions()

    sessions = stb._load_active_sessions()
    assert "C2" in sessions
    assert "C1" not in sessions
    assert any("chan-b" in text for _, text in messages)


def test_now_command_starts_monitor_and_notifies_when_busy(monkeypatch):
    calls = {"started": False}
    sent = []

    def _post_message(channel, text, thread_ts=None, blocks=None):
        sent.append((channel, text))

    class DummyThread:
        def __init__(self, target=None, args=(), daemon=None):
            assert target == stb._capture_and_reply_once
            self.args = args
            self.daemon = daemon

        def start(self):
            calls["started"] = True

    monkeypatch.setattr(stb, "_post_message", _post_message)
    monkeypatch.setattr(stb.threading, "Thread", DummyThread)

    stb._handle_now_command("C1", "thread1", "1:1.0")

    assert any("取得しています" in text for _, text in sent)
    assert calls["started"] is True


def test_now_command_errors_without_session(monkeypatch):
    sent = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: sent.append(text))
    monkeypatch.setattr(stb, "get_target_pane", lambda *_: None)

    stb._dispatch_command("/now", "C1", "thread1")

    assert sent
    assert "No active tmux session" in sent[0]


def test_now_uses_parent_thread_ts(monkeypatch):
    sent = []

    def _post_message(channel, text, thread_ts=None, blocks=None):
        sent.append((channel, text, thread_ts))

    class DummyThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.args = args
            self.daemon = daemon

        def start(self):
            return None

    monkeypatch.setattr(stb, "_post_message", _post_message)
    monkeypatch.setattr(stb.threading, "Thread", DummyThread)

    stb._handle_now_command("C1", "parent-ts", "1:1.0")

    assert any(ts == "parent-ts" for _, _, ts in sent)


def test_command_menu_blocks_shape():
    blocks = stb.get_command_menu_blocks()
    assert blocks
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert actions
    flat = [e for a in actions for e in a.get("elements", [])]
    values = {e.get("value") for e in flat}
    assert "/reset" in values
    assert "/clear" in values
    assert "/undo" in values
    assert "/save" in values
    assert "/model" in values
    assert "/system" in values
    assert "/help" in values
    assert "/version" in values


def test_sessions_output_handles_missing_fields(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    stb.LAST_EVENT_TS_BY_CHANNEL.clear()

    stb._atomic_write_json(str(sessions_path), {
        "C1": "1:1.0",
    })

    out = stb._build_sessions_output()
    assert "- C1 → -" in out


def test_escaped_now_command_dispatch(monkeypatch):
    called = {"count": 0}

    def _handle_now(channel_id, thread_ts, tmux_target):
        called["count"] += 1
        return True

    monkeypatch.setattr(stb, "_handle_now_command", _handle_now)
    monkeypatch.setattr(stb, "get_target_pane", lambda *_: "1:1.0")

    event = {"channel": "C1", "ts": "123.456", "text": "\\/now", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert called["count"] == 1


def test_sessions_output_is_code_block(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    out = stb._build_sessions_output()
    assert out.startswith("- ")


def test_sessions_output_when_empty(monkeypatch):
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", "/tmp/does-not-exist.json")

    out = stb._build_sessions_output()
    assert out == "(no active sessions)"


def test_escaped_sessions_command_dispatch(monkeypatch):
    called = {"count": 0}

    def _post_message(channel, text, thread_ts=None, blocks=None):
        called["count"] += 1

    monkeypatch.setattr(stb, "_post_message", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "\\/sessions", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert called["count"] == 1


def test_sessions_command_uses_parent_thread_ts(monkeypatch):
    captured = []

    def _post_message(channel, text, thread_ts=None, blocks=None):
        captured.append(thread_ts)

    monkeypatch.setattr(stb, "_post_message", _post_message)

    event = {"channel": "C1", "ts": "child-ts", "thread_ts": "parent-ts", "text": "/sessions", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert captured == ["parent-ts"]


def test_escaped_sessions_command_uses_parent_thread_ts(monkeypatch):
    captured = []

    def _post_message(channel, text, thread_ts=None, blocks=None):
        captured.append(thread_ts)

    monkeypatch.setattr(stb, "_post_message", _post_message)

    event = {"channel": "C1", "ts": "child-ts", "thread_ts": "parent-ts", "text": "\\/sessions", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert captured == ["parent-ts"]


def test_sessions_command_with_trailing_space(monkeypatch):
    captured = []

    def _post_message(channel, text, thread_ts=None, blocks=None):
        captured.append(text)

    monkeypatch.setattr(stb, "_post_message", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "/sessions ", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert captured


def test_sessions_command_with_zero_width(monkeypatch):
    captured = []

    def _post_message(channel, text, thread_ts=None, blocks=None):
        captured.append(text)

    monkeypatch.setattr(stb, "_post_message", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "/sessions\u200b", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert captured


def test_sessions_output_combinations(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    stb.LAST_EVENT_TS_BY_CHANNEL.clear()

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
        "C2": {"pane": "1:2.0", "name": "chan-b"},
        "C3": {"pane": "1:3.0", "dir": "/tmp/c"},
        "C4": "1:4.0",
    })

    out = stb._build_sessions_output()
    assert "- chan-a → /tmp/a" in out
    assert "- chan-b → -" in out
    assert "- C3 → /tmp/c" in out
    assert "- C4 → -" in out


def test_dir_command_without_session(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["text"] = text

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "/dir", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert "見つかりません" in sent["text"]


def test_escaped_dir_without_session(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["text"] = text

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "\\/dir", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert "見つかりません" in sent["text"]


def test_escaped_dir_uses_parent_thread_ts(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["thread_ts"] = thread_ts

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "child-ts", "thread_ts": "parent-ts", "text": "\\/dir", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert sent["thread_ts"] == "parent-ts"


def test_bye_command_without_session(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {})

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["text"] = text
        sent["thread_ts"] = thread_ts

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "/bye", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert "既に接続されていません" in sent["text"]
    assert sent["thread_ts"] == "123.456"


def test_escaped_bye_without_session(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {})

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["text"] = text
        sent["thread_ts"] = thread_ts

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "123.456", "text": "\\/bye", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert "既に接続されていません" in sent["text"]
    assert sent["thread_ts"] == "123.456"


def test_escaped_bye_uses_parent_thread_ts(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    sent = {}

    def _post_message(channel, thread_ts, text):
        sent["thread_ts"] = thread_ts

    monkeypatch.setattr(stb.app.client, "chat_postMessage", _post_message)

    event = {"channel": "C1", "ts": "child-ts", "thread_ts": "parent-ts", "text": "\\/bye", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert sent["thread_ts"] == "parent-ts"


def test_sessions_line_formatting_with_name_and_dir(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
    })

    out = stb._build_sessions_output()
    assert "- chan-a → /tmp/a" in out


def test_sessions_line_formatting_without_dir(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    stb.LAST_EVENT_TS_BY_CHANNEL.clear()

    stb._atomic_write_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "name": "chan-a"},
    })

    out = stb._build_sessions_output()
    assert "- chan-a → -" in out


def test_now_command_dispatches_with_event_ts(monkeypatch):
    calls = []

    def _handle_now(channel_id, thread_ts, tmux_target):
        calls.append((channel_id, thread_ts, tmux_target))
        return True

    monkeypatch.setattr(stb, "_handle_now_command", _handle_now)
    monkeypatch.setattr(stb, "get_target_pane", lambda *_: "1:1.0")

    event = {"channel": "C1", "ts": "123.456", "text": "/now", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert calls == [("C1", "123.456", "1:1.0")]


def test_now_command_uses_thread_ts_from_event(monkeypatch):
    calls = []

    def _handle_now(channel_id, thread_ts, tmux_target):
        calls.append((channel_id, thread_ts, tmux_target))
        return True

    monkeypatch.setattr(stb, "_handle_now_command", _handle_now)
    monkeypatch.setattr(stb, "get_target_pane", lambda *_: "1:1.0")

    event = {"channel": "C1", "ts": "child-ts", "thread_ts": "parent-ts", "text": "/now", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert calls == [("C1", "parent-ts", "1:1.0")]


def test_escaped_now_command_uses_parent_thread_ts(monkeypatch):
    calls = []

    def _handle_now(channel_id, thread_ts, tmux_target):
        calls.append((channel_id, thread_ts, tmux_target))
        return True

    monkeypatch.setattr(stb, "_handle_now_command", _handle_now)
    monkeypatch.setattr(stb, "get_target_pane", lambda *_: "1:1.0")

    event = {"channel": "C1", "ts": "child-ts", "thread_ts": "parent-ts", "text": "\\/now", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert calls == [("C1", "parent-ts", "1:1.0")]


def test_ctlc_command_dispatches_with_event_ts(monkeypatch):
    calls = []

    def _handle_ctlc(channel_id, thread_ts, tmux_target):
        calls.append((channel_id, thread_ts, tmux_target))
        return True

    monkeypatch.setattr(stb, "_handle_ctlc_command", _handle_ctlc)
    monkeypatch.setattr(stb, "get_target_pane", lambda *_: "1:1.0")

    event = {"channel": "C1", "ts": "123.456", "text": "/ctlc", "user": "U1"}
    stb.handle_message(event, stb.logger)

    assert calls == [("C1", "123.456", "1:1.0")]
