# Obsidian ↔ Google Tasks 同期システム — フォーマット仕様書

## 0. システム概要

### アーキテクチャ

```
[ユーザー]
  Obsidian アプリ（編集）
  livesync プラグイン
       ↕ sync
[CouchDB サーバー]
       ↕ sync
[同期サーバー（homelab VM等）]
  ローカル CouchDB（内部DB）
       ↕ mirror / pull / push
  ローカル Vault ディレクトリ
  Google Tasks 同期スクリプト
       ↕ Google Tasks API
[Google Tasks]
```

### コンポーネント説明

| コンポーネント | 場所 | 役割 |
|---|---|---|
| Obsidian アプリ | クライアント | ユーザーによる Vault 編集 |
| livesync プラグイン | クライアント | サーバー CouchDB との双方向同期 |
| CouchDB サーバー | サーバー | Vault の中間ストア |
| livesync CLI | 同期サーバー | ローカル CouchDB ↔ サーバー CouchDB の sync、ローカルディレクトリへの mirror/pull/push |
| ローカル CouchDB | 同期サーバー | livesync CLI が管理する内部DB。sync の中継点 |
| ローカル Vault ディレクトリ | 同期サーバー | mirror/pull で展開されたファイル群。同期スクリプトの読み書き対象 |
| Google Tasks 同期スクリプト | 同期サーバー | ローカル Vault ファイルと Google Tasks API の CRUD |
| SQLite | 同期サーバー | 同期状態管理（mtime・ID・競合判定用） |

### livesync CLI の役割

- **Obsidian アプリを同期サーバー上で動かす必要はない**
- livesync CLI は以下の責務を持つ：
  - `sync`：サーバーの CouchDB とローカル CouchDB を双方向同期
  - `mirror`：ローカル CouchDB の内容をローカルディレクトリへ全展開
  - `pull`：ローカル CouchDB → ローカルディレクトリへ差分反映
  - `push`：ローカルディレクトリの変更 → ローカル CouchDB へ書き戻し
- 同期スクリプトは展開されたローカル Vault ファイルを直接読み書きする
- livesync CLI の呼び出しは以下の2通り：
  - **定期実行**：cron で `sync → mirror → sync` を定期実行し、常に最新状態を維持
  - **明示的呼び出し**：ファイル変更前後に `sync → pull` / `push → sync` を実行

---

## 1. ファイル命名規則

| 種別 | パターン | 例 |
|---|---|---|
| アクティブ Todo リスト | `todo-{リスト名}.md` | `todo-仕事.md`, `todo-個人.md` |
| アーカイブ | `archives/todo-{リスト名}-アーカイブ.md` | `archives/todo-仕事-アーカイブ.md` |

- `todo-*.md` にマッチするファイルが同期対象（`archives/` ディレクトリ配下は除外）
- `{リスト名}` 部分が Google Tasks の TaskList 名に対応
- アーカイブファイルは `archives/` ディレクトリにまとめて配置し、リストごとに1ファイル自動生成される
- アーカイブファイルが存在しない場合はアーカイブ処理時に自動作成する

---

## 2. Todo ブロック フォーマット

### 基本構造

```
- [ ] {タイトル}
  created:: YYYY-MM-DD
  due:: YYYY-MM-DD
  notes::
    {メモ1行目}
    {メモ2行目}
  gtasks_id:: {Google Tasks ID}
```

### 完了済み

```
- [x] {タイトル}
  created:: YYYY-MM-DD
  due:: YYYY-MM-DD
  completed_at:: YYYY-MM-DDTHH:MM:SS+09:00
  notes::
    {メモ}
  gtasks_id:: {Google Tasks ID}
```

### 属性一覧

| 属性キー | 必須 | 説明 | Google Tasks 対応フィールド |
|---|---|---|---|
| `created::` | 任意 | 作成日 | `notes` 内に埋め込み |
| `due::` | 任意 | 期限日 | `due`（RFC3339） |
| `notes::` | 任意 | メモ（次行以降インデントで複数行） | `notes` |
| `gtasks_id::` | 自動 | Google Tasks ID（システム管理） | `id` |
| `completed_at::` | 自動 | 完了日時・日本時間（JST / UTC+9）で記録。フォーマット：`YYYY-MM-DDTHH:MM:SS+09:00` | `completed` |

### ルール

