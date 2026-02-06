- README.md と docs/L3_implementation/specification.md を読んでこのプロジェクトの内容を理解します
- slack_tmux_bridge.py と goslack.py を読んで仕様との矛盾点があれば指摘をします
- 想像や憶測に基づいた作業は一切禁止します
- 全ての作業はドキュメントの仕様に基づいて行います
- ユーザーからの指示がドキュメントと相違、矛盾がある場合にはそれを指摘します
- 堅牢性、セキュリティー、UX の観点からより良い実装があればそれを提案します

## プロジェクト設計ドキュメント

### 📋 プロジェクト要件
- `docs/L1_project/philosophy.md`
- `docs/L1_project/inception_deck.md`

### 🏗️ 技術設計ドキュメント
- `docs/L2_development/architecture_design.md`
- `docs/L2_development/development_setup.md`
- `docs/L2_development/test_strategy.md`
- `docs/L2_development/cicd_design.md`

### 🧩 実装仕様サマリ
- `docs/L3_implementation/specification_summary.md`

### クイックリファレンスマップ
| タスク | 主要ドキュメント |
|------|----------------|
| 新機能の追加 | architecture_design → specification_summary |
| APIエンドポイント作成 | api_design → specification_summary |
| DB変更 | database_design → specification_summary |
| 開発環境構築 | development_setup |

## Custom / Command の使い分け（AI向けルール）

- init-docs.md: repo の実態把握と設計ドキュメント生成。最初に使う。
- init-test.md: テスト基盤初期化。commands.test を確定。
- init-git.md: git 基盤初期化。ワーキングディレクトリをクリーンに保つ。
- fix.md: バグ修正専用。init-docs / init-test 完了が前提。
- change.md: 既存仕様・挙動の変更。
- feature.md: 新規機能実装。

※ custom / command は、単一のコードブロックで定義されたテキストのみを指す。
※ コードブロック外の文章は、実行・登録対象ではない。
※ AI は custom / command を自動実行しない。
  指示内容に応じて、使用すべき /command を提案・要求するために本表を用いる。
