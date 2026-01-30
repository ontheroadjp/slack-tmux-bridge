import os
import subprocess
import time
import threading
import re
import sys
import json
import logging
import atexit
import tempfile
from datetime import datetime

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

# =====================
# env
# =====================
load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

# =====================
# Paths
# =====================
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
ACTIVE_SESSIONS_FILE = os.path.join(BASE_DIR, "active_sessions.json")
ENTER_SCRIPT = os.path.join(BASE_DIR, "send_enter.sh")
TMP_DIR = os.path.join(BASE_DIR, "tmp")
PID_FILE = os.path.join(TMP_DIR, "slack_tmux_bridge.pid")

# Command filtering (comma-separated patterns; use "all" to match everything)
COMMAND_ALLOWLIST = os.environ.get("COMMAND_ALLOWLIST", "all")
COMMAND_DENYLIST = os.environ.get("COMMAND_DENYLIST", "")

# Output diff mode: "replace" (current behavior) or "suffix"
OUTPUT_DIFF_MODE = os.environ.get("OUTPUT_DIFF_MODE", "replace").lower()

# Healthcheck & cleanup
EVENT_HEALTH_TIMEOUT = int(os.environ.get("EVENT_HEALTH_TIMEOUT", "600"))
EVENT_HEALTH_ACTION = os.environ.get("EVENT_HEALTH_ACTION", "log").lower()  # log | exit | restart
EVENT_HEALTH_RESTART_COOLDOWN_SEC = int(os.environ.get("EVENT_HEALTH_RESTART_COOLDOWN_SEC", "300"))
EVENT_HEALTH_NOTIFY = os.environ.get("EVENT_HEALTH_NOTIFY", "0") == "1"
EVENT_HEALTH_NOTIFY_COOLDOWN_SEC = int(os.environ.get("EVENT_HEALTH_NOTIFY_COOLDOWN_SEC", "600"))
PROMPT_CACHE_TTL_SEC = int(os.environ.get("PROMPT_CACHE_TTL_SEC", "3600"))
SNAPSHOT_TTL_SEC = int(os.environ.get("SNAPSHOT_TTL_SEC", "86400"))
CHANNEL_IDLE_NOTIFY_SEC = int(os.environ.get("CHANNEL_IDLE_NOTIFY_SEC", "1800"))
CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC = int(os.environ.get("CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC", "1800"))

# =====================
# logging & utility
# =====================
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def configure_logging():
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # Slack SDK/Bolt logs connection status for Socket Mode here.
    logging.getLogger("slack_bolt").setLevel(level)
    logging.getLogger("slack_sdk").setLevel(level)
    logging.getLogger("slack_sdk.socket_mode").setLevel(level)

def ensure_single_instance():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                pid_str = f.read().strip()
            if pid_str:
                pid = int(pid_str)
                # Check if process is alive
                os.kill(pid, 0)
                log(f"Another instance is already running (pid={pid}). Exiting.")
                sys.exit(1)
        except ProcessLookupError:
            # Stale PID file
            pass
        except Exception as e:
            log(f"PID check failed: {e}")
            sys.exit(1)

    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    def _cleanup_pid():
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception:
            pass

    atexit.register(_cleanup_pid)

def _parse_patterns(value: str):
    if value is None:
        return []
    value = value.strip()
    if not value:
        return []
    if value.lower() == "all":
        return ["__ALL__"]
    return [v.strip() for v in value.split(",") if v.strip()]

def _match_any(patterns, text: str) -> bool:
    for pat in patterns:
        if pat == "__ALL__":
            return True
        # Regex pattern if wrapped with /.../
        if len(pat) >= 2 and pat.startswith("/") and pat.endswith("/"):
            try:
                if re.search(pat[1:-1], text):
                    return True
            except re.error:
                continue
        else:
            if pat in text:
                return True
    return False

def is_command_allowed(text: str) -> (bool, str):
    allowlist = _parse_patterns(COMMAND_ALLOWLIST)
    denylist = _parse_patterns(COMMAND_DENYLIST)

    # Default denylist if none provided: block standalone rm (same as previous behavior)
    if not denylist:
        denylist = [r"/(?<!\\)\brm\b/"]

    if _match_any(denylist, text):
        return False, "⚠️ 危険なコマンドとしてブロックされました。"

    if _match_any(allowlist, text):
        return True, ""

    # If allowlist is set and doesn't match, block
    if allowlist and "__ALL__" not in allowlist:
        return False, "⚠️ 許可されたコマンドに一致しないためブロックされました。"

    return True, ""

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)

