# Slack AI Notifier (Gemini-Tmux Bridge)

このプロジェクトは `tmux` で常駐している Gemini CLI セッションと Slack をブリッジし、Slack から Gemini にプロンプトやコマンドを送信し、スレッドに結果を受け取るしくみです。

## 機能

- **Slack 連携**: Bolt Socket Mode でチャンネルメッセージを受信し、返信やスラッシュコマンドを提供します。
- **スマート監視**: `tmux` 出力を 1 秒ごとにキャプチャし、3 秒の無変化（または権限プロンプト）で完了とみなしてレスポンスを投稿します。
- **事前クリアと出力整形**: 各操作前に `tmux clear-history` + `Ctrl+L` を実行し、実行プロンプト (`> [prompt]`) 以降だけを抽出します。
- **入力エルゴノミクス**: 数字メッセージは自動実行、テキストは「実行」ボタンで Enter、スラッシュコマンドはメニューで送信します。
- **コマンドフィルタ**: allowlist + denylist ルールと、デフォルトで `rm` をブロックする仕組み。
- **単一起動ガード**: PID ファイルで Socket Mode の二重接続を防ぎます。
- **ヘルス監視**: キャッシュ/スナップショットを定期クリーンし、イベント停止をログ・通知・再起動で検出。
- **セッション可視化**: `/sessions` で接続中のチャンネル名とディレクトリを一覧表示できます。
- **アイドル通知**: チャンネルが無反応の状態が続いたら定期的に通知します。
- **重複クリーンアップ**: 同一ペインの重複登録を定期検知し、片方を切断して通知します。
- **不一致ガード**: 保存済みペインと現在のペインが違う場合、確認して更新または切断します。

## 要件

- Python 3.x
- `tmux`
- Gemini CLI (`gemini`)
- Socket Mode 用 Slack App（Bot トークン `xoxb-…`、App レベルトークン `xapp-…`）

## セットアップ

### 1. 依存関係のインストール

仮想環境（例: `python -m venv venv && source venv/bin/activate`）を作成し、依存ライブラリをインストールします。

```bash
pip install -r requirements.txt
```

### 2. Slack アプリの作成

