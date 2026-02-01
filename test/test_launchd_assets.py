from pathlib import Path


def test_plist_uses_env_python3_and_tmux_bin():
    plist = Path("launchd/com.slack_tmux_bridge.plist").read_text(encoding="utf-8")
    assert "<string>/usr/bin/env</string>" in plist
    assert "TMUX_BIN=" in plist
    assert "<string>python3</string>" in plist
    assert "slack_tmux_bridge.py" in plist
    assert "slack_tmux_bridge.log" in plist


def test_launchd_ctl_has_expected_commands_and_log_tail():
    script = Path("launchd/launchd_ctl.sh").read_text(encoding="utf-8")
    assert "usage:" in script
    for cmd in ("install", "start", "stop", "restart", "status", "log"):
        assert cmd in script
    assert "tail -f" in script
    assert "slack_tmux_bridge.log" in script
