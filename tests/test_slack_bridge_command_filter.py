import os

os.environ.setdefault("SLACK_BOT_TOKEN", "xxxx-xxxx")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

import slack_tmux_bridge as stb


def test_default_denylist_blocks_rm():
    stb.COMMAND_ALLOWLIST = "all"
    stb.COMMAND_DENYLIST = ""
    allowed, reason = stb.is_command_allowed("rm -rf /")
    assert not allowed
    assert "ブロック" in reason


def test_default_denylist_allows_escaped_rm():
    stb.COMMAND_ALLOWLIST = "all"
    stb.COMMAND_DENYLIST = ""
    allowed, _ = stb.is_command_allowed(r"\rm -rf /")
    assert allowed


def test_allowlist_requires_match():
    stb.COMMAND_ALLOWLIST = "git"
    stb.COMMAND_DENYLIST = ""
    allowed, _ = stb.is_command_allowed("git status")
    assert allowed
    allowed, reason = stb.is_command_allowed("ls")
    assert not allowed
    assert "許可" in reason


def test_denylist_regex_blocks():
    stb.COMMAND_ALLOWLIST = "all"
    stb.COMMAND_DENYLIST = r"/\bshutdown\b/"
    allowed, reason = stb.is_command_allowed("shutdown now")
    assert not allowed
    assert "ブロック" in reason