def get_target_pane(channel_id: str) -> str:
    """チャンネルIDに対応する tmux target を取得する。未接続なら None"""
    if not os.path.exists(ACTIVE_SESSIONS_FILE):
        return None
    try:
        data = _load_active_sessions()
        value = data.get(channel_id)
        return _normalize_tmux_target(value)
    except Exception as e:
        log(f"Error reading active sessions: {e}")
        return None

def get_target_dir(channel_id: str) -> str:
    """チャンネルIDに対応する接続ディレクトリを取得する。未接続なら None"""
    if not os.path.exists(ACTIVE_SESSIONS_FILE):
        return None
    try:
        data = _load_active_sessions()
        value = data.get(channel_id)
        if isinstance(value, dict):
            return value.get("dir")
        return None
    except Exception as e:
        log(f"Error reading active sessions: {e}")
        return None

def _normalize_tmux_target(value):
    if isinstance(value, dict):
        return value.get("pane")
    return value

# =====================
# Slack App
# =====================
logger = logging.getLogger("slack_tmux_bridge")
app = App(token=SLACK_BOT_TOKEN, logger=logger)

def _post_message(channel_id: str, text: str, thread_ts: str = None, blocks=None):
    try:
        kwargs = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        if blocks:
            kwargs["blocks"] = blocks
        app.client.chat_postMessage(**kwargs)
    except Exception as e:
        log(f"⚠️ Slack post failed: {e}")

# =====================
# Slack: inbound logging
# =====================
@app.middleware  # runs on every incoming request
def log_incoming_payload(body, next):
    global LAST_EVENT_TS
    LAST_EVENT_TS = time.time()
    body_type = body.get("type")
    if body_type == "event_callback":
        event = body.get("event", {})
        event_type = event.get("type")
        subtype = event.get("subtype")
        channel = event.get("channel")
        user = event.get("user")
        text_present = bool(event.get("text"))
        if channel:
            LAST_EVENT_TS_BY_CHANNEL[channel] = time.time()
        log(f"EVENT IN: type={event_type} subtype={subtype} channel={channel} user={user} text={text_present}")
    else:
        log(f"PAYLOAD IN: type={body_type}")
    return next()

# =====================
# tmux helpers
# =====================
def pre_clear_tmux(tmux_target: str):
    """実行前に画面と履歴をクリーンにする (tmuxの機能のみを使用)"""
    log(f"PRE-EXEC CLEAR: Clearing tmux history and screen (C-l) on {tmux_target}")
    # 1. 履歴をクリア
    subprocess.run(["tmux", "clear-history", "-t", tmux_target])
    # 2. 画面をクリア (Ctrl+L)
    subprocess.run(["tmux", "send-keys", "-t", tmux_target, "C-l"])
    # 反映待ち
    time.sleep(0.3)

