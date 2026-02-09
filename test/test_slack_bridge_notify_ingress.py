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


def test_validate_notify_payload_bytes_accepts_json_object():
    _reset_ingress_state()
    ok, error, payload = stb._validate_notify_payload_bytes(
        b'{"channel_id":"C1","thread_ts":"123.456","last-assistant-message":"done"}'
    )
    assert ok is True
    assert error == ""
    assert payload["channel_id"] == "C1"


def test_validate_notify_payload_bytes_rejects_large_payload(monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_MAX_PAYLOAD_BYTES", 10)
    raw = b'{"channel_id":"C1","thread_ts":"123.456"}'
    ok, error, _payload = stb._validate_notify_payload_bytes(raw)
    assert ok is False
    assert error == "payload too large"


def test_accept_notify_payload_posts_with_explicit_destination(monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_COUNT", 30)
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_WINDOW_SEC", 60)

    sent = {}
    monkeypatch.setattr(
        stb,
        "_post_message",
        lambda channel_id, text, thread_ts=None, blocks=None: sent.update(
            {"channel_id": channel_id, "text": text, "thread_ts": thread_ts}
        ),
    )

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
    assert sent["channel_id"] == "C1"
    assert sent["thread_ts"] == "123.456"
    assert sent["text"] == "notify message"


def test_accept_notify_payload_resolves_destination_by_pane_id(tmp_path, monkeypatch):
    _reset_ingress_state()
    notify_context_path = tmp_path / "tmp" / "notify_context.json"
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", str(notify_context_path))
    stb._atomic_write_json(
        str(notify_context_path),
        {"%9": {"channel_id": "C9", "thread_ts": "9.999", "updated_at": time.time()}},
    )

    sent = {}
    monkeypatch.setattr(
        stb,
        "_post_message",
        lambda channel_id, text, thread_ts=None, blocks=None: sent.update(
            {"channel_id": channel_id, "text": text, "thread_ts": thread_ts}
        ),
    )

    accepted, reason = stb._accept_notify_payload(
        {"pane_id": "%9", "last-assistant-message": "hello"},
        source="test",
    )

    assert accepted is True
    assert reason == ""
    assert sent["channel_id"] == "C9"
    assert sent["thread_ts"] == "9.999"
    assert sent["text"] == "hello"


def test_accept_notify_payload_rejects_when_destination_missing(monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_CONTEXT_FILE", "/tmp/not-existing-notify-context.json")
    monkeypatch.setattr(stb, "_post_message", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not post")))

    accepted, reason = stb._accept_notify_payload({"pane_id": "%404"}, source="test")
    assert accepted is False
    assert reason == "destination not found"


def test_accept_notify_payload_rejects_by_rate_limit(monkeypatch):
    _reset_ingress_state()
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_COUNT", 1)
    monkeypatch.setattr(stb, "NOTIFY_RATE_LIMIT_WINDOW_SEC", 60)
    monkeypatch.setattr(stb, "_post_message", lambda *_args, **_kwargs: None)

    payload = {"channel_id": "C1", "thread_ts": "1.2", "last-assistant-message": "x"}
    first_ok, _ = stb._accept_notify_payload(payload, source="test")
    second_ok, reason = stb._accept_notify_payload(payload, source="test")

    assert first_ok is True
    assert second_ok is False
    assert reason == "rate limited"
