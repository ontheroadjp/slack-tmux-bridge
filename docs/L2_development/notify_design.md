Status: Draft
Last updated: 2026-02-10
Evidence:
- slack_tmux_bridge.py:43-45
- slack_tmux_bridge.py:52-71
- slack_tmux_bridge.py:355-455
- slack_tmux_bridge.py:456-552
- slack_tmux_bridge.py:587-783
- slack_tmux_bridge.py:2108-2134
- README.md:292-300

# Notify 設計（Codex -> Slack thread reply）

## 目的
- Codex のターン完了通知を、`slack_tmux_bridge` 経由で Slack スレッドへ配送する。
- 短命 CLI (`slack_tmux_bridge.py notify`) と常駐 bridge 本体をローカル ingress で接続する。

## 役割分離
- `slack_tmux_bridge.py notify`:
  - payload を受け取り、最小正規化と必須項目検証を行う。
  - local notify ingress へ転送して終了する。
- `slack_tmux_bridge` 本体:
  - ingress を受け付け、配送キューへ永続化する。
  - バックグラウンドワーカーで Slack 投稿（再試行あり）を実行する。

## エントリポイント
- Codex 設定例:

```toml
[notify]
command = ["python", "/Users/you/WORKSPACE/slack_tmux_bridge/slack_tmux_bridge.py", "notify"]
```

- `notify` サブコマンド実行時は CLI モードで動作し、Socket Mode は起動しない。

## Payload 契約（スレッド返信）
- JSON object であること。
- 必須:
  - `last-assistant-message`
- 補助:
  - `channel_id`（`channel-id` から補完可）
  - `thread_ts`（`thread-id` から補完可）
  - `pane_id`（`pane-id` から補完可）
  - `turn-id`（重複抑止イベント記録で利用）

`last-assistant-message` は forwarding 前に必須。`channel_id` / `thread_ts` は payload 直値または `pane_id` からの宛先解決（`active_sessions.json` / `tmp/notify_context.json`）で確定できる必要がある。最終的に `channel_id` / `thread_ts` を解決できない場合は reject する。

## 正規化ルール
- 既存 snake_case を優先する（上書きしない）。
- 補完:
  - `channel-id -> channel_id`
  - `pane-id -> pane_id`
  - `thread-id -> thread_ts`（`1234567890.123456` 形式のみ）

## 通信方式
- `NOTIFY_INGRESS_TRANSPORT=http`
  - `http://{NOTIFY_HTTP_HOST}:{NOTIFY_HTTP_PORT}{NOTIFY_HTTP_PATH}` に POST
- `NOTIFY_INGRESS_TRANSPORT=uds`
  - `NOTIFY_UDS_PATH` の Unix Domain Socket に 1 行 JSON を送信

## Ingress 受信制約
- `NOTIFY_INGRESS_ENABLED=1` で受信サーバ起動。
- HTTP は loopback ホストのみ許可。
- payload サイズ上限: `NOTIFY_MAX_PAYLOAD_BYTES`
- 受信レート制限:
  - `NOTIFY_RATE_LIMIT_COUNT`
  - `NOTIFY_RATE_LIMIT_WINDOW_SEC`

## 配送キューと再試行
- 受理 payload は `tmp/notify_delivery_queue.json` に永続化。
- ワーカー (`_notify_delivery_worker`) が定期処理:
  - Slack へ `chat_postMessage(channel, text, thread_ts)` で投稿
  - 失敗時は指数バックオフで再試行
  - 制御パラメータ:
    - `NOTIFY_RETRY_BASE_SEC`
    - `NOTIFY_RETRY_MAX_SEC`
    - `NOTIFY_RETRY_MAX_ATTEMPTS`
    - `NOTIFY_RETRY_TICK_SEC`
- `NOTIFY_QUEUE_TTL_SEC` 超過は破棄。
- 再起動後もキューはリプレイされる。
- `NOTIFY_QUEUE_RESET_ON_START=1` を設定した場合、起動時に `tmp/notify_delivery_queue.json` を空にする。既定値は `0`。
- `invalid_thread_ts` / `channel_not_found` / `not_in_channel` / `is_archived` は恒久エラーとして再試行せず破棄する。

## 主要エラー
- `notify payload rejected: ...`
  - JSON 不正 / 必須項目不足 / サイズ超過 / 宛先解決不能（CLI または ingress で reject）
- `notify forwarding failed: http 422 {"error":"destination not found"}`
  - ingress 側で `channel_id` を解決できない
- `notify forwarding failed: http 422 {"error":"thread destination not found"}`
  - ingress 側で `thread_ts` を解決できない（スレッド返信先未確定）
- `notify payload rejected: inactive session for pane_id`
  - `pane_id`（または `TMUX_PANE`）が `active_sessions.json` 上で未接続のため reject
- `notify forwarding failed: ...`
  - ingress 未起動、接続失敗、タイムアウトなど

## 関連状態ファイル
- `tmp/notify_delivery_queue.json`: 配送キュー
- `tmp/notify_delivery_dedupe.json`: notify/poll 重複抑止イベント
- `tmp/notify_context.json`: 実行時コンテキスト（`pane_id` ベース）
