# 03 Orchestrator / Worker（エージェント型: Agent as Tool）

[02](../02_orchestrator_worker/) と同じ処理を、コントローラではなく**オーケストレーターエージェント**に任せます。
エージェントは他のエージェントを直接呼べないため、Worker を呼ぶ**所有者権限プロシージャ**をカスタムツールとして渡します。
前提: [`00_common`](../00_common/) と [`02_orchestrator_worker`](../02_orchestrator_worker/)（Worker エージェントを使う）。比較: [パターン比較表](../README.md#comparison)

## 1. このパターンで分かること

- エージェントから別のエージェントを呼ぶ、最も基本的な方法（ラッパープロシージャ + generic ツール）
- 呼び先を**プロシージャ内に固定**し、任意のエージェントを呼べないようにする方法
- LLM が手順を決める構成でも、**最後はコードで検証**する方法

## 2. 構成図

```mermaid
flowchart LR
    U([CALL APP.RUN_MEETING_NOTE_ORCHESTRATED]) --> C[コントローラ]
    C -->|会議メモ| O[TMS_ORCHESTRATOR_AGENT]
    O -->|tool: ask_decomposer_worker| P1[/AGENTS.ASK_DECOMPOSER_WORKER/]
    O -->|tool: ask_dedupe_worker| P2[/AGENTS.ASK_DEDUPE_WORKER/]
    O -->|tool: ask_criteria_worker| P3[/AGENTS.ASK_CRITERIA_WORKER/]
    P1 -->|DATA_AGENT_RUN| D[TMS_DECOMPOSER_AGENT]
    P2 -->|DATA_AGENT_RUN| DD[TMS_DEDUPE_AGENT]
    P3 -->|DATA_AGENT_RUN| CR[TMS_CRITERIA_AGENT]
    O -->|package / dedupe / criteria の JSON| C
    C -->|02 と同じ契約で検証・集約| PA[(PROPOSED_ACTIONS)]
```

## 3. 作られるオブジェクト

| オブジェクト | 説明 |
|----|----|
| `AGENTS.TMS_ORCHESTRATOR_AGENT` | 3 つのツールで Worker を呼び、返答をそのまま 1 つの JSON にまとめる（予算 300 秒 / 40,000 トークン） |
| `AGENTS.ASK_DECOMPOSER_WORKER` / `ASK_DEDUPE_WORKER` / `ASK_CRITERIA_WORKER` | Worker を 1 回呼んでテキストだけを返す（所有者権限、呼び先は固定） |
| `APP.RUN_MEETING_NOTE_ORCHESTRATED(NOTE_ID)` | オーケストレーターを呼び、返答を検証して提案に保存するコントローラ |

## 4. 構築方法

ラッパープロシージャ（`sql/20_procedures.sql`、抜粋）。エージェント名は引数ではなく定数です。

```python
AGENT = "<% db %>.AGENTS.TMS_DECOMPOSER_AGENT"

def run(session, request):
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": request}]}]})
    raw = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R", params=[AGENT, body]).collect()[0]["R"]
    ...
    return text   # Worker の最終テキストだけを返す（思考過程やツール呼び出しは返さない）
```

オーケストレーターの仕様（`agents/orchestrator.yaml`、抜粋）。ツールはプロシージャに結び付けます。

```yaml
tools:
  - tool_spec:
      type: generic
      name: ask_decomposer_worker
      input_schema: {type: object, properties: {request: {type: string}}, required: [request]}
tool_resources:
  ask_decomposer_worker:
    type: procedure
    identifier: <% db %>.AGENTS.ASK_DECOMPOSER_WORKER
    execution_environment: {type: warehouse, warehouse: <% wh %>, query_timeout: 180}
```

`agent_toolset` のように他エージェントの**ツールを取り込む**方法では、Worker 自身の指示・コンテキスト・予算は使われません。
このパターンは Worker を**別のエージェントとして実行**するため、Worker の指示とツールがそのまま効きます。

## 5. 実行と期待結果

`./run.sh -c <your_connection>`（または `sql/90_try.sql`）。期待される提案は 02 と同じ 2 件（CREATE_TASK と T-108 への LINK_DUPLICATE）です。

2026-10-27 の検証では期待どおりの 2 件でした。オーケストレーター 1 回の呼び出しは約 42 秒で、02 の Worker 合計（約 28 秒）より長くなりました。
また、指示では Decomposer → Dedupe → Criteria の順ですが、トレース上は Criteria → Dedupe の順に呼ばれていました。結果は同じでしたが、**順序は保証されない**ことに注意してください。

トレース（`V_RUN_TRACE`）でコントローラから見えるのは、オーケストレーターの 1 ステップと、そのツール呼び出し（`VIA_ORCHESTRATOR`）だけです。
各 Worker の内部（ツール呼び出し、トークン）は Snowsight の **AI & ML > Agents > 各エージェント > Monitoring** で確認します。

## 6. 設計上のポイントとトレードオフ（02 との比較）

| 観点 | 02 コントローラ型 | 03 エージェント型 |
|----|----|----|
| 手順を決めるのは | コード（`WORKER_PLAN`） | オーケストレーターの LLM |
| 順序・入力の保証 | あり | 指示はできるが保証なし |
| 手順の変更 | コード / テーブルの変更 | 指示文の変更 |
| 所要時間 | 短い | オーケストレーターの推論分だけ長い |
| トレース | 1 本（コントローラが記録） | オーケストレーター + 各 Worker の Monitoring |

- **呼び先の固定**: プロシージャごとに呼べるエージェントを 1 つに固定し、オーケストレーターが任意のエージェントを呼べないようにしています。
- **所有者権限**: ラッパーは `EXECUTE AS OWNER` で、所有者の権限で Worker を呼びます。オーケストレーターに渡るのは「このプロシージャを呼ぶ」能力だけで、Worker の選択や任意の SQL 実行はできません。
- **最後はコードが検証**: オーケストレーターの返答も 02 と同じ契約（引用の存在確認など）で検証してから提案にします。

## 7. 自分のユースケースへの応用

- 呼び出す Worker が状況で変わる（例: 問い合わせ内容によって法務・経理・技術のエージェントを呼び分ける）場合に向きます。
- 外部の MCP クライアントにも公開したい場合は [05](../05_mcp_agent_chaining/)、手順の部品化が目的なら [06](../06_skill_composition/) と比較してください。

## 8. 削除

```bash
./teardown.sh -c <your_connection> --confirm   # オーケストレーターとプロシージャ 4 つを削除（Worker は 02 側に残る）
```

## 9. 参考リンク

- [CREATE AGENT（tools / tool_resources）](https://docs.snowflake.com/en/sql-reference/sql/create-agent)
- [Cortex Agents のアクセス制御](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-setup)
- [Cortex Agents のモニタリング](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-monitor)
