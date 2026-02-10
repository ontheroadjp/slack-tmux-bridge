# Slack AI Notifier (Gemini‑Tmux Bridge) 仕様書

本書は `slack_tmux_bridge.py` / `goslack.py` の**現行実装**に基づく詳細仕様です。プロジェクト未経験のエンジニアがこの文書だけで実装・運用できることを目的に、**「何をするか」だけでなく「なぜそうしているか」**も併記しています。

---

## 1. 目的とユースケース

### 1.1 目的
- Slack チャンネルから Gemini CLI を操作し、結果を同スレッドに返す。
- tmux セッションを継続利用し、モバイル/外出先でも「バイブコーディング」を継続できるようにする。

### 1.2 想定ユースケース
- 1人〜少人数のプライベートチャンネルで、複数の tmux ペイン（= 複数エージェント）を同時運用。
- 1チャンネル⇔1ペインの対応を厳格に維持し、混線を防止。

### 1.3 設計方針（Why）
- **Slack をUIにする**: SSH クライアント不要で、外出先でも操作が容易。
- **tmux セッション維持**: 長文/継続セッションのコンテキストを保つ。
- **事故を防ぐ**: コマンドフィルタ・プリクリア・二重起動防止で予期せぬ破壊を回避。

---

## 2. コンポーネント

| コンポーネント | 役割 |
| --- | --- |
| `slack_tmux_bridge.py` | Slackイベントを受け、tmuxに入力し、コマンド系の結果のみ返信するメインブリッジ |
| `goslack.py` | tmux ペインと Slack チャンネルの対応表を書き込む |
| `send_enter.sh` | tmux に Enter を送る最小ヘルパ |
| `active_sessions.json` | Slack チャンネルID → pane_id/ペイン/ディレクトリ/チャンネル名のマッピング |
| `tmp/` | スナップショット保存、PID ファイルなど |

---

## 3. 設定（.env）と理由

| 変数 | デフォルト | 説明 | なぜ必要か |
| --- | --- | --- | --- |
| `SLACK_BOT_TOKEN` | 必須 | Botトークン | Slack API 呼び出し用 |
| `SLACK_APP_TOKEN` | 必須 | Socket Mode 用 App トークン | 公開エンドポイント無しでイベント受信 |
| `LOG_LEVEL` | `INFO` | Bolt/SDK ログ | 接続/イベント/切断の可視化 |
| `COMMAND_ALLOWLIST` | `all` | 許可パターン | 事故を防ぎつつ運用側で制御 |
| `COMMAND_DENYLIST` | 空（→`rm` を含むコマンドを拒否。ただし `\\rm` は除外） | 拒否パターン | 破壊コマンド防止 |
| `EVENT_HEALTH_TIMEOUT` | `600` | イベント無受信閾値 | Socket Mode の沈黙検知 |
| `EVENT_HEALTH_ACTION` | `log` | `log` / `exit` / `restart` | 障害時の行動制御 |
| `EVENT_HEALTH_RESTART_COOLDOWN_SEC` | `300` | 再起動抑制 | 再起動ループ防止 |
| `EVENT_HEALTH_NOTIFY` | `0` | `1` で通知 | チャンネルに警告を表示 |
| `EVENT_HEALTH_NOTIFY_COOLDOWN_SEC` | `600` | 通知抑制 | 通知スパム防止 |
| `PROMPT_CACHE_TTL_SEC` | `3600` | プロンプトキャッシュ | メモリ肥大防止 |
| `CHANNEL_IDLE_NOTIFY_SEC` | `1800` | アイドル通知間隔 | 無反応チャンネルへの定期通知 |
| `CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC` | `1800` | アイドル通知抑制 | 通知スパム防止 |
| `PERMISSION_WATCH_SEC` | `120` | 承認待ち監視時間 | 承認要求をSlackへ可視化するため |
| `PERMISSION_WATCH_INTERVAL_SEC` | `2` | 監視間隔 | 負荷と反応速度のバランス |
| `PERMISSION_WATCH_PATTERN` | `(Allow once|Allow always|Approve|Permission|許可|承認)` | 承認検知パターン | 承認要求検知をチューニング可能にするため |
| `NOW_WATCH_INTERVAL_SEC` | `1` | `/now` 監視のポーリング間隔 | 出力変化の検知間隔を調整するため |
| `NOW_WATCH_IDLE_COUNT` | `3` | `/now` の停止判定回数 | 変化が止まったとみなす閾値 |
| `NOW_WATCH_TIMEOUT_SEC` | `180` | `/now` 監視タイムアウト | 変化が続く場合の打ち切りと継続促しのため |
| `EXECUTE_RESULT_MODE` | `poll` | 実行ボタン押下後の結果取得方式 (`poll`/`notify`/`both`) | ポーリングと Codex notify の重複運用を制御するため |
| `NOTIFY_DEDUPE_TTL_SEC` | `900` | poll/notify 重複排除キー保持秒数 | `both` での二重投稿を防ぐため |
| `NOTIFY_QUEUE_TTL_SEC` | `3600` | notify 配送キュー保持秒数 | 一時障害時の再試行と古い通知の破棄を両立するため |
| `NOTIFY_RETRY_BASE_SEC` | `2` | 再試行初期待機秒数 | 失敗直後の再送を間引くため |
| `NOTIFY_RETRY_MAX_SEC` | `60` | 再試行待機上限秒数 | 過剰な待機増加を抑えるため |
| `NOTIFY_RETRY_MAX_ATTEMPTS` | `10` | 再試行最大回数 | 永続失敗時の無限ループを防ぐため |
| `NOTIFY_RETRY_TICK_SEC` | `1` | キューワーカー周期秒数 | 起動時再処理と通常配送のポーリング間隔を制御するため |
| `NOTIFY_QUEUE_RESET_ON_START` | `1` | 起動時キュー初期化フラグ | 残骸キューによる再送ノイズを防ぐため |
| `TMUX_BIN` | 省略時 `tmux` | tmux の絶対パス | PATH に tmux が無い場合（launchd など）に必要 |

