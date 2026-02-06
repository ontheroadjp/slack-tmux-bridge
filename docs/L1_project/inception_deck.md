Status: Draft
Last updated: 2026-02-04
Evidence:
- README.md:1-19
- README.md:40-53
- slack_tmux_bridge.py:13-15
- slack_tmux_bridge.py:143-187
- slack_tmux_bridge.py:531-588
- slack_tmux_bridge.py:899-1015
- slack_tmux_bridge.py:1323
- goslack.py:267-283

# 我々はなぜここにいるのか
- Slack を UI として tmux 上の Gemini CLI を操作し、同じスレッドで結果を確認できる運用を実現するため。根拠: README.md:1-3,7-11

# エレベーターピッチ
Slack 上のメッセージを tmux の Gemini CLI に安全に届け、同じスレッドで結果を確認するためのブリッジ。Socket Mode でイベントを受け、チャンネルと tmux ペインの対応表を維持する。根拠: README.md:1-11,40-53 / slack_tmux_bridge.py:13-15,1323 / goslack.py:267-283

# プロダクトボックス（簡易）
- Slack で操作し、結果はスレッドで確認する。根拠: README.md:1-11
- 数字は即時実行、テキストはボタンで実行を確定する。根拠: README.md:9 / slack_tmux_bridge.py:899-969
- allowlist/denylist によるコマンドフィルタを持つ。根拠: README.md:11 / slack_tmux_bridge.py:143-187
- ヘルスチェックでイベント停止を検知し、必要に応じて通知/再起動する。根拠: README.md:13 / slack_tmux_bridge.py:542-588

# やらないこと / 未確認
- 他チャットツール対応や大規模マルチテナント運用の明示は未確認。根拠: README.md に明記なし

# 主要ペルソナ / 利用シナリオ
- Slack から Gemini CLI に指示を送り、同じスレッドで結果を確認したい利用者。根拠: README.md:1-3

# ソリューション概要
- Slack Bolt Socket Mode でイベントを受信する。根拠: README.md:7 / slack_tmux_bridge.py:13-15,1323
- goslack.py がチャンネルと tmux ペインの対応表を管理する。根拠: README.md:84-93 / goslack.py:267-283
- slack_tmux_bridge.py がコマンドフィルタ、実行制御、出力取得を行う。根拠: slack_tmux_bridge.py:150-310,516-583

# リスク / 不確実性
- Socket Mode の無反応検知や復旧に依存する。根拠: slack_tmux_bridge.py:542-588
- tmux ペイン再解決に失敗した場合は実行を中止する必要がある。根拠: slack_tmux_bridge.py:202-219,1011-1015

# 優先順位（根拠付き）
1. 安全性（コマンドフィルタ）: 仕様・実装で明示。根拠: README.md:11 / slack_tmux_bridge.py:143-187
2. 継続稼働（イベント監視・再起動）: 監視とアクションが実装されている。根拠: README.md:13 / slack_tmux_bridge.py:542-588
3. UX（数字即時/テキスト確認）: 操作分岐が実装されている。根拠: README.md:9 / slack_tmux_bridge.py:899-969

# 次に決めるべきこと / 未確認
- KPI/SLI の定義は未確認。根拠: README.md に明記なし
- バックアップ/復旧方針（active_sessions.json の保全）は未確認。根拠: README.md に明記なし
- 依存関係のバージョン固定方針は未確認。根拠: requirements.txt にピン留めなし
