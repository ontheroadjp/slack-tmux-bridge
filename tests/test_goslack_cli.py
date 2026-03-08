import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import goslack


def _write_sessions(path, data):
    goslack.save_json(path, data)


def test_cli_list_outputs_table_with_numbers(tmp_path, monkeypatch, capsys):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    _write_sessions(str(sessions_path), {
        "C2": {"pane": "1:2.0", "dir": "/tmp/b", "name": "ai-studio-02"},
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "ai-studio-01"},
        "C9": {"pane": "9:9.9", "dir": "/tmp/z", "name": "zzz"},
    })

    monkeypatch.setattr(sys, "argv", ["goslack.py", "list"])
    goslack.main()

    out = capsys.readouterr().out
    assert "num\tchannel_name\tpane\tpane_id\tdir" in out
    assert "1\tai-studio-01\t1:1.0\t-\t/tmp/a" in out
    assert "2\tai-studio-02\t1:2.0\t-\t/tmp/b" in out
    assert "3\tzzz\t9:9.9\t-\t/tmp/z" in out


def test_cli_rm_by_number(tmp_path, monkeypatch):
    sessions_path = tmp_path / "active_sessions.json"
    monkeypatch.setattr(goslack, "ACTIVE_SESSIONS_FILE", str(sessions_path))

    _write_sessions(str(sessions_path), {
        "C2": {"pane": "1:2.0", "dir": "/tmp/b", "name": "ai-studio-02"},
        "C1": {"pane": "1:1.0", "dir": "/tmp/a", "name": "ai-studio-01"},
        "C9": {"pane": "9:9.9", "dir": "/tmp/z", "name": "zzz"},
    })

    monkeypatch.setattr(sys, "argv", ["goslack.py", "rm", "2"])
    goslack.main()

    sessions = goslack.load_json(str(sessions_path))
    assert "C2" not in sessions
    assert "C1" in sessions
    assert "C9" in sessions


def test_cli_notify_subcommand_is_not_supported(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["goslack.py", "notify", "{\"thread-id\":\"t1\"}"])
    try:
        goslack.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("SystemExit expected")