def send_text_to_tmux(tmux_target: str, text: str, thread_ts: str = None, channel_id: str = None):
    cmd = ["tmux", "send-keys", "-t", tmux_target, text]
    log("EXEC TEXT: " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err_msg = f"⚠️ Error in send_text_to_tmux:\n{r.stderr}"
        log(err_msg)
        if thread_ts and channel_id:
            _post_message(channel_id, err_msg, thread_ts=thread_ts)

def send_enter(tmux_target: str, thread_ts: str = None, channel_id: str = None):
    # 実際のEnter送信
    cmd = ["sh", ENTER_SCRIPT, tmux_target]
    log("EXEC ENTER: " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err_msg = f"⚠️ Error in send_enter:\n{r.stderr}"
        log(err_msg)
        if thread_ts and channel_id:
            _post_message(channel_id, err_msg, thread_ts=thread_ts)

def capture_tmux(tmux_target: str, lines=None):
    args = ["-p", "-S", "-1000"] if lines else ["-p"]
    cmd = ["tmux", "capture-pane", "-t", tmux_target] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout or ""

# =====================
# snapshot helpers
# =====================
PROMPT_CACHE = {}  # thread_ts -> last_prompt
PROMPT_CACHE_TS = {}  # thread_ts -> last_seen_epoch
LAST_EVENT_TS = time.time()
LAST_EVENT_TS_BY_CHANNEL = {}
LAST_HEALTH_NOTIFY_TS_BY_CHANNEL = {}
LAST_IDLE_NOTIFY_TS_BY_CHANNEL = {}
LAST_RESTART_TS = 0.0
ACTIVE_MONITORS_BY_CHANNEL = {}
ACTIVE_MONITORS_BY_THREAD = {}
ACTIVE_MONITOR_LOCK = threading.Lock()

def get_snapshot_path(thread_ts: str) -> str:
    return os.path.join(TMP_DIR, f"snapshot_{thread_ts}.txt")

def save_snapshot(thread_ts: str, content: str, prompt: str = ""):
    path = get_snapshot_path(thread_ts)
    if not os.path.exists(TMP_DIR):
        os.makedirs(TMP_DIR)
    # JSON形式で保存してプロンプトも保持する
    import json
    data = {"content": content, "prompt": prompt}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    log(f"Snapshot saved: {path}")

def load_snapshot(thread_ts: str):
    path = get_snapshot_path(thread_ts)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            import json
            data = json.load(f)
            return data.get("content", ""), data.get("prompt", "")
    return "", ""

def delete_snapshot(thread_ts: str):
    path = get_snapshot_path(thread_ts)
    if os.path.exists(path):
        os.remove(path)
        log(f"Snapshot deleted: {path}")

def _atomic_write_json(path: str, data):
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

def _load_active_sessions():
    if not os.path.exists(ACTIVE_SESSIONS_FILE):
        return {}
    try:
        with open(ACTIVE_SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Error reading active sessions: {e}")
        return {}

def _format_age(seconds: float) -> str:
    if seconds < 0:
        return "0s"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"

def _build_sessions_output():
    sessions = _load_active_sessions()
    if not sessions:
        return "(no active sessions)"

    lines = []
    for channel_id, value in sessions.items():
        if isinstance(value, dict):
            target_dir = value.get("dir") or "-"
            channel_name = value.get("name") or channel_id
        else:
            target_dir = "-"
            channel_name = channel_id
        lines.append(f"- {channel_name} → {target_dir}")
    return "\n".join(lines)

def _extract_new_output(initial_clean: str, current_clean: str) -> str:
    if OUTPUT_DIFF_MODE == "suffix":
        if current_clean.startswith(initial_clean):
            return current_clean[len(initial_clean):].strip()
        idx = current_clean.rfind(initial_clean)
        if idx != -1:
            return current_clean[idx + len(initial_clean):].strip()
        return current_clean.strip()
    # default: replace (current behavior)
    return current_clean.replace(initial_clean, "").strip()

def _cleanup_prompt_cache(thread_ts: str):
    if thread_ts in PROMPT_CACHE:
        del PROMPT_CACHE[thread_ts]
    if thread_ts in PROMPT_CACHE_TS:
        del PROMPT_CACHE_TS[thread_ts]

def _cleanup_snapshots():
    if not os.path.exists(TMP_DIR):
        return
    now = time.time()
    for name in os.listdir(TMP_DIR):
        if not name.startswith("snapshot_") or not name.endswith(".txt"):
            continue
        path = os.path.join(TMP_DIR, name)
        try:
            if now - os.path.getmtime(path) > SNAPSHOT_TTL_SEC:
                os.remove(path)
        except Exception:
            continue

def _select_primary_channel(entries):
    def _score(entry):
        channel_id, value = entry
        last_ts = LAST_EVENT_TS_BY_CHANNEL.get(channel_id, 0)
        name = value.get("name") if isinstance(value, dict) else None
        return (last_ts, 1 if name else 0, channel_id)
    return max(entries, key=_score)

def _dedupe_active_sessions():
    sessions = _load_active_sessions()
    if not sessions:
        return

    pane_map = {}
    for channel_id, value in sessions.items():
        pane = _normalize_tmux_target(value)
        if not pane:
            continue
        pane_map.setdefault(pane, []).append((channel_id, value))

    updated = False
    for pane, entries in pane_map.items():
        if len(entries) <= 1:
            continue
        keep_channel_id, keep_value = _select_primary_channel(entries)
        keep_name = keep_value.get("name") if isinstance(keep_value, dict) else None
        target_label = f"#{keep_name}" if keep_name else keep_channel_id

        for channel_id, _ in entries:
            if channel_id == keep_channel_id:
                continue
            sessions.pop(channel_id, None)
            updated = True
            _post_message(
                channel_id,
                f"⚠️ 同じ tmux ペインが他チャンネルと重複していたため、このチャンネルの接続を解除しました。今後は {target_label} で通信してください。"
            )

    if updated:
        _atomic_write_json(ACTIVE_SESSIONS_FILE, sessions)

def _maintenance_worker():
    while True:
        time.sleep(60)
        now = time.time()
        # prune prompt cache
        for key, ts in list(PROMPT_CACHE_TS.items()):
            if now - ts > PROMPT_CACHE_TTL_SEC:
                _cleanup_prompt_cache(key)
        # prune old snapshots
        _cleanup_snapshots()
        # prune duplicate channel mappings
        _dedupe_active_sessions()

def _event_health_worker():
    global LAST_RESTART_TS
    while True:
        time.sleep(5)
        if EVENT_HEALTH_TIMEOUT <= 0:
            continue
        now = time.time()
        if now - LAST_EVENT_TS > EVENT_HEALTH_TIMEOUT:
            log(f"EVENT HEALTHCHECK: No events for {EVENT_HEALTH_TIMEOUT}s")
            if EVENT_HEALTH_ACTION == "exit":
                os._exit(1)
            if EVENT_HEALTH_ACTION == "restart":
                if now - LAST_RESTART_TS < EVENT_HEALTH_RESTART_COOLDOWN_SEC:
                    continue
                LAST_RESTART_TS = now
                log("EVENT HEALTHCHECK: restarting process")
                os.execv(sys.executable, [sys.executable] + sys.argv)

        if EVENT_HEALTH_NOTIFY:
            sessions = _load_active_sessions()
            for channel_id in sessions.keys():
                last_ts = LAST_EVENT_TS_BY_CHANNEL.get(channel_id, 0)
                if last_ts == 0 or now - last_ts <= EVENT_HEALTH_TIMEOUT:
                    continue
                last_notify = LAST_HEALTH_NOTIFY_TS_BY_CHANNEL.get(channel_id, 0)
                if now - last_notify < EVENT_HEALTH_NOTIFY_COOLDOWN_SEC:
                    continue
                LAST_HEALTH_NOTIFY_TS_BY_CHANNEL[channel_id] = now
                _post_message(
                    channel_id,
                    f"⚠️ {EVENT_HEALTH_TIMEOUT}秒以上イベントを受信していません。接続を確認してください。"
                )

        if CHANNEL_IDLE_NOTIFY_SEC > 0:
            sessions = _load_active_sessions()
            for channel_id in sessions.keys():
                last_ts = LAST_EVENT_TS_BY_CHANNEL.get(channel_id, 0)
                if last_ts == 0 or now - last_ts < CHANNEL_IDLE_NOTIFY_SEC:
                    continue
                last_notify = LAST_IDLE_NOTIFY_TS_BY_CHANNEL.get(channel_id, 0)
                if now - last_notify < CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC:
                    continue
                LAST_IDLE_NOTIFY_TS_BY_CHANNEL[channel_id] = now
                _post_message(
                    channel_id,
                    "📡 こちらは待機中です。必要があれば声をかけてください。"
                )

# =====================
# Monitoring Worker
# =====================
def monitor_and_reply(thread_ts, channel_id, tmux_target, initial_content, prompt=""):
    log(f"Starting monitor thread for {thread_ts} (Target: {tmux_target}, Prompt: {prompt})...")
    with ACTIVE_MONITOR_LOCK:
        ACTIVE_MONITORS_BY_THREAD[thread_ts] = True
        ACTIVE_MONITORS_BY_CHANNEL[channel_id] = ACTIVE_MONITORS_BY_CHANNEL.get(channel_id, 0) + 1
    
    # スナップショットを保存しておく（継続用）
    save_snapshot(thread_ts, initial_content, prompt)
    
    # 比較・処理用にANSIを除去した状態を使う
    initial_clean = strip_ansi(initial_content)
    last_clean = strip_ansi(capture_tmux(tmux_target, lines=True))
    
    stable_count = 0
    max_wait_cycles = 60
    try:
        for _ in range(max_wait_cycles):
            time.sleep(1.0)
            
            raw_content = capture_tmux(tmux_target, lines=True)
            current_clean = strip_ansi(raw_content)
            
            if current_clean == last_clean:
                stable_count += 1
            else:
                stable_count = 0
                last_clean = current_clean
            
            # 変化があったか？
            is_changed = (current_clean.strip() != initial_clean.strip())
            
            # 1. Allow once を検知した場合、または出力が安定した場合に応答
            last_lines = "\n".join(current_clean.strip().splitlines()[-10:])
            
            if (is_changed and "1. Allow once" in last_lines) or stable_count >= 3:
                log("Output stabilized or permission prompt detected. Sending to Slack.")
                
                # --- 回答抽出ロジックの厳格化 ---
                # 実行開始時の画面を削った後の新テキスト（変化が無い場合は現時点の画面を返す）
                if is_changed:
                    msg_text = _extract_new_output(initial_clean, current_clean)
                else:
                    msg_text = current_clean.strip()
                    
                # マーカー ("> [prompt]") を探し、それより前のスプラッシュ等はすべて捨てる
                found_marker = False
                if prompt:
                    marker = f"> {prompt}"
                    marker_idx = msg_text.find(marker)
                    if marker_idx == -1:
                        marker_idx = msg_text.find(f">{prompt}")
                    
                    if marker_idx != -1:
                        msg_text = msg_text[marker_idx:].strip()
                        found_marker = True
                
                # マーカーが見つからない場合でも、最古の ">" 行を探してそれ以前を捨てる
                if not found_marker:
                    lines = msg_text.splitlines()
                    for i, line in enumerate(lines):
                        if line.strip().startswith(">"):
                            msg_text = "\n".join(lines[i:]).strip()
                            found_marker = True
                            break

                # 整形: "> プロンプト" の後ろに空行を入れる
                if msg_text.startswith(">"):
                    split_idx = msg_text.find("\n")
                    if split_idx != -1:
                        header = msg_text[:split_idx]
                        body = msg_text[split_idx:].strip()
                        msg_text = f"{header}\n\n{body}"

                if not msg_text:
                    msg_text = "(No new output detected)"

                # 長文対策: 3000文字を超える場合は分割して送信
                chunk_size = 3000
                if len(msg_text) <= chunk_size:
                    # スマホ対策：長い区切り線を短縮
                    msg_text = re.sub(r"(-{20,})", "-" * 20, msg_text)
                    msg_text = re.sub(r"(={20,})", "=" * 20, msg_text)
                    msg_text = re.sub(r"(─{20,})", "─" * 20, msg_text)
                    msg_text = re.sub(r"(═{20,})", "═" * 20, msg_text)
                    
                    _post_message(
                        channel_id,
                        "```\n" + msg_text + "\n```",
                        thread_ts=thread_ts
                    )
                else:
                    # 分割送信
                    for i in range(0, len(msg_text), chunk_size):
                        chunk = msg_text[i:i + chunk_size]
                        # 区切り線短縮
                        chunk = re.sub(r"(-{20,})", "-" * 20, chunk)
                        chunk = re.sub(r"(={20,})", "=" * 20, chunk)
                        chunk = re.sub(r"(─{20,})", "─" * 20, chunk)
                        chunk = re.sub(r"(═{20,})", "═" * 20, chunk)
                        
                        _post_message(
                            channel_id,
                            "```\n" + chunk + "\n```",
                            thread_ts=thread_ts
                        )
                
                # 成功したのでスナップショット削除
                delete_snapshot(thread_ts)
                _cleanup_prompt_cache(thread_ts)
                return

        log("Monitor timed out.")
        
        # タイムアウト時は途中経過を送らず、継続確認ボタンのみを表示する
        _post_message(
            channel_id,
            "⚠️ タイムアウトしました（処理継続中）。",
            thread_ts=thread_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "⚠️ *タイムアウトしました（60秒経過）。*\nまだ処理中の可能性があります。監視を継続する場合は下のボタンを押してください。"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "🔄 監視を継続"
                            },
                            "action_id": "continue_monitor"
                        }
                    ]
                }
            ]
        )
        # タイムアウト時はスナップショットを削除せず残す
        _cleanup_prompt_cache(thread_ts)
    finally:
        with ACTIVE_MONITOR_LOCK:
            ACTIVE_MONITORS_BY_THREAD.pop(thread_ts, None)
            ACTIVE_MONITORS_BY_CHANNEL[channel_id] = max(
                0, ACTIVE_MONITORS_BY_CHANNEL.get(channel_id, 1) - 1
            )

