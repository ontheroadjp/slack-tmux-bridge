Status: Draft
Last updated: 2026-02-02
Note: The canonical file name is docs/L1_project/philosophy.md. This file remains for backward reference.
Evidence:
- README.md
- docs/L3_implementation/specification.md
- slack_tmux_bridge.py
- goslack.py
- requirements.txt
- requirements-dev.txt
- .env.sample
- launchd/com.slack_tmux_bridge.plist

# プロジェクトの目的 / ゴール
- Slack から tmux 上の Gemini CLI を安全に操作し、同スレッドへ結果を返せるようにする。
- tmux セッションを維持し、外出先でも継続的に作業できる体験を提供する。

# 解決する課題 / ユーザー
- SSH や tmux への直接アクセスが難しい状況でも、Slack から操作したい利用者。
- 1〜少人数で複数の tmux ペイン（= 複数エージェント）を同時運用するチーム。

# 非ゴール
- Slack 以外のチャットプラットフォーム対応。
- Gemini 以外のCLIエージェントの公式サポート（現状は Gemini CLI 前提）。
- 高負荷・大規模チームでのマルチテナント運用。

# 成功指標
- 不明（定量的なKPI/SLIの記載なし）。

# 設計原則
- 安全性: コマンドフィルタと二重起動防止で誤操作を抑止する。
- 継続性: tmux セッションを維持し、コンテキストを保持する。
- UX: 数字は即時実行、テキストは確認ボタンで実行し誤送信を防ぐ。
- 可観測性: イベント監視とヘルスチェックで接続状態を把握する。

# コーディング規約の方針
- Python 3系を前提としたシンプルなスクリプト構成。
- CLI/ボット両方で明示的なエラーハンドリング（Slack通知/標準出力）。
- 依存関係は最小限（slack_bolt / slack_sdk / python-dotenv）。

# 依存関係・バージョン方針
- 依存は requirements.txt / requirements-dev.txt で管理する（pip/venv）。
- バージョン固定方針は不明（requirements.txt にピン留めなし）。

# セキュリティ方針（最低限）
- Slack Bot/App トークンは .env で管理し、リポジトリに含めない。
- コマンド allowlist/denylist により危険コマンドを遮断する。
- tmux ペインの再解決/不一致検知で誤送信を回避する。

# 運用方針
- 起動は手動実行または launchd によるデーモン化を選択可能。
- 監視: EVENT_HEALTH_* と CHANNEL_IDLE_NOTIFY_* で無応答検知と通知を行う。
- ログ: LOG_LEVEL で Slack SDK/Bolt のログ出力を制御する。
- バックアップ: 不明（active_sessions.json の保全方針の記載なし）。
