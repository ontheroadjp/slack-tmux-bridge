#!/usr/bin/env python3
import os
import sys
import argparse
import json
import subprocess
import tempfile
from slack_sdk import WebClient
from dotenv import load_dotenv

# Paths
# Use realpath to resolve symlinks so we find files relative to the script, not the symlink
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
ACTIVE_SESSIONS_FILE = os.path.join(BASE_DIR, "active_sessions.json")
DOTENV_PATH = os.path.join(BASE_DIR, ".env")
AI_STUDIO_CHANNELS = ["ai-studio-01", "ai-studio-02", "ai-studio-03"]

# Load environment variables
load_dotenv(DOTENV_PATH)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_json(path, data):
    dir_name = os.path.dirname(path)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

def get_tmux_pane_id():
    """Returns the current tmux pane ID (e.g., %0, %1) or target format (e.g. session:window.pane)"""
    try:
        # Check if we are in tmux
        if not os.environ.get("TMUX"):
            print("Error: This script must be run inside a tmux session.")
            sys.exit(1)
            
        cmd = ["tmux", "display-message", "-p", "#{session_name}:#{window_index}.#{pane_index}"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error getting tmux info: {e}")
        sys.exit(1)

def get_tmux_pane_cwd(tmux_target):
    try:
        cmd = ["tmux", "display-message", "-p", "-t", tmux_target, "#{pane_current_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error getting tmux pane path: {e}")
        sys.exit(1)


def _get_slack_client():
    if not SLACK_BOT_TOKEN:
        print("❌ Error: SLACK_BOT_TOKEN not found in environment.")
        sys.exit(1)
    return WebClient(token=SLACK_BOT_TOKEN)

def send_slack_message(channel, text):
    """Sends a message to Slack using WebClient"""
    try:
        client = _get_slack_client()
        client.chat_postMessage(channel=channel, text=text)
    except Exception as e:
        print(f"⚠️ Warning: Failed to send Slack message: {e}")

def _find_channel_by_name(client, name):
    cursor = None
    while True:
        try:
            resp = client.conversations_list(
                limit=1000,
                cursor=cursor,
                types="public_channel,private_channel"
            )
        except Exception as e:
            print(f"⚠️ Warning: Slack API call failed while listing channels: {e}")
            return None
        for ch in resp.get("channels", []):
            if ch.get("name") == name:
                return ch
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return None

def _normalize_session_entry(channel_id, value):
    if isinstance(value, dict):
        return {
            "channel_id": channel_id,
            "channel_name": value.get("name"),
            "pane": value.get("pane"),
            "dir": value.get("dir"),
        }
    return {
        "channel_id": channel_id,
        "channel_name": None,
        "pane": value,
        "dir": None,
    }

def _session_sort_key(entry):
    name = entry.get("channel_name") or ""
    if name.startswith("ai-studio-"):
        try:
            num = int(name.split("ai-studio-")[1])
            return (0, num, name)
        except ValueError:
            return (1, 0, name)
    return (1, 0, name)

def _enumerate_sessions():
    sessions = load_json(ACTIVE_SESSIONS_FILE)
    entries = [_normalize_session_entry(ch_id, val) for ch_id, val in sessions.items()]
    entries.sort(key=_session_sort_key)
    return entries

def list_sessions():
    entries = _enumerate_sessions()
    if not entries:
        print("(no active sessions)")
        return
    lines = []
    for i, entry in enumerate(entries, start=1):
        name = entry["channel_name"] or "-"
        pane = entry["pane"] or "-"
        dir_path = entry["dir"] or "-"
        lines.append(f"{i}\t{name}\t{pane}\t{dir_path}")
    print("num\tchannel_name\tpane\tdir")
    print("\n".join(lines))

def remove_sessions_by_number(number):
    entries = _enumerate_sessions()
    if not entries:
        print("(no active sessions)")
        return
    if number < 1 or number > len(entries):
        print("Error: number out of range.")
        sys.exit(1)

    target = entries[number - 1]
    sessions = load_json(ACTIVE_SESSIONS_FILE)
    if target["channel_id"] in sessions:
        del sessions[target["channel_id"]]
        save_json(ACTIVE_SESSIONS_FILE, sessions)
        name = target["channel_name"] or "-"
        pane_val = target["pane"] or "-"
        dir_val = target["dir"] or "-"
        print(f"Removed: {number}\t{name}\t{pane_val}\t{dir_val}")
    else:
        print("Error: session not found.")
        sys.exit(1)

def _extract_pane(value):
    if isinstance(value, dict):
        return value.get("pane")
    return value

def _rr_state_path():
    base_dir = os.path.dirname(ACTIVE_SESSIONS_FILE)
    return os.path.join(base_dir, "tmp", "ai_studio_rr.json")

def _load_rr_state():
    data = load_json(_rr_state_path())
    if not isinstance(data, dict):
        return {"last_index": -1}
    return {"last_index": int(data.get("last_index", -1))}

def _save_rr_state(last_index: int):
    save_json(_rr_state_path(), {"last_index": last_index})

def _select_fallback_channel(active_sessions):
    used = set()
    for value in active_sessions.values():
        if isinstance(value, dict):
            name = value.get("name")
            if name:
                used.add(name)

    # Prefer first free slot
    for name in AI_STUDIO_CHANNELS:
        if name not in used:
            _save_rr_state(AI_STUDIO_CHANNELS.index(name))
            return name

    # All occupied (or unknown) -> round robin
    state = _load_rr_state()
    last_index = state.get("last_index", -1)
    next_index = (last_index + 1) % len(AI_STUDIO_CHANNELS)
    _save_rr_state(next_index)
    return AI_STUDIO_CHANNELS[next_index]

def _resolve_channel(client, dir_name, active_sessions):
    channel = _find_channel_by_name(client, dir_name)
    if channel:
        return channel
    fallback = _select_fallback_channel(active_sessions)
    if fallback:
        channel = _find_channel_by_name(client, fallback)
        if channel:
            return channel
    for name in AI_STUDIO_CHANNELS:
        if name == fallback:
            continue
        channel = _find_channel_by_name(client, name)
        if channel:
            return channel
    return None

def _register_session(target_channel, target_channel_name, pane_id, cwd):
    active_sessions = load_json(ACTIVE_SESSIONS_FILE)
    duplicates = [
        ch
        for ch, pane in active_sessions.items()
        if _extract_pane(pane) == pane_id and ch != target_channel
    ]
    for dup in duplicates:
        del active_sessions[dup]

    active_sessions[target_channel] = {"pane": pane_id, "dir": cwd, "name": target_channel_name}
    save_json(ACTIVE_SESSIONS_FILE, active_sessions)

def main():
    parser = argparse.ArgumentParser(description="Slack tmux bridge session helper")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="List active sessions")

    rm_parser = subparsers.add_parser("rm", help="Remove a session by number")
    rm_parser.add_argument("number", type=int, help="Session number from list")
    parser.add_argument("--add", metavar="PANE", help="Register a target tmux pane (e.g., 1:2.0)")

    args = parser.parse_args()

    if args.command == "list":
        list_sessions()
        return
    if args.command == "rm":
        remove_sessions_by_number(args.number)
        return

    # 1. Get current directory (or target pane directory)
    if args.add:
        pane_id = args.add
        cwd = get_tmux_pane_cwd(pane_id)
    else:
        cwd = os.getcwd()
    active_sessions = load_json(ACTIVE_SESSIONS_FILE)

    # 2. Resolve channel ID by current directory name
    client = _get_slack_client()
    dir_name = os.path.basename(cwd)
    channel = _resolve_channel(client, dir_name, active_sessions)

    if not channel:
        print("❌ Error: No channel matched this directory name.")
        print(f"Current Directory: {cwd}")
        print(f"Directory Name:    {dir_name}")
        print("Tried fallbacks:   ai-studio-01, ai-studio-02, ai-studio-03")
        sys.exit(1)
    
    target_channel = channel.get("id")
    target_channel_name = channel.get("name")
        
    # 4. Get Tmux Pane ID
    if not args.add:
        pane_id = get_tmux_pane_id()
    
    # 5. Update active sessions
    _register_session(target_channel, target_channel_name, pane_id, cwd)
    
    # 6. Send Slack Notification
    send_slack_message(
        target_channel,
        "✅ 接続しました。"
        f"\nディレクトリ: {cwd}"
        "\nこのチャンネルからのメッセージはこの tmux ペインに送られます。"
    )
    
    print(f"✅ Connected!")
    print(f"Directory: {cwd}")
    print(f"Channel:   {target_channel}")
    print(f"Tmux Pane: {pane_id}")
    print(f"Gemini bridge is now listening to {target_channel} and forwarding to this pane.")

if __name__ == "__main__":
    main()
