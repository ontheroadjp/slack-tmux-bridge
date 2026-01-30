#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from slack_sdk import WebClient
from dotenv import load_dotenv

# Paths
# Use realpath to resolve symlinks so we find config.json relative to the script, not the symlink
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ACTIVE_SESSIONS_FILE = os.path.join(BASE_DIR, "active_sessions.json")
DOTENV_PATH = os.path.join(BASE_DIR, ".env")

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

def expand_path(path):
    """Expands ~ and env vars, and returns absolute path without trailing slash"""
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))

def send_slack_message(channel, text):
    """Sends a message to Slack using WebClient"""
    if not SLACK_BOT_TOKEN:
        print("⚠️ Warning: SLACK_BOT_TOKEN not found. Skipping Slack notification.")
        return
    
    try:
        client = WebClient(token=SLACK_BOT_TOKEN)
        client.chat_postMessage(channel=channel, text=text)
    except Exception as e:
        print(f"⚠️ Warning: Failed to send Slack message: {e}")

def main():
    # 1. Get current directory
    cwd = os.getcwd()
    
    # 2. Load config
    raw_config = load_json(CONFIG_FILE)
    
    # Normalize config keys (expand vars, abspath)
    config = {}
    for k, v in raw_config.items():
        # Skip empty keys
        if not k: continue
        # Expand and normalize path
        norm_key = expand_path(k)
        config[norm_key] = v

    # 3. Find matching channel
    target_channel = config.get(cwd)
    
    if not target_channel:
        # Try finding if cwd is a subdirectory of a configured path
        # Sort by length desc to find the most specific match
        for registered_path in sorted(config.keys(), key=len, reverse=True):
            # Check if cwd starts with registered_path AND the next char is a separator or end
            # Using os.path.commonpath is safer but startswith is okay if we are careful
            if cwd == registered_path or cwd.startswith(registered_path + os.sep):
                 target_channel = config[registered_path]
                 break
    
    if not target_channel:
        print(f"❌ Error: No channel configured for this directory.")
        print(f"Current Directory: {cwd}")
        print(f"Config File used:  {CONFIG_FILE}")
        print("Loaded mappings:")
        for k in config.keys():
            print(f" - {k}")
        print("\nPlease add your path to config.json")
        sys.exit(1)
        
    # 4. Get Tmux Pane ID
    pane_id = get_tmux_pane_id()
    
    # 5. Update active sessions
    active_sessions = load_json(ACTIVE_SESSIONS_FILE)
    # Remove any other channels pointing to the same tmux pane
    duplicates = [ch for ch, pane in active_sessions.items() if pane == pane_id and ch != target_channel]
    for dup in duplicates:
        del active_sessions[dup]
    
    # Map Channel -> Pane
    active_sessions[target_channel] = pane_id
    
    save_json(ACTIVE_SESSIONS_FILE, active_sessions)
    
    # 6. Send Slack Notification
    send_slack_message(target_channel, "✅ 接続しました。このチャンネルからのメッセージはこの tmux ペインに送られます。")
    
    print(f"✅ Connected!")
    print(f"Directory: {cwd}")
    print(f"Channel:   {target_channel}")
    print(f"Tmux Pane: {pane_id}")
    print(f"Gemini bridge is now listening to {target_channel} and forwarding to this pane.")

if __name__ == "__main__":
    main()
