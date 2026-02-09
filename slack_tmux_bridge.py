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
import socket
import socketserver
import http.server
from datetime import datetime
from collections import deque

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

# =====================
# env
# =====================
load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
TMUX_BIN = os.environ.get("TMUX_BIN", "tmux")

def _tmux_cmd(*args):
    return [TMUX_BIN, *args]

# =====================
# Paths
# =====================
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
ACTIVE_SESSIONS_FILE = os.path.join(BASE_DIR, "active_sessions.json")
ENTER_SCRIPT = os.path.join(BASE_DIR, "send_enter.sh")
TMP_DIR = os.path.join(BASE_DIR, "tmp")
PID_FILE = os.path.join(TMP_DIR, "slack_tmux_bridge.pid")
NOTIFY_CONTEXT_FILE = os.path.join(TMP_DIR, "notify_context.json")
NOTIFY_DEDUPE_FILE = os.path.join(TMP_DIR, "notify_delivery_dedupe.json")
NOTIFY_QUEUE_FILE = os.path.join(TMP_DIR, "notify_delivery_queue.json")

# Command filtering (comma-separated patterns; use "all" to match everything)
COMMAND_ALLOWLIST = os.environ.get("COMMAND_ALLOWLIST", "all")
COMMAND_DENYLIST = os.environ.get("COMMAND_DENYLIST", "")

# Notify ingress (Issue #7 scope: localhost HTTP or Unix Domain Socket)
NOTIFY_INGRESS_ENABLED = os.environ.get("NOTIFY_INGRESS_ENABLED", "0") == "1"
NOTIFY_INGRESS_TRANSPORT = os.environ.get("NOTIFY_INGRESS_TRANSPORT", "http").lower()  # http | uds
if NOTIFY_INGRESS_TRANSPORT not in {"http", "uds"}:
    NOTIFY_INGRESS_TRANSPORT = "http"
NOTIFY_HTTP_HOST = os.environ.get("NOTIFY_HTTP_HOST", "127.0.0.1")
NOTIFY_HTTP_PORT = int(os.environ.get("NOTIFY_HTTP_PORT", "8765"))
NOTIFY_HTTP_PATH = os.environ.get("NOTIFY_HTTP_PATH", "/notify")
NOTIFY_UDS_PATH = os.environ.get("NOTIFY_UDS_PATH", os.path.join(TMP_DIR, "notify_ingress.sock"))
NOTIFY_UDS_MODE = int(os.environ.get("NOTIFY_UDS_MODE", "600"), 8)
NOTIFY_MAX_PAYLOAD_BYTES = int(os.environ.get("NOTIFY_MAX_PAYLOAD_BYTES", "65536"))
NOTIFY_RATE_LIMIT_COUNT = int(os.environ.get("NOTIFY_RATE_LIMIT_COUNT", "30"))
NOTIFY_RATE_LIMIT_WINDOW_SEC = int(os.environ.get("NOTIFY_RATE_LIMIT_WINDOW_SEC", "60"))
NOTIFY_DEDUPE_TTL_SEC = int(os.environ.get("NOTIFY_DEDUPE_TTL_SEC", "900"))
NOTIFY_QUEUE_TTL_SEC = int(os.environ.get("NOTIFY_QUEUE_TTL_SEC", "3600"))
NOTIFY_RETRY_BASE_SEC = float(os.environ.get("NOTIFY_RETRY_BASE_SEC", "2"))
NOTIFY_RETRY_MAX_SEC = float(os.environ.get("NOTIFY_RETRY_MAX_SEC", "60"))
NOTIFY_RETRY_MAX_ATTEMPTS = int(os.environ.get("NOTIFY_RETRY_MAX_ATTEMPTS", "10"))
NOTIFY_RETRY_TICK_SEC = float(os.environ.get("NOTIFY_RETRY_TICK_SEC", "1"))


# Healthcheck & cleanup
EVENT_HEALTH_TIMEOUT = int(os.environ.get("EVENT_HEALTH_TIMEOUT", "600"))
EVENT_HEALTH_ACTION = os.environ.get("EVENT_HEALTH_ACTION", "log").lower()  # log | exit | restart
EVENT_HEALTH_RESTART_COOLDOWN_SEC = int(os.environ.get("EVENT_HEALTH_RESTART_COOLDOWN_SEC", "300"))
EVENT_HEALTH_NOTIFY = os.environ.get("EVENT_HEALTH_NOTIFY", "0") == "1"
EVENT_HEALTH_NOTIFY_COOLDOWN_SEC = int(os.environ.get("EVENT_HEALTH_NOTIFY_COOLDOWN_SEC", "600"))
PROMPT_CACHE_TTL_SEC = int(os.environ.get("PROMPT_CACHE_TTL_SEC", "3600"))
CHANNEL_IDLE_NOTIFY_SEC = int(os.environ.get("CHANNEL_IDLE_NOTIFY_SEC", "1800"))
CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC = int(os.environ.get("CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC", "1800"))
# Permission prompt watch (best-effort capture for approval requests)
PERMISSION_WATCH_SEC = int(os.environ.get("PERMISSION_WATCH_SEC", "120"))
PERMISSION_WATCH_INTERVAL_SEC = float(os.environ.get("PERMISSION_WATCH_INTERVAL_SEC", "2"))
PERMISSION_WATCH_PATTERN = os.environ.get(
    "PERMISSION_WATCH_PATTERN",
    r"(Allow once|Allow always|Approve|Permission|許可|承認)",
)
# /now watch (pane change polling)
NOW_WATCH_INTERVAL_SEC = float(os.environ.get("NOW_WATCH_INTERVAL_SEC", "1"))
NOW_WATCH_IDLE_COUNT = int(os.environ.get("NOW_WATCH_IDLE_COUNT", "3"))
NOW_WATCH_TIMEOUT_SEC = int(os.environ.get("NOW_WATCH_TIMEOUT_SEC", "180"))
EXECUTE_RESULT_MODE = os.environ.get("EXECUTE_RESULT_MODE", "poll").lower()  # poll | notify | both
if EXECUTE_RESULT_MODE not in {"poll", "notify", "both"}:
    EXECUTE_RESULT_MODE = "poll"

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

def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        log(f"Missing required environment variable: {name}")
        sys.exit(1)
    return value

def ensure_required_tokens():
    global SLACK_BOT_TOKEN, SLACK_APP_TOKEN
    SLACK_BOT_TOKEN = _require_env("SLACK_BOT_TOKEN")
    SLACK_APP_TOKEN = _require_env("SLACK_APP_TOKEN")