# =====================
# Slack: message → 文字入力 + 操作ボタン表示（スレッド）
# =====================
def _get_thread_ts_from_message(message):
    return message.get("thread_ts") or message.get("ts")

def _normalize_slash_command_text(text: str) -> str:
    if not text:
        return text
    # Strip zero-width characters that can appear in Slack messages
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    return text.strip()

def _is_command(text: str, command: str) -> bool:
    text = _normalize_slash_command_text(text)
    return re.match(rf"^{re.escape(command)}(\s|$)", text) is not None

def _handle_bye_command(channel_id: str, thread_ts: str) -> bool:
    try:
        if os.path.exists(ACTIVE_SESSIONS_FILE):
            with open(ACTIVE_SESSIONS_FILE, "r", encoding="utf-8") as f:
                sessions = json.load(f)

            if channel_id in sessions:
                del sessions[channel_id]
                _atomic_write_json(ACTIVE_SESSIONS_FILE, sessions)

                log(f"Disconnected channel {channel_id}")
                _post_message(
                    channel_id,
                    "🔌 このチャンネルの接続を解除しました。",
                    thread_ts=thread_ts
                )
                return True

            _post_message(
                channel_id,
                "⚠️ このチャンネルは既に接続されていません。",
                thread_ts=thread_ts
            )
            return True
    except Exception as e:
        log(f"Error disconnecting: {e}")
        _post_message(
            channel_id,
            f"⚠️ 切断中にエラーが発生しました: {e}",
            thread_ts=thread_ts
        )
        return True
    return False

