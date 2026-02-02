import os
import time

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


def test_capture_sends_output(monkeypatch):
    monkeypatch.setattr(stb, "time", time)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))
    monkeypatch.setattr(stb, "capture_tmux", _sequence_capture(["prompt\nresult"]))

    stb._capture_and_reply_once("thread1", "C1", "1:1.0", prompt="")

    assert messages
    assert any("result" in msg for msg in messages)


def test_capture_handles_empty_output(monkeypatch):
    monkeypatch.setattr(stb, "time", time)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))
    monkeypatch.setattr(stb, "capture_tmux", _sequence_capture([""]))

    stb._capture_and_reply_once("thread2", "C1", "1:1.0", prompt="")

    assert messages
    assert "(No output detected)" in messages[0]


def test_capture_sends_on_permission_prompt(monkeypatch):
    monkeypatch.setattr(stb, "time", time)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))
    monkeypatch.setattr(stb, "capture_tmux", _sequence_capture(["start\n1. Allow once"]))

    stb._capture_and_reply_once("thread3", "C1", "1:1.0", prompt="")

    assert messages
    assert "Allow once" in messages[0] or "start" in messages[0]


def test_permission_prompt_detected():
    assert stb._permission_prompt_detected("Allow once")
    assert stb._permission_prompt_detected("許可")
    assert not stb._permission_prompt_detected("no prompt here")


def test_capture_extracts_prompt_block(monkeypatch):
    monkeypatch.setattr(stb, "time", time)
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

    stb._capture_and_reply_once("thread4", "C1", "1:1.0", prompt=prompt)

    assert messages
    assert "> do thing\n\nline1" in messages[0]


def test_capture_chunks_long_output(monkeypatch):
    monkeypatch.setattr(stb, "time", time)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    messages = []
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    long_text = "x" * 6500
    monkeypatch.setattr(
        stb,
        "capture_tmux",
        _sequence_capture([long_text, long_text, long_text, long_text]),
    )

    stb._capture_and_reply_once("thread5", "C1", "1:1.0", prompt="")

    assert len(messages) == 3
    assert all(msg.startswith("```") for msg in messages)