def _is_loopback_host(value: str) -> bool:
    if not value:
        return False
    try:
        addr = socket.gethostbyname(value)
    except Exception:
        return False
    return addr.startswith("127.") or addr == "::1"

def ensure_single_instance():
    # Guard against manual double-start even if PID file is missing.
    try:
        cmd = ["ps", "-ax", "-o", "pid=,command="]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pid_str, command = line.split(None, 1)
                pid = int(pid_str)
            except ValueError:
                continue
            if pid == os.getpid():
                continue
            if "slack_tmux_bridge.py" in command:
                log(f"Another instance is already running (pid={pid}). Exiting.")
                sys.exit(1)
    except Exception as e:
        log(f"Process scan failed: {e}")

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

def _compile_permission_pattern(value: str):
    try:
        return re.compile(value)
    except re.error:
        return re.compile(r"(Allow once|Allow always|Approve|Permission|許可|承認)")

PERMISSION_WATCH_RE = _compile_permission_pattern(PERMISSION_WATCH_PATTERN)

def get_target_pane(channel_id: str) -> str:
    """チャンネルIDに対応する tmux target を取得する。未接続なら None"""
    if not os.path.exists(ACTIVE_SESSIONS_FILE):
        return None
    try:
        data = _load_active_sessions()
        value = data.get(channel_id)
        if isinstance(value, dict):
            pane_id = value.get("pane_id")
            if not pane_id:
                log(f"Missing pane_id for channel {channel_id}; re-register with goslack.py")
                return None
            return _resolve_tmux_target_from_pane_id(pane_id)
        return None
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

