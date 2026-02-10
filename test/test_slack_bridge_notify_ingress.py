import os
import time

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

import slack_tmux_bridge as stb


def _reset_ingress_state():
    stb.NOTIFY_INGRESS_EVENTS.clear()
    with stb.NOTIFY_INGRESS_LOCK:
        stb.NOTIFY_INGRESS_STATE["accepted"] = 0
        stb.NOTIFY_INGRESS_STATE["rejected"] = 0
        stb.NOTIFY_INGRESS_STATE["last_error"] = None
    stb.NOTIFY_DELIVERY_STATE["enqueued"] = 0
    stb.NOTIFY_DELIVERY_STATE["sent"] = 0
    stb.NOTIFY_DELIVERY_STATE["failed"] = 0
    stb.NOTIFY_DELIVERY_STATE["dropped_ttl"] = 0
    stb.NOTIFY_DELIVERY_STATE["dropped_max_attempts"] = 0
    stb.NOTIFY_DELIVERY_STATE["last_error"] = None


def test_validate_notify_payload_bytes_accepts_json_object():
    _reset_ingress_state()
    ok, error, payload = stb._validate_notify_payload_bytes(
        b'{"channel_id":"C1","thread_ts":"123.456","last-assistant-message":"done"}'
    )
    assert ok is True
    assert error == ""
    assert payload["channel_id"] == "C1"


def test_maybe_reset_notify_queue_on_start_enabled(tmp_path, monkeypatch):
    _reset_ingress_state()
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_RESET_ON_START", True)
    stb._save_notify_queue(
        {
            "items": [
                {"channel_id": "C1", "thread_ts": "123.456", "created_at": time.time()},
                {"channel_id": "C2", "thread_ts": "223.456", "created_at": time.time()},
            ]
        }
    )

    dropped = stb._maybe_reset_notify_queue_on_start()
    state = stb._load_notify_queue()

    assert dropped == 2
    assert state["items"] == []


def test_maybe_reset_notify_queue_on_start_disabled(tmp_path, monkeypatch):
    _reset_ingress_state()
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_RESET_ON_START", False)
    stb._save_notify_queue(
        {
            "items": [
                {"channel_id": "C1", "thread_ts": "123.456", "created_at": time.time()},
            ]
        }
    )

    dropped = stb._maybe_reset_notify_queue_on_start()
    state = stb._load_notify_queue()

    assert dropped == 0
    assert len(state["items"]) == 1


def test_validate_notify_payload_bytes_rejects_large_payload(monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_MAX_PAYLOAD_BYTES", 10)
    raw = b'{"channel_id":"C1","thread_ts":"123.456"}'
    ok, error, _payload = stb._validate_notify_payload_bytes(raw)
    assert ok is False
    assert error == "payload too large"


def test_accept_notify_payload_queues_with_explicit_destination(tmp_path, monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_COUNT", 30)
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_WINDOW_SEC", 60)
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))

    accepted, reason = stb._accept_notify_payload(
        {
            "channel_id": "C1",
            "thread_ts": "123.456",
            "last-assistant-message": "notify message",
        },
        source="test",
    )

    assert accepted is True
    assert reason == ""
    state = stb._load_notify_queue()
    assert len(state["items"]) == 1
    assert state["items"][0]["channel_id"] == "C1"
    assert state["items"][0]["thread_ts"] == "123.456"
    assert state["items"][0]["text"] == "notify message"


def test_accept_notify_payload_resolves_destination_by_pane_id(tmp_path, monkeypatch):
    _reset_ingress_state()
    sessions_path = tmp_path / "active_sessions.json"
    notify_context_path = tmp_path / "tmp" / "notify_context.json"
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", str(notify_context_path))
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))
    stb._atomic_write_json(
        str(sessions_path),
        {"C9": {"pane_id": "%9", "pane": "1:9.0", "dir": "/tmp/z", "name": "chan-z"}},
    )
    stb._atomic_write_json(
        str(notify_context_path),
        {"%9": {"channel_id": "C9", "thread_ts": "9.999", "updated_at": time.time()}},
    )

    accepted, reason = stb._accept_notify_payload(
        {"pane_id": "%9", "last-assistant-message": "hello"},
        source="test",
    )

    assert accepted is True
    assert reason == ""
    state = stb._load_notify_queue()
    assert len(state["items"]) == 1
    assert state["items"][0]["channel_id"] == "C9"
    assert state["items"][0]["thread_ts"] == "9.999"
    assert state["items"][0]["text"] == "hello"


