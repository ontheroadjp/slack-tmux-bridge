import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import goslack


def _write_sessions(path, data):
    goslack.save_json(path, data)


def test_list_sessions_prints_entries(tmp_path, monkeypatch, capsys):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    _write_sessions(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "chan-a"},
        "C2": "0:0.0",
    })

    goslack.list_sessions()
    out = capsys.readouterr().out

    assert "num\tchannel_name\tpane\tdir" in out
    assert "1\t-\t0:0.0\t-" in out
    assert "2\tchan-a\t1:1.0\t/tmp/a" in out


def test_remove_by_number(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    _write_sessions(str(sessions_path), {
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "ai-studio-01"},
        "C2": {"pane": "1:2.0", "dir": "/tmp/b", "name": "ai-studio-02"},
    })

    goslack.remove_sessions_by_number(2)
    sessions = goslack.load_json(str(sessions_path))

    assert "C2" not in sessions
    assert "C1" in sessions