def _handle_dir_command(channel_id: str, thread_ts: str) -> bool:
    target_dir = get_target_dir(channel_id)
    if target_dir:
        _post_message(
            channel_id,
            f"📁 接続中のディレクトリ: {target_dir}",
            thread_ts=thread_ts
        )
    else:
        _post_message(
            channel_id,
            "⚠️ 接続中のディレクトリ情報が見つかりません。",
            thread_ts=thread_ts
        )
    return True

def _handle_now_command(channel_id: str, thread_ts: str, tmux_target: str) -> bool:
    if not tmux_target:
        _post_message(channel_id, "⚠️ Error: No active tmux session.", thread_ts=thread_ts)
        return True

    with ACTIVE_MONITOR_LOCK:
        if ACTIVE_MONITORS_BY_CHANNEL.get(channel_id, 0) > 0:
            _post_message(
                channel_id,
                "⏳ 処理中です。少々お待ちください。",
                thread_ts=thread_ts
            )

    initial_content, prompt = load_snapshot(thread_ts)
    if not initial_content:
        log(f"Snapshot not found for {thread_ts}, using current screen as initial.")
        initial_content = capture_tmux(tmux_target, lines=True)
        prompt = ""

    _post_message(
        channel_id,
        "🔄 現在の状態を取得しています...",
        thread_ts=thread_ts
    )

    threading.Thread(
        target=monitor_and_reply,
        args=(thread_ts, channel_id, tmux_target, initial_content, prompt),
        daemon=True
    ).start()
    return True

