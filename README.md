# Obsidian ↔ Google Tasks 同期システム

`specification.md` に定義されたフォーマット仕様・アーキテクチャを実装した一式。

## ディレクトリ構成

```
obsidian-googleTODO-sync/
├── specification.md
├── server/                  サーバー側 Python 実装
│   ├── config/
│   │   └── config.example.yaml
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── init_db.py        # SQLite 初期化
│   │   ├── cron_periodic.sh  # 5分ごとの sync→mirror→sync ラッパー
│   │   └── cron_examples.crontab
│   ├── src/
│   │   ├── config.py         # 設定ファイルローダ
│   │   ├── db.py             # SQLite ヘルパー
│   │   ├── locks.py          # process_locks による排他制御
│   │   ├── livesync.py       # livesync CLI ラッパー
│   │   ├── parser.py         # Markdown Todo パーサー
│   │   ├── mapping.py        # Obsidian ↔ Google Tasks 属性マッピング
│   │   ├── gtasks.py         # Google Tasks API クライアント (本番 / テスト用 InMemoryBackend)
│   │   ├── sync_obs_to_gt.py # Obsidian → Google Tasks
│   │   ├── sync_gt_to_obs.py # Google Tasks → Obsidian
│   │   ├── archive.py        # 1時間後アーカイブ / 復元
│   │   ├── verify.py         # 整合性検証 + Webhook / Zabbix 通知
│   │   └── cron_runner.py    # 定期 cron 用ラッパー
│   └── tests/                # unittest による単体・統合テスト
├── plugin/                  Obsidian プラグイン (TypeScript)
│   ├── manifest.json
│   ├── package.json
│   ├── tsconfig.json
│   ├── esbuild.config.mjs
│   ├── styles.css
│   ├── src/
│   │   ├── main.ts           # プラグインエントリ・コマンド登録
│   │   ├── parser.ts         # Todo パーサー (Python と等価ロジック)
│   │   ├── card.ts           # Todo カード DOM 生成
│   │   ├── editor.ts         # CodeMirror 6 ViewPlugin (Live Preview)
│   │   ├── reading.ts        # Reading View MarkdownPostProcessor
│   │   ├── modal.ts          # 編集モーダル
│   │   └── file_actions.ts   # ファイル書き換え
│   └── test/parser.test.mjs
└── snippets/
    └── todo-fallback.css     # プラグイン無効時のフォールバック CSS
```

## サーバー側セットアップ

### 1. 依存ライブラリのインストール

```bash
cd server
python3 -m pip install -r requirements.txt
```

### 2. 設定ファイルの作成

```bash
cp config/config.example.yaml config/config.yaml
$EDITOR config/config.yaml
```

主要な設定項目:

| キー | 用途 |
|---|---|
| `paths.vault_dir` | livesync が mirror するローカル Vault パス |
| `paths.db_path` | SQLite DB ファイルパス |
| `livesync.cli_command` | livesync CLI のコマンド (フルパス推奨) |
| `google.credentials_file` | OAuth2 クライアント情報の JSON |
| `google.token_file` | 認証済みトークンの保存先 |
| `verify.webhook_url` | 整合性検証アラートの Webhook URL |
| `locks.timeout_sec` | LOCK_TIMEOUT (秒) |

### 3. DB 初期化

```bash
python3 scripts/init_db.py --config config/config.yaml
```

3 つのテーブル (`sync_state` / `archived_tasks` / `process_locks`) が作成される。

### 4. Google OAuth 初回認証

`google.credentials_file` に Google Cloud Console から取得したクライアント JSON
(`https://www.googleapis.com/auth/tasks` スコープ) を配置し、初回は手動で同期スクリプトを
実行するとブラウザで認可フローが起動して `token_file` に書き出される。

### 5. cron 登録

`scripts/cron_examples.crontab` を参考に登録する:

```bash
crontab scripts/cron_examples.crontab
```

| 頻度 | 処理 |
|---|---|
| 5分ごと | `cron_periodic.sh` (sync→mirror→sync) |
| 5分ごと | `python3 -m src.sync_gt_to_obs` (GT→Obsidian) |
| 5分ごと | `python3 -m src.sync_obs_to_gt` (Obsidian→GT) |
| 1時間ごと | `python3 -m src.archive` (アーカイブ処理) |
| 1時間ごと | `python3 -m src.verify` (整合性検証) |

すべて `livesync_vault` ロックを取得してから実行されるため、競合は自動でリトライ・解除される。

## 同期スクリプトの個別実行

```bash
# Obsidian → Google Tasks
python3 -m src.sync_obs_to_gt --config config/config.yaml

# Google Tasks → Obsidian
python3 -m src.sync_gt_to_obs --config config/config.yaml

# アーカイブ処理
python3 -m src.archive --config config/config.yaml

# 整合性検証
python3 -m src.verify --config config/config.yaml
```

開発・検証時は `--no-livesync` を付けると livesync CLI を呼び出さずローカル Vault だけを操作する。

## サーバー側テスト

```bash
cd server
python3 -m unittest discover -s tests -v
```

## Obsidian プラグイン

### ビルド

```bash
cd plugin
npm install --legacy-peer-deps
npm run build              # main.js を生成
```

### Vault への配置

`<Vault>/.obsidian/plugins/obsidian-gtodo-sync/` ディレクトリを作成し、以下を配置する:

- `manifest.json`
- `main.js` (build 後に生成される)
- `styles.css`

Obsidian の設定 → Community plugins から有効化する。

### 機能

- `todo-*.md` を開くとカード形式で Todo を描画
  - チェックボックス・タイトル・期限バッジ・作成日バッジ・notes
  - カーソルがブロック内に入ると生 Markdown に戻る
- カード上の要素クリックで編集モーダルが開く
- ファイル末尾に **「＋ タスクを追加」** ボタン
- コマンドパレット:
  - `gtodo:add-task`
  - `gtodo:toggle-complete`
  - `gtodo:open-edit-modal`

### プラグイン用テスト

```bash
cd plugin
node --test test/parser.test.mjs
```

## CSS スニペット

プラグインを使用しない場合の最低限のフォールバック表示:

```bash
cp snippets/todo-fallback.css <Vault>/.obsidian/snippets/
```

Obsidian の設定 → Appearance → CSS snippets から有効化。

## 排他制御

すべての書き込み系プロセスは SQLite の `process_locks` テーブルに対し
`livesync_vault` ロックを取得してから実行される。

- `LOCK_TIMEOUT` (デフォルト 600 秒) を超えたロックはスタールロックとみなし、
  pid の生死確認 (`os.kill(pid, 0)`) を行ったうえで強制解除する。
- `LOCK_RETRY_INTERVAL` 秒ごとに `LOCK_MAX_RETRY` 回までリトライする。

## 競合判定

Google Tasks → Obsidian の同期では、`google_updated_at` と SQLite の
`last_script_written_at` を比較し、新しい方を採用する。
ファイルの mtime は livesync の sync/pull で更新されるため使用しない。

## 整合性検証

1 時間ごとに以下を検証する:

- Obsidian にしかない `gtasks_id` (Google 側で削除済み)
- Google Tasks にしかない ID (`archived_tasks` に登録済みのものは除外)
- 両方に存在するが `title` / `due` / `status` が異なる

存在不一致は Webhook / Zabbix へアラート送信、フィールド不一致は WARN ログのみ。
