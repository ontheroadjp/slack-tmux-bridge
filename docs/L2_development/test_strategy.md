Status: Draft
Last updated: 2026-02-02
Evidence:
- requirements-dev.txt:1
- test/test_goslack_cli.py:1-200
- test/test_goslack_main.py:1-200
- test/test_goslack_sessions.py:1-200
- test/test_launchd_assets.py:1-200
- test/test_slack_bridge_command_filter.py:1-200
- test/test_slack_bridge_monitor.py:1-200
- test/test_slack_bridge_sessions.py:1-200
- test/test_slack_bridge_tmux_io.py:1-200

# テストピラミッド（unit/integration/e2e）
- Unit 相当: goslack と slack_tmux_bridge の関数/挙動単体テストが中心。根拠: test/ 配下の各テストファイル
- Integration/E2E: 外部 Slack/tmux との統合テストの設定は未確認。根拠: リポジトリ内に E2E 設定なし

# 対象範囲と責務分担
- goslack.py: セッション管理、CLI 動作、並び順の検証。根拠: test/test_goslack_*.py
- slack_tmux_bridge.py: コマンドフィルタ、監視、セッション処理、tmux I/O。根拠: test/test_slack_bridge_*.py
- launchd: plist / スクリプトの資材検証。根拠: test/test_launchd_assets.py

# 実行コマンド
- `pytest`。根拠: requirements-dev.txt:1

# CI上の実行方針
- GitHub Actions の CI で `pytest` を実行する。根拠: .github/workflows/ci.yml:1-20

# モック/スタブ方針
- テスト内のモック/スタブ方針は未確認（個別テスト実装に依存）。根拠: test/ 配下の実装
