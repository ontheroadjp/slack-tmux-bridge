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
    monkeypatch.setattr(goslack, "get_tmux_pane_id", lambda: "1:1.0")
    monkeypatch.setattr(goslack, "send_slack_message", lambda *_: None)
    monkeypatch.setattr(os, "getcwd", lambda: "/tmp/workdir")

    monkeypatch.setattr(sys, "argv", ["goslack.py"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert sessions["C1"]["pane"] == "1:1.0"
    assert sessions["C1"]["dir"] == "/tmp/workdir"
    assert sessions["C1"]["name"] == "workdir"


def test_main_fallback_channel(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    channels = [{"id": "C2", "name": "ai-studio-02"}]
    monkeypatch.setattr(goslack, "_get_slack_client", lambda: FakeClient(channels))
    monkeypatch.setattr(goslack, "get_tmux_pane_id", lambda: "2:3.4")
    monkeypatch.setattr(goslack, "send_slack_message", lambda *_: None)
    monkeypatch.setattr(os, "getcwd", lambda: "/tmp/unknown")

    monkeypatch.setattr(sys, "argv", ["goslack.py"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert sessions["C2"]["pane"] == "2:3.4"
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
    monkeypatch.setattr(goslack, "get_tmux_pane_id", lambda: "1:1.0")
    monkeypatch.setattr(goslack, "send_slack_message", lambda *_: None)
    monkeypatch.setattr(os, "getcwd", lambda: "/tmp/workdir")

    monkeypatch.setattr(sys, "argv", ["goslack.py"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert "C1" not in sessions
    assert "C2" in sessions
    assert sessions["C3"]["pane"] == "1:1.0"