def test_accept_notify_payload_rejects_when_destination_missing(monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", "/tmp/not-existing-notify-context.json")

    accepted, reason = stb._accept_notify_payload(
        {"pane_id": "%404", "last-assistant-message": "hello"},
        source="test",
    )
    assert accepted is False
    assert reason == "inactive session for pane_id"

def test_accept_notify_payload_rejects_when_thread_missing(tmp_path, monkeypatch):
    _reset_ingress_state()
    sessions_path = tmp_path / "active_sessions.json"
    notify_context_path = tmp_path / "tmp" / "notify_context.json"
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", str(notify_context_path))
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))
    stb._atomic_write_json(
        str(sessions_path),
        {"C1": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )

    accepted, reason = stb._accept_notify_payload(
        {"pane_id": "%1", "last-assistant-message": "hello"},
        source="test",
    )

    assert accepted is False
    assert reason == "thread destination not found"
    state = stb._load_notify_queue()
    assert state["items"] == []


def test_accept_notify_payload_rejects_by_rate_limit(monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_COUNT", 1)
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_WINDOW_SEC", 60)

    payload = {"channel_id": "C1", "thread_ts": "1.2", "last-assistant-message": "x"}
    first_ok, _ = stb._accept_notify_payload(payload, source="test")
    second_ok, reason = stb._accept_notify_payload(payload, source="test")

    assert first_ok is True
    assert second_ok is False
    assert reason == "rate limited"


def test_process_notify_queue_retries_and_succeeds(tmp_path, monkeypatch):
    _reset_ingress_state()
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))
    monkeypatch.setattr(stb, "NOTIFY_RETRY_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(stb, "NOTIFY_RETRY_BASE_SEC", 1.0)
    monkeypatch.setattr(stb, "NOTIFY_RETRY_MAX_SEC", 10.0)

    now = time.time()
    stb._save_notify_queue(
        {
            "items": [
                {
                    "channel_id": "C1",
                    "thread_ts": "t1",
                    "pane_id": "%1",
                    "turn_id": "turn-1",
                    "text": "hello",
                    "source": "http",
                    "created_at": now,
                    "next_attempt_at": now,
                    "attempts": 0,
                    "last_error": "",
                }
            ]
        }
    )

    calls = {"count": 0}

    def _post_result(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return False, "temporary error"
        return True, ""

    monkeypatch.setattr(stb, "_post_message_with_result", _post_result)
    monkeypatch.setattr(stb, "_record_notify_delivery_event", lambda *_args, **_kwargs: None)

    stb._process_notify_queue_once(now_ts=now)
    state = stb._load_notify_queue()
    assert len(state["items"]) == 1
    assert state["items"][0]["attempts"] == 1

    retry_at = state["items"][0]["next_attempt_at"]
    stb._process_notify_queue_once(now_ts=retry_at + 0.1)
    state = stb._load_notify_queue()
    assert state["items"] == []


def test_process_notify_queue_drops_ttl(tmp_path, monkeypatch):
    _reset_ingress_state()
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_TTL_SEC", 1)

    now = time.time()
    stb._save_notify_queue(
        {
            "items": [
                {
                    "channel_id": "C1",
                    "thread_ts": "t1",
                    "pane_id": "%1",
                    "turn_id": "turn-1",
                    "text": "hello",
                    "source": "http",
                    "created_at": now - 100,
                    "next_attempt_at": now - 99,
                    "attempts": 0,
                    "last_error": "",
                }
            ]
        }
    )

    monkeypatch.setattr(stb, "_post_message_with_result", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not post")))
    stb._process_notify_queue_once(now_ts=now)
    state = stb._load_notify_queue()
    assert state["items"] == []
    assert stb.NOTIFY_DELIVERY_STATE["dropped_ttl"] >= 1


def test_process_notify_queue_drops_invalid_thread_ts_error(tmp_path, monkeypatch):
    _reset_ingress_state()
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))

    now = time.time()
    stb._save_notify_queue(
        {
            "items": [
                {
                    "channel_id": "C1",
                    "thread_ts": "019c44e4-0c68-7572-b3f1-dc74fe64b5ea",
                    "pane_id": "%1",
                    "turn_id": "turn-1",
                    "text": "hello",
                    "source": "http",
                    "created_at": now,
                    "next_attempt_at": now,
                    "attempts": 0,
                    "last_error": "",
                }
            ]
        }
    )

    monkeypatch.setattr(
        stb,
        "_post_message_with_result",
        lambda *_args, **_kwargs: (False, "The server responded with: {'ok': False, 'error': 'invalid_thread_ts'}"),
    )
    stb._process_notify_queue_once(now_ts=now)
    state = stb._load_notify_queue()
    assert state["items"] == []


def test_process_notify_queue_drops_channel_not_found_error(tmp_path, monkeypatch):
    _reset_ingress_state()
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))

    now = time.time()
    stb._save_notify_queue(
        {
            "items": [
                {
                    "channel_id": "C1",
                    "thread_ts": "123.456",
                    "pane_id": "%1",
                    "turn_id": "turn-1",
                    "text": "hello",
                    "source": "http",
                    "created_at": now,
                    "next_attempt_at": now,
                    "attempts": 0,
                    "last_error": "",
                }
            ]
        }
    )

    monkeypatch.setattr(
        stb,
        "_post_message_with_result",
        lambda *_args, **_kwargs: (False, "The server responded with: {'ok': False, 'error': 'channel_not_found'}"),
    )
    stb._process_notify_queue_once(now_ts=now)
    state = stb._load_notify_queue()
    assert state["items"] == []


