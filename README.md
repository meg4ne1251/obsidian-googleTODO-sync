# Obsidian ↔ Google Tasks 同期システム

Obsidian の `todo-*.md` ファイルと Google Tasks を双方向同期するシステム。
詳細なフォーマット仕様・アーキテクチャは `specification.md` を参照。

---

## システム概要

```
[ユーザー]
  Obsidian アプリ（編集）
  livesync プラグイン
       ↕ CouchDB プロトコル
[CouchDB サーバー]
       ↕ sync
[同期サーバー（homelab VM 等）]
  ローカル CouchDB（内部DB）
       ↕ mirror / pull / push (livesync CLI)
  ローカル Vault ディレクトリ (/var/lib/obsidian-sync/vault/)
  Google Tasks 同期スクリプト (Python)
       ↕ Google Tasks API
[Google Tasks]
```

Obsidian アプリは同期サーバー上では動かない。livesync CLI が CouchDB ↔ ローカルディレクトリ間の同期を担い、Python スクリプトがローカルディレクトリを直接読み書きする。

---

## 前提条件

### 同期サーバー側

| 項目 | バージョン / 備考 |
|---|---|
| Python | 3.10 以上 |
| SQLite | Python 標準ライブラリに含まれる |
| Node.js | 18 以上（livesync CLI を npm で実行するため必須） |
| npm | 9 以上（livesync CLI を npm で実行するため必須） |
| obsidian-livesync | [obsidian-livesync](https://github.com/vrtmrz/obsidian-livesync) リポジトリを clone し、`src/apps/cli` を `cli_dir` に指定する |
| CouchDB | livesync CLI が接続するサーバー CouchDB（別サーバーでも可） |

### Obsidian クライアント側

| 項目 | 備考 |
|---|---|
| Obsidian | バージョン 1.4.0 以上 |
| Self-hosted LiveSync プラグイン | Community Plugins から導入 |

### Obsidian プラグインビルド用（開発時のみ）

| 項目 | バージョン |
|---|---|
| Node.js | 18 以上 |
| npm | 9 以上 |

---

## ディレクトリ構成

```
obsidian-googleTODO-sync/
├── specification.md            # フォーマット仕様書（必読）
├── server/                     # 同期サーバー側 Python 実装
│   ├── config/
│   │   └── config.example.yaml # 設定ファイルのテンプレート
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── init_db.py          # SQLite 初期化スクリプト
│   │   ├── cron_periodic.sh    # 5分ごとの sync→mirror→sync ラッパー
│   │   └── cron_examples.crontab # cron 設定例
│   ├── src/
│   │   ├── config.py           # 設定ファイルローダ
│   │   ├── db.py               # SQLite ヘルパー
│   │   ├── locks.py            # process_locks による排他制御
│   │   ├── livesync.py         # livesync CLI ラッパー
│   │   ├── parser.py           # Markdown Todo パーサー
│   │   ├── mapping.py          # Obsidian ↔ Google Tasks 属性マッピング
│   │   ├── gtasks.py           # Google Tasks API クライアント
│   │   ├── sync_obs_to_gt.py   # Obsidian → Google Tasks
│   │   ├── sync_gt_to_obs.py   # Google Tasks → Obsidian
│   │   ├── archive.py          # 完了 1時間後アーカイブ / 復元
│   │   ├── verify.py           # 整合性検証 + Webhook / Zabbix 通知
│   │   └── cron_runner.py      # 定期 cron 用ラッパー
│   └── tests/                  # unittest による単体・統合テスト
├── plugin/                     # Obsidian プラグイン (TypeScript)
│   ├── manifest.json
│   ├── package.json
│   ├── src/
│   │   ├── main.ts             # プラグインエントリ・コマンド登録
│   │   ├── parser.ts           # Todo パーサー（Python 側と等価ロジック）
│   │   ├── card.ts             # Todo カード DOM 生成
│   │   ├── editor.ts           # CodeMirror 6 ViewPlugin (Live Preview)
│   │   ├── reading.ts          # Reading View MarkdownPostProcessor
│   │   ├── modal.ts            # 編集モーダル
│   │   └── file_actions.ts     # ファイル書き換え
│   └── test/parser.test.mjs
└── snippets/
    └── todo-fallback.css       # プラグイン無効時のフォールバック CSS
```

---

## セットアップ：同期サーバー側

### ステップ 1 — リポジトリを配置する

```bash
# 例: /opt/obsidian-sync に配置する場合
sudo mkdir -p /opt/obsidian-sync
sudo chown $USER /opt/obsidian-sync
git clone <このリポジトリ> /opt/obsidian-sync
```

以降のコマンドは `/opt/obsidian-sync/server` を作業ディレクトリとして想定する。

### ステップ 2 — Python 依存ライブラリのインストール

```bash
cd /opt/obsidian-sync/server
python3 -m pip install -r requirements.txt
```

### ステップ 3 — Google Cloud Console で OAuth クライアントを作成する

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（または既存を選択）
2. **「APIとサービス」→「ライブラリ」** から **「Tasks API」** を有効化
3. **「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth クライアント ID」** を選択
   - アプリケーションの種類：**「デスクトップアプリ」**
   - 名前：任意（例: `obsidian-sync`）
4. 作成後、JSON ファイルをダウンロードして同期サーバーの任意のパスに保存する
   ```bash
   # 例:
   mv ~/Downloads/client_secret_*.json /opt/obsidian-sync/config/credentials.json
   chmod 600 /opt/obsidian-sync/config/credentials.json
   ```
5. **「OAuth 同意画面」** で以下を設定
   - ユーザーの種類：**「外部」**（個人利用の場合は「内部」不可）
   - テストユーザーに自分の Google アカウントを追加（公開しない場合）

> **スコープ:** `https://www.googleapis.com/auth/tasks` のみ必要。

### ステップ 4 — 設定ファイルを作成する

```bash
cd /opt/obsidian-sync
cp server/config/config.example.yaml server/config/config.yaml
$EDITOR server/config/config.yaml
```

設定項目の詳細は後述の **[設定ファイルリファレンス](#設定ファイルリファレンス)** を参照。

必須で変更する項目:

```yaml
paths:
  vault_dir: /var/lib/obsidian-sync/vault   # ← Vault を展開するパス
  db_path:   /var/lib/obsidian-sync/state.sqlite
  log_dir:   /var/log/obsidian-sync

livesync:
  npm: /usr/bin/npm                          # ← npm のフルパス
  cli_dir: /path/to/obsidian-livesync/src/apps/cli  # ← obsidian-livesync の CLI ディレクトリ
  db_dir: /path/to/couchdb/                 # ← CouchDB データディレクトリ

google:
  credentials_file: /opt/obsidian-sync/config/credentials.json
  token_file:       /opt/obsidian-sync/config/token.json
```

Vault ディレクトリとログディレクトリを事前に作成しておく:

```bash
sudo mkdir -p /var/lib/obsidian-sync/vault
sudo mkdir -p /var/log/obsidian-sync
sudo chown -R $USER /var/lib/obsidian-sync /var/log/obsidian-sync
```

### ステップ 5 — SQLite DB を初期化する

```bash
cd /opt/obsidian-sync/server
python3 scripts/init_db.py --config config/config.yaml
# => Initialized DB at: /var/lib/obsidian-sync/state.sqlite
```

`sync_state` / `archived_tasks` / `process_locks` の 3 テーブルが作成される。

### ステップ 6 — Google OAuth 初回認証

```bash
cd /opt/obsidian-sync/server
python3 -m src.sync_obs_to_gt --config config/config.yaml
```

初回実行時はブラウザが開き Google の認可画面が表示される。
許可すると `token_file` にトークンが保存され、以降はブラウザ認証なしで実行できる。

> サーバー環境でブラウザが使えない場合:
> ローカル PC で一度認証してから `token.json` をサーバーにコピーする方法でも可。
> その際は `credentials.json` のリダイレクト URI を `http://localhost` にしておく。

### ステップ 7 — 動作確認（手動実行）

```bash
cd /opt/obsidian-sync/server

# Obsidian → Google Tasks（ローカル Vault のみ、livesync を呼ばない）
python3 -m src.sync_obs_to_gt --config config/config.yaml --no-livesync

# Google Tasks → Obsidian
python3 -m src.sync_gt_to_obs --config config/config.yaml --no-livesync

# 整合性検証
python3 -m src.verify --config config/config.yaml --no-livesync
```

`--no-livesync` フラグを付けると livesync CLI を呼び出さずローカルファイルのみ操作する。
開発・動作確認時に使用する。

### ステップ 8 — cron に登録する

```bash
# cron_examples.crontab のパスを実環境に合わせて編集してから登録
$EDITOR /opt/obsidian-sync/server/scripts/cron_examples.crontab
crontab /opt/obsidian-sync/server/scripts/cron_examples.crontab
```

crontab に設定する環境変数:

```bash
GTODO_HOME=/opt/obsidian-sync/server
GTODO_CONFIG=/opt/obsidian-sync/server/config/config.yaml
```

| 頻度 | 処理 | ログ |
|---|---|---|
| 5分ごと | `cron_periodic.sh`（livesync sync→mirror→sync） | `cron.log` |
| 5分ごと | `sync_gt_to_obs`（Google Tasks → Obsidian） | `gt2obs.log` |
| 5分ごと | `sync_obs_to_gt`（Obsidian → Google Tasks） | `obs2gt.log` |
| 1時間ごと | `archive`（完了 1 時間以上経過した Todo をアーカイブ） | `archive.log` |
| 1時間ごと | `verify`（整合性検証） | `verify.log` |

すべてのプロセスは SQLite の `process_locks` テーブルで `livesync_vault` ロックを取得してから実行される。競合時は自動でリトライし、スタールロックは pid の生死確認後に強制解除する。

---

## セットアップ：Obsidian プラグイン

### ビルド

```bash
cd plugin
npm install --legacy-peer-deps
npm run build   # => main.js を生成
```

### Vault への配置

```bash
VAULT_DIR="/path/to/your/Vault"
PLUGIN_DIR="$VAULT_DIR/.obsidian/plugins/obsidian-gtodo-sync"

mkdir -p "$PLUGIN_DIR"
cp plugin/manifest.json "$PLUGIN_DIR/"
cp plugin/main.js       "$PLUGIN_DIR/"
cp plugin/styles.css    "$PLUGIN_DIR/"
```

Obsidian の **設定 → Community plugins** で `Google Todo Sync` を有効化する。

### 機能

- `todo-*.md` を開くとカード形式で Todo を描画
  - チェックボックス・タイトル・期限バッジ・作成日バッジ・notes を表示
  - カーソルがブロック内に入ると生 Markdown に戻る（Live Preview）
- カード上の要素クリックで編集モーダルが開く
- ファイル末尾の **「＋ タスクを追加」** ボタンで新規 Todo を追加
- コマンドパレット（`Ctrl+P`）で実行できるコマンド:
  - `gtodo:add-task` — カーソル位置に新規 Todo を挿入
  - `gtodo:toggle-complete` — カーソル行の完了状態をトグル
  - `gtodo:open-edit-modal` — 編集モーダルを開く

### プラグイン用テスト

```bash
cd plugin
node --test test/parser.test.mjs
```

---

## CSS スニペット（プラグイン不使用時）

プラグインを使用しない場合のフォールバック表示:

```bash
cp snippets/todo-fallback.css "$VAULT_DIR/.obsidian/snippets/"
```

Obsidian の **設定 → Appearance → CSS snippets** から `todo-fallback` を有効化する。

---

## サーバー側テスト

```bash
cd server
python3 -m unittest discover -s tests -v
```

---

## 設定ファイルリファレンス

`server/config/config.yaml` の全項目:

```yaml
paths:
  vault_dir: /var/lib/obsidian-sync/vault
  # livesync CLI が mirror するローカル Vault パス。
  # todo-*.md はここから読み書きされる。

  db_path: /var/lib/obsidian-sync/state.sqlite
  # 同期状態を管理する SQLite ファイルのパス。
  # init_db.py で初期化する。

  log_dir: /var/log/obsidian-sync
  # 各スクリプトのログ出力先ディレクトリ。

livesync:
  npm: /usr/bin/npm
  # npm 実行パス。フルパス推奨。

  cli_dir: /path/to/obsidian-livesync/src/apps/cli
  # npm --prefix に渡す CLI ディレクトリ（obsidian-livesync の src/apps/cli）。

  db_dir: /path/to/couchdb/
  # CLI に渡す CouchDB データディレクトリ。

  timeout_sec: 300
  # livesync の各サブコマンド（sync / mirror / pull / push）のタイムアウト秒。

google:
  credentials_file: /var/lib/obsidian-sync/credentials.json
  # Google Cloud Console からダウンロードした OAuth2 クライアント情報 JSON のパス。

  token_file: /var/lib/obsidian-sync/token.json
  # 初回認証後に生成されるアクセストークン・リフレッシュトークンの保存先。
  # 自動更新されるため通常は手動編集不要。

  scopes:
    - https://www.googleapis.com/auth/tasks
  # 必要なスコープ。Tasks API のみなので変更不要。

locks:
  timeout_sec: 600
  # この秒数を超えたロックをスタールロックとみなし、pid 確認後に強制解除する。

  retry_interval_sec: 10
  # ロック取得に失敗したとき、次のリトライまでの待機秒数。

  max_retry: 6
  # リトライの最大回数。max_retry 回失敗したらエラーで終了する。
  # デフォルト設定では最大 60 秒待機（10秒 × 6回）。

verify:
  webhook_url: ""
  # 存在不一致検知時に POST する Webhook URL（Slack Incoming Webhook 等）。
  # 空文字列のときは送信しない。

  zabbix:
    enabled: false
    server: ""         # Zabbix サーバーのホスト名/IP
    host: ""           # Zabbix 上のホスト名
    item_count: ""     # 不一致件数を送るアイテムキー
    item_log: ""       # ログを送るアイテムキー

logging:
  level: INFO
  # ログレベル: DEBUG / INFO / WARN / ERROR
```

---

## Todo フォーマット

`todo-{リスト名}.md` ファイルに以下の形式で記述する:

```markdown
- [ ] MTGの議事録をまとめる
  created:: 2025-05-03
  due:: 2025-06-01
  notes::
    Aさんに確認してから書く
    テンプレートはDriveのフォルダを参照
  gtasks_id:: abc123xyz

- [ ] 環境構築ドキュメント更新
  created:: 2025-05-01
  gtasks_id:: def456uvw

- [x] キックオフMTG準備
  created:: 2025-04-28
  due:: 2025-04-30
  completed_at:: 2025-04-30T14:32:00+09:00
  gtasks_id:: ghi789rst
```

| 属性 | 必須 | 説明 |
|---|---|---|
| `created::` | 任意 | 作成日（`YYYY-MM-DD`） |
| `due::` | 任意 | 期限日（`YYYY-MM-DD`） |
| `notes::` | 任意 | メモ。次行以降をインデント 4 スペースで記述（複数行可） |
| `gtasks_id::` | **自動** | Google Tasks ID。システムが自動挿入・管理する |
| `completed_at::` | **自動** | 完了日時（JST）。チェック時にシステムが自動挿入 |

- ファイル名の `{リスト名}` 部分が Google Tasks のリスト名に対応する
- `gtasks_id::` のない Todo は同期時に Google Tasks へ新規登録され、ID が書き戻される
- アーカイブファイルは `archives/todo-{リスト名}-アーカイブ.md` に自動生成される

---

## 排他制御

すべての書き込み系プロセスは SQLite の `process_locks` テーブルで `livesync_vault` ロックを取得してから実行される。

- `locks.timeout_sec`（デフォルト 600 秒）を超えたロックはスタールロックとみなし、`os.kill(pid, 0)` でプロセスの生死を確認後に強制解除する
- `locks.retry_interval_sec` 秒ごとに `locks.max_retry` 回までリトライする

---

## 競合判定

Google Tasks → Obsidian の同期では `google_updated_at` と SQLite の `last_script_written_at` を比較し、新しい方を採用する。
ファイルの mtime は livesync の sync/pull で更新されるため競合判定には使用しない。

---

## 整合性検証

1 時間ごとに以下を検証する（`verify.py`）:

| パターン | 対応 |
|---|---|
| Obsidian にしかない `gtasks_id`（Google 側で削除済み） | Webhook / Zabbix へアラート |
| Google Tasks にしかない ID（`archived_tasks` 登録済みは除外） | Webhook / Zabbix へアラート |
| 両方に存在するが `title` / `due` / `status` が異なる | WARN ログのみ |

---

## ログの確認

```bash
# livesync 定期実行ログ
tail -f /var/log/obsidian-sync/cron.log

# Google Tasks → Obsidian
tail -f /var/log/obsidian-sync/gt2obs.log

# Obsidian → Google Tasks
tail -f /var/log/obsidian-sync/obs2gt.log

# アーカイブ処理
tail -f /var/log/obsidian-sync/archive.log

# 整合性検証
tail -f /var/log/obsidian-sync/verify.log
```

---

## トラブルシューティング

### `npm not found` / `livesync CLI が起動しない`

`config.yaml` の `livesync.npm` に npm のフルパスを指定する。
`which npm` で確認して絶対パスを設定する。
また、`livesync.cli_dir` が obsidian-livesync の `src/apps/cli` を正しく指しているか確認する。

### `FileNotFoundError: credentials.json`

Google Cloud Console からダウンロードした JSON ファイルのパスが
`config.yaml` の `google.credentials_file` と一致しているか確認する。

### `Token has been expired or revoked`

`token.json` を削除して再度手動で OAuth 認証を行う:

```bash
rm /var/lib/obsidian-sync/token.json
cd /opt/obsidian-sync/server
python3 -m src.sync_obs_to_gt --config config/config.yaml
```

### ロックが解除されない（別のプロセスがクラッシュした場合）

SQLite で直接確認・削除する:

```bash
sqlite3 /var/lib/obsidian-sync/state.sqlite \
  "SELECT * FROM process_locks;"

# スタールロックを手動削除（pid が死んでいることを確認してから）
sqlite3 /var/lib/obsidian-sync/state.sqlite \
  "DELETE FROM process_locks WHERE lock_name = 'livesync_vault';"
```

### cron が動いているか確認する

```bash
# cron デーモンのログ（Ubuntu/Debian）
grep CRON /var/log/syslog | tail -20

# または journalctl
journalctl -u cron --since "1 hour ago"
```

### `--no-livesync` で動作確認する

livesync CLI が未設定でも同期スクリプト単体の動作確認ができる:

```bash
python3 -m src.sync_obs_to_gt --config config/config.yaml --no-livesync
python3 -m src.sync_gt_to_obs --config config/config.yaml --no-livesync
python3 -m src.archive        --config config/config.yaml --no-livesync
python3 -m src.verify         --config config/config.yaml --no-livesync
```