def _handle_command_menu(channel_id: str, thread_ts: str) -> bool:
    _post_message(
        channel_id,
        "⚡ スラッシュコマンドメニュー:",
        thread_ts=thread_ts,
        blocks=get_command_menu_blocks()
    )
    return True

def _handle_numeric_message(channel_id: str, thread_ts: str, tmux_target: str, text: str):
    # ① プリクリア
    pre_clear_tmux(tmux_target)

    # ② 文字送信
    send_text_to_tmux(tmux_target, text, thread_ts=thread_ts, channel_id=channel_id)

    # ③ 通知
    _post_message(
        channel_id,
        "🔢 数字入力を検知: 自動実行を開始します...",
        thread_ts=thread_ts
    )

    # ④ 状態保存 -> Enter送信 & 監視開始
    initial_content = capture_tmux(tmux_target, lines=True)
    send_enter(tmux_target, thread_ts=thread_ts, channel_id=channel_id)

    threading.Thread(
        target=monitor_and_reply,
        args=(thread_ts, channel_id, tmux_target, initial_content, text),
        daemon=True
    ).start()

def _handle_text_message(channel_id: str, thread_ts: str, tmux_target: str, text: str):
    # ① 文字だけ tmux に送る
    send_text_to_tmux(tmux_target, text, thread_ts=thread_ts, channel_id=channel_id)

    # ② 同じメッセージのスレッドに操作ボタンを出す
    _post_message(
        channel_id,
        "操作を選んでください（実行すると自動で監視・応答します）",
        thread_ts=thread_ts,
        blocks=[
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "▶︎ 実行（Enter）"
                        },
                        "action_id": "send_enter"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "👀 Geminiを見る"
                        },
                        "action_id": "show_gemini"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🗑️ プロンプト削除"
                        },
                        "style": "danger",
                        "action_id": "delete_prompt"
                    }
                ]
            }
        ]
    )

@app.event("message")
def handle_message(event, logger):
    channel_id = event.get("channel")
    if not channel_id:
        return

    # 1. Extract text and check validity
    text = ""
    if (
        event.get("user")
        and not event.get("bot_id")
        and event.get("text")
    ):
        text = event["text"].strip()
    
    if not text:
        return

    log(f"TEXT RAW: {repr(text)}")
    log(f"TEXT NORM: {repr(_normalize_slash_command_text(text))}")

    # Slackでスラッシュコマンドをエスケープした際（例: \/quit）にバックスラッシュを削除
    # ただし、 \rm や \ls のようなシェル用エスケープは維持したいので、
    # 次の文字が / の場合のみ削除する
    if text.startswith("\\/"):
        text = text[1:]

    thread_ts = _get_thread_ts_from_message(event)

    # =====================
    # Command: /bye (Connection cleanup)
    # Works even if not connected (to clean up state)
    # =====================
    if _is_command(text, "/bye"):
        if _handle_bye_command(channel_id, thread_ts):
            return
    
    # =====================
    # Command: /dir (Show connected directory)
    # =====================
    if _is_command(text, "/dir"):
        _handle_dir_command(channel_id, thread_ts)
        return
    if _is_command(text, "/now"):
        tmux_target = _normalize_tmux_target(get_target_pane(channel_id))
        _handle_now_command(channel_id, thread_ts, tmux_target)
        return
    if _is_command(text, "/sessions"):
        output = _build_sessions_output()
        _post_message(channel_id, output, thread_ts=thread_ts)
        return

    # =====================
    # Active Session Check
    # =====================
    # Check if this channel has an active tmux session
    tmux_target = _normalize_tmux_target(get_target_pane(channel_id))
    if not tmux_target:
        # Ignore messages from unconfigured channels
        return

    log(f"SLACK MESSAGE: {text} (Channel: {channel_id} -> Tmux: {tmux_target})")

    # プロンプトをキャッシュに保存（ボタン実行時に使用するため）
    PROMPT_CACHE[event["ts"]] = text
    PROMPT_CACHE_TS[event["ts"]] = time.time()

    # 「スラッシュコマンド」というメッセージを受け取った場合は、ボタンメニューを表示
    if text == "スラッシュコマンド":
        _handle_command_menu(channel_id, thread_ts)
        return

    # =====================
    # Command filter (allowlist/denylist)
    # =====================
    allowed, reason = is_command_allowed(text)
    if not allowed:
        log(f"BLOCKED COMMAND: {text}")
        _post_message(channel_id, reason, thread_ts=thread_ts)
        return

    # 数字だけの場合は即時実行
    if text.isdigit():
        _handle_numeric_message(channel_id, thread_ts, tmux_target, text)
        return

    _handle_text_message(channel_id, thread_ts, tmux_target, text)

