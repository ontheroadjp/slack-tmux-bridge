import os
import time

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

import slack_tmux_bridge as stb


def test_capture_execute_skips_when_recent_notify_delivery(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    dedupe_path = tmp_path / "tmp" / "notify_delivery_dedupe.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_DEDUPE_FILE", str(dedupe_path))
    monkeypatch.setattr(stb, "EXECUTE_RESULT_MODE", "both")
    monkeypatch.setattr(stb.time, "sleep", lambda *_: None)
    monkeypatch.setattr(stb, "capture_tmux", lambda *_args, **_kwargs: "> run\nresult")

    stb._atomic_write_json(
        str(sessions_path),
        {"C1": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )
    stb._atomic_write_json(
        str(dedupe_path),
        {
            "entries": {
                "%1:thread-1:turn-1": {
                    "pane_id": "%1",
                    "thread_ts": "thread-1",
                    "turn_id": "turn-1",
                    "source": "notify",
                    "ts": time.time(),
                }
            }
        },
    )

    posted = []
    monkeypatch.setattr(stb, "_post_message", lambda *_args, **_kwargs: posted.append("posted"))

    stb._capture_and_reply_once("thread-1", "C1", "1:1.0", prompt="", reason="execute")

    assert posted == []


def test_capture_execute_posts_and_records_poll_delivery(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    dedupe_path = tmp_path / "tmp" / "notify_delivery_dedupe.json"
    monkeypatch.setattr(stb, "ACTIVE_SESSIONS_FILE", str(sessions_path))
    monkeypatch.setattr(stb, "NOTIFY_DEDUPE_FILE", str(dedupe_path))
    monkeypatch.setattr(stb, "EXECUTE_RESULT_MODE", "both")
    monkeypatch.setattr(stb.time, "sleep", lambda *_: None)
    monkeypatch.setattr(stb, "capture_tmux", lambda *_args, **_kwargs: "> run\nresult")

    stb._atomic_write_json(
        str(sessions_path),
        {"C1": {"pane_id": "%1", "pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"}},
    )

    posted = []
    monkeypatch.setattr(stb, "_post_message", lambda *_args, **_kwargs: posted.append("posted"))

    stb._capture_and_reply_once("thread-1", "C1", "1:1.0", prompt="", reason="execute")

    assert posted == ["posted"]
    state = stb._load_notify_dedupe()
    assert state.get("entries")
    assert any(v.get("source") == "poll" for v in state["entries"].values())