def _resolve_tmux_target_from_pane_id(pane_id: str):
    try:
        cmd = _tmux_cmd("display-message", "-p", "-t", pane_id, "#{session_name}:#{window_index}.#{pane_index}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        target = result.stdout.strip()
        return target if target else None
    except subprocess.CalledProcessError:
        return None

# =====================
# Slack App
# =====================
logger = logging.getLogger("slack_tmux_bridge")

def _is_token_verification_enabled() -> bool:
    value = os.environ.get("SLACK_TOKEN_VERIFICATION_ENABLED")
    if value is not None:
        return value == "1"
    # Test suite uses "xoxb-test" dummy token; skip auth.test in that case.
    return not (SLACK_BOT_TOKEN or "").startswith("xoxb-test")

app = App(
    token=SLACK_BOT_TOKEN,
    logger=logger,
    token_verification_enabled=_is_token_verification_enabled(),
)

def _post_message(channel_id: str, text: str, thread_ts: str = None, blocks=None):
    ok, error = _post_message_with_result(channel_id, text, thread_ts=thread_ts, blocks=blocks)
    if not ok:
        log(f"⚠️ Slack post failed: {error}")

def _post_message_with_result(channel_id: str, text: str, thread_ts: str = None, blocks=None):
    try:
        kwargs = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        if blocks:
            kwargs["blocks"] = blocks
        app.client.chat_postMessage(**kwargs)
        return True, ""
    except Exception as e:
        return False, str(e)

def _load_notify_queue():
    if not os.path.exists(NOTIFY_QUEUE_FILE):
        return {"items": []}
    try:
        with open(NOTIFY_QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
            return {"items": []}
    except Exception:
        return {"items": []}

def _save_notify_queue(state):
    if not isinstance(state, dict):
        state = {"items": []}
    items = state.get("items")
    if not isinstance(items, list):
        state = {"items": []}
    _atomic_write_json(NOTIFY_QUEUE_FILE, state)

def _calc_retry_delay(attempt: int) -> float:
    base = NOTIFY_RETRY_BASE_SEC if NOTIFY_RETRY_BASE_SEC > 0 else 1.0
    max_delay = NOTIFY_RETRY_MAX_SEC if NOTIFY_RETRY_MAX_SEC > 0 else base
    delay = base * (2 ** max(attempt - 1, 0))
    return min(delay, max_delay)

def _enqueue_notify_message(item: dict):
    now_ts = time.time()
    with NOTIFY_QUEUE_LOCK:
        state = _load_notify_queue()
        items = state.setdefault("items", [])
        items.append(item)
        _save_notify_queue(state)
        NOTIFY_DELIVERY_STATE["enqueued"] += 1
        NOTIFY_DELIVERY_STATE["last_error"] = None
    log(
        "notify queued"
        f" channel={item.get('channel_id')} thread_ts={item.get('thread_ts')}"
        f" source={item.get('source')} size={len(items)}"
    )

def _drop_notify_item(reason: str, item: dict):
    NOTIFY_DELIVERY_STATE["failed"] += 1
    NOTIFY_DELIVERY_STATE["last_error"] = reason
    if reason == "ttl":
        NOTIFY_DELIVERY_STATE["dropped_ttl"] += 1
    if reason == "max_attempts":
        NOTIFY_DELIVERY_STATE["dropped_max_attempts"] += 1
    log(
        "notify dropped"
        f" reason={reason} channel={item.get('channel_id')}"
        f" thread_ts={item.get('thread_ts')} attempts={item.get('attempts')}"
    )

def _process_notify_queue_once(now_ts=None):
    now_ts = now_ts if now_ts is not None else time.time()
    with NOTIFY_QUEUE_LOCK:
        state = _load_notify_queue()
        items = state.get("items", [])
        if not isinstance(items, list):
            state = {"items": []}
            _save_notify_queue(state)
            return

        kept = []
        for item in items:
            if not isinstance(item, dict):
                continue
            created_at = item.get("created_at")
            if not isinstance(created_at, (int, float)):
                _drop_notify_item("invalid_created_at", item)
                continue
            if now_ts - created_at > max(NOTIFY_QUEUE_TTL_SEC, 1):
                _drop_notify_item("ttl", item)
                continue

            next_attempt_at = item.get("next_attempt_at", created_at)
            if isinstance(next_attempt_at, (int, float)) and next_attempt_at > now_ts:
                kept.append(item)
                continue

            channel_id = item.get("channel_id")
            thread_ts = item.get("thread_ts")
            text = item.get("text")
            pane_id = item.get("pane_id")
            turn_id = item.get("turn_id")
            attempts = int(item.get("attempts", 0))

            ok, error = _post_message_with_result(channel_id, text, thread_ts=thread_ts)
            if ok:
                NOTIFY_DELIVERY_STATE["sent"] += 1
                NOTIFY_DELIVERY_STATE["last_error"] = None
                if pane_id:
                    _record_notify_delivery_event(pane_id, thread_ts, source="notify", turn_id=turn_id)
                continue

            attempts += 1
            item["attempts"] = attempts
            item["last_error"] = error
            item["last_attempt_at"] = now_ts
            NOTIFY_DELIVERY_STATE["last_error"] = error
            if NOTIFY_RETRY_MAX_ATTEMPTS > 0 and attempts >= NOTIFY_RETRY_MAX_ATTEMPTS:
                _drop_notify_item("max_attempts", item)
                continue
            delay = _calc_retry_delay(attempts)
            item["next_attempt_at"] = now_ts + delay
            kept.append(item)
            log(
                "notify delivery retry scheduled"
                f" attempts={attempts} delay={delay}s"
                f" channel={channel_id} thread_ts={thread_ts} error={error}"
            )

        state["items"] = kept
        _save_notify_queue(state)

def _notify_delivery_worker():
    # Startup replay: process persisted queue as soon as worker starts.
    while True:
        try:
            _process_notify_queue_once()
        except Exception as e:
            NOTIFY_DELIVERY_STATE["last_error"] = str(e)
            log(f"notify delivery worker error: {e}")
        sleep_sec = NOTIFY_RETRY_TICK_SEC if NOTIFY_RETRY_TICK_SEC > 0 else 1.0
        time.sleep(sleep_sec)

# =====================
# Notify ingress helpers
# =====================
NOTIFY_INGRESS_STATE = {
    "accepted": 0,
    "rejected": 0,
    "last_error": None,
}
NOTIFY_DELIVERY_STATE = {
    "enqueued": 0,
    "sent": 0,
    "failed": 0,
    "dropped_ttl": 0,
    "dropped_max_attempts": 0,
    "last_error": None,
}
NOTIFY_INGRESS_EVENTS = deque()
NOTIFY_INGRESS_LOCK = threading.Lock()
NOTIFY_INGRESS_SERVERS = []
NOTIFY_QUEUE_LOCK = threading.Lock()

def _notify_rate_limited(now=None) -> bool:
    if NOTIFY_RATE_LIMIT_COUNT <= 0 or NOTIFY_RATE_LIMIT_WINDOW_SEC <= 0:
        return False
    now_ts = now if now is not None else time.time()
    with NOTIFY_INGRESS_LOCK:
        while NOTIFY_INGRESS_EVENTS and now_ts - NOTIFY_INGRESS_EVENTS[0] > NOTIFY_RATE_LIMIT_WINDOW_SEC:
            NOTIFY_INGRESS_EVENTS.popleft()
        if len(NOTIFY_INGRESS_EVENTS) >= NOTIFY_RATE_LIMIT_COUNT:
            return True
        NOTIFY_INGRESS_EVENTS.append(now_ts)
        return False

def _validate_notify_payload_bytes(raw_payload: bytes):
    if not isinstance(raw_payload, (bytes, bytearray)):
        return False, "payload is not bytes", None
    if len(raw_payload) == 0:
        return False, "payload is empty", None
    if len(raw_payload) > NOTIFY_MAX_PAYLOAD_BYTES:
        return False, "payload too large", None
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except Exception:
        return False, "invalid json", None
    if not isinstance(payload, dict):
        return False, "payload must be object", None
    return True, "", payload

def _resolve_notify_destination(payload: dict):
    if not isinstance(payload, dict):
        return None, None
    channel_id = payload.get("channel_id")
    thread_ts = payload.get("thread_ts")
    if channel_id and thread_ts:
        return channel_id, thread_ts
    pane_id = payload.get("pane_id")
    if not pane_id:
        return None, None
    context = _load_notify_context()
    ctx = context.get(pane_id) if isinstance(context, dict) else None
    if not isinstance(ctx, dict):
        return None, None
    return ctx.get("channel_id"), ctx.get("thread_ts")

def _resolve_pane_id_for_delivery(payload: dict, channel_id: str):
    pane_id = payload.get("pane_id") if isinstance(payload, dict) else None
    if pane_id:
        return pane_id
    sessions = _get_sessions()
    value = sessions.get(channel_id)
    if isinstance(value, dict):
        return value.get("pane_id")
    return None

def _build_ingress_notify_text(payload: dict) -> str:
    message = payload.get("last-assistant-message")
    if isinstance(message, str):
        text = message.strip()
        if text:
            return text
    return "(empty notify message)"

def _accept_notify_payload(payload: dict, source: str):
    if _notify_rate_limited():
        with NOTIFY_INGRESS_LOCK:
            NOTIFY_INGRESS_STATE["rejected"] += 1
            NOTIFY_INGRESS_STATE["last_error"] = "rate limited"
        return False, "rate limited"

    channel_id, thread_ts = _resolve_notify_destination(payload)
    if not channel_id or not thread_ts:
        with NOTIFY_INGRESS_LOCK:
            NOTIFY_INGRESS_STATE["rejected"] += 1
            NOTIFY_INGRESS_STATE["last_error"] = "destination not found"
        return False, "destination not found"

    pane_id = _resolve_pane_id_for_delivery(payload, channel_id)
    turn_id = payload.get("turn-id") if isinstance(payload, dict) else None
    text = _build_ingress_notify_text(payload)
    _enqueue_notify_message(
        {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "pane_id": pane_id,
            "turn_id": turn_id,
            "text": text,
            "source": source,
            "created_at": time.time(),
            "next_attempt_at": time.time(),
            "attempts": 0,
            "last_error": "",
        }
    )
    with NOTIFY_INGRESS_LOCK:
        NOTIFY_INGRESS_STATE["accepted"] += 1
        NOTIFY_INGRESS_STATE["last_error"] = None
    log(f"notify ingress accepted source={source} channel={channel_id} (queued)")
    return True, ""

class _NotifyHttpHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SlackTmuxNotifyHTTP/1.0"

    def _json_response(self, status: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != NOTIFY_HTTP_PATH:
            self._json_response(404, {"ok": False, "error": "not found"})
            return
        client_ip = (self.client_address[0] if self.client_address else "") or ""
        if not (client_ip.startswith("127.") or client_ip == "::1"):
            self._json_response(403, {"ok": False, "error": "forbidden"})
            return
        content_length = self.headers.get("Content-Length")
        if not content_length:
            self._json_response(400, {"ok": False, "error": "missing content length"})
            return
        try:
            size = int(content_length)
        except ValueError:
            self._json_response(400, {"ok": False, "error": "invalid content length"})
            return
        if size <= 0:
            self._json_response(400, {"ok": False, "error": "empty payload"})
            return
        if size > NOTIFY_MAX_PAYLOAD_BYTES:
            self._json_response(413, {"ok": False, "error": "payload too large"})
            return

        raw_payload = self.rfile.read(size)
        ok, error, payload = _validate_notify_payload_bytes(raw_payload)
        if not ok:
            self._json_response(400, {"ok": False, "error": error})
            return
        accepted, reason = _accept_notify_payload(payload, source="http")
        if not accepted:
            status = 429 if reason == "rate limited" else 422
            self._json_response(status, {"ok": False, "error": reason})
            return
        self._json_response(200, {"ok": True})

    def log_message(self, format, *args):
        return

class _NotifyUnixSocketServer(socketserver.UnixStreamServer):
    allow_reuse_address = True

class _NotifyUnixSocketHandler(socketserver.StreamRequestHandler):
    def handle(self):
        raw_payload = self.rfile.readline(NOTIFY_MAX_PAYLOAD_BYTES + 2)
        if not raw_payload:
            self.wfile.write(b'{"ok":false,"error":"empty payload"}\n')
            return
        if len(raw_payload) > NOTIFY_MAX_PAYLOAD_BYTES:
            self.wfile.write(b'{"ok":false,"error":"payload too large"}\n')
            return
        ok, error, payload = _validate_notify_payload_bytes(raw_payload.strip())
        if not ok:
            self.wfile.write(json.dumps({"ok": False, "error": error}).encode("utf-8") + b"\n")
            return
        accepted, reason = _accept_notify_payload(payload, source="uds")
        if not accepted:
            self.wfile.write(json.dumps({"ok": False, "error": reason}).encode("utf-8") + b"\n")
            return
        self.wfile.write(b'{"ok":true}\n')

def start_notify_ingress():
    if not NOTIFY_INGRESS_ENABLED:
        log("notify ingress disabled")
        return
    if NOTIFY_INGRESS_TRANSPORT == "http":
        if not _is_loopback_host(NOTIFY_HTTP_HOST):
            log(f"Invalid NOTIFY_HTTP_HOST for localhost-only mode: {NOTIFY_HTTP_HOST}")
            sys.exit(1)
        server = http.server.ThreadingHTTPServer((NOTIFY_HTTP_HOST, NOTIFY_HTTP_PORT), _NotifyHttpHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        NOTIFY_INGRESS_SERVERS.append(server)
        log(f"notify ingress listening http://{NOTIFY_HTTP_HOST}:{NOTIFY_HTTP_PORT}{NOTIFY_HTTP_PATH}")
        return

    uds_dir = os.path.dirname(NOTIFY_UDS_PATH)
    if uds_dir and not os.path.exists(uds_dir):
        os.makedirs(uds_dir)
    if os.path.exists(NOTIFY_UDS_PATH):
        os.remove(NOTIFY_UDS_PATH)
    server = _NotifyUnixSocketServer(NOTIFY_UDS_PATH, _NotifyUnixSocketHandler)
    os.chmod(NOTIFY_UDS_PATH, NOTIFY_UDS_MODE)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    NOTIFY_INGRESS_SERVERS.append(server)
    log(f"notify ingress listening uds://{NOTIFY_UDS_PATH}")

# =====================
# Slack: inbound logging
# =====================
@app.middleware  # runs on every incoming request
def log_incoming_payload(body, next):
    global LAST_EVENT_TS
    LAST_EVENT_TS = time.time()
    event_id = body.get("event_id")
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
        log(f"EVENT IN: id={event_id} type={event_type} subtype={subtype} channel={channel} user={user} text={text_present}")
    else:
        log(f"PAYLOAD IN: id={event_id} type={body_type}")
    return next()

# =====================
# tmux helpers
# =====================
def pre_clear_tmux(tmux_target: str):
    """実行前に画面と履歴をクリーンにする (tmuxの機能のみを使用)"""
    log(f"PRE-EXEC CLEAR: Clearing tmux history and screen (C-l) on {tmux_target}")
    # 1. 履歴をクリア
    subprocess.run(_tmux_cmd("clear-history", "-t", tmux_target))
    # 2. 画面をクリア (Ctrl+L)
    subprocess.run(_tmux_cmd("send-keys", "-t", tmux_target, "C-l"))
    # 反映待ち
    time.sleep(0.3)

def send_text_to_tmux(tmux_target: str, text: str, thread_ts: str = None, channel_id: str = None):
    cmd = _tmux_cmd("send-keys", "-t", tmux_target, text)
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

def send_ctrl_c(tmux_target: str, thread_ts: str = None, channel_id: str = None):
    cmd = _tmux_cmd("send-keys", "-t", tmux_target, "C-c")
    log("EXEC CTRL+C: " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err_msg = f"⚠️ Error in send_ctrl_c:\n{r.stderr}"
        log(err_msg)
        if thread_ts and channel_id:
            _post_message(channel_id, err_msg, thread_ts=thread_ts)

def capture_tmux(tmux_target: str, lines=None):
    args = ["-p", "-S", "-1000"] if lines else ["-p"]
    cmd = _tmux_cmd("capture-pane", "-t", tmux_target) + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout or ""

# =====================
# snapshot helpers (removed monitoring snapshots)
# =====================
PROMPT_CACHE = {}  # thread_ts -> last_prompt
PROMPT_CACHE_TS = {}  # thread_ts -> last_seen_epoch
PERMISSION_ALERTED = set()
LAST_EVENT_TS = time.time()
LAST_EVENT_TS_BY_CHANNEL = {}
LAST_HEALTH_NOTIFY_TS_BY_CHANNEL = {}
LAST_IDLE_NOTIFY_TS_BY_CHANNEL = {}
LAST_RESTART_TS = 0.0
PENDING_REBIND_BY_THREAD = {}
NOTIFY_DEDUPE_LOCK = threading.Lock()

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

def _load_notify_context():
    if not os.path.exists(NOTIFY_CONTEXT_FILE):
        return {}
    try:
        with open(NOTIFY_CONTEXT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _load_notify_dedupe():
    if not os.path.exists(NOTIFY_DEDUPE_FILE):
        return {}
    try:
        with open(NOTIFY_DEDUPE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_notify_dedupe(state):
    _atomic_write_json(NOTIFY_DEDUPE_FILE, state)

def _prune_notify_dedupe(state, now_ts=None):
    now_ts = now_ts if now_ts is not None else time.time()
    entries = state.get("entries", {})
    if not isinstance(entries, dict):
        return {"entries": {}}
    ttl = max(NOTIFY_DEDUPE_TTL_SEC, 1)
    kept = {}
    for key, value in entries.items():
        if not isinstance(value, dict):
            continue
        ts = value.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        if now_ts - ts <= ttl:
            kept[key] = value
    return {"entries": kept}

def _record_notify_delivery_event(pane_id: str, thread_ts: str, source: str, turn_id: str = None):
    if not pane_id or not thread_ts:
        return
    now_ts = time.time()
    turn_key = turn_id if turn_id else "-"
    key = f"{pane_id}:{thread_ts}:{turn_key}:{source}"
    with NOTIFY_DEDUPE_LOCK:
        state = _prune_notify_dedupe(_load_notify_dedupe(), now_ts=now_ts)
        entries = state.setdefault("entries", {})
        entries[key] = {
            "pane_id": pane_id,
            "thread_ts": thread_ts,
            "turn_id": turn_id,
            "source": source,
            "ts": now_ts,
        }
        _save_notify_dedupe(state)

def _has_recent_notify_delivery(pane_id: str, thread_ts: str):
    if not pane_id or not thread_ts:
        return False
    now_ts = time.time()
    with NOTIFY_DEDUPE_LOCK:
        state = _prune_notify_dedupe(_load_notify_dedupe(), now_ts=now_ts)
        _save_notify_dedupe(state)
    entries = state.get("entries", {})
    if not isinstance(entries, dict):
        return False
    for value in entries.values():
        if not isinstance(value, dict):
            continue
        if value.get("source") != "notify":
            continue
        if value.get("pane_id") == pane_id and value.get("thread_ts") == thread_ts:
            return True
    return False

def _get_session_pane_id(channel_id: str):
    sessions = _get_sessions()
    value = sessions.get(channel_id)
    if isinstance(value, dict):
        return value.get("pane_id")
    return None

def _save_notify_context(context):
    _atomic_write_json(NOTIFY_CONTEXT_FILE, context)

def _record_notify_context(channel_id: str, thread_ts: str):
    if not channel_id or not thread_ts:
        return
    sessions = _get_sessions()
    entry = sessions.get(channel_id)
    if not isinstance(entry, dict):
        return
    pane_id = entry.get("pane_id")
    if not pane_id:
        return
    context = _load_notify_context()
    context[pane_id] = {"channel_id": channel_id, "thread_ts": thread_ts, "updated_at": time.time()}
    _save_notify_context(context)

def _get_sessions():
    return _load_active_sessions()

def _save_sessions(sessions):
    _atomic_write_json(ACTIVE_SESSIONS_FILE, sessions)

def _update_session_entry(channel_id, pane_id=None, pane=None, dir_path=None, name=None, sessions=None):
    if sessions is None:
        sessions = _get_sessions()
    entry = sessions.get(channel_id)
    if not isinstance(entry, dict):
        entry = {}
    if pane_id is not None:
        entry["pane_id"] = pane_id
    if pane is not None:
        entry["pane"] = pane
    if dir_path is not None:
        entry["dir"] = dir_path
    if name is not None:
        entry["name"] = name
    sessions[channel_id] = entry
    return sessions

def _delete_session_entry(channel_id, sessions=None):
    if sessions is None:
        sessions = _get_sessions()
    entry = sessions.pop(channel_id, None)
    return sessions, entry

def _format_age(seconds: float) -> str:
    if seconds < 0:
        return "0s"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"

def _permission_prompt_detected(text: str) -> bool:
    if not text:
        return False
    return PERMISSION_WATCH_RE.search(text) is not None

def _post_permission_prompt(channel_id: str, thread_ts: str, content: str):
    excerpt = content.strip()
    if not excerpt:
        excerpt = "(no output)"
    max_len = 3000
    if len(excerpt) > max_len:
        excerpt = excerpt[-max_len:]
    _post_message(
        channel_id,
        "⚠️ 承認待ちの可能性があります:\n```\n" + excerpt + "\n```",
        thread_ts=thread_ts,
    )

def _watch_permission_prompt(thread_ts: str, channel_id: str, tmux_target: str):
    if PERMISSION_WATCH_SEC <= 0:
        return
    if not thread_ts or not channel_id or not tmux_target:
        return
    if thread_ts in PERMISSION_ALERTED:
        return

    deadline = time.time() + PERMISSION_WATCH_SEC
    while time.time() < deadline:
        raw_content = capture_tmux(tmux_target, lines=True)
        current_clean = strip_ansi(raw_content)
        if _permission_prompt_detected(current_clean):
            if thread_ts not in PERMISSION_ALERTED:
                PERMISSION_ALERTED.add(thread_ts)
                _post_permission_prompt(channel_id, thread_ts, current_clean)
            break
        time.sleep(PERMISSION_WATCH_INTERVAL_SEC)

def _start_permission_watch(thread_ts: str, channel_id: str, tmux_target: str):
    if PERMISSION_WATCH_SEC <= 0:
        return
    watcher = threading.Thread(
        target=_watch_permission_prompt,
        args=(thread_ts, channel_id, tmux_target),
        daemon=True,
    )
    watcher.start()

def _watch_now_output(thread_ts: str, channel_id: str, tmux_target: str):
    if not thread_ts or not channel_id or not tmux_target:
        return
    if NOW_WATCH_INTERVAL_SEC <= 0 or NOW_WATCH_IDLE_COUNT <= 0 or NOW_WATCH_TIMEOUT_SEC <= 0:
        _capture_and_reply_once(thread_ts, channel_id, tmux_target, "")
        return

    start_ts = time.time()
    idle_count = 0
    try:
        last_content = strip_ansi(capture_tmux(tmux_target, lines=True))
    except Exception as e:
        log(f"/now watch capture failed: {e}")
        last_content = ""

    while True:
        if time.time() - start_ts >= NOW_WATCH_TIMEOUT_SEC:
            _post_message(
                channel_id,
                "⏳ 監視がタイムアウトしました。続けますか？",
                thread_ts=thread_ts,
                blocks=[
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "監視を継続"},
                                "action_id": "continue_now_watch",
                            }
                        ],
                    }
                ],
            )
            return

        time.sleep(NOW_WATCH_INTERVAL_SEC)
        try:
            current_content = strip_ansi(capture_tmux(tmux_target, lines=True))
        except Exception as e:
            log(f"/now watch capture failed: {e}")
            current_content = last_content

        if current_content != last_content:
            last_content = current_content
            idle_count = 0
            continue

        idle_count += 1
        if idle_count >= NOW_WATCH_IDLE_COUNT:
            _capture_and_reply_once(thread_ts, channel_id, tmux_target, "")
            return

def _start_now_watch(thread_ts: str, channel_id: str, tmux_target: str):
    watcher = threading.Thread(
        target=_watch_now_output,
        args=(thread_ts, channel_id, tmux_target),
        daemon=True,
    )
    watcher.start()

def _watch_execute_output(thread_ts: str, channel_id: str, tmux_target: str):
    if not thread_ts or not channel_id or not tmux_target:
        return
    if NOW_WATCH_INTERVAL_SEC <= 0 or NOW_WATCH_IDLE_COUNT <= 0 or NOW_WATCH_TIMEOUT_SEC <= 0:
        _capture_and_reply_once(thread_ts, channel_id, tmux_target, "", reason="execute")
        return

    start_ts = time.time()
    idle_count = 0
    try:
        last_content = strip_ansi(capture_tmux(tmux_target, lines=True))
    except Exception as e:
        log(f"execute watch capture failed: {e}")
        last_content = ""

    while True:
        if time.time() - start_ts >= NOW_WATCH_TIMEOUT_SEC:
            _post_message(
                channel_id,
                "タイムアウトしました。監視を継続しますか？",
                thread_ts=thread_ts,
                blocks=[
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "監視を継続"},
                                "action_id": "continue_execute_watch",
                            }
                        ],
                    }
                ],
            )
            return

        time.sleep(NOW_WATCH_INTERVAL_SEC)
        try:
            current_content = strip_ansi(capture_tmux(tmux_target, lines=True))
        except Exception as e:
            log(f"execute watch capture failed: {e}")
            current_content = last_content

        if current_content != last_content:
            last_content = current_content
            idle_count = 0
            continue

        idle_count += 1
        if idle_count >= NOW_WATCH_IDLE_COUNT:
            _capture_and_reply_once(thread_ts, channel_id, tmux_target, "", reason="execute")
            return