# =====================
# Slack: ▶︎ 実行（Enter） → 自動監視開始
# =====================
@app.action("send_enter")
def handle_send_enter(ack, body):
    ack()
    log("BUTTON CLICKED: send_enter")
    
    channel_id = body["channel"]["id"]
    tmux_target = get_target_pane(channel_id)
    if not tmux_target:
        _post_message(channel_id, "⚠️ Error: No active tmux session for this channel. Run `goslack` in your terminal.")
        return

    # スレッドの親TSを取得
    thread_ts = _get_thread_ts_from_message(body["message"])

    # プロンプトをキャッシュから取得
    prompt = PROMPT_CACHE.get(thread_ts, "")

    # 通知
    _post_message(
        channel_id,
        "🚀 実行を開始しました（監視中）...",
        thread_ts=thread_ts
    )

    # プリクリアを実行
    pre_clear_tmux(tmux_target)

    # 文字列を再送してから Enter を送信する
    if prompt:
        send_text_to_tmux(tmux_target, prompt, thread_ts=thread_ts, channel_id=channel_id)

    # 現在の画面状態を保存 (クリーンな状態)
    initial_content = capture_tmux(tmux_target, lines=True)

    # Enterを送る
    send_enter(tmux_target, thread_ts=thread_ts, channel_id=channel_id)

    # 完了監視スレッドを開始
    threading.Thread(
        target=monitor_and_reply,
        args=(thread_ts, channel_id, tmux_target, initial_content, prompt),
        daemon=True
    ).start()

# =====================
# Slack: 🔄 監視を継続 → 再監視開始
# =====================
@app.action("continue_monitor")
def handle_continue_monitor(ack, body):
    ack()
    log("BUTTON CLICKED: continue_monitor")
    
    channel_id = body["channel"]["id"]
    tmux_target = get_target_pane(channel_id)
    if not tmux_target:
        _post_message(channel_id, "⚠️ Error: No active tmux session.")
        return

    thread_ts = _get_thread_ts_from_message(body["message"])
    
    initial_content, prompt = load_snapshot(thread_ts)
    if not initial_content:
        # スナップショットが見つからない場合は現在の画面を基準にする
        log(f"Snapshot not found for {thread_ts}, using current screen as initial.")
        initial_content = capture_tmux(tmux_target, lines=True)
        prompt = ""

    _post_message(
        channel_id,
        "🔄 監視を再開しました...",
        thread_ts=thread_ts
    )

    threading.Thread(
        target=monitor_and_reply,
        args=(thread_ts, channel_id, tmux_target, initial_content, prompt),
        daemon=True
    ).start()

# =====================
# Slack: ⚡ /コマンド → コマンド選択肢を表示
# =====================
def get_command_menu_blocks():
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "実行したいコマンドを選択してください（即時実行されます）:"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Session & History*"}
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/reset"},
                    "value": "/reset",
                    "action_id": "exec_cmd_reset"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/clear"},
                    "value": "/clear",
                    "action_id": "exec_cmd_clear"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/undo"},
                    "value": "/undo",
                    "action_id": "exec_cmd_undo"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/save"},
                    "value": "/save",
                    "action_id": "exec_cmd_save"
                }
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Config & Info*"}
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/model"},
                    "value": "/model",
                    "action_id": "exec_cmd_model"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/system"},
                    "value": "/system",
                    "action_id": "exec_cmd_system"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/help"},
                    "value": "/help",
                    "action_id": "exec_cmd_help"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "/version"},
                    "value": "/version",
                    "action_id": "exec_cmd_version"
                }
            ]
        }
    ]