1. [https://api.slack.com/apps](https://api.slack.com/apps) にアクセスし、"From scratch" で新規アプリを作成。ワークスペースを選択。
2. **Socket Mode** を有効にして App-Level Token (`xapp-…`) を生成・控えます。
3. **OAuth & Permissions** の Bot Token Scopes に以下を追加：
   - `chat:write`
   - `channels:history`
   - 必要なら `groups:history`, `im:history`, `mpim:history`
4. **Event Subscriptions** をオンにし、bot イベントに `message.channels`（必要なら `message.groups` / `message.im` / `message.mpim`）を追加。
5. **OAuth & Permissions** に戻り「Install to Workspace」で Bot をインストールし、`xoxb-…` トークンを控えます。
6. 対象チャンネルに Bot を招待（`/invite @AppName`）。
7. `goslack.py` は「作業ディレクトリ名 = チャンネル名」を Slack API で解決するため、ディレクトリ名をチャンネル名に合わせる（または `ai-studio-01/02/03` を用意する）ことを推奨します。

### 3. 環境変数

`.env.sample` を `.env` にコピーし、必要な値を設定します。

```bash
cp .env.sample .env
```

- `SLACK_BOT_TOKEN`: `xoxb-…` Bot トークン
- `SLACK_APP_TOKEN`: `xapp-…` Socket Mode 用 App トークン
- `TARGET_CHANNEL_ID`: 旧設定（現行実装では未使用）
- `LOG_LEVEL`: ロギングレベル（`INFO`, `DEBUG` など）
- `TMUX_BIN`: tmux の絶対パス。PATH に `tmux` が無い場合（launchd など）に必要。
- `OUTPUT_DIFF_MODE`: 出力差分方式（`replace` または `suffix`）
- `EVENT_HEALTH_TIMEOUT`: 指定秒数イベントがこなければ警告（`0` で無効）
- `EVENT_HEALTH_ACTION`: ヘルスチェックの挙動（`log`, `exit`, `restart`）
- `EVENT_HEALTH_RESTART_COOLDOWN_SEC`: 再起動時のクールダウン（秒）
- `EVENT_HEALTH_NOTIFY`: `1` でチャネル通知を有効化
- `EVENT_HEALTH_NOTIFY_COOLDOWN_SEC`: 通知間のクールダウン（秒）
- `PROMPT_CACHE_TTL_SEC` / `SNAPSHOT_TTL_SEC`: キャッシュ・スナップショットの保持時間
- `CHANNEL_IDLE_NOTIFY_SEC` / `CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC`: アイドル通知の間隔とクールダウン（チャンネル単位）
- `COMMAND_ALLOWLIST` / `COMMAND_DENYLIST`: カンマ区切りのマッチパターン（`all` で全許可/拒否）

コマンドフィルタの注意点:

- denylist が最優先。デフォルトで `/\brm\b/`（単独の `rm`）をブロックします。
- allowlist は `all` 以外では一致しないとブロックされる。
- `/…/` で囲まれたパターンは正規表現、それ以外は部分一致です。

推奨 denylist 例:

```
sudo,rm -rf,/\brm\b/,mkfs,dd,/\bshutdown\b/,/\breboot\b/,/curl\s+.*\|\s*sh/,/wget\s+.*\|\s*sh/
```

`goslack.py` のセッション制御:

- `goslack.py` は `active_sessions.json` を atomic に書き込み、途中でファイルが壊れるのを防ぎます。
- 同じ tmux ペインを指す別チャネルがあれば、起動時に削除されて現在のチャネルだけが残る仕組みです。
- チャンネルは「作業ディレクトリ名 = チャンネル名」で解決され、見つからない場合は `ai-studio-01/02/03` にフォールバックします。
  - 未使用の `ai-studio-*` を優先し、すべて使用中なら `01 → 02 → 03 → 01 ...` でローテーションします。
- `active_sessions.json` には `pane_id`, `pane`, `dir`, `name`（チャンネル名）を保存します。
- `goslack.py list` で番号付き一覧を表示し（`pane_id` も表示）、`goslack.py rm <番号>` で削除します。
- `goslack.py --add <pane>` で別ペインから指定ペインを登録できます（対象ペインの作業ディレクトリを利用）。
  - 並び順: `ai-studio-01`, `ai-studio-02`, `ai-studio-03` が先頭（番号順）、それ以外が続きます。
  - `ai-studio` 以外はチャンネル名の昇順。名前が無い場合は `-` と表示されます。
  - `goslack.py rm <番号>` は番号が範囲外の場合にエラー終了します。

出力例（`goslack.py list`）:

```
num	channel_name	pane	pane_id	dir
1	ai-studio-01	1:1.0	%1	/Users/you/WORKSPACE/ai-studio-01
2	ai-studio-02	1:2.0	%2	/Users/you/WORKSPACE/ai-studio-02
3	ai-studio-03	1:3.0	%3	/Users/you/WORKSPACE/ai-studio-03
4	project-x	2:0.0	%4	/Users/you/WORKSPACE/project-x
```

削除例:

```
python goslack.py rm 4
```

### 4. スクリプトを準備

- `send_enter.sh` には実行権限を付与してください。

```bash
chmod +x send_enter.sh
```

- `run_slack_bridge.sh` は廃止し、launchd から `python3` を直接起動します。

### 5. macOS Launchd（任意）

このリポジトリには `launchd/com.slack_tmux_bridge.plist` を同梱しています。`~/Library/LaunchAgents` にコピーし、必要に応じてパスを修正してください。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.slack_tmux_bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>TMUX_BIN=/usr/local/bin/tmux</string>
    <string>python3</string>
    <string>/Users/you/WORKSPACE/slack_tmux_bridge/slack_tmux_bridge.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/you/Library/Logs/slack_tmux_bridge.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/you/Library/Logs/slack_tmux_bridge.log</string>
</dict>
</plist>
```

環境に合わせてパスを修正し、次のコマンドでコピー・起動/停止します:

```bash
cp launchd/com.slack_tmux_bridge.plist ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
launchctl load ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
launchctl unload ~/Library/LaunchAgents/com.slack_tmux_bridge.plist
```

補助スクリプトも利用できます:

```bash
./launchd/launchd_ctl.sh install
./launchd/launchd_ctl.sh start
./launchd/launchd_ctl.sh stop
./launchd/launchd_ctl.sh restart
./launchd/launchd_ctl.sh status
./launchd/launchd_ctl.sh log
```

`launchctl list | grep slack_tmux_bridge` で状態を確認できます。

## インストール＆運用

### 1. クローンと構成

```bash
git clone <repo> slack_tmux_bridge
cd slack_tmux_bridge
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env
```

`.env` に Slack トークンや各種設定値を記入してください。

### 2. tmux と goslack

1. `tmux new-session -s gemini` などで Gemini を起動。
2. 対象ペイン内で `python goslack.py` を実行し、チャンネルとペインの対応を `active_sessions.json` に書き込みます。チャンネルは作業ディレクトリ名から解決し、見つからない場合は `ai-studio-01/02/03` にフォールバックします。他のチャンネルが同じペインを参照している場合は自動で削除されます。
   - `goslack.py` は `pane_id` を保存し、送信時に現在のターゲットへ解決するため、ウインドウ番号の変更でも誤送信しません。
   - ペインが既に占有されている場合は、別ペインから `python goslack.py --add 1:2.0` を実行して登録できます。

### 3. ブリッジを起動

```bash
source venv/bin/activate
python slack_tmux_bridge.py
```

ターゲットはデフォルト `0:0.0`。`1:2.0` などを引数に渡して別ペインを指定できます。

- `LOG_LEVEL=DEBUG` で Socket Mode やヘルス関連のログを `bot.log` に出力。
- `OUTPUT_DIFF_MODE` を切り替えて差分抽出の挙動を試す。
- `run_slack_bridge.sh` は不要になりました（launchd から `python3` を直接起動します）。

### 4. Slack の手順

1. チャンネルにメッセージを送信。
   - テキスト: 表示される「実行（Enter）」で確定。
   - 数字のみ: 自動で実行されます。
   - `/sessions`（または `\/sessions`）で接続中のチャンネル名とディレクトリを表示。
   - `/dir`（または `\/dir`）で接続中ディレクトリを表示。
   - `/now`（または `\/now`）で「監視を継続」と同じ処理を実行し、最新状態を取得。
   - `pane_id` から解決したペインが保存値と異なる場合、確認メッセージが出ます。
2. ブリッジは Gemini の出力完了を待ってスレッドで返信します（3,000文字ごとに分割）。3 秒無変化なら完了として投稿します。監視は 180 秒でタイムアウトします。

### 5. ヘルス監視

- `_maintenance_worker` が `PROMPT_CACHE_TTL_SEC` / `SNAPSHOT_TTL_SEC` に従ってキャッシュとスナップショットを削除します。
- `_maintenance_worker` は同一ペインの重複登録も検知し、片方を切断して通知します。
- `_event_health_worker` が `EVENT_HEALTH_TIMEOUT` 秒イベントがないチャンネルを監視し、`EVENT_HEALTH_ACTION` に応じてログ出力・終了・再起動します。
- `EVENT_HEALTH_NOTIFY=1` なら静かなチャンネルに通知を投げ、`EVENT_HEALTH_NOTIFY_COOLDOWN_SEC` で通知間隔を調整します。
- 再起動は `EVENT_HEALTH_RESTART_COOLDOWN_SEC` で連続を防止します。
- `CHANNEL_IDLE_NOTIFY_SEC` を設定すると、一定時間無反応のチャンネルに定期通知します。

## 運用フェーズ

1. **最小構成**: `.env` 設定後に `slack_tmux_bridge.py` を直接起動。トライアル用。
2. **推奨構成**: `goslack.py` でマッピングを登録してから橋を起動し、複数チャネル/ペイン環境でも整合性を保ちます。
3. **デーモン構成**: `launchd` で常駐させ、`goslack.py` で `active_sessions.json` を維持しながら自動的に再起動させます。

## ユーティリティ

- `/sessions`: 接続中のチャンネル名とディレクトリを一覧表示。
- `/dir`: 接続中ディレクトリを表示。
- `/now`: 監視を再開し、最新の Gemini 出力を取得。
- `goslack.py`: 現在の tmux ペインにチャンネルを紐づけ、同一ペインの古い記録を削除。`list`/`rm`（番号指定）や `--add` で管理可能。

出力例（`/sessions`）:

```
- ai-studio-01 → /Users/you/WORKSPACE/ai-studio-01
- project-x → /Users/you/WORKSPACE/project-x
```

出力例（`/dir`）:

```
📁 接続中のディレクトリ: /Users/you/WORKSPACE/project-x
```
- `run_slack_bridge.sh`: 旧ラッパー（現在は未使用）。