def _start_execute_watch(thread_ts: str, channel_id: str, tmux_target: str):
    watcher = threading.Thread(
        target=_watch_execute_output,
        args=(thread_ts, channel_id, tmux_target),
        daemon=True,
    )
    watcher.start()

def _build_sessions_output():
    sessions = _get_sessions()
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

def _cleanup_prompt_cache(thread_ts: str):
    if thread_ts in PROMPT_CACHE:
        del PROMPT_CACHE[thread_ts]
    if thread_ts in PROMPT_CACHE_TS:
        del PROMPT_CACHE_TS[thread_ts]
    if thread_ts in PERMISSION_ALERTED:
        PERMISSION_ALERTED.discard(thread_ts)

def _select_primary_channel(entries):
    def _score(entry):
        channel_id, value = entry
        last_ts = LAST_EVENT_TS_BY_CHANNEL.get(channel_id, 0)
        name = value.get("name") if isinstance(value, dict) else None
        return (last_ts, 1 if name else 0, channel_id)
    return max(entries, key=_score)

def _dedupe_active_sessions():
    sessions = _get_sessions()
    if not sessions:
        return

    pane_map = {}
    for channel_id, value in sessions.items():
        pane_key = None
        if isinstance(value, dict):
            pane_key = value.get("pane_id") or value.get("pane")
        else:
            pane_key = value
        if not pane_key:
            continue
        pane_map.setdefault(pane_key, []).append((channel_id, value))

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
        _save_sessions(sessions)

