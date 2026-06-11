# CLAUDE.md — slack-tmux-bridge

このファイルは AI がこのリポジトリで作業する際の起点。

## このリポジトリについて

Slack を UI として tmux 上の AI CLI（Gemini、Codex 等）を操作するブリッジ。
詳細は以下を参照:
- `docs/L0_concept/concept.md` — WHY・目的・制約
- `docs/L1_project/project_overview.md` — 機能一覧・技術スタック
- `docs/L3_implementation/specification_summary.md` — 実装仕様サマリ

## run / test コマンド

```bash
# 依存インストール
pip install -r requirements.txt
pip install -r requirements-dev.txt

# テスト実行
pytest

# ブリッジ起動
python slack_tmux_bridge.py

# セッション登録
python goslack.py
```

## 設計制約（コード変更前に確認）

- `slack_tmux_bridge.py` は単一ファイル構成を維持する（分割不可）
- コマンドフィルタ（allowlist/denylist）は安全性の核心。変更時は `tests/test_slack_bridge_command_filter.py` を必ず確認
- notify ingress の HTTP transport は `127.0.0.1` バインドを厳守（外部公開禁止）
- `active_sessions.json` の書き込みはアトミック操作を維持する（`goslack.py` の書き込みパターンを踏襲）

## Custom Command の使い分け（AI向けルール）

グローバル `~/.claude/CLAUDE.md` のルールが優先される。このリポジトリへの変更は `/work` を経由すること。

- **docs/* の変更を伴う場合** → task フロー（issue 自動生成 → 実装 → ドラフト PR → `/docs-sync`）
- **docs/* の変更を伴わない場合** → patch フロー（branch + commit → ユーザーが ff-merge）

## 未確認事項（2026-06-11 時点）

- `scripts/test_now.sh` が参照する `test/test_slack_bridge_sessions.py` は存在しない（実在は `tests/`）。実行時にエラーになる可能性あり
- `TARGET_CHANNEL_ID` 環境変数は `.env.sample` に存在するが実装での使用箇所が未確認
- requirements.txt のバージョンピン留め方針は未定
