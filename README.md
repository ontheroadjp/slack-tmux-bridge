# Slack AI Notifier (Gemini-Tmux Bridge)

This project bridges Slack and a persistent Gemini CLI session running inside `tmux`. You can type prompts from Slack, send them to Gemini, and receive replies in the same thread without manually attaching to tmux or SSHing into the host.

## Features

- **Slack integration**: Bolt Socket Mode receives channel messages, posts replies, and exposes slash commands.
- **Pre-clear and clean output**: Runs `tmux clear-history` + `Ctrl+L` before each command, then extracts everything after the echoed prompt (`> [prompt]`).
- **Input ergonomics**: Numeric messages auto-run, text messages stay pending until you press “Execute (Enter)”, and selected slash commands send prebuilt inputs.
- **Reply delegation**: When executing, the bridge posts a snapshot when monitoring detects output has stabilized.
- **Permission prompt watch**: After sending Enter, the bridge watches tmux output and posts a snippet to the thread if an approval prompt appears.
- **Command filtering**: Allowlist + denylist rules ensure only safe commands reach tmux, with `rm` blocked by default unless escaped as `\rm`.
- **Single-instance guard**: A PID file prevents duplicate Socket Mode connections and duplicate event streams.
- **Health monitoring**: Workers prune prompt cache and detect stalled event streams, with optional warnings or self-restart actions.
- **Session visibility**: `/sessions` command lists connected channel names and directories.
- **Interrupt**: `/ctlc` sends Ctrl+C to the connected tmux pane.
- **Idle ping**: Per-channel idle notifications when no messages arrive for a while.
- **Duplicate cleanup**: Periodically detects duplicate pane mappings and disconnects the older one with a notice.
- **Mismatch guard**: If a pane changes, the bridge prompts before sending and can update or disconnect.

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
7. `goslack.py` resolves channels by the current directory name via Slack API; align your directory name with your Slack channel name (or prepare `ai-studio-01/02/03` as fallbacks).

### 3. Environment variables

Copy `.env.sample` to `.env` and populate the values:

```bash
cp .env.sample .env
```

- `SLACK_BOT_TOKEN` – `xoxb-…` token.
- `SLACK_APP_TOKEN` – `xapp-…` token for Socket Mode.
- `TARGET_CHANNEL_ID` – legacy setting (unused by current implementation).
- `LOG_LEVEL` – controls Bolt/SDK logging (`INFO`, `DEBUG`).
- `TMUX_BIN` – absolute path to the tmux binary. Required if `tmux` is not in PATH (common under launchd).
- `EVENT_HEALTH_*` – tune timeout, action (`log`, `exit`, `restart`), restart cooldown, notification delivery, and notification cooldown.
- `PROMPT_CACHE_TTL_SEC` – retention window for cached prompts; maintenance workers purge expired entries.
- `CHANNEL_IDLE_NOTIFY_SEC` / `CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC` – idle notification interval and cooldown (per channel).
- `PERMISSION_WATCH_SEC` / `PERMISSION_WATCH_INTERVAL_SEC` / `PERMISSION_WATCH_PATTERN` – after sending Enter, watch tmux output for approval prompts and post a snippet to the thread.
- `NOW_WATCH_INTERVAL_SEC` / `NOW_WATCH_IDLE_COUNT` / `NOW_WATCH_TIMEOUT_SEC` – `/now` polling interval, consecutive idle count to reply, and timeout before prompting to continue.
- `EXECUTE_RESULT_MODE` – behavior after pressing “Execute (Enter)”: `poll` (watch output and post snapshot), `notify` (notify-only), `both` (notify-first with poll fallback; dedupe enabled).
- `NOTIFY_INGRESS_*` – optional local notify ingress for `slack_tmux_bridge` (`http` localhost-only or `uds`), including payload size and rate-limit settings.
- `NOTIFY_DEDUPE_TTL_SEC` – retention window for dedupe keys used by `poll/notify` coordination.
- `NOTIFY_QUEUE_TTL_SEC` / `NOTIFY_RETRY_BASE_SEC` / `NOTIFY_RETRY_MAX_SEC` / `NOTIFY_RETRY_MAX_ATTEMPTS` / `NOTIFY_RETRY_TICK_SEC` – notify delivery queue TTL and retry policy (backoff, max attempts, worker interval).
- `COMMAND_ALLOWLIST` / `COMMAND_DENYLIST` – comma-separated patterns; include `all` to allow/deny everything. Default behavior blocks `rm` (use `\rm` to bypass).