def _maintenance_worker():
    while True:
        time.sleep(60)
        now = time.time()
        # prune prompt cache
        for key, ts in list(PROMPT_CACHE_TS.items()):
            if now - ts > PROMPT_CACHE_TTL_SEC:
                _cleanup_prompt_cache(key)
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
# Single-capture reply (no monitoring)
# =====================
def _capture_and_reply_once(thread_ts, channel_id, tmux_target, prompt="", reason="generic"):
    log(f"Capturing output for {thread_ts} (Target: {tmux_target}, Prompt: {prompt})...")
    time.sleep(1.0)

    raw_content = capture_tmux(tmux_target, lines=True)
    current_clean = strip_ansi(raw_content)
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
        msg_text = "(No output detected)"

    pane_id = _get_session_pane_id(channel_id)
    if reason == "execute" and EXECUTE_RESULT_MODE == "both" and _has_recent_notify_delivery(pane_id, thread_ts):
        log(f"dedupe: skip poll snapshot due to recent notify pane_id={pane_id} thread_ts={thread_ts}")
        _cleanup_prompt_cache(thread_ts)
        return

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
        for i in range(0, len(msg_text), chunk_size):
            chunk = msg_text[i:i + chunk_size]
            chunk = re.sub(r"(-{20,})", "-" * 20, chunk)
            chunk = re.sub(r"(={20,})", "=" * 20, chunk)
            chunk = re.sub(r"(─{20,})", "─" * 20, chunk)
            chunk = re.sub(r"(═{20,})", "═" * 20, chunk)

            _post_message(
                channel_id,
                "```\n" + chunk + "\n```",
                thread_ts=thread_ts
            )

    if pane_id:
        _record_notify_delivery_event(pane_id, thread_ts, source="poll")
    _cleanup_prompt_cache(thread_ts)

