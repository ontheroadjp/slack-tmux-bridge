Status: Draft
Last updated: 2026-02-04
Evidence:
- README.md:7-18
- docs/L2_development/notify_design.md
- slack_tmux_bridge.py:13-15
- slack_tmux_bridge.py:32-55
- slack_tmux_bridge.py:202-219
- slack_tmux_bridge.py:291-336
- slack_tmux_bridge.py:531-588
- slack_tmux_bridge.py:899-1015
- slack_tmux_bridge.py:1316-1323
- goslack.py:11-16
- goslack.py:164-205
- goslack.py:267-283
- send_enter.sh:1-8

# 全体アーキテクチャ概要
```
Slack (Socket Mode)
   |
   v
slack_tmux_bridge.py  <---->  active_sessions.json  <----  goslack.py
   |
   v
tmux (Gemini CLI)
```
根拠: README.md:7-18 / slack_tmux_bridge.py:13-15,32-55 / goslack.py:267-283

# 主要コンポーネントと責務
- slack_tmux_bridge.py: Slack イベント受信、コマンドフィルタ、tmux への入力/実行、出力取得、イベント監視。根拠: slack_tmux_bridge.py:143-336,531-588,970-1015
- goslack.py: Slack チャンネルと tmux ペインの対応表を作成/更新/一覧/削除。根拠: goslack.py:164-205,267-283
- send_enter.sh: tmux へ Enter を送るヘルパ。根拠: send_enter.sh:1-8
- active_sessions.json: チャンネルID→pane_id/pane/dir/name のマッピング。根拠: goslack.py:267-283
- notify 経路の詳細設計（payload 契約、ingress、配送キュー、再試行）は `docs/L2_development/notify_design.md` を参照。根拠: docs/L2_development/notify_design.md

# ディレクトリ構成の意図
- docs/: プロジェクト設計・仕様ドキュメント。根拠: docs/ 配下
- launchd/: macOS launchd 用の補助スクリプト/設定。根拠: README.md:123-170 / launchd/ 配下
- test/: pytest のテスト群。根拠: test/ 配下
- tmp/: PID/状態ファイルの保存先。根拠: slack_tmux_bridge.py:35-36,1310-1312 / goslack.py:211-213

# データフロー / リクエストフロー
1. Slack の message イベントを受信する。根拠: slack_tmux_bridge.py:970-1015
2. active_sessions.json から channel_id に対応する pane_id を取得する。根拠: slack_tmux_bridge.py:175-206
3. pane_id から現在の tmux target を再解決する。根拠: slack_tmux_bridge.py:212-219
4. allowlist/denylist でコマンドを判定する。根拠: slack_tmux_bridge.py:143-187,732-735
5. 数字は即時実行、テキストはボタンで Enter を送信する。根拠: slack_tmux_bridge.py:899-969

# エラーハンドリング方針
- tmux 操作失敗時はログを出し、必要に応じて Slack へ通知する。根拠: slack_tmux_bridge.py:301-330
- pane_id の再解決ができない場合は送信しない。根拠: slack_tmux_bridge.py:175-219,934-937

# 設計上のトレードオフ
- Socket Mode により外部公開不要だが、イベント停止監視が必要。根拠: slack_tmux_bridge.py:542-588,1323
- 実行結果の投稿を AI エージェントに委譲するため、ブリッジ側は結果投稿を行わない。根拠: slack_tmux_bridge.py:678-683,931-936

# 依存関係境界（レイヤ分割）
- Slack I/O 層: Slack Bolt / Slack SDK を利用。根拠: slack_tmux_bridge.py:13-15 / requirements.txt:1-3
- tmux 操作層: subprocess で tmux コマンドを実行。根拠: slack_tmux_bridge.py:2,264-310
- 状態管理層: active_sessions.json と tmp/ 配下の状態管理。根拠: slack_tmux_bridge.py:32-36,351-405 / goslack.py:23-47,211-213

# スケーラビリティ / パフォーマンス観点
- capture-pane は最大 1000 行で取得する。根拠: slack_tmux_bridge.py:332-336
- 監視系は常駐スレッドで実行される。根拠: slack_tmux_bridge.py:1316-1317

# セキュリティ観点
- コマンド allowlist/denylist による危険操作の制限。根拠: slack_tmux_bridge.py:150-168
- トークンは .env で管理し、リポジトリに含めない。根拠: README.md:54-76 / .env.sample:1-27
