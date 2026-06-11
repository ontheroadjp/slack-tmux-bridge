Status: Active
Last updated: 2026-06-11
Evidence:
- README.md:1-19
- slack_tmux_bridge.py:1-100
- goslack.py:1-50
- requirements.txt:1-3
- .github/workflows/ci.yml:1-24

# プロジェクト概要

## 目的
Slack を UI として tmux 上の AI CLI（Gemini、Codex 等）を操作し、
同一 Slack スレッドで結果を確認できるブリッジを提供する。
根拠: README.md:1-3

## 技術スタック

| 項目 | 内容 | 根拠 |
|------|------|------|
| 言語 | Python 3.11 | .github/workflows/ci.yml:12-14 |
| 依存 | slack_bolt, slack_sdk, python-dotenv | requirements.txt:1-3 |
| テスト | pytest | requirements-dev.txt:1 |
| CI | GitHub Actions | .github/workflows/ci.yml:1-24 |
| デプロイ | 手動 または macOS launchd | README.md:114-170 |

## 主要機能一覧

| 機能 | 説明 | 根拠 |
|------|------|------|
| Slack Socket Mode 受信 | Bot/App トークンでイベントを受け、外部公開なしで動作 | README.md:7 / slack_tmux_bridge.py:13-15 |
| tmux 入力・出力取得 | コマンドを tmux ペインへ送信し、出力スナップショットをスレッドへ返信 | README.md:8-9 |
| コマンドフィルタ | allowlist + denylist でコマンドをブロック | README.md:11 / slack_tmux_bridge.py:143-187 |
| 入力種別制御 | 数字は即時実行、テキストはボタン確認後に実行 | README.md:9 |
| セッション管理 (`goslack.py`) | channel ↔ pane マッピングの登録/一覧/削除 | README.md:84-113 |
| 承認プロンプト監視 | Enter 送信後に承認要求パターンを検知してスレッドへ通知 | README.md:13 |
| 単一起動制御 | PID ファイル + プロセス一覧で二重起動を防止 | README.md:12 / slack_tmux_bridge.py:139-188 |
| ヘルスモニタリング | イベント停止を検知し log/exit/restart を選択可能 | README.md:13 |
| notify ingress | Codex 等から HTTP/UDS 経由でターン完了通知を受信しスレッドへ配送 | README.md:292-300 |
| Slack コマンド | `/sessions` `/dir` `/now` `/ctlc` をサポート | README.md:242-247 |
| launchd 対応 | macOS launchd による常駐起動 | README.md:123-170 |

## コンポーネント構成

```
Slack (Socket Mode)
   │
   ▼
slack_tmux_bridge.py  ◄──►  active_sessions.json  ◄────  goslack.py
   │                         tmp/notify_context.json
   ▼
tmux (Gemini / Codex / etc.)
```

根拠: docs/L2_development/architecture_design.md:23-33