# =====================
# Slack: message → 文字入力 + 操作ボタン表示（スレッド）
# =====================
def _get_thread_ts_from_message(message):
    return message.get("thread_ts") or message.get("ts")

def _require_thread_ts(message, channel_id: str):
    thread_ts = message.get("thread_ts")
    if thread_ts:
        return thread_ts
    _post_message(
        channel_id,
        "⚠️ 実行結果はスレッドに返信します。スレッド内のボタンから実行してください。"
    )
    return None

def _build_reply_instruction(channel_id: str, thread_ts: str) -> str:
    return ""

def _with_reply_instruction(text: str, channel_id: str, thread_ts: str) -> str:
    return text

def _normalize_slash_command_text(text: str) -> str:
    if not text:
        return text
    # Strip zero-width characters that can appear in Slack messages
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    return text.strip()

def _is_command(text: str, command: str) -> bool:
    text = _normalize_slash_command_text(text)
    return re.match(rf"^{re.escape(command)}(\s|$)", text) is not None

def _get_channel_name_from_slack(channel_id: str):
    try:
        resp = app.client.conversations_info(channel=channel_id)
        return resp.get("channel", {}).get("name")
    except Exception:
        return None

def _get_pane_current_path(pane_id: str):
    try:
        cmd = _tmux_cmd("display-message", "-p", "-t", pane_id, "#{pane_current_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def _get_tmux_target_or_notify(channel_id: str, thread_ts: str = None, message: str = "⚠️ Error: No active tmux session.") -> str:
    tmux_target = get_target_pane(channel_id)
    if not tmux_target:
        _post_message(channel_id, message, thread_ts=thread_ts)
    return tmux_target

def _handle_prompt_text(channel_id: str, thread_ts: str, tmux_target: str, text: str):
    log(f"SLACK MESSAGE: {text} (Channel: {channel_id} -> Tmux: {tmux_target})")

    # プロンプトをキャッシュに保存（ボタン実行時に使用するため）
    PROMPT_CACHE[thread_ts] = text
    PROMPT_CACHE_TS[thread_ts] = time.time()

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

def _dispatch_command(text: str, channel_id: str, thread_ts: str) -> bool:
    if _is_command(text, "/bye"):
        return _handle_bye_command(channel_id, thread_ts)
    if _is_command(text, "/dir"):
        _handle_dir_command(channel_id, thread_ts)
        return True
    if _is_command(text, "/now"):
        tmux_target = _get_tmux_target_or_notify(channel_id, thread_ts=thread_ts)
        _handle_now_command(channel_id, thread_ts, tmux_target)
        return True
    if _is_command(text, "/ctlc"):
        tmux_target = _get_tmux_target_or_notify(channel_id, thread_ts=thread_ts)
        _handle_ctlc_command(channel_id, thread_ts, tmux_target)
        return True
    if _is_command(text, "/sessions"):
        output = _build_sessions_output()
        _post_message(channel_id, output, thread_ts=thread_ts)
        return True
    return False

def _handle_rebind_guard(channel_id: str, thread_ts: str, text: str, tmux_target: str) -> bool:
    sessions = _get_sessions()
    entry = sessions.get(channel_id)
    if not isinstance(entry, dict):
        return False
    expected_pane = entry.get("pane")
    pane_id = entry.get("pane_id")
    expected_name = entry.get("name")
    current_name = _get_channel_name_from_slack(channel_id)
    mismatch = False
    if expected_pane and expected_pane != tmux_target:
        mismatch = True
    if expected_name and current_name and expected_name != current_name:
        mismatch = True
    if pane_id and mismatch:
        PENDING_REBIND_BY_THREAD[thread_ts] = {
            "channel_id": channel_id,
            "text": text,
            "pane_id": pane_id,
        }
        _post_message(
            channel_id,
            "⚠️ 接続先が変わっている可能性があります。続行しますか？",
            thread_ts=thread_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*現在のペイン*: `{tmux_target}`\n*登録ペイン*: `{expected_pane}`"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "OK"},
                            "action_id": "confirm_rebind"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "キャンセル（切断）"},
                            "style": "danger",
                            "action_id": "cancel_rebind"
                        }
                    ]
                }
            ]
        )
        return True
    return False

