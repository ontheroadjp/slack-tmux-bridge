Status: Active
Last updated: 2026-06-11
Evidence:
- slack_tmux_bridge.py:32-46
- goslack.py:1-50
- .github/workflows/ci.yml:1-24
- README.md:114-170
- tests/ (全ファイル)
- launchd/
- scripts/

# リポジトリ構造

## トップレベル構成

```
slack-tmux-bridge/
├── slack_tmux_bridge.py   # メインブリッジ（2429行）
├── goslack.py             # セッション登録ツール（405行）
├── send_enter.sh          # tmux Enter 送信ヘルパ
├── active_sessions.json   # チャンネル ↔ ペイン マッピング（実行時生成）
├── requirements.txt       # 本番依存: slack_bolt, slack_sdk, python-dotenv
├── requirements-dev.txt   # 開発依存: pytest
├── .env.sample            # 環境変数テンプレート
├── .env                   # 実際のトークン（.gitignore 済み）
├── docs/                  # 設計ドキュメント
├── tests/                 # pytest テスト群
├── launchd/               # macOS launchd 設定
├── scripts/               # 補助スクリプト
├── tmp/                   # 実行時状態ファイル（PID, notify キュー等）
├── venv/                  # 仮想環境（.gitignore 済み）
└── .github/workflows/     # CI 定義
```

## 各ディレクトリの責務

### `slack_tmux_bridge.py`
Slack Bolt Socket Mode でイベントを受信し、tmux へコマンドを送信して出力を返信するメインブリッジ。
コマンドフィルタ、単一起動制御、イベントヘルスチェック、notify ingress 受信・配送キュー管理をすべて含む単一ファイル構成。
根拠: README.md:7-18 / slack_tmux_bridge.py:1-2429

### `goslack.py`
Slack チャンネルと tmux ペインの対応表（`active_sessions.json`）を作成・更新・一覧・削除するCLIツール。
tmux ペインで直接実行し、カレントディレクトリ名でチャンネルを解決する。
根拠: goslack.py:1-405 / README.md:84-113

### `send_enter.sh`
tmux ペインへ Enter キーを送信する最小ヘルパスクリプト。
`slack_tmux_bridge.py` から subprocess 経由で呼ばれる。
根拠: send_enter.sh:1-8

### `active_sessions.json`
チャンネルID → `{pane_id, pane, dir, name}` のマッピングを保持するランタイム状態ファイル。
`goslack.py` が書き込み、`slack_tmux_bridge.py` が読み込む。
根拠: goslack.py:267-283 / slack_tmux_bridge.py:39-45

### `docs/`
プロジェクト設計・仕様ドキュメント。

```
docs/
├── .ai/repo.profile.json      # AI 用リポジトリプロファイル
├── L0_concept/                # プロダクトコンセプト・設計ポリシー（WHY層）
│   ├── concept.md
│   └── policy.md
├── L1_project/                # プロジェクト全体像
│   ├── project_overview.md
│   ├── repository_structure.md  (本ファイル)
│   ├── inception_deck.md
│   └── philosophy.md
├── L2_development/            # 開発・運用手順
│   ├── architecture_design.md
│   ├── cicd_design.md
│   ├── development_setup.md
│   ├── notify_design.md
│   ├── operation_model.md
│   ├── consistency_checks.md
│   └── test_strategy.md
└── L3_implementation/         # 実装仕様
    ├── specification_summary.md
    └── specification.md
```

### `tests/`
pytest テスト群。Slack API / tmux / スレッドは monkeypatch で差し替える。
根拠: tests/ 配下 / docs/L2_development/test_strategy.md

```
tests/
├── conftest.py
├── test_goslack_cli.py          # goslack.py CLI 操作テスト
├── test_goslack_main.py         # goslack.py メインロジックテスト
├── test_goslack_sessions.py     # セッション管理テスト
├── test_launchd_assets.py       # launchd 資材検証
├── test_slack_bridge_command_filter.py   # コマンドフィルタテスト
├── test_slack_bridge_mode_dedupe.py      # poll/notify 重複抑止テスト
├── test_slack_bridge_monitor.py          # 監視ワーカーテスト
├── test_slack_bridge_notify_ingress.py   # notify ingress テスト
├── test_slack_bridge_sessions.py         # セッション処理テスト
└── test_slack_bridge_tmux_io.py          # tmux 入出力テスト
```

### `launchd/`
macOS launchd による常駐起動のための設定ファイルと管理スクリプト。
根拠: README.md:123-170

```
launchd/
├── com.slack_tmux_bridge.plist  # launchd ジョブ定義
└── launchd_ctl.sh               # install/start/stop/status/log 管理スクリプト
```

根拠: ls -la launchd/

### `scripts/`
補助スクリプト置き場。

```
scripts/
└── test_now.sh   # /now 監視テストの短縮実行スクリプト（venv Python で pytest を実行）
```

根拠: scripts/test_now.sh:1-20

### `tmp/`
実行時状態ファイルの保存先。

```
tmp/
├── slack_tmux_bridge.pid         # 単一起動制御用 PID ファイル
├── notify_context.json           # 最新の channel/thread コンテキスト
├── notify_delivery_dedupe.json   # notify 重複抑止キー
└── notify_delivery_queue.json    # notify 配送キュー（永続化）
```

根拠: slack_tmux_bridge.py:35-46

## 未確認事項
なし（2026-06-11 時点で全パスを実体確認済み）
