# Slack AI Notifier (Gemini-Tmux Bridge)

This project bridges Slack and a persistent Gemini CLI session running inside `tmux`. You can type prompts from Slack, send them to Gemini, and receive replies in the same thread without manually attaching to tmux or SSHing into the host.

## Features

- **Slack integration**: Bolt Socket Mode receives channel messages, posts replies, and exposes slash commands.
- **Smart monitoring**: Captures `tmux` output every second, detects stability or permission prompts, and only posts the completed response.
- **Pre-clear and clean output**: Runs `tmux clear-history` + `Ctrl+L` before each command, then extracts everything after the echoed prompt (`> [prompt]`).
- **Input ergonomics**: Numeric messages auto-run, text messages stay pending until you press “Execute (Enter)”, and selected slash commands send prebuilt inputs.
- **Command filtering**: Allowlist + denylist rules ensure only safe commands reach tmux, with `rm` blocked by default unless explicitly escaped.
- **Single-instance guard**: A PID file prevents duplicate Socket Mode connections and duplicate event streams.
- **Health monitoring**: Workers prune old snapshots/prompts and detect stalled event streams, with optional warnings or self-restart actions.
- **Session visibility**: `/sessions` command shows which Slack channel maps to which tmux pane plus the last activity age.

## Requirements

- Python 3.x
- `tmux`
- Gemini CLI (`gemini`)
- Slack App with a Bot token (`xoxb-…`) and App Level token (`xapp-…`) for Socket Mode

## Setup

### 1. Install dependencies

Use a virtual environment so the bridge’s dependencies stay isolated.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Slack App setup

