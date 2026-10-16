# セットアップの補足とつまずきやすい点

README の手順 0〜7 を新しいアカウントで最初から実行して確認した内容です。
手順どおりに進めて止まったときは、ここを参照してください。

## 全体の流れと所要時間の目安

| 手順 | 内容 | 目安 |
|---|---|---|
| 1 | Postgres インスタンス作成と接続許可 | 数分（作成待ち） |
| 3 | Snowflake / Postgres のテーブル作成 | 1 分 |
| 4 | デモデータ投入（`generate_data.py` → `generate_ml_inputs.py` → `setup_line_manager_demo.py`）と同期（`sync_pg_to_iceberg.py`） | 同期は約 6 分 |
| 5 | 特徴量 → SHAP プロシージャ → ML パイプライン → 異動適合 | 約 20 分 |
| 6 | Semantic View・人材検索・エージェント | 数分 |
| 7 | App Runtime へデプロイ | 数分 |

## Snowflake CLI の接続先

- `snow` コマンドには必ず `-c <接続名>`（`--connection`）を付けます。付けないと `connections.toml` の既定の接続先に作られてしまいます。
- Python スクリプトは `.env` の `SNOWFLAKE_CONNECTION_NAME` を使います。

## 手順 1: Postgres に接続できない

**症状:** `psql` やスクリプトが `server closed the connection unexpectedly` で切れる。

**原因:** Postgres のネットワークポリシーで許可した IP が、実際の送信元 IP と違う。
VPN やプロキシを使っていると、`checkip` などのサイトで見える IP と、Postgres に届く IP が違うことがあります。

**対処:** 一時的に広めに許可して一度つなぎ、Postgres 側から見えた IP を確認してから絞ります。

```sql
SELECT inet_client_addr();
```

このネットワークルールは `MODE = POSTGRES_INGRESS` で作ります。

## 手順 3: `Database 'HR_ANALYTICS' already exists, but current role has no privileges on it`

手順 1 のネットワークルールを置くために、`HR_ANALYTICS` を ACCOUNTADMIN で先に作ると起こります。
`setup_analytics.sql` は DB を SYSADMIN で作るため、所有者が違うと止まります。

- ネットワークルールは、`HR_ANALYTICS` 以外の DB.SCHEMA に作ってください。
- すでに作ってしまった場合は、所有者を移してから流し直します。

```sql
GRANT OWNERSHIP ON SCHEMA HR_ANALYTICS.PUBLIC TO ROLE SYSADMIN COPY CURRENT GRANTS;
GRANT OWNERSHIP ON DATABASE HR_ANALYTICS TO ROLE SYSADMIN COPY CURRENT GRANTS;
```

## 手順 2: `.env` を `source` すると `parse error`

`.env.example` の `<YOUR_...>` が残っていると、シェルの `source .env` は失敗します。
README のとおり `export $(grep -v '^#' .env | xargs)` で読み込んでください。

## 手順 4: 同期が遅い・途中で切れる

- `sync_pg_to_iceberg.py` は、VARIANT 列も含めてまとめて INSERT し、テーブルごとに Postgres へつなぎ直します。全体で約 6 分です。
- 1 行ずつ INSERT する作りにすると、件数の多いテーブルに 30 分近くかかります。その間に Postgres の接続が切れることがあります（`SSL connection has been closed unexpectedly`）。

## 手順 4: ML の入力テーブルについて

- 経歴、プロフィール、360 度フィードバック、1on1 分析、評価コメント分析は `generate_ml_inputs.py` で作ります。
- 乱数は固定なので、何度実行しても同じデータになります。実行のたびに TRUNCATE し直します。
- ML の正解ラベルは特徴量から SQL で作る合成値です。このため入力データは「それらしい分布」になっていれば十分です。

## 手順 5: 順番に注意

1. `build_feature_tables.py`: 特徴量テーブル（`ATTRITION_FEATURES` など）を作ります。
2. `register_shap_sproc.py`: SHAP 計算用のプロシージャ `COMPUTE_SHAP_ATTRITION` を登録します。ML パイプラインの中で呼ばれるので、必ず先に実行します。
3. `ml_pipeline_v3.py`
4. `add_transfer_fit_fv.py`