def _handle_bye_command(channel_id: str, thread_ts: str) -> bool:
    try:
        sessions = _get_sessions()
        sessions, removed = _delete_session_entry(channel_id, sessions)
        if removed:
            _save_sessions(sessions)
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
        return True
    _post_message(
        channel_id,
        "🔄 現在の状態を取得しています...",
        thread_ts=thread_ts
    )
    _start_now_watch(thread_ts, channel_id, tmux_target)
    return True

def _handle_ctlc_command(channel_id: str, thread_ts: str, tmux_target: str) -> bool:
    if not tmux_target:
        return True
    send_ctrl_c(tmux_target, thread_ts=thread_ts, channel_id=channel_id)
    _post_message(
        channel_id,
        "🛑 Ctrl+C を送信しました。",
        thread_ts=thread_ts
    )
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
    send_text_to_tmux(
        tmux_target,
        _with_reply_instruction(text, channel_id, thread_ts),
        thread_ts=thread_ts,
        channel_id=channel_id
    )

    # ③ 通知
    _post_message(
        channel_id,
        "🔢 数字入力を検知: 自動実行を開始します...",
        thread_ts=thread_ts
    )

    # ④ Enter送信
    send_enter(tmux_target, thread_ts=thread_ts, channel_id=channel_id)
    _start_permission_watch(thread_ts, channel_id, tmux_target)
    _record_notify_context(channel_id, thread_ts)

