## Disclaimer

This application is not part of the Snowflake Service and is governed by the terms in LICENSE, unless expressly agreed to in writing. You use this application at your own risk, and Snowflake has no obligation to support your use of this application.

[Read more](https://github.com/Snowflake-Labs/sf-samples-jp/blob/main/LEGAL.md)

# Snowflake マルチエージェント構成パターン集

[English](README.en.md)

Snowflake Cortex Agents を組み合わせた、**8 種類のマルチエージェント構成**を紹介します。
各パターンには構築スクリプトと解説があり、スクリプトを実行すると自分のアカウントに同じ構成を再現できます。
各 README では、スクリプトの処理内容を SQL の抜粋とともに説明し、設計上のポイントや自分のユースケースへ応用する方法をまとめています。

> この資料は、手順書に沿って 1 ステップずつ構築する形式ではありません。まず動作する構成を作り、そのコードを読みながら仕組みを理解します。

> **注意**: 本資材のマルチエージェント構成パターンは **2026 年 10 月時点** の Snowflake の機能・仕様に基づいています。
> Cortex Agents、MCP サーバー、エージェントスキルなどは今後の機能追加や仕様変更により、利用できる構成や挙動が変わる可能性があります。
> 最新の情報は [公式ドキュメント](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents) を確認してください。

## パターン一覧

| No. | フォルダ | パターン | 一言でいうと |
|----|----|----|----|
| 00 | [`00_common/`](00_common/) | 共通基盤 | 01〜04・07・08 が使う架空のタスク管理システム（データ、ツール、制御テーブル、コントローラ） |
| 01 | [`01_router_handoff/`](01_router_handoff/) | Router / Handoff | ルーターが依頼を分類し、専門エージェント 1 つ（または人間）に渡す |
| 02 | [`02_orchestrator_worker/`](02_orchestrator_worker/) | Orchestrator / Worker（コントローラ型） | Python コントローラが Worker エージェントを順に呼んで結果を集約する |
| 03 | [`03_agent_as_tool/`](03_agent_as_tool/) | Orchestrator / Worker（エージェント型） | オーケストレーター**エージェント**がプロシージャツール経由で Worker エージェントを呼ぶ |
| 04 | [`04_verifier_human_in_the_loop/`](04_verifier_human_in_the_loop/) | Verifier + 人間承認 | 決定論チェック → Verifier エージェント → 人間承認 → 適用・監査 |
| 05 | [`05_mcp_agent_chaining/`](05_mcp_agent_chaining/) | MCP 経由のエージェント呼び出し | Snowflake マネージド MCP サーバーの `CORTEX_AGENT_RUN` ツールで別のエージェントを呼ぶ（1 ホップ / 2 ホップ） |
| 06 | [`06_skill_composition/`](06_skill_composition/) | スキル / サブスキル構成 | エージェントスキルから別スキル（サブスキル）やサブエージェントへ処理を渡す |
| 07 | [`07_parallel_fanout/`](07_parallel_fanout/) | 並列ファンアウト／ファンイン | タスクグラフで 3 つのレビュアーエージェントを**同時に**動かし、決定論的に集約する |
| 08 | [`08_blackboard/`](08_blackboard/) | ブラックボード／イベント駆動 | エージェントは共有の掲示板だけを介して協調。ストリーム + トリガータスクで、状態の変化に反応して動く |

マルチエージェントアーキテクチャの一般的な分類（P01〜P11）との対応:

| 一般的なパターン | 本資材 |
|----|----|
| P01 シーケンシャル（パイプライン） | `02_orchestrator_worker`（配線テーブルどおりに順に呼ぶ） |
| P02 並列ファンアウト／ファンイン | **`07_parallel_fanout`** |
| P03 ルーター／ハンドオフ | `01_router_handoff` |
| P04 オーケストレーター・ワーカー | `02_orchestrator_worker`（コードが調整役）、`03_agent_as_tool`（エージェントが調整役）、`05_mcp_agent_chaining`（MCP 経由で呼ぶ） |
| P05 階層型、P06 スウォーム、P07 グループチャット、P11 A2A | 収録なし（エージェント数が少ない本ユースケースでは利点が小さい、または Snowflake にネイティブの仕組みが無いため） |
| P08 検証（評価・最適化ループ） | `04_verifier_human_in_the_loop`（検証役 + 人間承認） |
| P09 ブラックボード／共有状態・イベント駆動 | **`08_blackboard`** |
| P10 グラフ／状態機械 | `07_parallel_fanout` のタスクグラフ（条件付きタスクで拡張可能） |

## どのパターンを選ぶか

<a id="comparison"></a>

| 観点 | `01_router_handoff` | `02_orchestrator_worker` | `03_agent_as_tool` | `04_verifier_human_in_the_loop` | `05_mcp_agent_chaining` | `06_skill_composition` | `07_parallel_fanout` | `08_blackboard` |
|----|----|----|----|----|----|----|----|----|
| 連携を決めるもの | コード（ルーター出力を検証） | コード（配線テーブル） | オーケストレーターの LLM | コード（固定の検証手順） | 親エージェントの LLM | 親エージェントの LLM（スキル本文の指示） | コード（タスクグラフ） | 掲示板の状態（購読条件） |
| 最終応答の担当 | 選ばれた専門エージェント／人間 | コントローラ（集約）→ 人間 | オーケストレーター（コントローラが検証） | 人間（承認者） | 親エージェント | 親エージェント | 集約プロシージャ（決定論的処理） | 掲示板の `PROPOSALS` 項目 → 人間 |
| コンテキストの分離 | エージェントごとに独立 | エージェントごとに独立 | Worker は独立（1 回のツール入力で呼び出す） | 独立 | 子は独立。ただし、子の応答全体が親に返る | ピア／統合スキルは同一。サブエージェントは独立 | 独立（観点ごとに必要な列だけを渡す） | 独立（掲示板の項目だけを読む） |
| 呼び出し順の保証 | あり | あり | なし（指示はできるが、実行順は LLM が決める） | あり | なし | なし | 順序なし（同時実行）。集約は必ず最後 | 依存関係のみ（状態の条件で決まる） |
| ペイロード | 小 | 小（必要な項目だけを渡す） | 中 | 小 | **ホップごとに増える** | 小〜中 | 小 | 小（項目単位） |
| トレース | `V_RUN_TRACE`（各ステップを 1 行で記録） | `V_RUN_TRACE` | オーケストレーターの記録 + 各エージェントの Monitoring | `V_RUN_TRACE` + `AUDIT_EVENTS` | 親の応答 JSON に入れ子で含まれる | 親の応答（`server_skill` 呼び出し） | `V_REVIEW_WORKERS` + Task History | `V_BOARD_TIMELINE`（来歴）+ Task History |
| 書き込み | 提案のみ | 提案のみ | 提案のみ | 承認後、所有者権限プロシージャだけが実行 | なし（参照用） | なし（参照用） | なし（レポートのみ） | 提案のみ |
| 適した用途 | 窓口での振り分け | 手順が決まった分解・集約 | 実行手順を柔軟に決めたい分解・集約 | 書き込みを伴う業務 | 別チームのエージェントの再利用、外部 MCP クライアントとの共用 | 手順や書式の再利用、エージェントの部品化 | 独立した観点による網羅的な調査・レビュー | 疎結合で非同期の長時間処理、購読者の追加・交換 |

選び方の目安:

```mermaid
flowchart TD
  Q1{書き込みや外部への副作用がある?} -->|はい| P04["04_verifier_human_in_the_loop<br/>Verifier + 人間承認を必ず通す"]
  Q1 -->|いいえ| Q2{処理の順番を保証したい?}
  P04 --> Q2
  Q2 -->|はい| Q3{1 つに振り分けるだけ?}
  Q3 -->|はい| P01["01_router_handoff<br/>Router / Handoff"]
  Q3 -->|いいえ| P02["02_orchestrator_worker<br/>コントローラ型"]
  Q2 -->|いいえ| Q6{独立した観点を同時に調べたい?}
  Q6 -->|はい| P07["07_parallel_fanout<br/>並列ファンアウト"]
  Q6 -->|いいえ| Q7{非同期・疎結合で、参加者を後から増やしたい?}
  Q7 -->|はい| P08["08_blackboard<br/>ブラックボード"]
  Q7 -->|いいえ| Q4{呼び出す対象は?}
  Q4 -->|手順・書式の部品| P06["06_skill_composition<br/>スキル"]
  Q4 -->|独立したエージェント| Q5{MCP クライアントにも公開したい?}
  Q5 -->|はい| P05["05_mcp_agent_chaining<br/>MCP"]
  Q5 -->|いいえ| P03["03_agent_as_tool<br/>エージェント型（プロシージャツール）"]
```

## 前提条件

- Snowflake アカウントと、`ACCOUNTADMIN` ロールを使えるユーザー（ロール・ウェアハウス・データベースを作るため）
- Cortex Agents が使えるリージョン、またはクロスリージョン推論（`CORTEX_ENABLED_CROSS_REGION`）が有効なアカウント
- ユーザーに既定ウェアハウス（`DEFAULT_WAREHOUSE`）が設定されていること（エージェント実行に必要）
- [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/installation/installation) 3.x（`snow`）と、自分のアカウントへの接続（`snow connection add`）
- Python 3.11 以上（`05_mcp_agent_chaining` / `06_skill_composition` の実行スクリプトとテスト用）。テストを動かす場合は `pip install -r tests/requirements.txt`

## クイックスタート

```bash
cd handson/multi-agent-patterns
cp .env.example .env                 # MAP_CONNECTION=<your_connection> を設定（.env は git 管理外）
snow connection list                 # 接続名を確認

scripts/setup_all.sh                 # 00_common〜08_blackboard をすべて作成（-c <your_connection> でも指定可）
./01_router_handoff/run.sh           # 各パターンを試す（run.sh または sql/90_try.sql）
scripts/teardown_all.sh --confirm    # すべて削除（各パターン → 共通基盤の順。--confirm なしでは何も削除しない）
```

1 つのパターンだけ試す場合は、依存関係に注意してください。`01_router_handoff`〜`04_verifier_human_in_the_loop` には `00_common` が必要です。また、`03_agent_as_tool` は `02_orchestrator_worker` の Worker を使います。

```bash
./00_common/setup.sh -c <your_connection>
./02_orchestrator_worker/setup.sh -c <your_connection>
./02_orchestrator_worker/run.sh -c <your_connection>
```

`05_mcp_agent_chaining` と `06_skill_composition` は単独で動きます（`./05_mcp_agent_chaining/setup.sh` → `run.sh`）。`07_parallel_fanout` は `00_common` だけ、`08_blackboard` は `00_common` と `02_orchestrator_worker` が前提です。

## 作成されるオブジェクト

名前はすべて環境変数で変更できます（[`.env.example`](.env.example)）。既存のオブジェクトには触れず、専用の名前空間に作ります。

| 変数 | 既定値 | 用途 |
|----|----|----|
| `MAP_DATABASE` | `MULTI_AGENT_PATTERNS` | `00_common`〜`04_verifier_human_in_the_loop`・`07_parallel_fanout`・`08_blackboard`（スキーマ `APP` / `AGENTS` / `INTERNAL`） |
| `MAP_MCP_DATABASE` | `MAP_MCP_CHAIN` | `05_mcp_agent_chaining`（スキーマ `LAB`） |
| `MAP_SKILL_DATABASE` | `MAP_SKILL_COMPOSITION` | `06_skill_composition`（スキーマ `LAB`） |
| `MAP_WAREHOUSE` | `MULTI_AGENT_PATTERNS_WH` | 全パターン共通（XSMALL、60 秒で自動停止） |
| `MAP_ROLE` | `MULTI_AGENT_PATTERNS_ROLE` | `01_router_handoff`〜`04_verifier_human_in_the_loop`・`07_parallel_fanout`・`08_blackboard` を最小権限で実行するロール |
| `MAP_ENABLE_CROSS_REGION` | `false` | `true` かつ無効な場合だけ、アカウントのクロスリージョン推論を有効化 |

### 削除（teardown）

| スクリプト | 削除するもの |
|----|----|
| `scripts/teardown_all.sh --confirm` | すべてのパターンと共通基盤を、依存関係の逆順で削除する。存在しないパターンはスキップするため、繰り返し実行できる |
| `<パターン>/teardown.sh --confirm` | そのパターンが作ったものだけ。`01_router_handoff`〜`04_verifier_human_in_the_loop` はエージェントとプロシージャ、`07_parallel_fanout` / `08_blackboard` はさらにタスク・ストリーム・テーブル、`05_mcp_agent_chaining` / `06_skill_composition` は各 DB |
| `00_common/teardown.sh --confirm` | 共通 DB（`01_router_handoff`〜`04_verifier_human_in_the_loop`・`07_parallel_fanout`・`08_blackboard` を含む）、共通ウェアハウス、ロール。`05_mcp_agent_chaining` / `06_skill_composition` を残したまま実行すると、`05_mcp_agent_chaining` / `06_skill_composition` が使うウェアハウスも消える |

`teardown_all.sh` は、`08_blackboard` → `07_parallel_fanout` → `04_verifier_human_in_the_loop` → `03_agent_as_tool` → `02_orchestrator_worker` → `01_router_handoff` → `06_skill_composition` → `05_mcp_agent_chaining` → `00_common` の順に削除します。

ウェアハウスはすべてのパターンで共用するため、`05_mcp_agent_chaining` / `06_skill_composition` の teardown では削除しません。この 2 つだけを試した場合も、最後に `scripts/teardown_all.sh --confirm` を実行してください。
アカウントレベルの設定（クロスリージョン推論）は teardown でも元に戻しません。

アカウントレベルの設定は、`MAP_ENABLE_CROSS_REGION=true` を指定したときしか変更しません。ユーザー設定（既定ウェアハウスなど）は変更せず、必要な場合は案内を表示するだけです。

## コストの目安

- ウェアハウスは XSMALL で、60 秒で自動停止します。
- エージェント 1 回の呼び出しは数秒〜数十秒です（下記の参考値）。`run.sh` 1 回あたりのエージェント呼び出しは、`01_router_handoff` が 8 回（ルーター 5 + 専門 3）、`02_orchestrator_worker` が 3 回、`03_agent_as_tool` が 4 回（オーケストレーター 1 + Worker 3）、`04_verifier_human_in_the_loop` が 2 回、`07_parallel_fanout` が 6 回（並列 3 + 逐次ベースライン 3）、`08_blackboard` が 3 回です。`05_mcp_agent_chaining` は親 12 回 + 入れ子の呼び出し、`06_skill_composition` は 15 回 + P4 のサブエージェント呼び出しです（既定 3 回 × パターン数、`-n` で変更可）。
- `07_parallel_fanout` / `08_blackboard` はタスクを使います。タスクはウェアハウス `MAP_WAREHOUSE` で動き、`08_blackboard` のトリガータスクは掲示板に新しい項目が来たときだけ実行されます（待機中は課金されません）。試し終わったら teardown してください。
- Cortex Agents の料金はモデルとトークン数で決まります。最新の単価は Snowflake の Service Consumption Table を参照してください。

## 参考値（検証時の挙動）

2026-10-27 に、1 つのテストアカウントで各パターンを実行した結果です。モデルの挙動は変わることがあるため、保証値ではありません。

| パターン | 結果 |
|----|----|
| `01_router_handoff` | 5 件の依頼が期待どおり status / intake / change / human / human に振り分けられた。ルーター 5〜9 秒、Status 約 12 秒 |
| `02_orchestrator_worker` | 会議メモ N-003 から CREATE_TASK 1 件と LINK_DUPLICATE（T-108）1 件。注入行は無視された。エージェント合計約 28 秒 |
| `03_agent_as_tool` | `02_orchestrator_worker` と同じ 2 件。オーケストレーター 1 回の呼び出しで約 42 秒。Worker の呼び出し順は指示と異なった（Criteria → Dedupe） |
| `04_verifier_human_in_the_loop` | 承認前の適用は拒否、PASS → 承認 → 適用（T-1001 作成）、再適用は no-op、HIGH リスク変更は NEEDS_HUMAN |
| `05_mcp_agent_chaining` | 3 回中、子への到達は M1 3/3・M2 3/3・M3 3/3。応答サイズは M0 約 2 KB、M1 約 11 KB、M2 約 26 KB、M3 約 5 KB |
| `06_skill_composition` | ピア登録（P1）3/3 で成功、ネスト配置（P2）0/3（読まれない）、統合（P3）3/3、サブエージェント（P4）3/3 |
| `07_parallel_fanout` | 並列 約 21〜23 秒（3 レビュアーが同時刻に開始）、逐次ベースライン 約 39〜41 秒。どちらも同じ 5 タスク（HIGH 2、MEDIUM 3）を指摘。1 ワーカーを失敗させると PARTIAL のレポート |
| `08_blackboard` | N-003 の投稿から PROPOSALS まで約 82〜86 秒（1 ホップ 20〜30 秒、Dedupe と Criteria は並行）。提案は `02_orchestrator_worker` と同じ 2 件、二重処理なし |

## フォルダ構成

```text
multi-agent-patterns/
|-- README.md               このファイル（パターン比較・選び方）
|-- .env.example            接続名・オブジェクト名の設定例
|-- scripts/                共通シェル関数、全体の setup / teardown、公開前チェック、エージェント SQL の生成
|-- controller/             01_router_handoff〜04_verifier_human_in_the_loop・07_parallel_fanout・08_blackboard が使う Python コントローラ（src/）と JSON 契約（schemas/）
|-- 00_common/ .. 08_*/     各パターン（README.md, setup.sh, run.sh, teardown.sh, sql/, agents/ など）
|-- docs/troubleshooting.md よくあるエラーと対処
`-- tests/                  オフラインの静的テスト（python3 -m pytest tests -q）
```

## 開発者向け

- エージェント仕様の正本は各パターンの `agents/*.yaml` です。編集したら `python3 scripts/build_agents_sql.py` で `sql/10_agents.sql` を再生成してください。
- コミット前に `scripts/check_public.sh` を実行してください。`.env` の `MAP_DENYLIST` に書いた文字列（自分のアカウント名など）が公開ファイルに含まれていないか、静的テストが通るかを確認します。

## トラブルシューティング

[docs/troubleshooting.md](docs/troubleshooting.md) を参照してください。

## 参考リンク

- [Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents)
- [CREATE AGENT](https://docs.snowflake.com/en/sql-reference/sql/create-agent)
- [DATA_AGENT_RUN (SNOWFLAKE.CORTEX)](https://docs.snowflake.com/en/sql-reference/functions/data_agent_run-snowflake-cortex)
- [Cortex Agents のアクセス制御](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-setup)
- [Snowflake マネージド MCP サーバー](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [CREATE MCP SERVER](https://docs.snowflake.com/en/sql-reference/sql/create-mcp-server)
- [Agent skills](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-skills)
- [Cortex Agents のモニタリング](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-monitor)

## データとライセンス

サンプルデータ（プロジェクト・タスク・会議メモ・人名）はすべて架空で、本資材のために作成したものです。外部のデータセットは使用していません。

## 作成者 / Author

- 作成者: [sfc-gh-yshibui](https://github.com/sfc-gh-yshibui)
- 作成日: 2026-10
- 最終更新: 2026-10
