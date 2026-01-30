import os
import time
from pathlib import Path

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

import slack_tmux_bridge as stb


def _sequence_capture(seq):
    it = iter(seq)

    def _capture(_tmux_target, lines=None):
        try:
            return next(it)
        except StopIteration:
            return seq[-1]

    return _capture


def test_monitor_sends_on_stable_output(tmp_path, monkeypatch):
    monkeypatch.setattr(stb, "TMP_DIR", str(tmp_path))
    monkeypatch.setattr(stb, "time", time)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    initial = "prompt"
    monkeypatch.setattr(
        stb,
        "capture_tmux",
        _sequence_capture(["prompt\nresult", "prompt\nresult", "prompt\nresult", "prompt\nresult"]),
    )

    stb.monitor_and_reply("thread1", "C1", "1:1.0", initial, prompt="")

    assert messages
    assert any("result" in msg for msg in messages)
    assert not Path(tmp_path / "snapshot_thread1.txt").exists()


def test_monitor_sends_even_without_change(tmp_path, monkeypatch):
    monkeypatch.setattr(stb, "TMP_DIR", str(tmp_path))
    monkeypatch.setattr(stb, "time", time)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    initial = "no-change"
    monkeypatch.setattr(stb, "capture_tmux", _sequence_capture(["no-change", "no-change", "no-change", "no-change"]))

    stb.monitor_and_reply("thread2", "C1", "1:1.0", initial, prompt="")

    assert messages
    assert "no-change" in messages[0]


def test_monitor_sends_on_permission_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(stb, "TMP_DIR", str(tmp_path))
    monkeypatch.setattr(stb, "time", time)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    initial = "start"
    monkeypatch.setattr(
        stb,
        "capture_tmux",
        _sequence_capture(["start\n1. Allow once", "start\n1. Allow once"]),
    )

    stb.monitor_and_reply("thread3", "C1", "1:1.0", initial, prompt="")

    assert messages
    assert "Allow once" in messages[0] or "start" in messages[0]


def test_monitor_extracts_prompt_block(tmp_path, monkeypatch):
    monkeypatch.setattr(stb, "TMP_DIR", str(tmp_path))
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    prompt = "do thing"
    initial = ""
    monkeypatch.setattr(
        stb,
        "capture_tmux",
        _sequence_capture([
            f"> {prompt}\nline1\nline2",
            f"> {prompt}\nline1\nline2",
            f"> {prompt}\nline1\nline2",
            f"> {prompt}\nline1\nline2",
        ]),
    )

    stb.monitor_and_reply("thread4", "C1", "1:1.0", initial, prompt=prompt)

    assert messages
    assert "line1" in messages[0]


def test_monitor_chunks_long_output(tmp_path, monkeypatch):
    monkeypatch.setattr(stb, "TMP_DIR", str(tmp_path))
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    long_text = "x" * 6500
    monkeypatch.setattr(
        stb,
        "capture_tmux",
        _sequence_capture([long_text, long_text, long_text, long_text]),
    )

    stb.monitor_and_reply("thread5", "C1", "1:1.0", "", prompt="")

    assert len(messages) >= 3
    assert all(msg.startswith("```") for msg in messages)
