Status: Draft
Last updated: 2026-02-04
Evidence:
- README.md:1-19
- README.md:21-26
- slack_tmux_bridge.py:143-187
- slack_tmux_bridge.py:531-588
- slack_tmux_bridge.py:899-969
- goslack.py:267-283
- requirements.txt:1-3

# プロジェクトの目的 / ゴール
- Slack を UI として、tmux 上の Gemini CLI へ指示を送り、同じスレッドで結果を確認できる運用を実現する。根拠: README.md:1-3,7-11
- tmux セッションを維持し、外出先からでも継続的に作業できる体験を提供する。根拠: README.md:1-3

# 解決する課題 / 想定ユーザー
- SSH や tmux への直接アクセスが難しい環境でも、Slack 経由で AI CLI を操作したい利用者。根拠: README.md:1-3
- 1チャンネル⇔1ペインを維持しながら複数ペイン運用したい利用者。根拠: goslack.py:267-283

# 主要な設計原則
- 安全性: allowlist/denylist によるコマンド制御を行う。根拠: slack_tmux_bridge.py:143-187
- 継続性: tmux セッションを前提とし、セッション情報を active_sessions.json で保持する。根拠: goslack.py:267-283
- UX: 数字は自動実行、テキストはボタンで実行を確定する。根拠: slack_tmux_bridge.py:899-969
- 可観測性: イベント監視・プロンプトキャッシュの維持や通知を行う。根拠: slack_tmux_bridge.py:531-588

# 前提条件 / 依存
- Python 3.x、tmux、Gemini CLI、Slack App の Bot/App トークンが必要。根拠: README.md:21-26
- 依存ライブラリは slack_bolt / slack_sdk / python-dotenv を使用。根拠: requirements.txt:1-3

# 非ゴール / 未確認
- 非ゴールやスコープ外の明示的な記載は未確認。根拠: README.md に明記なし
- KPI/SLI 等の成功指標は未確認。根拠: README.md に明記なし
