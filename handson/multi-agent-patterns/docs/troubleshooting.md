# トラブルシューティング

| 症状 | 原因と対処 |
|----|----|
| `接続が指定されていません` | `-c <your_connection>` を付けるか、`.env` に `MAP_CONNECTION=<your_connection>` を書いてください。接続一覧は `snow connection list`。 |
| `ACCOUNTADMIN ロールを使える接続が必要です` | setup はロール・ウェアハウス・データベースを作るため `ACCOUNTADMIN` が必要です。接続のロールを確認してください。 |
| `WARNING: CORTEX_ENABLED_CROSS_REGION が DISABLED` | モデルがリージョンにないとエージェントが失敗します。`MAP_ENABLE_CROSS_REGION=true` で再実行するか、管理者に `ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION'` を依頼してください。 |
| エージェントの呼び出しでウェアハウスのエラー | ユーザーに既定ウェアハウスがありません。`ALTER USER <your_user> SET DEFAULT_WAREHOUSE = <warehouse>;` |
| `Unknown function RUN_...` / `does not exist or not authorized` | そのパターンの setup が未実行か、権限が付いていません。`./<pattern>/setup.sh` を再実行してください（GRANT も再実行されます）。 |
| `先に 00_common/setup.sh を実行してください` | 01〜04 は共通基盤が前提です。 |
| 03 の setup で `TMS_DECOMPOSER_AGENT がありません` | 03 は 02 の Worker を使います。先に `02_orchestrator_worker/setup.sh` を実行してください。 |
| `sql/10_agents.sql が agents/*.yaml と一致しません` | `agents/*.yaml` を編集したら `python3 scripts/build_agents_sql.py` で再生成してください。 |
| 00_common の setup がスモークテストで止まる | 表示された `CHECK_NAME` の `FAIL` を確認してください。`controller_zip` が FAIL ならコントローラのアップロード（`snow stage copy`）が失敗しています。 |
| エージェントの結果が期待と違う | LLM の結果は毎回少しずつ変わります。`run.sh` を再実行するか、05 / 06 は `-n` で回数を増やして傾向を見てください。トレースは `APP.V_RUN_TRACE`、エージェント内部は Snowsight の Agent Monitoring で確認できます。 |
| タイムアウト | エージェントの予算（`orchestration.budget`）とプロシージャツールの `query_timeout` を確認してください。03 のオーケストレーターは 300 秒です。 |
| Snowsight だけで試したい | 各パターンの `sql/*.sql` の `<% db %>` / `<% wh %>` / `<% role %>` などを自分の名前に置き換えて、番号順に実行してください。00_common では `controller/src/*.py` を `@<DB>.AGENTS.APP_STAGE/lib/src/` に、06 では `skills/` を `@<DB>.LAB.SKILL_STAGE/skills/` に、Snowsight からアップロードしてください。 |
