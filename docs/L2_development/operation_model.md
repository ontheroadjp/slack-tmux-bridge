Status: Active
Last updated: 2026-06-11
Evidence:
- README.md:29-37
- README.md:189-210
- .github/workflows/ci.yml:15-23
- requirements.txt:1-3
- requirements-dev.txt:1
- scripts/test_now.sh:1-20

# 運用モデル（ローカル起動・テスト・デプロイ）

## 初期セットアップ

```bash
# 1. 仮想環境作成・有効化
python -m venv venv
source venv/bin/activate

# 2. 依存インストール
pip install -r requirements.txt      # 本番依存
pip install -r requirements-dev.txt  # 開発依存（pytest）

# 3. 環境変数設定
cp .env.sample .env
# .env を編集して SLACK_BOT_TOKEN / SLACK_APP_TOKEN を設定する
```

根拠: README.md:29-37 / README.md:54-60

## ブリッジ起動（手動）

```bash
# 1. tmux ペインで AI CLI を起動
tmux new-session -s gemini
gemini  # または codex 等

# 2. 同ペイン（または別ペイン）でセッションを登録
python goslack.py
# カレントディレクトリ名で Slack チャンネルを自動解決する

# 3. ブリッジを起動
python slack_tmux_bridge.py
```

根拠: README.md:189-210

## セッション管理コマンド

| コマンド | 説明 | 根拠 |
|---------|------|------|
| `python goslack.py` | カレントディレクトリ名でチャンネルを解決して登録 | goslack.py:245-260 |
| `python goslack.py --add 1:2.0` | 別ペインを指定して登録 | README.md:201 |
| `python goslack.py list` | 登録済みセッション一覧 | README.md:96-113 |
| `python goslack.py rm <number>` | 番号でセッション削除 | README.md:106-110 |

## テスト実行

```bash
# 全テスト
pytest

# /now 監視テストのみ（venv Python 使用）
./scripts/test_now.sh
```

根拠: requirements-dev.txt:1 / .github/workflows/ci.yml:22-23 / scripts/test_now.sh:1-20

注: `scripts/test_now.sh` は `test/test_slack_bridge_sessions.py` を `-k now` で実行する。
パス参照が `test/` だが実際のテストディレクトリは `tests/`（末尾 s あり）。
根拠: scripts/test_now.sh:20

## macOS launchd デーモン起動

```bash
# plist をコピーして起動
cp launchd/com.slack_tmux_bridge.plist ~/Library/LaunchAgents/
# plist 内のパスを自環境に合わせて編集後:
./launchd/launchd_ctl.sh install
./launchd/launchd_ctl.sh start

# 管理コマンド
./launchd/launchd_ctl.sh stop
./launchd/launchd_ctl.sh status
./launchd/launchd_ctl.sh log
```

根拠: README.md:123-170 / launchd/launchd_ctl.sh:1-65

## 環境変数（主要）

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `SLACK_BOT_TOKEN` | 必須 | Bot トークン `xoxb-…` |
| `SLACK_APP_TOKEN` | 必須 | App Level トークン `xapp-…` |
| `TMUX_BIN` | `tmux` | tmux バイナリのフルパス（launchd 等で PATH が効かない場合に指定） |
| `LOG_LEVEL` | `INFO` | ログレベル（DEBUG でデバッグ出力増加） |
| `EXECUTE_RESULT_MODE` | `poll` | `poll` / `notify` / `both` |
| `NOTIFY_INGRESS_ENABLED` | `0` | notify ingress を有効化するか |

全環境変数の詳細は `.env.sample` と `docs/L2_development/development_setup.md` を参照。

## デバッグ

```bash
LOG_LEVEL=DEBUG python slack_tmux_bridge.py
```

根拠: README.md:206

## 未確認事項
- `scripts/test_now.sh:20` で参照される `test/test_slack_bridge_sessions.py` は実在しない（実際は `tests/test_slack_bridge_sessions.py`）。スクリプト自体が壊れている可能性がある。
  確認: `bash scripts/test_now.sh` を実行して確認する。