---

## 4. マッピング管理（goslack.py）

### 4.1 役割
- **現在の tmux ペイン**を取得し、`active_sessions.json` に**Slack チャンネルとの対応**を書き込む（`pane_id`, `pane`, `dir`, `name` を保持）。
- `pane_id` が送信時の**唯一の識別子**で、`pane` は表示・参考用（古くなっても送信先は `pane_id` から解決される）。
- 同一ペインを指す他チャンネルのエントリは**自動で削除**。

### 4.2 フロー
1. 現在の作業ディレクトリ名（= Slack チャンネル名）を Slack API で解決し、該当チャンネルIDを取得する。見つからない場合は `ai-studio-01/02/03` をフォールバックとして解決する（未使用を優先、すべて使用中なら `01 → 02 → 03 → 01 ...` でローテーション）。
   - ただし `--channel <NAME>` が指定された場合はその名前のみを解決し、フォールバックは行わない。
2. `tmux display-message` で `pane_id` と `session:window.pane` を取得する。`TMUX_PANE` がある場合は `-t $TMUX_PANE` を使って実行元ペインを明示的に解決する。
3. 通常登録（`--add` なし）では、取得した `pane_id` から `session:window.pane` を再解決し、妥当な形式ならその値を保存に使う。
4. 既存の `active_sessions.json` から同一ペインの他エントリを削除。
5. 新しいチャンネル→ペインを登録（atomic 書き込み）。`dir` と `name`（チャンネル名）も保存する。
6. Slack に「接続しました」通知を送信。

### 4.3 なぜこうするか
- **同一ペインの二重登録を防ぎたい**: ペイン再利用時に古いチャンネル情報が残る事故を防止。
- **atomic 書き込み**: JSON が途中で壊れると全運用が止まるため。

---

### 4.4 サブコマンド
- `goslack.py list`: `active_sessions.json` の一覧を番号付きで表示（`num`, `channel_name`, `pane`, `pane_id`, `dir`）。
- `goslack.py rm <number>`: 一覧の番号を指定して削除。
- `goslack.py --add <pane>`: 別ペインから指定ペインを登録（対象ペインの `pane_current_path` を利用）。
- `goslack.py --add <pane> --channel <NAME>`: チャンネル解決を指定名のみに固定し、フォールバックを行わない。
- `goslack.py list` の並び順: `ai-studio-01/02/03` が先頭（番号順）、それ以外はチャンネル名の昇順。チャンネル名が無い場合は `-`。
- `goslack.py rm <number>`: 番号が範囲外の場合はエラー終了。

#### 4.4.1 `list` の出力例

```
num	channel_name	pane	pane_id	dir
1	ai-studio-01	1:1.0	%1	/Users/you/WORKSPACE/ai-studio-01
2	ai-studio-02	1:2.0	%2	/Users/you/WORKSPACE/ai-studio-02
3	ai-studio-03	1:3.0	%3	/Users/you/WORKSPACE/ai-studio-03
4	project-x	2:0.0	%4	/Users/you/WORKSPACE/project-x
```

#### 4.4.2 `rm` の例

```
python goslack.py rm 4
```