- 属性行はタイトル行の**直下にインデント2スペース**で記述
- `notes::` の値は次行以降に**インデント4スペース**で記述（複数行対応）
- `gtasks_id::` と `completed_at::` はシステムが自動挿入・更新する
- 属性の順序は上記テーブルの順番を推奨（パーサーは順不同で対応）

---

## 3. 実例

### アクティブな Todo（todo-仕事.md）

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

### Vault ディレクトリ構成

```
Vault/
├── todo-仕事.md
├── todo-個人.md
├── todo-勉強.md
└── archives/
    ├── todo-仕事-アーカイブ.md
    ├── todo-個人-アーカイブ.md
    └── todo-勉強-アーカイブ.md   ← 初回アーカイブ時に自動作成
```

### アーカイブファイル（archives/todo-仕事-アーカイブ.md）

```markdown
- [x] キックオフMTG準備
  created:: 2025-04-28
  due:: 2025-04-30
  completed_at:: 2025-04-30T14:32:00+09:00
  archived_from:: todo-仕事.md
  gtasks_id:: ghi789rst

- [x] 契約書レビュー
  created:: 2025-04-10
  completed_at:: 2025-04-15T09:10:00+09:00
  archived_from:: todo-仕事.md
  gtasks_id:: jkl012mno
```

- `archived_from::` はアーカイブ時にシステムが自動付与（復元先の特定に使用）
- アーカイブファイルは元の Todo ファイルと1対1対応（`todo-{リスト名}.md` → `archives/todo-{リスト名}-アーカイブ.md`）

---

## 4. アーカイブ・復元ルール

| 項目 | 内容 |
|---|---|
| アーカイブ発火条件 | `- [x]` になってから **1時間後** |
| アーカイブ先 | `archives/todo-{リスト名}-アーカイブ.md` の末尾に追記（なければ自動作成） |
| 元ファイルからの削除 | アーカイブ書き込み完了後に削除 |
| Google Tasks 側の扱い | 完了済みのまま **放置**（削除しない） |
| アーカイブ時の SQLite 記録 | アーカイブ完了後、対象エントリの `gtasks_id` を `archived_tasks` テーブルに記録する |
| 復元トリガー | Google Tasks 側で未完了に戻す → ポーリングで検知 |
| 復元先 | `archived_from::` の値のファイルに追記 |
| 復元後のアーカイブ側 | 該当エントリを削除（アーカイブファイルが空になっても削除しない） |
| 復元時の SQLite 更新 | 復元完了後、`archived_tasks` テーブルから該当 `gtasks_id` を削除する |

---

## 5. Obsidian プラグイン仕様

### 5.1 概要

- **実装言語**：TypeScript（Obsidian Plugin API）
- **有効化条件**：ファイル名が `todo-*.md` にマッチするファイルを開いたとき（`archives/` 配下は対象外）
- **動作モード**：Edit モード（CM6 デコレーション）・Reading View の両方でリッチ表示を適用

---

### 5.2 リッチ表示（Todo ブロックレンダリング）

#### 有効化トリガー

`todo-*.md` を開いた際にプラグインが自動でリッチ表示を適用する。それ以外のファイルでは一切動作しない。

#### Edit モード（CM6 デコレーション）

- CodeMirror 6 の `ViewPlugin` + `DecorationSet` を使用し、編集中もリッチ表示を維持する
- Todo ブロック（`- [ ]` / `- [x]` ＋ 属性行）を検出し、ウィジェットデコレーションでカード形式に置き換える
- カーソルが該当ブロック内に入った場合は**生の Markdown テキストに戻す**（編集可能状態）
- カーソルがブロック外に出た時点でリッチ表示に戻す

#### Reading View

- `MarkdownPostProcessor` を登録し、レンダリング後の DOM を Todo カードに差し替える

---

### 5.3 Todo カードの表示仕様

各 Todo ブロックは以下のカード形式で表示する：

```
┌─────────────────────────────────────────┐
│ ☐  MTGの議事録をまとめる               │
│    📅 2025-06-01（期限バッジ：青）      │
│    🗓 作成: 2025-05-03（グレーバッジ）  │
│    📝 Aさんに確認してから書く           │
│       テンプレートはDriveのフォルダ参照 │
└─────────────────────────────────────────┘
```

#### 属性の表示ルール

