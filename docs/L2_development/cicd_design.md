Status: Draft
Last updated: 2026-02-02
Evidence:
- .github/workflows/ci.yml:1-20
- requirements.txt:1-3
- requirements-dev.txt:1

# CI/CD の目的
- 変更時に pytest を実行し、基本的なリグレッションを検出する。根拠: .github/workflows/ci.yml:1-20

# CI の構成
- GitHub Actions を使用。根拠: .github/workflows/ci.yml:1-20
- `push` と `pull_request` で実行。根拠: .github/workflows/ci.yml:3-6
- Python 3.11 を使用。根拠: .github/workflows/ci.yml:12-14
- `requirements.txt` と `requirements-dev.txt` をインストールして `pytest` を実行。根拠: .github/workflows/ci.yml:15-20

# 未確認事項
- デプロイの自動化は未確認（ワークフローに記載なし）。根拠: .github/workflows/ci.yml:1-20