### 4.5 Codex notify 連携
- Codex CLI の `notify` は外部コマンドに JSON 文字列を 1 引数で渡す。
- `slack_tmux_bridge.py notify` は受け取った JSON を最小正規化してから、`NOTIFY_INGRESS_TRANSPORT` (`http` / `uds`) に従って `slack_tmux_bridge` notify ingress へ転送する。
- 正規化ルール: `channel_id` が未指定かつ `channel-id` がある場合は `channel-id -> channel_id`、`pane_id` が未指定かつ `pane-id` がある場合は `pane-id -> pane_id`、`thread_ts` が未指定かつ `thread-id` がある場合は `thread-id -> thread_ts` を補完する（`1234567890.123456` 形式のみ、既存 snake_case キーは上書きしない）。
- スレッド返信用途の notify では `last-assistant-message` を必須とし、`channel_id` / `thread_ts` は payload 直値または `pane_id` からの宛先解決（`active_sessions.json` / `tmp/notify_context.json`）で確定できる必要がある。最終的に `channel_id` / `thread_ts` を解決できない場合は reject する。
- Slack 投稿先の解決と実際の投稿は `slack_tmux_bridge` 側の責務である。
- notify 宛先解決は payload の `channel_id/thread_ts` を優先し、欠落時は `pane_id`（未指定時は条件付きで `TMUX_PANE`）を起点に解決する。`pane_id` 起点の場合は `active_sessions.json` で接続済みであることを必須とする。
- `notify` は `/now` のポーリング挙動を変更しない。実行ボタンの監視有無は `EXECUTE_RESULT_MODE` に従う。
- `slack_tmux_bridge` の local notify ingress を使う場合、受信 payload は `tmp/notify_delivery_queue.json` に永続化され、Slack 投稿失敗時は backoff 付き再試行を行う。TTL 超過または試行上限到達で破棄し、失敗理由をログに残す。`invalid_thread_ts` / `channel_not_found` / `not_in_channel` / `is_archived` は恒久エラーとして即時破棄する。
- notify 配送ワーカーは、キューの走査・対象抽出と結果反映をロック内で行い、Slack 投稿（外部I/O）はロック外で実行する。

---

## 5. Slack → tmux の入力処理（slack_tmux_bridge.py）

### 5.1 受信処理
- `@app.event("message")` でユーザメッセージのみ処理。
  - bot 由来は除外（`bot_id` を見て除外）。
- `/bye` は特別扱いで接続解除する。
- `/dir` は接続中ディレクトリを返す（記録がある場合）。
- `/sessions` は接続中のチャンネル名とディレクトリの一覧を返す。
- `/now` は tmux 出力の変化を監視し、変化が止まったタイミングで取得結果を返信する（タイムアウト時は継続ボタンを提示）。
- `/ctlc` は tmux に Ctrl+C を送信する。
- `active_sessions.json` に登録がないチャンネルは**無視**。
- 送信時は `pane_id` から現在の `session:window.pane` を解決し、解決できない場合は送信しない（誤送信防止）。
- `pane_id` から解決した `pane` が保存値と異なる場合、確認ボタンを提示し、OK で更新して実行／キャンセルで切断する。

### 5.2 コマンドフィルタ
- **denylist優先**。正規表現 `/.../` に対応。
- allowlist が `all` でない場合、一致しない入力は拒否。
- denylist 未指定時は `rm` を含むコマンドをブロック（`\\rm` は除外）。

### 5.3 入力の種類
- **数字のみ**: 即実行（プリクリア → 入力 → Enter）。
- **テキスト**: 受信時に tmux へ入力を送り、ボタンを表示。
- 「▶︎ 実行（Enter）」で Enter 送信後、`EXECUTE_RESULT_MODE` が `poll` または `both` の場合に `/now` と同じ監視に入る。`both` では notify 投稿を優先し、同一 `pane_id/thread_ts` に notify 配送が観測された場合は poll 投稿を抑止する。
  - 「👀 Geminiを見る」現在の tmux 出力を送信。
  - 「🗑️ プロンプト削除」Ctrl+U で入力行を消去。
- **スラッシュコマンド**: `スラッシュコマンド` というメッセージによりボタンメニューを提示。

### 5.4 実行時の返信
- 「▶︎ 実行（Enter）」は Enter 送信後に監視し、停止したタイミングで結果を投稿する。
- 実行結果の投稿はブリッジの監視スナップショットを基本とする。

### 5.5 承認要求の検知（補助）
- Enter 送信後、一定時間 tmux 出力を監視し、承認要求と思われる出力が見つかった場合はスレッドに抜粋を投稿する。
- 監視は `PERMISSION_WATCH_*` で制御し、正規表現で検知パターンを調整できる。

