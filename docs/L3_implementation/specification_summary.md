Status: Draft
Last updated: 2026-02-02
Evidence:
- README.md:1-18
- README.md:84-113
- README.md:208-218
- slack_tmux_bridge.py:32-52
- slack_tmux_bridge.py:150-219
- slack_tmux_bridge.py:264-310
- slack_tmux_bridge.py:516-583
- slack_tmux_bridge.py:640-685
- slack_tmux_bridge.py:892-972
- goslack.py:11-16
- goslack.py:164-205
- goslack.py:245-359
- send_enter.sh:1-8

# 実装全体像（何をするか / なぜそうするか）
本リポジトリは、Slack から tmux 上の Gemini CLI に入力を送り、同じスレッドで結果を確認できる運用を実現する。外部公開不要な Socket Mode で Slack イベントを受け、チャンネルと tmux ペインの対応表を維持することで、1チャンネル⇔1ペインの誤送信を避ける。根拠: README.md:1-18 / goslack.py:245-359

# コンポーネント構成
- `slack_tmux_bridge.py`: Slack イベント受信、コマンドフィルタ、tmux 入力/実行、出力取得、監視を担当。根拠: slack_tmux_bridge.py:150-310,516-583,640-685,892-972
- `goslack.py`: チャンネル↔ペインの対応表 (active_sessions.json) を登録/更新/一覧/削除。根拠: goslack.py:164-205,245-359
- `send_enter.sh`: tmux に Enter を送信するヘルパ。根拠: send_enter.sh:1-8
- `active_sessions.json`: チャンネルID→pane_id/pane/dir/name のマッピング。根拠: goslack.py:267-283

# チャンネルとペインの対応管理（goslack.py）
- 現在のディレクトリ名を Slack チャンネル名として解決し、見つからない場合は `ai-studio-01/02/03` を順にフォールバックする。根拠: README.md:84-113 / goslack.py:245-260
- `pane_id` と `session:window.pane` を保存し、同一ペインの重複登録は削除する。根拠: goslack.py:267-283
- `list` は番号付きでセッションを出力し、`rm <number>` で削除する。根拠: goslack.py:164-205

# Slack 受信 → tmux 実行
- Slack message イベントのみ処理し、未接続チャンネルは無視する。根拠: slack_tmux_bridge.py:892-938
- `pane_id` から現在の tmux target を再解決し、失敗時は送信しない。根拠: slack_tmux_bridge.py:175-219,934-937
- 送信前に allowlist/denylist でコマンドを判定し、危険な入力をブロックする。根拠: slack_tmux_bridge.py:150-168,652-659

# 入力種別と UX
- 数字のみ: 事前に画面/履歴をクリアし、即時実行する。根拠: slack_tmux_bridge.py:264-272,822-843
- テキスト: 入力を tmux に送った後、Slack のボタン操作で Enter を送信する。根拠: slack_tmux_bridge.py:844-890,947-972
- `/sessions` `/dir` `/now` `/ctlc` などのコマンドは即時処理する。根拠: slack_tmux_bridge.py:668-685

# 返信の取り扱い
- 通常の実行結果は AI エージェントがスレッドに返信する前提で、プロンプト末尾に返信指示を付与する。根拠: README.md:10 / slack_tmux_bridge.py:601-607
- `/now` や「👀 Geminiを見る」は tmux 出力を単発取得して返信する。根拠: README.md:215 / slack_tmux_bridge.py:516-583,1143-1163
- 承認要求が発生した場合の見落としを防ぐため、Enter 送信後に tmux 出力を監視して該当パターンが出たらスレッドに抜粋を投稿する。根拠: slack_tmux_bridge.py:415-460,822-843,947-972

# tmux 入出力制御
- 実行前に `tmux clear-history` と `Ctrl+L` を送信し、出力の混在を避ける。根拠: README.md:8 / slack_tmux_bridge.py:264-272
- 出力取得は `capture-pane -p -S -1000` を使用する。根拠: slack_tmux_bridge.py:305-307,516-521

# 監視・保守
- イベント停止を監視し、`log/exit/restart` のアクションを選択可能。根拠: slack_tmux_bridge.py:43-52,465-490
- プロンプトキャッシュの TTL 管理と重複セッションのクリーンアップを行う。根拠: slack_tmux_bridge.py:314-463

# 単一起動制御
- PID ファイルとプロセス一覧で二重起動を防止する。根拠: slack_tmux_bridge.py:73-123

# 実装上の未確認事項
- `TARGET_CHANNEL_ID` の利用箇所は未確認。根拠: .env.sample:1-3 / slack_tmux_bridge.py に参照なし
- CI/CD 設定は未確認（.github/workflows が存在しない）。根拠: リポジトリ内に該当ファイルなし