1. Visit [https://api.slack.com/apps](https://api.slack.com/apps) and create a new app “From scratch”. Choose your workspace.
2. In **Socket Mode**, enable it and generate an App-Level Token (`xapp-…`). Copy it for later.
3. In **OAuth & Permissions**, add these Bot Token Scopes:
   - `chat:write` (send replies)
   - `channels:history` (read public channel messages)
   - `groups:history` / `im:history` / `mpim:history` if you plan to use private/group DMs.
4. In **Event Subscriptions**, enable events and add:
   - `message.channels`
   - `message.groups`, `message.im`, `message.mpim` if you will use those surfaces.
5. Back in **OAuth & Permissions**, click **Install to Workspace** and allow the scopes. Copy the Bot Token (`xoxb-…`).
6. Invite the app to your target channel (`/invite @YourAppName`).
7. `goslack.py` resolves channels by the current directory name; align your directory name with your Slack channel name (or prepare `ai-studio-01/02/03` as fallbacks).

### 3. Environment variables

Copy `.env.sample` to `.env` and populate the values:

```bash
cp .env.sample .env
```

- `SLACK_BOT_TOKEN` – `xoxb-…` token.
- `SLACK_APP_TOKEN` – `xapp-…` token for Socket Mode.
- `TARGET_CHANNEL_ID` – legacy setting (unused by current implementation).
- `LOG_LEVEL` – controls Bolt/SDK logging (`INFO`, `DEBUG`).
- `OUTPUT_DIFF_MODE` – choose `replace` (current output) or `suffix` (print everything after the last occurrence of the initial screen).
- `EVENT_HEALTH_*` – tune timeout, action (`log`, `exit`, `restart`), restart cooldown, notification delivery, and notification cooldown.
- `PROMPT_CACHE_TTL_SEC` / `SNAPSHOT_TTL_SEC` – retention windows for cached prompts and snapshots; maintenance workers purge expired files.
- `COMMAND_ALLOWLIST` / `COMMAND_DENYLIST` – comma-separated patterns; include `all` to allow/deny everything. Default behavior blocks standalone `rm`.

Command filter notes:

- Denylist is evaluated first and includes the default `/\brm\b/` pattern unless you override it.
- Allowlist must match unless you set it to `all`.
- Patterns surrounded by `/…/` are treated as regex; otherwise, they match substrings.

Recommended denylist example:

```
sudo,rm -rf,/\brm\b/,mkfs,dd,/\bshutdown\b/,/\breboot\b/,/curl\s+.*\|\s*sh/,/wget\s+.*\|\s*sh/
```

`goslack.py` session control:

- `goslack.py` writes `active_sessions.json` atomically, avoiding partial writes.
- If another Slack channel already points to the same tmux pane, running `goslack.py` removes the stale entry so only the current channel remains.
- Channel resolution uses the current directory name; if not found, it falls back to `ai-studio-01/02/03`.

### 4. Prepare scripts

- `send_enter.sh` sends Enter into tmux; ensure it is executable.

```bash
chmod +x send_enter.sh
```

- `run_slack_bridge.sh` loads `.env` before launching the bridge; it is used for macOS `launchd`.

### 5. Optional macOS Launchd deployment

Create `~/Library/LaunchAgents/com.slack_tmux_bridge.plist` containing:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.slack_tmux_bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/WORKSPACE/slack_tmux_bridge/run_slack_bridge.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/you/Library/Logs/slack_tmux_bridge.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/you/Library/Logs/slack_tmux_bridge.log</string>
</dict>
</plist>
```

Adjust paths to your environment. Load/unload with:

```bash
launchctl load ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
launchctl unload ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
```

Monitor status via `launchctl list | grep slack_tmux_bridge`. Logs contain `LOG_LEVEL` output plus restart history.

## Installation & usage

### 1. Clone & configure

```bash
git clone <repo> slack_tmux_bridge
cd slack_tmux_bridge
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env
```

Edit `.env` with your Slack tokens and optional tuning values documented above.

### 2. tmux & goslack

1. Start Gemini inside a tmux pane (`tmux new-session -s gemini`, run `gemini`).
2. Inside that pane, run `python goslack.py` to register the channel ↔ pane mapping. `goslack.py` resolves the Slack channel by the current directory name; if not found, it falls back to `ai-studio-01/02/03` in order. It also automatically removes any other channel that referenced the same pane.

### 3. Run the bridge

```bash
source venv/bin/activate
python slack_tmux_bridge.py
```

Default target is `0:0.0`. Pass `1:2.0` to target a different session/window/pane.

- Set `LOG_LEVEL=DEBUG` to capture Bolt/Socket Mode state and health logs.
- Toggle `OUTPUT_DIFF_MODE` to test the old/new diff extraction behavior.
- Use `run_slack_bridge.sh` if you intend to run under `launchd`.

### 4. Slack operations

1. Send a message to the configured channel.
   - Text requires pressing the “Execute (Enter)” button that appears in the thread.
   - Numeric-only messages send automatically.
   - `text == "/sessions"` (or `\/sessions`) shows the active mappings and last event times.
2. The bridge monitors Gemini and replies in the thread, chunking long outputs into 3,000-character pieces.

### 5. Health monitoring

- `_maintenance_worker` prunes prompt cache and snapshot files using `PROMPT_CACHE_TTL_SEC` / `SNAPSHOT_TTL_SEC`.
- `_event_health_worker` watches for `EVENT_HEALTH_TIMEOUT` seconds of no events and either logs, exits, restarts, or notifies channels.
- Set `EVENT_HEALTH_NOTIFY=1` to post warnings per channel when they go silent; `EVENT_HEALTH_NOTIFY_COOLDOWN_SEC` throttles repeats.
- Restart actions respect `EVENT_HEALTH_RESTART_COOLDOWN_SEC` to avoid rapid loops.

## Deployment tiers

1. **Minimal**: Run `slack_tmux_bridge.py` directly after configuring `.env`. Good for trial runs.
2. **Recommended**: Always run `goslack.py` from each tmux pane to keep `active_sessions.json` accurate, then start the bridge. Keeps multiple channels/panes organized.
3. **Daemon**: Use `run_slack_bridge.sh` with macOS `launchd` for persistent operation and auto-restarts. Continue to manage mappings via `goslack.py`.

## Utilities

- `/sessions`: Slack command that posts a table of channel-to-pane mappings plus the age of the last event.
- `goslack.py`: Registers the current tmux pane with the target channel and cleans up duplicates.
- `run_slack_bridge.sh`: Loads `.env` before launching the core bridge script (used by `launchd`).
