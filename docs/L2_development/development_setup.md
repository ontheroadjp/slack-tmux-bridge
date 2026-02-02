Status: Draft
Last updated: 2026-02-02
Evidence:
- README.md:20-37
- README.md:54-76
- README.md:114-170
- requirements.txt:1-3
- requirements-dev.txt:1
- .env.sample:1-16
- slack_tmux_bridge.py:22-52
- goslack.py:18-22
- launchd/com.slack_tmux_bridge.plist:1-23
- launchd/launchd_ctl.sh:1-65

# 必要要件
- Python 3.x、tmux、Gemini CLI、Slack App の Bot/App トークンが必要。根拠: README.md:20-25
- 依存ライブラリは slack_bolt / slack_sdk / python-dotenv。根拠: requirements.txt:1-3

# 初期セットアップ手順
1. 仮想環境を作成し依存関係をインストールする。根拠: README.md:29-37
2. `.env.sample` を `.env` にコピーし、トークン等を設定する。根拠: README.md:54-60 / .env.sample:1-16
3. tmux 内で Gemini CLI を起動する。根拠: README.md:189-193
4. 対象ペインで `python goslack.py` を実行し、チャンネルとペインを紐付ける。根拠: README.md:189-196 / goslack.py:285-359
5. `python slack_tmux_bridge.py` を起動する。根拠: README.md:197-203

# 環境変数一覧
`.env.sample` および実装に基づく。
- SLACK_BOT_TOKEN
- SLACK_APP_TOKEN
- TARGET_CHANNEL_ID（現行実装では使用箇所が未確認）
- LOG_LEVEL
- TMUX_BIN
- EVENT_HEALTH_TIMEOUT
- EVENT_HEALTH_ACTION
- EVENT_HEALTH_RESTART_COOLDOWN_SEC
- EVENT_HEALTH_NOTIFY
- EVENT_HEALTH_NOTIFY_COOLDOWN_SEC
- PROMPT_CACHE_TTL_SEC
- CHANNEL_IDLE_NOTIFY_SEC
- CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC
- PERMISSION_WATCH_SEC
- PERMISSION_WATCH_INTERVAL_SEC
- PERMISSION_WATCH_PATTERN
- COMMAND_ALLOWLIST
- COMMAND_DENYLIST
根拠: .env.sample:1-16 / slack_tmux_bridge.py:22-52 / goslack.py:20-22

# 開発コマンド一覧
| コマンド | 説明 | 根拠 |
| --- | --- | --- |
| `python -m venv venv` | 仮想環境の作成 | README.md:33-35 |
| `source venv/bin/activate` | 仮想環境の有効化 | README.md:34-35 |
| `pip install -r requirements.txt` | 依存関係のインストール | README.md:36-37 |
| `python slack_tmux_bridge.py` | ブリッジの起動 | README.md:197-203 |
| `python goslack.py` | ペインとチャンネルの登録 | README.md:189-193 |
| `python goslack.py list` | セッション一覧 | README.md:96-104 |
| `python goslack.py rm <number>` | セッション削除 | README.md:106-110 |
| `pytest` | テスト実行 | requirements-dev.txt:1 |

# テスト/リント/フォーマット手順
- テスト: `pytest`。根拠: requirements-dev.txt:1 / test/ 配下
- リント/フォーマット: 設定ファイルは未確認。根拠: リポジトリ内に該当設定なし

# デバッグ方法
- `LOG_LEVEL=DEBUG` で Slack SDK/Bolt の詳細ログを出す。根拠: README.md:206 / slack_tmux_bridge.py:60-71
- `/now` で現在の tmux 出力を単発取得する。根拠: README.md:215 / slack_tmux_bridge.py:674-681,787-800

# macOS launchd での常駐運用
- `launchd/com.slack_tmux_bridge.plist` と `launchd/launchd_ctl.sh` を使用可能。根拠: README.md:123-170 / launchd/com.slack_tmux_bridge.plist:1-23 / launchd/launchd_ctl.sh:1-65