def _handle_text_message(channel_id: str, thread_ts: str, tmux_target: str, text: str):
    # ① 文字だけ tmux に送る
    send_text_to_tmux(
        tmux_target,
        _with_reply_instruction(text, channel_id, thread_ts),
        thread_ts=thread_ts,
        channel_id=channel_id
    )
    _record_notify_context(channel_id, thread_ts)

    # ② 同じメッセージのスレッドに操作ボタンを出す
    _post_message(
        channel_id,
        "操作を選んでください（実行すると結果をこのスレッドに投稿します）",
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

    if _dispatch_command(text, channel_id, thread_ts):
        return

    # =====================
    # Command: /bye (Connection cleanup)
    # Works even if not connected (to clean up state)
    # =====================
    # (handled by _dispatch_command)

    # =====================
    # Active Session Check
    # =====================
    # Check if this channel has an active tmux session
    tmux_target = get_target_pane(channel_id)
    if not tmux_target:
        # Ignore messages from unconfigured channels
        return

    # pane/name mismatch detection
    if _handle_rebind_guard(channel_id, thread_ts, text, tmux_target):
        return
    _handle_prompt_text(channel_id, thread_ts, tmux_target, text)

# =====================
# Slack: ▶︎ 実行（Enter） → Enter送信のみ
# =====================
@app.action("send_enter")
def handle_send_enter(ack, body):
    ack()
    log("BUTTON CLICKED: send_enter")
    
    channel_id = body["channel"]["id"]
    thread_ts = _get_thread_ts_from_message(body["message"])
    tmux_target = _get_tmux_target_or_notify(
        channel_id,
        message="⚠️ Error: No active tmux session for this channel. Run `goslack` in your terminal."
    )
    if not tmux_target:
        return

    _post_message(
        channel_id,
        ":rocket: 実行を開始しました（処理中）...",
        thread_ts=thread_ts,
    )

    # 仕様に合わせて実行前に必ずプリクリア
    pre_clear_tmux(tmux_target)

    # Enterを送る
    send_enter(tmux_target, channel_id=channel_id)
    _start_permission_watch(thread_ts, channel_id, tmux_target)
    _record_notify_context(channel_id, thread_ts)
    if EXECUTE_RESULT_MODE in ("poll", "both"):
        _start_execute_watch(thread_ts, channel_id, tmux_target)

# =====================
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
    tmux_target = _get_tmux_target_or_notify(channel_id)
    if not tmux_target:
        return

    # action_id が何であれ、value にコマンドが入っているのでそれを使う
    cmd_text = body["actions"][0]["value"]
    log(f"COMMAND CLICKED: {cmd_text}")
    
    thread_ts = _get_thread_ts_from_message(body["message"])
    thread_ts = _require_thread_ts({"thread_ts": thread_ts}, channel_id)
    if not thread_ts:
        return

    # Apply command filter to button-triggered commands as well
    allowed, reason = is_command_allowed(cmd_text)
    if not allowed:
        log(f"BLOCKED COMMAND (button): {cmd_text}")
        _post_message(channel_id, reason, thread_ts=thread_ts)
        return

    _post_message(
        channel_id,
        f"⚡ コマンド実行: `{cmd_text}`",
        thread_ts=thread_ts
    )

    # 1. プリクリア (既存の入力も C-u の代わりに C-l で実質的に消えるか、C-uを併用)
    subprocess.run(_tmux_cmd("send-keys", "-t", tmux_target, "C-u")) # 念のため既存行クリア
    pre_clear_tmux(tmux_target)
    
    # 2. コマンド入力
    send_text_to_tmux(
        tmux_target,
        _with_reply_instruction(cmd_text, channel_id, thread_ts),
        thread_ts,
        channel_id
    )
    
    # 3. Enter
    send_enter(tmux_target, thread_ts=thread_ts, channel_id=channel_id)
    _start_permission_watch(thread_ts, channel_id, tmux_target)

# =====================
# Slack: 🗑️ プロンプト削除
# =====================
@app.action("delete_prompt")
def handle_delete_prompt(ack, body):
    ack()
    log("BUTTON CLICKED: delete_prompt")
    
    channel_id = body["channel"]["id"]
    tmux_target = _get_tmux_target_or_notify(channel_id)
    if not tmux_target:
        return # 静かに無視、あるいはエラー表示

    thread_ts = _get_thread_ts_from_message(body["message"])

    # Ctrl+u を送信して行をクリア
    cmd = _tmux_cmd("send-keys", "-t", tmux_target, "C-u")
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
    tmux_target = _get_tmux_target_or_notify(channel_id)
    if not tmux_target:
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
# Slack: 監視を継続（/now と同じ挙動）
# =====================
@app.action("continue_now_watch")
def handle_continue_now_watch(ack, body):
    ack()
    log("BUTTON CLICKED: continue_now_watch")

    channel_id = body["channel"]["id"]
    thread_ts = _get_thread_ts_from_message(body["message"])
    tmux_target = _get_tmux_target_or_notify(
        channel_id,
        message="⚠️ Error: No active tmux session for this channel. Run `goslack` in your terminal."
    )
    if not tmux_target:
        return

    _handle_now_command(channel_id, thread_ts, tmux_target)

# =====================
# Slack: 実行の監視を継続
# =====================
@app.action("continue_execute_watch")
def handle_continue_execute_watch(ack, body):
    ack()
    log("BUTTON CLICKED: continue_execute_watch")

    channel_id = body["channel"]["id"]
    thread_ts = _get_thread_ts_from_message(body["message"])
    tmux_target = _get_tmux_target_or_notify(
        channel_id,
        message="⚠️ Error: No active tmux session for this channel. Run `goslack` in your terminal."
    )
    if not tmux_target:
        return

    _start_execute_watch(thread_ts, channel_id, tmux_target)

# =====================
# Slack: rebind confirmation
# =====================
@app.action("confirm_rebind")
def handle_confirm_rebind(ack, body):
    ack()
    channel_id = body["channel"]["id"]
    thread_ts = _get_thread_ts_from_message(body["message"])
    pending = PENDING_REBIND_BY_THREAD.pop(thread_ts, None)
    if not pending:
        _post_message(channel_id, "⚠️ 対象の再接続情報が見つかりません。", thread_ts=thread_ts)
        return

    pane_id = pending.get("pane_id")
    text = pending.get("text", "")
    tmux_target = _resolve_tmux_target_from_pane_id(pane_id)
    if not tmux_target:
        _post_message(channel_id, "⚠️ ペインが見つからないため実行を中止しました。", thread_ts=thread_ts)
        return

    sessions = _get_sessions()
    sessions = _update_session_entry(
        channel_id,
        pane_id=pane_id,
        pane=tmux_target,
        dir_path=_get_pane_current_path(pane_id),
        name=_get_channel_name_from_slack(channel_id),
        sessions=sessions,
    )
    _save_sessions(sessions)

    _post_message(channel_id, "✅ 接続先を更新しました。実行します。", thread_ts=thread_ts)
    _handle_prompt_text(channel_id, thread_ts, tmux_target, text)


@app.action("cancel_rebind")
def handle_cancel_rebind(ack, body):
    ack()
    channel_id = body["channel"]["id"]
    thread_ts = _get_thread_ts_from_message(body["message"])
    pending = PENDING_REBIND_BY_THREAD.pop(thread_ts, None)

    sessions = _get_sessions()
    entry = sessions.get(channel_id)
    channel_name = entry.get("name") if isinstance(entry, dict) else None
    if channel_id in sessions:
        sessions, _ = _delete_session_entry(channel_id, sessions)
        _save_sessions(sessions)

    label = channel_name or channel_id
    _post_message(channel_id, f"キャンセルをして {label} の接続を解除しました。", thread_ts=thread_ts)

# =====================
# 起動通知
# =====================
def post_startup_message():
    log("Bot started. Waiting for connections in active_sessions.json")

def stop_notify_ingress():
    for server in NOTIFY_INGRESS_SERVERS:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    if NOTIFY_INGRESS_TRANSPORT == "uds" and os.path.exists(NOTIFY_UDS_PATH):
        try:
            os.remove(NOTIFY_UDS_PATH)
        except Exception:
            pass

# =====================
# main
# =====================
if __name__ == "__main__":
    configure_logging()
    log("Slack → tmux bridge (Multi-channel) started")
    ensure_required_tokens()
    # 初期化時に tmp ディレクトリ作成
    if not os.path.exists(TMP_DIR):
        os.makedirs(TMP_DIR)

    ensure_single_instance()
    atexit.register(stop_notify_ingress)

    threading.Thread(target=_maintenance_worker, daemon=True).start()
    threading.Thread(target=_event_health_worker, daemon=True).start()
    threading.Thread(target=_notify_delivery_worker, daemon=True).start()
    start_notify_ingress()
    
    # active_sessions.json がなければ作成
    if not os.path.exists(ACTIVE_SESSIONS_FILE):
        _atomic_write_json(ACTIVE_SESSIONS_FILE, {})
    if not os.path.exists(NOTIFY_QUEUE_FILE):
        _atomic_write_json(NOTIFY_QUEUE_FILE, {"items": []})

    SocketModeHandler(app, SLACK_APP_TOKEN).start()