| 属性 | 表示スタイル |
|---|---|
| チェックボックス（`- [ ]` / `- [x]`） | クリック可能なチェックボックス。完了時に `completed_at::` を自動挿入 |
| タイトル | テキスト。完了済みは打ち消し線 |
| `due::` | バッジ（期限超過：赤、当日：オレンジ、それ以外：青） |
| `created::` | バッジ（グレー） |
| `notes::` | インデントブロック（薄いボーダー左）。複数行対応 |
| `gtasks_id::` | 非表示 |
| `completed_at::` | 非表示 |
| `archived_from::` | 非表示 |

---

### 5.4 インライン編集（タッチ/クリックで編集）

カード上の各要素をクリック/タップすると編集モーダルが開く。

#### 編集モーダルの仕様

- Obsidian の `Modal` クラスを使用
- モーダル内に以下のフィールドを表示：

| フィールド | UI 部品 |
|---|---|
| タイトル | テキストインプット |
| due | 日付ピッカー（`<input type="date">`） |
| notes | テキストエリア（複数行） |

- `gtasks_id::` / `completed_at::` / `archived_from::` はモーダルに表示しない（システム管理フィールド）
- 保存ボタン押下でファイルの該当ブロックを差分更新し、モーダルを閉じる
- キャンセル時はファイルを変更しない

---

### 5.5 タスク追加ボタン

- `todo-*.md` を開いたとき、ファイル末尾（最後の Todo ブロックの下）に**「＋ タスクを追加」ボタン**をインライン描画する
- ボタンクリックで 5.4 と同様の編集モーダルを開く（空フィールド）
- 保存時、以下のフォーマットでファイル末尾に追記する：

```markdown
- [ ] {タイトル}
  created:: YYYY-MM-DD
  due:: YYYY-MM-DD        ← 未入力の場合は行ごと省略
  notes::                 ← 未入力の場合は行ごと省略
    {メモ}
```

- `gtasks_id::` はこの時点では挿入しない（サーバー側同期スクリプトが付与）

---

### 5.6 コマンドパレット

以下のコマンドを登録する：

| コマンド ID | 説明 |
|---|---|
| `gtodo:add-task` | タスク追加モーダルを開く（現在のファイルが `todo-*.md` のとき有効） |
| `gtodo:toggle-complete` | カーソル位置の Todo の完了/未完了をトグル |
| `gtodo:open-edit-modal` | カーソル位置の Todo の編集モーダルを開く |

---

### 5.7 CSS スニペット

プラグインが動作しない環境（プラグイン無効時など）向けの最低限のフォールバック表示として、別途 CSS スニペットを提供する。プラグインが有効な場合はプラグイン側のレンダリングが優先される。

| 属性 | フォールバック表示スタイル |
|---|---|
| `due::` | バッジ（期限超過で赤、当日でオレンジ、それ以外で青） |
| `created::` | バッジ（グレー） |
| `notes::` | インデントブロック（薄いボーダー左） |
| `gtasks_id::` | `display: none` |
| `completed_at::` | `display: none` |
| `archived_from::` | `display: none` |

---

## 6. Google Tasks ↔ Obsidian 属性マッピング

| Obsidian | Google Tasks | 備考 |
|---|---|---|
| タイトル（`- [ ] ...`） | `title` | |
| `due::` | `due` | RFC3339 形式に変換 |
| `notes::`（複数行結合） | `notes` | **Obsidian → Google Tasks**：改行を `\n` で結合し、先頭に `created: YYYY-MM-DD\n` を付与して送信。**Google Tasks → Obsidian**：`notes` 先頭行が `created: YYYY-MM-DD` に一致する場合はその行を `created::` に復元し残りを `notes::` とする。一致しない場合は `notes` 全体を `notes::` とし `created::` は変更しない |
| `- [ ]` / `- [x]` | `status: needsAction` / `completed` | |
| リスト（ファイル名） | TaskList | `todo-仕事.md` → TaskList "仕事" |
| `gtasks_id::` | `id` | システム管理 |

---

## 7. パーサー仕様（実装メモ）

### 共通：livesync CLI コマンド体系