def test_notify_ingress_accept_then_delivery_posts_to_slack(tmp_path, monkeypatch):
    _reset_ingress_state()
    queue_path = tmp_path / "tmp" / "notify_delivery_queue.json"
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "NOTIFY_QUEUE_FILE", str(queue_path))
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_COUNT", 30)
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_WINDOW_SEC", 60)
    monkeypatch.setattr(stb, "NOTIFY_RETRY_MAX_ATTEMPTS", 3)

    stb._atomic_write_json(
        str(sessions_path),
        {"C1": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )

    accepted, reason = stb._accept_notify_payload(
        {
            "channel_id": "C1",
            "thread_ts": "123.456",
            "turn-id": "turn-1",
            "last-assistant-message": "notify message",
        },
        source="http",
    )
    assert accepted is True
    assert reason == ""

    posted = {}
    monkeypatch.setattr(
        stb,
        "_post_message_with_result",
        lambda channel_id, text, thread_ts=None, blocks=None: posted.update(
            {"channel_id": channel_id, "text": text, "thread_ts": thread_ts}
        ) or (True, ""),
    )

    dedupe = {}
    monkeypatch.setattr(
        stb,
        "_record_notify_delivery_event",
        lambda pane_id, thread_ts, source="notify", turn_id="": dedupe.update(
            {"pane_id": pane_id, "thread_ts": thread_ts, "source": source, "turn_id": turn_id}
        ),
    )

    stb._process_notify_queue_once(now_ts=time.time())
    state = stb._load_notify_queue()
    assert state["items"] == []
    assert posted["channel_id"] == "C1"
    assert posted["thread_ts"] == "123.456"
    assert posted["text"] == "notify message"
    assert dedupe["pane_id"] == "%1"
    assert dedupe["thread_ts"] == "123.456"


def test_run_notify_cli_forwards_payload(monkeypatch, capsys):
    monkeypatch.setattr(stb, "_forward_notify_payload", lambda raw: (True, "") if raw else (False, "empty"))
    rc = stb.run_notify_cli('{"channel_id":"C1","thread_ts":"123.456","last-assistant-message":"done"}')
    assert rc == 0
    out = capsys.readouterr().out
    assert "forwarded to slack_tmux_bridge ingress" in out


def test_run_notify_cli_rejects_invalid_payload(capsys):
    rc = stb.run_notify_cli("not-json")
    assert rc == 1
    out = capsys.readouterr().out
    assert "notify payload rejected" in out


def test_run_notify_cli_normalizes_thread_id(monkeypatch):
    captured = {}
    def _forward(raw):
        captured["payload"] = raw
        return True, ""
    monkeypatch.setattr(
        stb,
        "_forward_notify_payload",
        _forward,
    )
    rc = stb.run_notify_cli('{"channel-id":"C123","thread-id":"123.456","last-assistant-message":"done"}')
    assert rc == 0
    forwarded = captured["payload"]
    payload = stb.json.loads(forwarded)
    assert payload["thread_ts"] == "123.456"
    assert payload["thread-id"] == "123.456"


def test_run_notify_cli_keeps_existing_thread_ts(monkeypatch):
    captured = {}
    def _forward(raw):
        captured["payload"] = raw
        return True, ""
    monkeypatch.setattr(
        stb,
        "_forward_notify_payload",
        _forward,
    )
    rc = stb.run_notify_cli('{"channel-id":"C123","thread-id":"123.456","thread_ts":"999.000","last-assistant-message":"done"}')
    assert rc == 0
    forwarded = captured["payload"]
    payload = stb.json.loads(forwarded)
    assert payload["thread_ts"] == "999.000"


def test_run_notify_cli_normalizes_channel_id(monkeypatch):
    captured = {}

    def _forward(raw):
        captured["payload"] = raw
        return True, ""

    monkeypatch.setattr(stb, "_forward_notify_payload", _forward)
    rc = stb.run_notify_cli('{"channel-id":"C123","thread-id":"123.456","last-assistant-message":"done"}')
    assert rc == 0
    payload = stb.json.loads(captured["payload"])
    assert payload["channel_id"] == "C123"
    assert payload["channel-id"] == "C123"
    assert payload["thread_ts"] == "123.456"


def test_run_notify_cli_normalizes_pane_id(tmp_path, monkeypatch):
    captured = {}
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    stb._atomic_write_json(
        str(sessions_path),
        {"C123": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )

    def _forward(raw):
        captured["payload"] = raw
        return True, ""

    monkeypatch.setattr(stb, "_forward_notify_payload", _forward)
    rc = stb.run_notify_cli('{"channel-id":"C123","thread-id":"123.456","pane-id":"%1","last-assistant-message":"done"}')
    assert rc == 0
    payload = stb.json.loads(captured["payload"])
    assert payload["pane_id"] == "%1"
    assert payload["pane-id"] == "%1"


def test_run_notify_cli_keeps_existing_channel_id_and_pane_id(tmp_path, monkeypatch):
    captured = {}
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    stb._atomic_write_json(
        str(sessions_path),
        {"C-snake": {"pane_id": "%8", "pane": "1:8.0", "dir": "/tmp/a", "name": "chan-a"}},
    )

    def _forward(raw):
        captured["payload"] = raw
        return True, ""

    monkeypatch.setattr(stb, "_forward_notify_payload", _forward)
    rc = stb.run_notify_cli(
        '{"channel-id":"C-hyphen","channel_id":"C-snake","thread-id":"123.456","pane-id":"%9","pane_id":"%8","last-assistant-message":"done"}'
    )
    assert rc == 0
    payload = stb.json.loads(captured["payload"])
    assert payload["channel_id"] == "C-snake"
    assert payload["pane_id"] == "%8"


def test_run_notify_cli_rejects_when_channel_id_missing_after_normalization(monkeypatch, capsys):
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", "/tmp/not-existing-notify-context.json")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    rc = stb.run_notify_cli('{"thread-id":"123.456","last-assistant-message":"done"}')
    assert rc == 1
    out = capsys.readouterr().out
    assert "missing required field: channel_id" in out


def test_run_notify_cli_resolves_channel_by_thread_id_from_context(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.delenv("TMUX_PANE", raising=False)
    notify_context_path = tmp_path / "tmp" / "notify_context.json"
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", str(notify_context_path))
    stb._atomic_write_json(
        str(notify_context_path),
        {
            "%1": {"channel_id": "C1", "thread_ts": "123.456", "updated_at": 10},
            "%2": {"channel_id": "C2", "thread_ts": "999.000", "updated_at": 11},
        },
    )

    def _forward(raw):
        captured["payload"] = raw
        return True, ""

    monkeypatch.setattr(stb, "_forward_notify_payload", _forward)
    rc = stb.run_notify_cli('{"thread-id":"123.456","last-assistant-message":"done"}')
    assert rc == 0
    payload = stb.json.loads(captured["payload"])
    assert payload["channel_id"] == "C1"
    assert payload["thread_ts"] == "123.456"


def test_run_notify_cli_resolves_channel_and_thread_by_pane_id(tmp_path, monkeypatch):
    captured = {}
    sessions_path = tmp_path / "active_sessions.json"
    notify_context_path = tmp_path / "tmp" / "notify_context.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", str(notify_context_path))
    stb._atomic_write_json(
        str(sessions_path),
        {"C1": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )
    stb._atomic_write_json(
        str(notify_context_path),
        {"%1": {"channel_id": "C1", "thread_ts": "123.456", "updated_at": time.time()}},
    )

    def _forward(raw):
        captured["payload"] = raw
        return True, ""

    monkeypatch.setattr(stb, "_forward_notify_payload", _forward)
    rc = stb.run_notify_cli('{"pane-id":"%1","last-assistant-message":"done"}')
    assert rc == 0
    payload = stb.json.loads(captured["payload"])
    assert payload["pane_id"] == "%1"


def test_run_notify_cli_resolves_destination_by_tmux_pane_env(tmp_path, monkeypatch):
    captured = {}
    sessions_path = tmp_path / "active_sessions.json"
    notify_context_path = tmp_path / "tmp" / "notify_context.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", str(notify_context_path))
    monkeypatch.setenv("TMUX_PANE", "%1")
    stb._atomic_write_json(
        str(sessions_path),
        {"C1": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )
    stb._atomic_write_json(
        str(notify_context_path),
        {"%1": {"channel_id": "C1", "thread_ts": "123.456", "updated_at": time.time()}},
    )

    def _forward(raw):
        captured["payload"] = raw
        return True, ""

    monkeypatch.setattr(stb, "_forward_notify_payload", _forward)
    rc = stb.run_notify_cli('{"last-assistant-message":"done"}')
    assert rc == 0
    payload = stb.json.loads(captured["payload"])
    assert payload["channel_id"] == "C1"
    assert payload["thread_ts"] == "123.456"


def test_run_notify_cli_ignores_non_slack_thread_id_and_uses_context(tmp_path, monkeypatch):
    captured = {}
    sessions_path = tmp_path / "active_sessions.json"
    notify_context_path = tmp_path / "tmp" / "notify_context.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", str(notify_context_path))
    monkeypatch.setenv("TMUX_PANE", "%1")
    stb._atomic_write_json(
        str(sessions_path),
        {"C1": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )
    stb._atomic_write_json(
        str(notify_context_path),
        {"%1": {"channel_id": "C1", "thread_ts": "123.456", "updated_at": time.time()}},
    )

    def _forward(raw):
        captured["payload"] = raw
        return True, ""

    monkeypatch.setattr(stb, "_forward_notify_payload", _forward)
    rc = stb.run_notify_cli(
        '{"thread-id":"019c44e4-0c68-7572-b3f1-dc74fe64b5ea","last-assistant-message":"done"}'
    )
    assert rc == 0
    payload = stb.json.loads(captured["payload"])
    assert payload["channel_id"] == "C1"
    assert payload["thread_ts"] == "123.456"
    assert "thread-id" in payload


def test_run_notify_cli_rejects_when_thread_ts_missing_after_normalization(monkeypatch, capsys):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    rc = stb.run_notify_cli('{"channel-id":"C123","last-assistant-message":"done"}')
    assert rc == 1
    out = capsys.readouterr().out
    assert "missing required field: thread_ts" in out


def test_run_notify_cli_rejects_when_last_assistant_message_missing(capsys):
    rc = stb.run_notify_cli('{"channel-id":"C123","thread-id":"123.456"}')
    assert rc == 1
    out = capsys.readouterr().out
    assert "missing required field: last-assistant-message" in out
