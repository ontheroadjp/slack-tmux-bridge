import os
import types

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

import slack_tmux_bridge as stb


class _ProcResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_pre_clear_tmux_sends_commands(monkeypatch):
    calls = []

    def _run(cmd, *args, **kwargs):
        calls.append(cmd)
        return _ProcResult()

    monkeypatch.setattr(stb.subprocess, "run", _run)
    monkeypatch.setattr(stb.time, "sleep", lambda _: None)

    stb.pre_clear_tmux("1:2.0")

    assert ["tmux", "clear-history", "-t", "1:2.0"] in calls
    assert ["tmux", "send-keys", "-t", "1:2.0", "C-l"] in calls


def test_send_text_to_tmux_posts_error(monkeypatch):
    messages = []

    def _run(cmd, *args, **kwargs):
        return _ProcResult(returncode=1, stderr="fail")

    monkeypatch.setattr(stb.subprocess, "run", _run)
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    stb.send_text_to_tmux("1:2.0", "hello", thread_ts="123", channel_id="C1")

    assert messages
    assert "Error in send_text_to_tmux" in messages[0]


def test_send_enter_posts_error(monkeypatch):
    messages = []

    def _run(cmd, *args, **kwargs):
        return _ProcResult(returncode=1, stderr="fail")

    monkeypatch.setattr(stb.subprocess, "run", _run)
    monkeypatch.setattr(stb, "_post_message", lambda ch, text, thread_ts=None, blocks=None: messages.append(text))

    stb.send_enter("1:2.0", thread_ts="123", channel_id="C1")

    assert messages
    assert "Error in send_enter" in messages[0]


def test_capture_tmux_returns_stdout(monkeypatch):
    def _run(cmd, *args, **kwargs):
        return _ProcResult(stdout="output")

    monkeypatch.setattr(stb.subprocess, "run", _run)

    assert stb.capture_tmux("1:2.0", lines=True) == "output"
