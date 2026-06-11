Status: Active
Last updated: 2026-06-11
Evidence:
- README.md:1-19
- docs/L1_project/philosophy.md:12-32
- docs/L1_project/inception_deck.md:13-47
- slack_tmux_bridge.py:1-30

# プロダクトコンセプト

## 目的
Slack を UI として、`tmux` 上で動作する AI CLI（Gemini、Codex 等）を遠隔操作し、
同一 Slack スレッドで結果を確認できる「ブリッジ」を提供する。

SSH クライアント不要で、外出先・モバイル環境でも長時間 AI セッションを継続できる。
根拠: README.md:1-3 / docs/L1_project/philosophy.md:12-14

## 解決する問題
- tmux への直接アクセスが難しい環境でも、Slack 経由で AI CLI を操作したい
- 1チャンネル ⇔ 1ペインの厳格な対応を維持しながら複数エージェントを同時運用したい
- AI の応答をリアルタイムに Slack スレッドへ受け取りたい

根拠: README.md:7-18 / docs/L1_project/philosophy.md:17-22

## 対象ユーザー
1〜少人数のプライベートチャンネルで複数の tmux ペインを運用する個人・小チーム。
大規模マルチテナント運用は対象外。
根拠: docs/L1_project/pyilosophy.md:22-25

## 設計上の制約（Why が設計を決めた点）
- **Socket Mode 採用**: Slack への HTTP エンドポイント公開が不要。外部公開なしで動作する。
  根拠: README.md:7 / slack_tmux_bridge.py:13-15
- **tmux 前提**: セッション維持が核心要件であるため、tmux を必須とする。他ターミナルマルチプレクサは非対象。
  根拠: README.md:21-26
- **単一ファイル構成**: `slack_tmux_bridge.py` に全機能を集約し、デプロイの複雑さを排除する。
  根拠: slack_tmux_bridge.py（1ファイル 2429 行）
- **active_sessions.json による状態管理**: DB 不要でローカルファイルに channel ↔ pane マッピングを保持する。
  根拠: slack_tmux_bridge.py:39-45 / goslack.py:267-283

## 非ゴール
- Slack 以外のチャットプラットフォーム対応
- 高負荷・大規模チームでのマルチテナント運用
- KPI/SLI の定義（現時点で未設定）

根拠: docs/L1_project/pyilosophy.md:22-28
