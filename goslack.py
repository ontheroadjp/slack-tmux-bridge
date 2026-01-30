#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import tempfile
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

# Paths
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
ACTIVE_SESSIONS_FILE = os.path.join(BASE_DIR, "active_sessions.json")
DOTENV_PATH = os.path.join(BASE_DIR, ".env")
FALLBACK_STATE_FILE = os.path.join(BASE_DIR, "tmp", "fallback_state.json")

# Load environment variables
load_dotenv(DOTENV_PATH)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

# Fallback channel names (fixed order)
FALLBACK_CHANNEL_NAMES = [
    "ai-studio-01",
    "ai-studio-02",
    "ai-studio-03",
]

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

def send_slack_message(channel, text):
    """Sends a message to Slack using WebClient"""
    if not SLACK_BOT_TOKEN:
        print("⚠️ Warning: SLACK_BOT_TOKEN not found. Skipping Slack notification.")
        return
    
    try:
        client = WebClient(token=SLACK_BOT_TOKEN)
        client.chat_postMessage(channel=channel, text=text)
    except SlackApiError as e:
        print(f"⚠️ Warning: Failed to send Slack message: {e}")

def _normalize_channel_name(value: str) -> str:
    return value[1:] if value.startswith("#") else value

def _get_slack_client():
    if not SLACK_BOT_TOKEN:
        return None
    return WebClient(token=SLACK_BOT_TOKEN)

def _resolve_channel_id_by_name(client: WebClient, name: str):
    name = _normalize_channel_name(name)
    cursor = None
    while True:
        try:
            resp = client.conversations_list(
                limit=1000,
                cursor=cursor,
                types="public_channel,private_channel",
            )
        except SlackApiError as e:
            if e.response.get("error") == "missing_scope":
                return None, None, "missing_scope"
            raise
        for ch in resp.get("channels", []):
            if ch.get("name") == name:
                return ch.get("id"), ch.get("name"), None
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return None, None, None

def _resolve_fallback_channels(client: WebClient):
    resolved = []
    for raw in FALLBACK_CHANNEL_NAMES:
        ch_id, ch_name, err = _resolve_channel_id_by_name(client, raw)
        if err == "missing_scope":
            return None, "missing_scope"
        if not ch_id:
            return None, f"not_found:{raw}"
        resolved.append({"id": ch_id, "name": ch_name or raw})
    return resolved, None

def _next_fallback_index(count: int) -> int:
    state = load_json(FALLBACK_STATE_FILE)
    last_idx = state.get("last_index", -1)
    next_idx = (last_idx + 1) % count
    save_json(FALLBACK_STATE_FILE, {"last_index": next_idx})
    return next_idx

def _select_fallback_channel(active_sessions, fallback_channels, pane_id: str):
    # If this pane is already mapped to a fallback channel, keep it.
    for ch in fallback_channels:
        if active_sessions.get(ch["id"]) == pane_id:
            return ch, False

    active_ids = set(active_sessions.keys())
    for ch in fallback_channels:
        if ch["id"] not in active_ids:
            return ch, False

    # All fallback channels are in use; overwrite in round-robin order.
    idx = _next_fallback_index(len(fallback_channels))
    return fallback_channels[idx], True

def main():
    # 1. Get current directory
    cwd = os.getcwd()
    dir_name = os.path.basename(cwd)

    client = _get_slack_client()
    if not client:
        print("❌ Error: SLACK_BOT_TOKEN is required.")
        sys.exit(1)

    target_channel = None
    target_display = None
    used_fallback = False
    fallback_overwrite = False
    fallback_display = None

    if dir_name:
        ch_id, ch_name, err = _resolve_channel_id_by_name(client, dir_name)
        if err == "missing_scope":
            print("❌ Error: Missing channels:read/groups:read/mpim:read/im:read scopes to resolve channel names.")
            sys.exit(1)
        if ch_id:
            target_channel = ch_id
            target_display = ch_name or dir_name

    # 2. Get Tmux Pane ID
    pane_id = get_tmux_pane_id()

    # 3. Load active sessions (needed for fallback selection)
    active_sessions = load_json(ACTIVE_SESSIONS_FILE)

    if not target_channel:
        fallback_channels, err = _resolve_fallback_channels(client)
        if err == "missing_scope":
            print("❌ Error: Missing channels:read/groups:read/mpim:read/im:read scopes to resolve ai-studio channels.")
            sys.exit(1)
        if err and err.startswith("not_found"):
            missing = err.split(":", 1)[1]
            print(f"❌ Error: Fallback channel not found: {missing}")
            sys.exit(1)
        if not fallback_channels:
            print("❌ Error: No fallback channels available. Please ensure ai-studio-01/02/03 exist.")
            sys.exit(1)

        selected, fallback_overwrite = _select_fallback_channel(active_sessions, fallback_channels, pane_id)
        target_channel = selected["id"]
        fallback_display = selected["name"]
        used_fallback = True

    # 4. Update active sessions
    duplicates = [ch for ch, pane in active_sessions.items() if pane == pane_id and ch != target_channel]
    for dup in duplicates:
        del active_sessions[dup]

    active_sessions[target_channel] = pane_id
    save_json(ACTIVE_SESSIONS_FILE, active_sessions)

    # 5. Send Slack Notification
    send_slack_message(target_channel, "✅ 接続しました。このチャンネルからのメッセージはこの tmux ペインに送られます。")

    print(f"✅ Connected!")
    print(f"Directory: {cwd}")
    if used_fallback:
        overwrite_note = " (overwrite)" if fallback_overwrite else ""
        print(f"Channel:   {fallback_display}{overwrite_note}")
        print(f"ChannelID:{target_channel}")
    else:
        print(f"Channel:   {target_display or target_channel}")
    print(f"Tmux Pane: {pane_id}")
    print(f"Gemini bridge is now listening to {target_channel} and forwarding to this pane.")

if __name__ == "__main__":
    main()
