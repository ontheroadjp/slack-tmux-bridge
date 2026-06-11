Status: Active
Last updated: 2026-06-11
Evidence:
- .github/workflows/ci.yml:1-24
- requirements.txt:1-3
- requirements-dev.txt:1

# 整合性確認の観点と手順

## 目的
コード変更・リファクタ・依存更新後に、実装とドキュメントの乖離を検出する。

## チェックリスト

### 1. CI が通ること（最優先）
```bash
pytest
```
根拠: .github/workflows/ci.yml:22-23

### 2. エントリポイントが起動すること
```bash
python slack_tmux_bridge.py --help 2>&1 | head -5
# または
python -c "import slack_tmux_bridge"
```
根拠: slack_tmux_bridge.py:1-30

### 3. goslack.py が動作すること
```bash
python goslack.py list
```
根拠: goslack.py:164-205

### 4. notify サブコマンドが存在すること
```bash
python slack_tmux_bridge.py notify --help 2>&1 | head -5
```
根拠: docs/L2_development/notify_design.md / slack_tmux_bridge.py（notify サブコマンド実装）

### 5. docs/.ai/repo.profile.json のコマンド確認
`docs/.ai/repo.profile.json` に定義されたコマンドが全て実体に存在するか確認する:
- `pip install -r requirements.txt` → `requirements.txt` 存在確認
- `pytest` → `requirements-dev.txt` に pytest が定義されていること
- `python slack_tmux_bridge.py` → ファイル存在確認
- `python goslack.py` → ファイル存在確認

### 6. 環境変数の整合性
`.env.sample` に記載の変数が `slack_tmux_bridge.py` の `os.environ.get` で参照されているか確認する。
```bash
grep -o 'os.environ.get("[A-Z_]*"' slack_tmux_bridge.py | sort -u
```

### 7. テストファイルとテスト対象の整合性
`tests/` 内の各テストファイルが参照するモジュールが存在するか確認する。
```bash
pytest --collect-only 2>&1 | head -30
```

## よくある乖離パターン

| 乖離 | 検出方法 |
|------|---------|
| docs の行番号参照が古い | grep でシンボル名を検索して現在行を確認 |
| `.env.sample` 未記載の新変数 | `grep 'os.environ.get' slack_tmux_bridge.py` と `.env.sample` を突合 |
| テストが存在しないファイルを参照 | `pytest --collect-only` |
| goslack.py の `active_sessions.json` スキーマ変更 | `tests/test_goslack_sessions.py` を実行 |

## 未確認事項
- `scripts/test_now.sh` が `test/` を参照しているが実在するのは `tests/` である。スクリプト実行時にエラーになる可能性がある。
  確認: `scripts/test_now.sh` を実行して確認する。
