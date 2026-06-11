Status: Active
Last updated: 2026-06-11
Evidence:
- docs/L1_project/philosophy.md:20-48
- docs/L1_project/pyilosophy.md:31-54
- slack_tmux_bridge.py:143-187
- slack_tmux_bridge.py:139-162
- .env.sample:1-48
- README.md:54-76

# 設計・運用ポリシー

## 技術選定ポリシー
- **言語**: Python 3.11（CI で固定）。シンプルなスクリプト構成を維持する。根拠: .github/workflows/ci.yml:12-14
- **依存最小化**: `slack_bolt` / `slack_sdk` / `python-dotenv` のみ。追加依存は慎重に評価する。根拠: requirements.txt:1-3
- **パッケージ管理**: pip + venv。バージョン固定は現状なし（lock ファイルなし）。根拠: requirements.txt / requirements-dev.txt

## セキュリティ方針
- **トークン管理**: `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` は `.env` で管理し、リポジトリにコミットしない。根拠: .env.sample:1-3 / .gitignore
- **コマンドフィルタ**: allowlist + denylist により危険なコマンドをブロックする。denylist が先に評価される。根拠: slack_tmux_bridge.py:143-187
  - デフォルトで `rm` をブロック（`\rm` でバイパス可能）
  - 推奨 denylist: `sudo,rm -rf,/\brm\b/,mkfs,dd,/\bshutdown\b/,/\breboot\b/`
- **notify ingress セキュリティ**: HTTP transport は localhost のみ（127.0.0.1）。UDS transport は `NOTIFY_UDS_MODE=600` でオーナーのみアクセス可。根拠: slack_tmux_bridge.py:53-61
- **ペイン再解決**: 送信前に `pane_id` から現在の tmux target を再解決し、ペイン変更による誤送信を防ぐ。根拠: slack_tmux_bridge.py:175-219

## パフォーマンス要件
- `capture-pane` は最大 1000 行で取得（大量出力時のメモリ抑制）。根拠: slack_tmux_bridge.py:332-336
- notify キュー TTL: デフォルト 3600 秒。キューは永続化される（`tmp/notify_delivery_queue.json`）。根拠: slack_tmux_bridge.py:65

## 禁止事項
- `.env` や Slack トークンをリポジトリにコミットしない
- notify ingress の HTTP transport を `127.0.0.1` 以外の host にバインドしない（外部公開禁止）
- UDS socket のパーミッションを `600` より緩くしない

## 運用方針
- 起動: 手動実行（開発・試験用）または macOS launchd デーモン化（本番推奨）
- ログ: `LOG_LEVEL` 環境変数で制御（デフォルト `INFO`）
- 監視: `EVENT_HEALTH_*` でイベント停止を検知し `log/exit/restart` を選択可能
- セッション管理: `goslack.py` で明示的に channel ↔ pane を登録・管理する

根拠: README.md:114-170 / docs/L2_development/development_setup.md:77-79
