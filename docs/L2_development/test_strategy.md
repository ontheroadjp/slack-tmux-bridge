Status: Draft
Last updated: 2026-02-04
Evidence:
- requirements-dev.txt:1
- test/test_goslack_cli.py:1-51
- test/test_goslack_main.py:1-227
- test/test_goslack_sessions.py:1-45
- test/test_launchd_assets.py:1-19
- test/test_slack_bridge_command_filter.py:1-39
- test/test_slack_bridge_monitor.py:1-112
- test/test_slack_bridge_sessions.py:1-624
- test/test_slack_bridge_tmux_io.py:1-200

# テストピラミッド（unit/integration/e2e）
- Unit 相当: goslack と slack_tmux_bridge の関数/挙動単体テストが中心。根拠: test/ 配下の各テストファイル
- Integration/E2E: 外部 Slack/tmux との統合テストの設定は未確認。根拠: リポジトリ内に E2E 設定なし

# 対象範囲と責務分担
- goslack.py: セッション管理、CLI 動作、並び順の検証。根拠: test/test_goslack_cli.py:1-51 / test/test_goslack_main.py:20-227 / test/test_goslack_sessions.py:15-45
- slack_tmux_bridge.py: コマンドフィルタ、セッション処理、tmux I/O、/now や /dir 等のコマンド挙動。根拠: test/test_slack_bridge_command_filter.py:9-39 / test/test_slack_bridge_sessions.py:10-624 / test/test_slack_bridge_tmux_io.py:1-200 / test/test_slack_bridge_monitor.py:22-112
- launchd: plist / スクリプトの資材検証。根拠: test/test_launchd_assets.py

# 実行コマンド
- `pytest`。根拠: requirements-dev.txt:1

# CI上の実行方針
- GitHub Actions の CI で `pytest` を実行する。根拠: .github/workflows/ci.yml:1-20

# モック/スタブ方針
- Slack API / tmux / スレッド等は monkeypatch で差し替えるテストが中心。根拠: test/test_slack_bridge_sessions.py:10-624 / test/test_slack_bridge_monitor.py:22-112 / test/test_goslack_main.py:20-127