@app.action("show_commands")
def handle_show_commands(ack, body):
    ack()
    log("BUTTON CLICKED: show_commands")
    
    channel_id = body["channel"]["id"]
    thread_ts = _get_thread_ts_from_message(body["message"])

    _post_message(
        channel_id,
        "実行したいコマンドを選択してください（即時実行されます）:",
        thread_ts=thread_ts,
        blocks=get_command_menu_blocks()
    )

# =====================
# Slack: コマンドボタン押下 → 即時実行
# =====================
@app.action(re.compile("exec_cmd_.*"))
def handle_slash_command(ack, body):
    ack()
    
    channel_id = body["channel"]["id"]
    tmux_target = get_target_pane(channel_id)
    if not tmux_target:
        _post_message(channel_id, "⚠️ Error: No active tmux session.")
        return

    # action_id が何であれ、value にコマンドが入っているのでそれを使う
    cmd_text = body["actions"][0]["value"]
    log(f"COMMAND CLICKED: {cmd_text}")
    
    thread_ts = _get_thread_ts_from_message(body["message"])

    _post_message(
        channel_id,
        f"⚡ コマンド実行: `{cmd_text}`",
        thread_ts=thread_ts
    )

    # 1. プリクリア (既存の入力も C-u の代わりに C-l で実質的に消えるか、C-uを併用)
    subprocess.run(["tmux", "send-keys", "-t", tmux_target, "C-u"]) # 念のため既存行クリア
    pre_clear_tmux(tmux_target)
    
    # 2. コマンド入力
    send_text_to_tmux(tmux_target, cmd_text, thread_ts, channel_id)
    
    # 3. 状態保存 -> Enter & 監視開始
    initial_content = capture_tmux(tmux_target, lines=True)
    send_enter(tmux_target, thread_ts=thread_ts, channel_id=channel_id)
    
    threading.Thread(
        target=monitor_and_reply,
        args=(thread_ts, channel_id, tmux_target, initial_content, cmd_text),
        daemon=True
    ).start()

# =====================
# Slack: 🗑️ プロンプト削除
# =====================
@app.action("delete_prompt")
def handle_delete_prompt(ack, body):
    ack()
    log("BUTTON CLICKED: delete_prompt")
    
    channel_id = body["channel"]["id"]
    tmux_target = get_target_pane(channel_id)
    if not tmux_target:
        return # 静かに無視、あるいはエラー表示

    thread_ts = _get_thread_ts_from_message(body["message"])

    # Ctrl+u を送信して行をクリア
    cmd = ["tmux", "send-keys", "-t", tmux_target, "C-u"]
    subprocess.run(cmd)
    
    _post_message(
        channel_id,
        "🗑️ 入力中のプロンプトを削除しました。",
        thread_ts=thread_ts
    )

# =====================
# Slack: 👀 Geminiを見る（手動確認用）
# =====================
@app.action("show_gemini")
def handle_show_gemini(ack, body):
    ack()
    log("BUTTON CLICKED: show_gemini")
    
    channel_id = body["channel"]["id"]
    tmux_target = get_target_pane(channel_id)
    if not tmux_target:
        _post_message(channel_id, "⚠️ Error: No active tmux session.")
        return

    thread_ts = _get_thread_ts_from_message(body["message"])

    out = capture_tmux(tmux_target).strip()
    if not out:
        out = "(no output)"

    _post_message(
        channel_id,
        "```" + out[-3500:] + "```",
        thread_ts=thread_ts
    )

# =====================
# Slack: /sessions -> show active sessions
# =====================
@app.message(re.compile(r"^/sessions$"))
def handle_sessions_message(message, say):
    output = _build_sessions_output()
    say(text=output)

# =====================
# 起動通知
# =====================
def post_startup_message():
    log("Bot started. Waiting for connections in active_sessions.json")

# =====================
# main
# =====================
if __name__ == "__main__":
    configure_logging()
    log("Slack → tmux bridge (Multi-channel) started")
    # 初期化時に tmp ディレクトリ作成
    if not os.path.exists(TMP_DIR):
        os.makedirs(TMP_DIR)

    ensure_single_instance()

    threading.Thread(target=_maintenance_worker, daemon=True).start()
    threading.Thread(target=_event_health_worker, daemon=True).start()
    
    # active_sessions.json がなければ作成
    if not os.path.exists(ACTIVE_SESSIONS_FILE):
        _atomic_write_json(ACTIVE_SESSIONS_FILE, {})

    SocketModeHandler(app, SLACK_APP_TOKEN).start()