次のメッセージが出ても、結果には影響しません。

- `ATTRITION_MONITOR does not exist`: Model Monitor がない環境での警告です。
- `HR_APP_ROLE does not exist`: 付与先のロールがない場合はスキップします。

確認したときの結果の目安は次のとおりです。

| 項目 | 結果 |
|---|---|
| 離職予測 | AUC 約 0.95、14,071 件 |
| 上長との相性予測 | RMSE 約 0.08、13,941 件 |
| 異動適合 | 698,237 件 |
| SHAP | 50,000 件 |

## 手順 6: 人材検索が空になる

人材検索の元テーブル `SEARCH_TALENT_SOURCE` は、手順 3 の時点ではデータが入っていません。
`setup_search_and_agent.sql` で作り直してから、Cortex Search Service を作ります。

## 手順 7: App Runtime のつまずき

### アプリから Postgres につながらない

App Runtime のコンテナは、Snowflake の送信元 IP 帯から Postgres に接続します（2026 年 10 月時点の仕様）。
Postgres のネットワークルールに、この IP 帯も追加します。値はリージョンによって違います。

```sql
SELECT SYSTEM$GET_SNOWFLAKE_EGRESS_IP_RANGES();
```

外部アクセス統合（`HR_APP_EAI`）には、次の両方を許可します。

- Postgres のホスト（`:5432`）
- アカウントのホスト（`:443`）

アカウントのホストは、ハイフン区切りとアンダースコア区切りの 2 通りを入れておくと確実です。

### コンテナが `390422 INCOMING_REQUEST_BLOCKED` で起動しない

アカウントにネットワークポリシーがあると、コンテナから Snowflake への接続も止められます。
アカウントのポリシーに、上の送信元 IP 帯を追加します。

アカウントのポリシーは全員のログインに効きます。必ず次の手順で変更します。

1. 変更前に `DESC NETWORK POLICY <名前>;` で今の IP リストを控えます。
2. 控えたリストに送信元 IP 帯を足して、`ALTER NETWORK POLICY ... SET ALLOWED_IP_LIST = (...)` を実行します。
3. 片付けのときは、控えたリストで同じく `SET` し直して元に戻します。

`UNSET` や、ポリシーを丸ごと置き換える操作はしないでください。

### ログの見方

```bash
snow app events --connection <接続名> --target v3 --type log --since 10m
```

### ダッシュボードなどがエラーになる（pg_lake 経路）

アプリは既定で、Postgres の `hr_lake` スキーマ（pg_lake 経由の Iceberg）から ML の結果を読みます。
この README の手順では `hr_lake` を作りません。

- ログイン後、サイドバーでデータ経路を `snowflake-sdk` に切り替えてください（Cookie に保存されます）。
- pg_lake は Postgres の STANDARD 以上の階層でしか有効にできません。BURSTABLE では `CREATE EXTENSION pg_lake CASCADE` が `pg_extension_base can only be loaded via shared_preload_libraries` で失敗します。

### ローカルでアプリを動かす場合

アプリは `SNOWFLAKE_PASSWORD` を PAT として扱います。ローカルで動かすには PAT が必要です。

## 画面の見え方

- **評価期間:** `2025-H2` を選びます。既定の `2026-H2` では「評価データなし」と表示されます。
- **締切表示:** 締切日が過去のため「締切超過」と表示されますが、操作には影響しません。
- **上長のデモの状態:** 上長のデモ（`linemgr`、内田洋平と部下 8 人）で AI 採点や提出をするとデータが変わります。元に戻すには、`setup_line_manager_demo.py` を実行してから `sync_pg_to_iceberg.py` で同期し直します。
- **「昇進から 440 ヶ月」:** 昇進日が入っていない社員では、根拠文にこのような不自然な月数が出ることがあります。

## 片付けの順番

1. `DROP APPLICATION SERVICE ...`（アプリ）
2. `DROP POSTGRES INSTANCE ...` と、Postgres 用のネットワークポリシーとネットワークルール。ルールを置いた DB を先に消すとポリシーだけが残るので、この順に消します。
3. `teardown.sql`
4. アカウントのネットワークポリシーを、控えておいた IP リストで元に戻します。
