import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import goslack


class FakeClient:
    def __init__(self, channels):
        self.channels = channels

    def conversations_list(self, limit=1000, cursor=None, types=None):
        return {"channels": self.channels, "response_metadata": {"next_cursor": ""}}


def test_main_registers_session_with_dir_name_channel(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    channels = [{"id": "C1", "name": "workdir"}]
    monkeypatch.setattr(goslack, "_get_slack_client", lambda: FakeClient(channels))
    monkeypatch.setattr(goslack, "get_tmux_pane_id", lambda: "%1")
    monkeypatch.setattr(goslack, "get_tmux_target", lambda: "1:1.0")
    monkeypatch.setattr(goslack, "send_slack_message", lambda *_: None)
    monkeypatch.setattr(os, "getcwd", lambda: "/tmp/workdir")

    monkeypatch.setattr(sys, "argv", ["goslack.py"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert sessions["C1"]["pane"] == "1:1.0"
    assert sessions["C1"]["pane_id"] == "%1"
    assert sessions["C1"]["dir"] == "/tmp/workdir"
    assert sessions["C1"]["name"] == "workdir"


def test_main_fallback_channel(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    channels = [{"id": "C2", "name": "ai-studio-02"}]
    monkeypatch.setattr(goslack, "_get_slack_client", lambda: FakeClient(channels))
    monkeypatch.setattr(goslack, "get_tmux_pane_id", lambda: "%2")
    monkeypatch.setattr(goslack, "get_tmux_target", lambda: "2:3.4")
    monkeypatch.setattr(goslack, "send_slack_message", lambda *_: None)
    monkeypatch.setattr(os, "getcwd", lambda: "/tmp/unknown")

    monkeypatch.setattr(sys, "argv", ["goslack.py"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert sessions["C2"]["pane"] == "2:3.4"
    assert sessions["C2"]["pane_id"] == "%2"
    assert sessions["C2"]["dir"] == "/tmp/unknown"
    assert sessions["C2"]["name"] == "ai-studio-02"


def test_main_removes_duplicate_pane(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    goslack.save_json(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "old"},
        "C2": {"pane": "9:9.9", "dir": "/tmp/b", "name": "keep"},
    })

    channels = [{"id": "C3", "name": "workdir"}]
    monkeypatch.setattr(goslack, "_get_slack_client", lambda: FakeClient(channels))
    monkeypatch.setattr(goslack, "get_tmux_pane_id", lambda: "%1")
    monkeypatch.setattr(goslack, "get_tmux_target", lambda: "1:1.0")
    monkeypatch.setattr(goslack, "send_slack_message", lambda *_: None)
    monkeypatch.setattr(os, "getcwd", lambda: "/tmp/workdir")

    monkeypatch.setattr(sys, "argv", ["goslack.py"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert "C1" not in sessions
    assert "C2" in sessions
    assert sessions["C3"]["pane"] == "1:1.0"
    assert sessions["C3"]["pane_id"] == "%1"


def test_main_add_registers_target_pane(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    channels = [{"id": "C1", "name": "workdir"}]
    monkeypatch.setattr(goslack, "_get_slack_client", lambda: FakeClient(channels))
    monkeypatch.setattr(goslack, "get_tmux_pane_cwd", lambda _: "/tmp/workdir")
    monkeypatch.setattr(goslack, "get_tmux_pane_id_from_target", lambda _: "%9")
    monkeypatch.setattr(goslack, "send_slack_message", lambda *_: None)

    def _should_not_call():
        raise AssertionError("get_tmux_pane_id should not be called when --add is used")

    monkeypatch.setattr(goslack, "get_tmux_pane_id", _should_not_call)
    monkeypatch.setattr(sys, "argv", ["goslack.py", "--add", "1:2.0"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert sessions["C1"]["pane"] == "1:2.0"
    assert sessions["C1"]["pane_id"] == "%9"


def test_find_channel_by_name_handles_api_error(monkeypatch, capsys):
    class BadClient:
        def conversations_list(self, *args, **kwargs):
            raise RuntimeError("boom")

    ch = goslack._find_channel_by_name(BadClient(), "nope")
    out = capsys.readouterr().out
    assert ch is None
    assert "Slack API call failed" in out


def test_get_tmux_pane_cwd_error(monkeypatch):
    def _run(*args, **kwargs):
        raise goslack.subprocess.CalledProcessError(1, ["tmux"])

    monkeypatch.setattr(goslack.subprocess, "run", _run)
    try:
        goslack.get_tmux_pane_cwd("1:2.0")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("SystemExit expected")


def test_resolve_channel_prefers_unused_fallback(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    channels = [
        {"id": "C1", "name": "ai-studio-01"},
        {"id": "C2", "name": "ai-studio-02"},
        {"id": "C3", "name": "ai-studio-03"},
    ]
    client = FakeClient(channels)
    active_sessions = {"C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "ai-studio-01"}}

    channel = goslack._resolve_channel(client, "unknown", active_sessions)
    assert channel["name"] == "ai-studio-02"

    rr_path = tmp_path / "tmp" / "ai_studio_rr.json"
    rr_state = goslack.load_json(str(rr_path))
    assert rr_state["last_index"] == 1


def test_resolve_channel_round_robin_when_all_used(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    channels = [
        {"id": "C1", "name": "ai-studio-01"},
        {"id": "C2", "name": "ai-studio-02"},
        {"id": "C3", "name": "ai-studio-03"},
    ]
    client = FakeClient(channels)
    active_sessions = {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "ai-studio-01"},
        "C2": {"pane": "1:2.0", "dir": "/tmp/b", "name": "ai-studio-02"},
        "C3": {"pane": "1:3.0", "dir": "/tmp/c", "name": "ai-studio-03"},
    }

    rr_path = tmp_path / "tmp" / "ai_studio_rr.json"
    rr_path.parent.mkdir(parents=True, exist_ok=True)
    goslack.save_json(str(rr_path), {"last_index": 0})

    channel = goslack._resolve_channel(client, "unknown", active_sessions)
    assert channel["name"] == "ai-studio-02"

    channel = goslack._resolve_channel(client, "unknown", active_sessions)
    assert channel["name"] == "ai-studio-03"


def test_select_fallback_prefers_unused(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    active_sessions = {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "ai-studio-01"},
        "C2": "0:0.0",
    }

    name = goslack._select_fallback_channel(active_sessions)
    assert name == "ai-studio-02"


def test_select_fallback_round_robin_state(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    rr_path = tmp_path / "tmp" / "ai_studio_rr.json"
    rr_path.parent.mkdir(parents=True, exist_ok=True)
    goslack.save_json(str(rr_path), {"last_index": 2})

    active_sessions = {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "ai-studio-01"},
        "C2": {"pane": "1:2.0", "dir": "/tmp/b", "name": "ai-studio-02"},
        "C3": {"pane": "1:3.0", "dir": "/tmp/c", "name": "ai-studio-03"},
    }

    name = goslack._select_fallback_channel(active_sessions)
    assert name == "ai-studio-01"