### 5.4 なぜこうするか
- 誤送信防止のため、テキスト入力は「送信」ボタンで確定。
- 数字回答など軽量操作は即時実行で UX を改善。

---

## 6. tmux 入出力の制御

### 6.1 Pre-clear
全コマンド前に以下を実施:
1. `tmux clear-history`
2. `tmux send-keys C-l`

**なぜ**: 以前の出力やスクロールバックが混ざると抽出結果が汚れるため、毎回クリーンな状態から開始する。

### 6.2 出力取得
- `tmux capture-pane -p -S -1000` で過去 1000 行を取得。
- ANSI エスケープを除去して整形に利用。

---

## 7. 応答生成（コマンド系のみ）

### 7.1 `/now` と実行ボタンの監視取得
- `/now` は `NOW_WATCH_INTERVAL_SEC` 間隔で tmux 出力を監視する。
- 連続 `NOW_WATCH_IDLE_COUNT` 回変化がなければ、`tmux capture-pane` で取得して返信する。
- 変化が `NOW_WATCH_TIMEOUT_SEC` を超えて続く場合はタイムアウトを通知し、「監視を継続」ボタンを提示する。
- 実行ボタンは `EXECUTE_RESULT_MODE` が `poll` または `both` の場合のみ、Enter 送信後に監視する。`both` では notify 優先で重複排除を行い、notify が観測されない場合のみ poll スナップショットを投稿する。
- `permission` / `/now` / `execute` の各監視は、同一 `thread_ts` で同種監視が起動中の場合は重複起動を抑止する。

### 7.2 抽出ロジック
1. `"> prompt"` 行を探し、その行以降のみ採用。
2. 先頭が `>` の場合は**プロンプト行の直後に空行**を挿入。

### 7.3 返信形式
- Slack スレッドに **コードブロック**形式で投稿。
- 3,000 文字で分割し、区切り線は長すぎる場合短縮。

**なぜ**: 結果投稿のタイミングや内容は AI エージェントに委ね、ブリッジはコマンド系のみに限定するため。

---

## 9. ヘルスチェックと自動復旧

### 9.1 イベント監視
- `LAST_EVENT_TS` と `LAST_EVENT_TS_BY_CHANNEL` を更新。
- `EVENT_HEALTH_TIMEOUT` 秒イベントが来ないと警告。

### 9.2 アクション
- `EVENT_HEALTH_ACTION=log` → ログのみ
- `EVENT_HEALTH_ACTION=exit` → 強制終了（外部プロセスで再起動想定）
- `EVENT_HEALTH_ACTION=restart` → `os.execv` で自己再起動

### 9.3 通知
- `EVENT_HEALTH_NOTIFY=1` の場合、イベント停止チャンネルに通知。
- 通知は `EVENT_HEALTH_NOTIFY_COOLDOWN_SEC` で抑制。
- `CHANNEL_IDLE_NOTIFY_SEC` が有効な場合、無反応チャンネルに定期通知（`CHANNEL_IDLE_NOTIFY_COOLDOWN_SEC` で抑制）。

### 9.4 重複検知
- 同一 tmux ペインが複数チャンネルに紐づいている場合、定期的に検出して重複を解消する。
- 直近でアクティブなチャンネルを優先し、もう一方は切断して通知する。

**なぜ**: Socket Mode は静かに切断される可能性があるため、監視と自己復旧が必要。

---

## 10. 単一起動制御

- `tmp/slack_tmux_bridge.pid` を使用。
- PID が存在し生存していれば起動を拒否。

**なぜ**: 複数接続はイベントの配送先が分散し、Slack 上で「反応しない」状態を引き起こすため。

---

## 11. 運用手順（未経験者向け）

1. `.env` を作成し、Slack トークンを設定。
2. tmux で Gemini を起動。
3. 対象ペインで `python goslack.py` を実行。
4. 別ターミナルで `python slack_tmux_bridge.py` を起動。
5. Slack にメッセージを送り、ボタンで実行。

---

## 12. ディレクトリ構成

```
. 
├── slack_tmux_bridge.py  # ブリッジ本体
├── goslack.py            # チャンネル→ペイン登録
├── send_enter.sh         # Enter送信ヘルパ
├── active_sessions.json  # チャンネル→pane_id/ペイン/ディレクトリ/チャンネル名対応表
├── tmp/                  # スナップショット/ PID
└── docs/
    └── specification.md  # 本仕様書
```

## 13. 出力例

### 13.1 `/sessions`

```
- ai-studio-01 → /Users/you/WORKSPACE/ai-studio-01
- project-x → /Users/you/WORKSPACE/project-x
```

### 13.2 `/dir`

```
📁 接続中のディレクトリ: /Users/you/WORKSPACE/project-x
```
