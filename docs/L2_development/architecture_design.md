Status: Draft
Last updated: 2026-02-10
Evidence:
- README.md:7-18
- docs/L2_development/notify_design.md
- slack_tmux_bridge.py:39-45
- slack_tmux_bridge.py:249-272
- slack_tmux_bridge.py:313-330
- slack_tmux_bridge.py:588-623
- slack_tmux_bridge.py:712-754
- slack_tmux_bridge.py:1616-1655
- slack_tmux_bridge.py:1657-1695
- slack_tmux_bridge.py:1725-1743
- slack_tmux_bridge.py:1945-1981
- slack_tmux_bridge.py:1986-2007
- slack_tmux_bridge.py:2087-2281
- slack_tmux_bridge.py:1485-1560
- goslack.py:15-18
- goslack.py:191-231
- goslack.py:294-313
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

# Slack入力方式と正規化
- 入力方式（Slack 側）:
  - message イベント (`@app.event("message")`)
  - action: `send_enter`
  - action: `show_commands`
  - action: `exec_cmd_*`
  - action: `delete_prompt`
  - action: `show_gemini`
  - action: `continue_now_watch`
  - action: `continue_execute_watch`
  - action: `confirm_rebind`
  - action: `cancel_rebind`
- 正規化コンテキスト（bridge 内部）:
  - `source`
  - `channel_id`
  - `thread_ts`
  - `text`
  - `tmux_target`
- 正規化関数:
  - message 経路は `_normalize_message_input` で正規化。
  - action 経路の主要ハンドラ（`send_enter`, `exec_cmd_*`）は `_normalize_action_input` で正規化。
  - 一部 action（`show_commands` など）は現状、`body` 直接参照で処理している。
根拠: slack_tmux_bridge.py:1616-1655,1945-1981,1986-2007,2087-2281

# データフロー / リクエストフロー（共通パイプライン）
1. Slack 入力を受信し、入力種別に応じてコンテキスト化する。根拠: slack_tmux_bridge.py:1616-1655,1945-1981,1986-2007,2087-2281
2. `active_sessions.json` から channel_id に対応する pane_id/接続情報を解決する。未接続チャンネルは処理しない。根拠: slack_tmux_bridge.py:249-272,1945-1981
3. pane_id から現在の tmux target を再解決し、誤送信を防止する。根拠: slack_tmux_bridge.py:249-272
4. メッセージ入力はコマンド判定と allowlist/denylist 判定を通す。根拠: slack_tmux_bridge.py:1725-1743,1697-1723
5. tmux 送信処理は `_send_tmux_text_for_context` / `_execute_enter_for_context` に集約し、入力方式に関係なく `channel_id/thread_ts/tmux_target` を保持して送信する。根拠: slack_tmux_bridge.py:1657-1695,1875-1943,1986-2007,2105-2141
6. 実行後は `EXECUTE_RESULT_MODE` に従って監視投稿（poll）または notify 経路を使ってスレッド返信する。根拠: slack_tmux_bridge.py:1485-1560,588-623,712-754

# エラーハンドリング方針
- tmux 操作失敗時はログを出し、必要に応じて Slack へ通知する。根拠: slack_tmux_bridge.py:301-330
- pane_id の再解決ができない場合は送信しない。根拠: slack_tmux_bridge.py:175-219,934-937

# 設計上のトレードオフ
- Socket Mode により外部公開不要だが、イベント停止監視が必要。根拠: slack_tmux_bridge.py:542-588,1323
- 実行結果投稿には poll と notify の2経路があるため、`both` 運用では重複抑止（dedupe）が必要。根拠: slack_tmux_bridge.py:1086-1123,1485-1560

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