livesync CLI は以下の4コマンドを持つ。コマンドの詳細は [公式ドキュメント](https://github.com/vrtmrz/obsidian-livesync/blob/main/src/apps/cli/README.md) に従う。

| コマンド | 説明 |
|---|---|
| `sync` | サーバーの CouchDB とローカル CouchDB（内部DB）を双方向同期する |
| `mirror` | ローカル CouchDB の内容をローカルディレクトリ（Vault）に展開する |
| `pull` | ローカル CouchDB からローカルディレクトリへ差分を反映する |
| `push` | ローカルディレクトリの変更をローカル CouchDB へ書き戻す |

---

### 共通：排他制御

同期サーバー上で動作する全プロセス（Obsidian → Google Tasks 同期、Google Tasks → Obsidian 同期、アーカイブ処理、定期 cron）は、livesync CLI およびローカル Vault ディレクトリへのアクセスを排他制御する。

排他制御の実装には SQLite の `process_locks` テーブル（セクション9参照）を使用する。

#### ロック取得・解放の手順

各プロセスは処理開始時に以下の手順でロックを取得する：

```
1. process_locks テーブルへ INSERT（lock_name, pid, acquired_at）
   - UNIQUE 制約により、同名ロックが既に存在する場合は INSERT が失敗する
2. INSERT 失敗（= ロック競合）の場合：
   a. locked_at を確認し、現在時刻との差が LOCK_TIMEOUT（デフォルト: 10分）を超えていれば
      古いロックとみなして DELETE 後に再 INSERT（スタールロック解除）
   b. タイムアウト未満であれば一定間隔（デフォルト: 10秒）でリトライ
   c. MAX_RETRY（デフォルト: 6回）を超えた場合はエラーログを出力して終了
3. 処理完了後（正常・異常いずれの場合も）、自プロセスの pid に対応するロックを DELETE する
   - finally ブロック等で確実に解放すること
```

#### ロック名の定義

| ロック名 | 取得するプロセス |
|---|---|
| `livesync_vault` | livesync CLI を呼び出す全プロセス（sync / pull / push / mirror）および Vault ファイルへの書き込みを伴う全処理 |

- 定期 cron（`sync → mirror → sync`）も同一ロックを取得してから実行する
- 整合性検証スクリプト（セクション8）は Vault を**読み取り専用**で参照するためロック取得不要とする。ただし livesync CLI（pull）を呼び出す場合はロックを取得すること

#### スタールロックの検出

プロセスが異常終了した場合、ロックが解放されないまま残留する（スタールロック）。`acquired_at` が現在時刻から `LOCK_TIMEOUT` 以上前である場合はスタールロックとみなし、`pid` の生死確認（`/proc/{pid}` の存在確認 or `kill -0`）を行った上で解放する。

---

### 共通：livesync CLI の呼び出しパターン

同期スクリプトによる**明示的呼び出し**と、cron による**定期実行**の2系統がある。

#### 定期実行（cron）

最新状態の定期取得を行う。

```
# 例: 5分ごと
*/5 * * * *  livesync-cli sync && livesync-cli mirror && livesync-cli sync
```

`sync → mirror → sync` の順で実行し、サーバー CouchDB の最新内容をローカルディレクトリに反映した上で、mirror による変更を再度サーバーへ伝搬する。

**cron から実行する際も `livesync_vault` ロックを取得してから実行すること。** cron ジョブのラッパースクリプトでロック取得・解放を行う。

#### ファイル変更を伴う処理（明示的呼び出し）

同期スクリプトが特定の `.md` ファイルを書き換える際は、前後に以下を実行する。

```
（livesync_vault ロック取得）
livesync-cli sync
livesync-cli pull
（対象ファイルの変更処理）
livesync-cli push
livesync-cli sync
（livesync_vault ロック解放）
```

- `sync → pull` で対象ファイルを最新化してから変更する
- `push → sync` で変更をサーバー CouchDB まで伝搬する
- pull/push/sync の前後で SQLite の `last_obsidian_mtime` を更新し、二重処理を防ぐ

---

### Obsidian → Google Tasks（ポーリングトリガー）

1. `livesync_vault` ロックを取得する
2. `livesync-cli sync` → `livesync-cli pull`（対象ファイルを最新化）
3. 変更ファイルが `todo-*.md` かつ `archives/` 配下でないことを確認
4. ファイル全体を再パース
5. 各 Todo ブロックを抽出（`^- \[[ x]\]` で開始、次の `- [` または EOF まで）
6. `gtasks_id::` の有無で新規/更新を判定
7. SQLite の `last_obsidian_mtime` と比較して実際に変更があったか確認
8. Google Tasks API を叩いて CRUD
9. 新規の場合は返却された `id` を `gtasks_id::` としてファイルに書き戻す
10. ファイルへの書き戻しが発生した場合、SQLite の `last_script_written_at` を現在時刻で更新する
11. `livesync-cli push` → `livesync-cli sync`（変更をサーバーへ伝搬）
12. `livesync_vault` ロックを解放する

---

### Google Tasks → Obsidian（5分ポーリング）

1. `livesync_vault` ロックを取得する
2. `livesync-cli sync` → `livesync-cli pull`（対象ファイルを最新化）
3. 全 TaskList を取得
4. SQLite の `last_google_updated` より新しいタスクを抽出
5. `gtasks_id::` で Obsidian ファイル内の対応エントリを検索
6. 競合判定：`google_updated_at` vs SQLite の `last_script_written_at`（同期スクリプトが最後にファイルを書いた時刻）を比較し、新しい方を正とする。ファイルの `mtime` は livesync の sync/pull でも更新されるため使用しない
7. `notes` フィールドのパース：Google Tasks の `notes` 先頭行が `created: YYYY-MM-DD` の形式に一致する場合、その行を `created::` 属性として取り出し、残りを `notes::` の値とする。一致しない場合は `notes` 全体を `notes::` の値として扱い、`created::` は更新しない
8. Obsidian ファイルを更新（差分のみ書き換え）
9. 書き込み完了後、SQLite の `last_script_written_at` を現在時刻で更新する
10. `livesync-cli push` → `livesync-cli sync`（変更をサーバーへ伝搬）
11. `livesync_vault` ロックを解放する

---

### アーカイブ処理（1時間ごとの cron ジョブ）

1. `livesync_vault` ロックを取得する
2. `livesync-cli sync` → `livesync-cli pull`（対象ファイルを最新化）
3. 全 `todo-*.md` を走査（`archives/` 配下は除外）
4. `- [x]` かつ `completed_at::` から1時間以上経過したエントリを抽出
5. リスト名を元に `archives/todo-{リスト名}-アーカイブ.md` のパスを生成
6. アーカイブファイルが存在しなければ新規作成
7. `archived_from::` を付与して対象アーカイブファイルの末尾に追記
8. 元ファイルから該当エントリを削除
9. 対象エントリの `gtasks_id` を SQLite の `archived_tasks` テーブルに記録する（Google Tasks 側は完了済みのまま放置）
10. `livesync-cli push` → `livesync-cli sync`（変更をサーバーへ伝搬）
11. `livesync_vault` ロックを解放する

---

## 8. 同期整合性検証システム

### 8.1 概要

コア同期機能（セクション7）とは**独立したスクリプト**として実装する。双方向同期の補完・修正は行わず、**不一致の検知とレポートのみ**を責務とする。

| 項目 | 内容 |
|---|---|
| 実行方式 | 独立スクリプト（cron による定期実行） |
| 実行頻度 | 1時間に1回 |
| 共有リソース | Google Tasks API 認証情報のみ（SQLite・Vault ファイルは読み取り専用参照） |
| 不一致検知時の挙動 | ログ記録 ＋ 通知のみ（自動修正なし） |
| 正値の優先判定 | 将来課題（現時点では判定せずに両側の状態をそのまま報告） |

---

### 8.2 検証ロジック

1. `livesync-cli sync` → `livesync-cli pull`（Vault を最新化、読み取り専用で使用）
   - livesync CLI を呼び出すため `livesync_vault` ロックを取得すること
2. 全 `todo-*.md` を走査して Obsidian 側のタスク一覧を構築
   - `gtasks_id::` を持つエントリのみ対象（未同期の新規タスクは除外）
3. SQLite の `archived_tasks` テーブルから除外リストを取得する。以降の突き合わせ処理では、この除外リストに含まれる `gtasks_id` を持つタスクをスキップする（Google Tasks 側に完了済みで残存しているアーカイブ済みタスクの誤検知を防ぐため）
4. Google Tasks API から全 TaskList・全タスクを取得
5. `gtasks_id::` をキーに突き合わせ、以下の不一致パターンを検出：

| パターン | 説明 | 深刻度 |
|---|---|---|
| **Obsidian にのみ存在** | `gtasks_id::` があるが Google Tasks 側に該当 ID がない | **アラート（通知）** |
| **Google Tasks にのみ存在** | Google Tasks 側に存在するが Obsidian 側に対応エントリがない（除外リスト対象を除く） | **アラート（通知）** |
| **フィールド不一致** | 両側に存在するが `title` / `due` / `status`（完了・未完了）が異なる | WARN（ログのみ） |

- **存在不一致**（どちらかにしか存在しない）は「タスクの欠落」として最も深刻とみなし、Webhook・Zabbix へアラートを送信する
- **フィールド不一致**はログへの WARN 記録のみとし、通知は行わない
- 存在不一致とフィールド不一致が混在する場合は、存在不一致のみ通知ペイロードに含める

6. 存在不一致・フィールド不一致ともに0件であれば正常ログを記録して終了
7. 存在不一致が1件以上あれば通知処理へ（8.3）
8. フィールド不一致のみの場合はログ記録のみで終了

---

### 8.3 通知仕様

#### Webhook 通知

不一致を検知した場合、設定済みの Webhook URL へ POST する。**存在不一致（タスクの欠落）のみ**を通知対象とする。

```json
{
  "summary": "タスク欠落を検出しました（2件）",
  "checked_at": "2025-06-01T10:00:00",
  "alerts": [
    {
      "pattern": "obsidian_only",
      "gtasks_id": "abc123xyz",
      "title": "MTGの議事録をまとめる",
      "list": "仕事"
    },
    {
      "pattern": "gtasks_only",
      "gtasks_id": "xyz789abc",
      "title": "契約書レビュー",
      "list": "仕事"
    }
  ]
}
```

- Webhook URL は設定ファイルで管理（コア同期スクリプトとは独立した設定）
- Discord Webhook など汎用 HTTP POST を受け付けるサービスに対応

#### Zabbix 通知（将来対応）

homelab に Zabbix 環境が整い次第、以下の方式で統合する。

| 方式 | 説明 |
|---|---|
| **Zabbix external check** | 検証スクリプトの終了コード（0: 正常 / 1: 不一致あり）を Zabbix が定期ポーリング |
| **Zabbix sender** | `zabbix_sender` コマンドでスクリプトから能動的にアイテム値を送信 |

- 不一致件数を数値アイテムとして送信し、閾値超過でトリガー発火・アラート通知する
- 不一致の詳細テキストは別アイテム（`log` 型）として送信し、Zabbix 上で確認可能にする

---

### 8.4 ログ仕様

| レベル | 出力条件 |
|---|---|
| `INFO` | 検証実行開始・終了、不一致0件の正常終了 |
| `WARN` | 不一致検知（存在不一致・フィールド不一致ともに記録。件数・パターン・対象タスクを出力） |
| `ERROR` | API 接続失敗、Vault 読み取り失敗など検証自体が実行できない場合 |

- 存在不一致（タスク欠落）は WARN ログ記録 ＋ Webhook・Zabbix へのアラート送信
- フィールド不一致は WARN ログ記録のみ（通知なし）

- ログファイルはコア同期スクリプトとは別ファイルに出力する
- `ERROR` 時も Webhook・Zabbix へ通知する（検証が実行できなかった旨を送信）

---

## 9. SQLite テーブル定義

### sync_state（既存テーブルへの補足）

競合判定に使用する `last_script_written_at` カラムを同期状態管理テーブルに持つ。ファイルの `mtime` は livesync の sync/pull によっても更新されるため競合判定には使用できない。同期スクリプトがファイルへの書き込みを行った際に必ずこのカラムを更新する。

| カラム | 説明 |
|---|---|
| `last_script_written_at` | 同期スクリプトが最後に対象ファイルを書き換えた日時（UTC）。Google Tasks → Obsidian の競合判定で `google_updated_at` と比較するために使用 |

**更新タイミング：**
- Obsidian → Google Tasks 処理でファイルへの書き戻しが発生した直後（ステップ10）
- Google Tasks → Obsidian 処理でファイルを更新した直後（ステップ9）
- アーカイブ処理・復元処理でファイルを書き換えた直後

---

### archived_tasks

アーカイブ済みタスクを管理するテーブル。整合性検証スクリプトが誤検知（「Google Tasks にのみ存在」アラート）を防ぐための除外リストとして参照する。

```sql
CREATE TABLE archived_tasks (
    gtasks_id   TEXT PRIMARY KEY,
    list_name   TEXT NOT NULL,          -- 復元先ファイルの特定に使用（例: "仕事"）
    archived_at DATETIME NOT NULL
);
```

| カラム | 説明 |
|---|---|
| `gtasks_id` | Google Tasks 側のタスク ID（`gtasks_id::` の値） |
| `list_name` | アーカイブ元のリスト名。復元時に `todo-{list_name}.md` へ書き戻す |
| `archived_at` | アーカイブ処理を実行した日時（UTC） |

**更新タイミング：**
- **INSERT**：アーカイブ処理（セクション7）でエントリを `archives/` に移動した直後
- **DELETE**：復元処理（Google Tasks 側で未完了に戻す → ポーリング検知）でエントリを元ファイルに書き戻した直後

---

### process_locks

livesync CLI およびローカル Vault への同時アクセスを防ぐための排他制御テーブル。

```sql
CREATE TABLE process_locks (
    lock_name   TEXT PRIMARY KEY,
    pid         INTEGER NOT NULL,       -- ロックを保持しているプロセスの PID
    acquired_at DATETIME NOT NULL       -- ロック取得日時（UTC）。スタールロック検出に使用
);
```

| カラム | 説明 |
|---|---|
| `lock_name` | ロックの識別名。現在定義されているロック名はセクション7「共通：排他制御」を参照 |
| `pid` | ロックを保持しているプロセスの PID。スタールロック判定時にプロセスの生死確認に使用 |
| `acquired_at` | ロック取得日時（UTC）。`LOCK_TIMEOUT`（デフォルト: 10分）を超えている場合はスタールロックとみなす |

**操作タイミング：**
- **INSERT**：各プロセスの処理開始時（ロック取得）
- **DELETE**：各プロセスの処理終了時・異常終了時（ロック解放）。finally ブロック等で確実に実行すること

**設定値（設定ファイルで管理）：**

| 設定キー | デフォルト値 | 説明 |
|---|---|---|
| `LOCK_TIMEOUT` | 600秒（10分） | この秒数を超えたロックをスタールロックとみなす |
| `LOCK_RETRY_INTERVAL` | 10秒 | ロック競合時のリトライ間隔 |
| `LOCK_MAX_RETRY` | 6回 | リトライ上限。超過した場合はエラーログを出力して処理を中断する |

---

## 10. 実装フェーズ

### フェーズ 1 — インフラ・基盤整備

同期サーバー側の土台を固める。以降の全フェーズがここに依存する。

- [ ] 同期サーバー VM のセットアップ（livesync CLI インストール・設定、CouchDB ローカルインスタンス起動）
- [ ] livesync CLI の動作確認（`sync` / `mirror` / `pull` / `push` が正常に実行できること）
- [ ] ローカル Vault ディレクトリへの初回 `mirror` 展開
- [ ] SQLite DB の初期化・テーブル作成（`sync_state` / `archived_tasks` / `process_locks`）
- [ ] 設定ファイルの雛形作成（`LOCK_TIMEOUT` / `LOCK_RETRY_INTERVAL` / `LOCK_MAX_RETRY`・Google Tasks API 認証情報・Webhook URL 等）
- [ ] Google Tasks API の認証フロー確認（OAuth2 トークン取得・更新）
- [ ] 排他制御ライブラリ（`process_locks` テーブルを使ったロック取得・解放・スタールロック検出）の実装・単体テスト

---

### フェーズ 2 — Todo パーサー実装

同期スクリプトの入出力となる Markdown パーサーを先行して実装・検証する。フェーズ3以降の全同期処理がここに依存する。

- [ ] Todo ブロックパーサーの実装（セクション2のフォーマット仕様に準拠）
  - `- [ ]` / `- [x]` の検出
  - 属性行（`created::` / `due::` / `notes::` / `gtasks_id::` / `completed_at::` / `archived_from::` など）の順不同パース
  - `notes::` の複数行インデントパース
- [ ] パーサーの単体テスト（正常系・属性欠落・複数行 notes・属性順序違い・空ファイル等の異常系）
- [ ] Markdown ファイルへの差分書き戻し処理の実装（特定ブロックの属性のみ更新・追記・削除）
- [ ] `todo-*.md` のファイル名からリスト名を抽出するユーティリティの実装

---

### フェーズ 3 — 同期スクリプト：Obsidian → Google Tasks

ユーザーが Obsidian でタスクを作成・編集した内容を Google Tasks へ反映する方向の同期を実装する。

- [ ] Google Tasks API ラッパーの実装（TaskList 一覧取得・タスク作成・更新・完了操作）
- [ ] セクション6の属性マッピング実装（`notes::` への `created:` 埋め込み・RFC3339 変換等）
- [ ] Obsidian → Google Tasks 同期スクリプト本体の実装（セクション7のフロー準拠）
  - 新規タスク作成 → `gtasks_id::` 書き戻し
  - 既存タスク更新（タイトル・due・notes・完了ステータス）
  - `last_obsidian_mtime` による変更検知・二重処理防止
  - `last_script_written_at` の更新
- [ ] 排他制御（フェーズ1実装済み）との結合
- [ ] 動作確認（手動実行で Obsidian の変更が Google Tasks に反映されること）

---

### フェーズ 4 — 同期スクリプト：Google Tasks → Obsidian

Google Tasks 側の変更（スマートフォン等からの編集）を Obsidian へ反映する方向の同期を実装する。フェーズ3完了後に着手する（競合判定に `last_script_written_at` が必要なため）。

- [ ] Google Tasks → Obsidian 同期スクリプト本体の実装（セクション7のフロー準拠）
  - `last_google_updated` によるポーリング差分抽出
  - `notes` 先頭行の `created: YYYY-MM-DD` パースと `created::` 復元
  - 競合判定（`google_updated_at` vs `last_script_written_at`）
  - Obsidian ファイルの差分更新
  - `last_script_written_at` の更新
- [ ] 排他制御との結合
- [ ] cron 登録（5分ポーリング）
- [ ] 動作確認（Google Tasks 側の変更が Obsidian に反映されること・競合時に新しい方が勝つこと）

---

### フェーズ 5 — アーカイブ・復元処理

完了タスクの自動アーカイブと、Google Tasks 側からの復元を実装する。フェーズ3・4完了後に着手する（`completed_at::` の書き込みと `archived_tasks` テーブルが前提）。

- [ ] アーカイブ処理スクリプトの実装（セクション7のフロー準拠）
  - `completed_at::` から1時間経過した `- [x]` エントリの抽出
  - `archives/todo-{リスト名}-アーカイブ.md` への追記・自動作成
  - 元ファイルからの削除
  - `archived_tasks` テーブルへの INSERT
- [ ] 復元処理の実装（Google Tasks 側で未完了に戻したタスクを `archived_from::` の値のファイルに書き戻す）
  - `archived_tasks` テーブルからの DELETE
- [ ] cron 登録（1時間ごと）
- [ ] 動作確認（完了後1時間でアーカイブされること・Google Tasks 側で未完了に戻すと復元されること）

---

### フェーズ 6 — Obsidian プラグイン

クライアント側のリッチ表示・インライン編集を実装する。フェーズ3完了後（フォーマット仕様が固まった状態）に着手できる。サーバー側同期とは独立して開発可能。

- [ ] プラグイン雛形の作成（`esbuild` + TypeScript 環境、Obsidian Plugin API）
- [ ] Todo ブロックパーサーの実装（フェーズ2のロジックを TypeScript に移植）
- [ ] Reading View 向け `MarkdownPostProcessor` の実装（Todo カード DOM 生成）
- [ ] Edit モード向け CM6 `ViewPlugin` + `DecorationSet` の実装
  - カーソルがブロック内に入ったら生 Markdown に戻す
  - カーソルがブロック外に出たらカード表示に戻す
- [ ] チェックボックスのクリック処理（`- [ ]` ↔ `- [x]` トグル・`completed_at::` 自動挿入）
- [ ] 編集モーダルの実装（セクション5.4）
- [ ] タスク追加ボタンの実装（セクション5.5）
- [ ] コマンドパレットへのコマンド登録（セクション5.6）
- [ ] CSS スニペットの作成（セクション5.7。フォールバック用）
- [ ] 動作確認（カード表示・編集モーダル・タスク追加・チェックボックストグル）

---

### フェーズ 7 — 整合性検証システム

全フェーズ完了後、本番稼働前の品質担保として実装する。フェーズ1〜5が動作していることが前提。

- [ ] 整合性検証スクリプト本体の実装（セクション8のロジック準拠）
  - `archived_tasks` 除外リストの参照
  - 存在不一致・フィールド不一致の検出
- [ ] Webhook 通知の実装（セクション8.3のペイロード形式）
- [ ] ログ出力の実装（セクション8.4。コア同期ログとは別ファイル）
- [ ] cron 登録（1時間ごと）
- [ ] 動作確認（意図的に不一致を作って通知が届くこと）
- [ ] Zabbix 統合（homelab Zabbix 環境構築後に対応）