Command filter notes:

- Denylist is evaluated first and includes the default `/(?<!\\)\brm\b/` pattern unless you override it.
- Allowlist must match unless you set it to `all`.
- Patterns surrounded by `/…/` are treated as regex; otherwise, they match substrings.

Recommended denylist example:

```
sudo,rm -rf,/\brm\b/,mkfs,dd,/\bshutdown\b/,/\breboot\b/,/curl\s+.*\|\s*sh/,/wget\s+.*\|\s*sh/
```

`goslack.py` session control:

- `goslack.py` writes `active_sessions.json` atomically, avoiding partial writes.
- If another Slack channel already points to the same tmux pane, running `goslack.py` removes the stale entry so only the current channel remains.
- `active_sessions.json` stores `pane_id`, `pane`, `dir`, and `name` (channel name) per channel ID.
- `goslack.py list` prints numbered mappings (including `pane_id`); `goslack.py rm <number>` removes a mapping by its list number.
- `goslack.py --add <pane>` registers a target tmux pane from another pane (uses the target pane’s current directory).
  - Optional: `--channel <NAME>` to override the channel name (no fallback).
  - Ordering rules: `ai-studio-01`, `ai-studio-02`, `ai-studio-03` come first (in numeric order), then all other channels.
  - For non ai-studio channels, ordering is by channel name (ascending). Channels without a name appear as `-`.
  - `goslack.py rm <number>` exits with an error if the number is out of range.

Example (`goslack.py list`):

```
num	channel_name	pane	pane_id	dir
1	ai-studio-01	1:1.0	%1	/Users/you/WORKSPACE/ai-studio-01
2	ai-studio-02	1:2.0	%2	/Users/you/WORKSPACE/ai-studio-02
3	ai-studio-03	1:3.0	%3	/Users/you/WORKSPACE/ai-studio-03
4	project-x	2:0.0	%4	/Users/you/WORKSPACE/project-x
```

Example removal:

```
python goslack.py rm 4
```
- Channel resolution uses the current directory name; if not found, it falls back to `ai-studio-01/02/03`.
  - Fallback selection prefers an unused `ai-studio-*` name; if all are in use, it rotates `01 → 02 → 03 → 01 ...`.

### 4. Prepare scripts

- `send_enter.sh` sends Enter into tmux; ensure it is executable.

```bash
chmod +x send_enter.sh
```


### 5. Optional macOS Launchd deployment

This repo includes a ready plist at `launchd/com.slack_tmux_bridge.plist`. Copy it to `~/Library/LaunchAgents` and adjust paths if needed:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.slack_tmux_bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>TMUX_BIN=/usr/local/bin/tmux</string>
    <string>python3</string>
    <string>/Users/you/WORKSPACE/slack_tmux_bridge/slack_tmux_bridge.py</string>
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

Adjust paths to your environment. Copy and load/unload with:

```bash
cp launchd/com.slack_tmux_bridge.plist ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
launchctl load ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
launchctl unload ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
```

You can also use the helper script:

```bash
./launchd/launchd_ctl.sh install
./launchd/launchd_ctl.sh start
./launchd/launchd_ctl.sh stop
./launchd/launchd_ctl.sh status
./launchd/launchd_ctl.sh log
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
   - `goslack.py` stores `pane_id` and resolves the current pane target at runtime, so window number changes won’t cause misrouting.
   - If the target pane is already occupied, run `python goslack.py --add 1:2.0` from another pane to register it by tmux target.
     - Optional: add `--channel <NAME>` to override the channel name (no fallback).

### 3. Run the bridge

```bash
source venv/bin/activate
python slack_tmux_bridge.py
```

- Set `LOG_LEVEL=DEBUG` to capture Bolt/Socket Mode state and health logs.

### 4. Slack operations

1. Send a message to the configured channel.
   - Text requires pressing the “Execute (Enter)” button that appears in the thread; after Enter the bridge polls until output stabilizes and posts a snapshot (timeout offers a continue button).
   - Numeric-only messages send automatically.
   - `text == "/sessions"` (or `\/sessions`) shows connected channel names and directories.
   - `text == "/dir"` (or `\/dir`) shows the connected directory for the channel.
   - `text == "/now"` (or `\/now`) polls for pane changes and replies after the output stops changing; if it keeps changing for `NOW_WATCH_TIMEOUT_SEC`, it posts a timeout message with a “continue watch” button.
   - `text == "/ctlc"` (or `\/ctlc`) sends Ctrl+C to the connected tmux pane.
   - If the saved pane target differs from the current pane resolved via `pane_id`, the bridge prompts to confirm updating the connection before running.
2. The bridge posts a snapshot when output stabilizes; the AI agent still replies in the thread using the appended instruction.

### 5. Health monitoring

- `_maintenance_worker` prunes prompt cache using `PROMPT_CACHE_TTL_SEC`.
- `_maintenance_worker` also checks for duplicate pane mappings and disconnects the redundant channel with a notice.
- `_event_health_worker` watches for `EVENT_HEALTH_TIMEOUT` seconds of no events and either logs, exits, restarts, or notifies channels.
- Set `EVENT_HEALTH_NOTIFY=1` to post warnings per channel when they go silent; `EVENT_HEALTH_NOTIFY_COOLDOWN_SEC` throttles repeats.
- Restart actions respect `EVENT_HEALTH_RESTART_COOLDOWN_SEC` to avoid rapid loops.
- Set `CHANNEL_IDLE_NOTIFY_SEC` to post periodic “idle” pings per channel.

## Deployment tiers

1. **Minimal**: Run `slack_tmux_bridge.py` directly after configuring `.env`. Good for trial runs.
2. **Recommended**: Always run `goslack.py` from each tmux pane to keep `active_sessions.json` accurate, then start the bridge. Keeps multiple channels/panes organized.
3. **Daemon**: Use macOS `launchd` for persistent operation and auto-restarts. Continue to manage mappings via `goslack.py`.

## Utilities

- `/sessions`: Slack command that posts a list of channel names and connected directories.
- `/dir`: Slack command that returns the connected directory.
- `/now`: Slack command that waits until pane output stabilizes, then posts the capture (timeout offers a continue button).
- `/ctlc`: Slack command that sends Ctrl+C to the connected tmux pane.
- `goslack.py`: Registers the current tmux pane with the target channel, cleans up duplicates, and supports `list`/`rm` (numbered), `--add`, and optional `--channel` override for session maintenance.

## Tips

### Wrapper with automatic unmap on exit (example)

If you launch Gemini from a wrapper, you can add a `trap` so that when Gemini exits the mapping is removed and Slack is notified. The example below shows only the essential parts; add your own pre-checks if needed.

```bash
gemini() {
  goslack
  trap '
    if [ -n "$TMUX" ]; then
      pane_id=$(tmux display-message -p "#{pane_id}" 2>/dev/null)
      if [ -n "$pane_id" ]; then
        num=$(python goslack.py list | awk -v pid="$pane_id" "NR>1 && \\$4==pid {print \\$1; exit}")
        if [ -n "$num" ]; then
          python goslack.py rm "$num" --notify "gemini exited, mapping removed."
        fi
      fi
    fi
  ' RETURN
  command gemini "$@"
}
```

You can apply the same pattern to Codex:

```bash
codex() {
  goslack
  trap '
    if [ -n "$TMUX" ]; then
      pane_id=$(tmux display-message -p "#{pane_id}" 2>/dev/null)
      if [ -n "$pane_id" ]; then
        num=$(python goslack.py list | awk -v pid="$pane_id" "NR>1 && \\$4==pid {print \\$1; exit}")
        if [ -n "$num" ]; then
          python goslack.py rm "$num" --notify "codex exited, mapping removed."
        fi
      fi
    fi
  ' RETURN
  command codex "$@"
}
```

### Codex CLI notify -> Slack

Codex CLI can run an external program when a turn completes. Configure it to call `slack_tmux_bridge.py notify`; the bridge polling (`/now`) remains unchanged.

`~/.codex/config.toml`:

```toml
[notify]
command = ["python", "/Users/you/WORKSPACE/slack_tmux_bridge/slack_tmux_bridge.py", "notify"]
```

Codex passes one JSON argument to `notify` with keys like:
- `thread-id`
- `turn-id`
- `input-messages`
- `last-assistant-message`

`slack_tmux_bridge.py notify` normalizes payload keys before forwarding to `slack_tmux_bridge` ingress using `NOTIFY_INGRESS_TRANSPORT` (`http` or `uds`).
- Normalization rules:
  - if `channel_id` is missing and `channel-id` is present, map `channel-id` to `channel_id`
  - if `pane_id` is missing and `pane-id` is present, map `pane-id` to `pane_id`
  - if `thread_ts` is missing and `thread-id` is present, map `thread-id` to `thread_ts`
- Existing snake_case keys are prioritized (no overwrite).
The bridge is responsible for destination resolution and final Slack posting.

### Notify ingress on slack_tmux_bridge

You can enable a local notify receiver on the bridge itself:

- `NOTIFY_INGRESS_ENABLED=1`
- `NOTIFY_INGRESS_TRANSPORT=http` with `NOTIFY_HTTP_HOST=127.0.0.1` (localhost-only) and `NOTIFY_HTTP_PORT` / `NOTIFY_HTTP_PATH`
- or `NOTIFY_INGRESS_TRANSPORT=uds` with `NOTIFY_UDS_PATH` / `NOTIFY_UDS_MODE`
- `NOTIFY_FORWARD_TIMEOUT_SEC` controls timeout (seconds) for `slack_tmux_bridge.py notify` forwarding requests

Security controls:

- payload size limit: `NOTIFY_MAX_PAYLOAD_BYTES`
- rate limit: `NOTIFY_RATE_LIMIT_COUNT` per `NOTIFY_RATE_LIMIT_WINDOW_SEC`

Delivery reliability:

- accepted notify payloads are persisted to `tmp/notify_delivery_queue.json`
- failed Slack posts are retried with backoff (`NOTIFY_RETRY_*`)
- expired queue items are dropped by `NOTIFY_QUEUE_TTL_SEC`
- pending queue items are replayed on startup by the background worker
- logs include delivery failures and last error details

Payload must be a JSON object and must include either:

- `channel_id` (with optional `thread_ts`)
- or `pane_id`
  - `channel_id` is resolved from `active_sessions.json` when omitted.
  - `thread_ts` is resolved from payload first, then `tmp/notify_context.json`.
  - if `thread_ts` is still unavailable, the bridge posts to the channel (non-thread reply).

The message body is taken from `last-assistant-message`.

### EXECUTE_RESULT_MODE details

- `poll`: bridge posts tmux snapshot when output stabilizes.
- `notify`: bridge skips poll watch and expects notify delivery path.
- `both`: notify is preferred; if notify is not observed for the same `pane_id/thread_ts`, poll snapshot is posted as fallback.

Duplicate prevention uses a shared key space (`pane_id/thread_ts/turn-id`) in `tmp/notify_delivery_dedupe.json`.

Example (`/sessions` output):

```
- ai-studio-01 → /Users/you/WORKSPACE/ai-studio-01
- project-x → /Users/you/WORKSPACE/project-x
```

Example (`/dir` output):

```
📁 接続中のディレクトリ: /Users/you/WORKSPACE/project-x
```
