# データベース設計の概要

このデモで使うデータベースの全体像と、各テーブルの役割をまとめます。
列の定義・制約・インデックスは SQL ファイルを正としてください（この文書には列は書きません）。

| 定義の場所 | 内容 |
|---|---|
| `sql/setup_postgres.sql` | Snowflake Postgres の `hr` スキーマ（業務データ、行レベルセキュリティ） |
| `sql/setup_analytics.sql` | Snowflake の `HR_ANALYTICS`（ロール、ウェアハウス、同期先、ML 結果、マスキング） |
| `sql/setup_search_and_agent.sql` | 人材検索（Cortex Search）と `HR_AGENT` |
| `semantic_models/hr_semantic_view.yaml` | Cortex Analyst 用の Semantic View |
| `scripts/build_feature_tables.py` / `scripts/ml_pipeline_v3.py` | 特徴量・学習・推論・SHAP のテーブルへの書き込み |

---

## 1. 全体の構成

```
Snowflake Postgres（hr スキーマ）        … アプリの読み書き（OLTP）
  │  scripts/sync_pg_to_iceberg.py / sync_remaining.py
  ▼
HR_ANALYTICS.STAGING（Iceberg テーブル） … Postgres の写し。保存先は SNOWFLAKE_MANAGED（外部ボリューム不要）
  │  scripts/build_feature_tables.py
  ▼
HR_ANALYTICS.PUBLIC                       … 特徴量、ML の推論結果、SHAP、AI の根拠文、人材検索の元データ
HR_ANALYTICS.ML                           … Model Registry（ATTRITION_MODEL / RELATIONSHIP_MODEL / TRANSFER_FIT_MODEL）
HR_ANALYTICS.FEATURE_STORE                … Feature Store の Feature View（実体は Dynamic Table。ml_pipeline_v3.py が作る）
HR_ANALYTICS.GOVERNANCE                   … マスキングポリシー、行アクセスポリシー、アクセス履歴ビュー
```

アプリ（`hr-app-v2`）は、業務データを Postgres から、ML の結果を Snowflake から読みます（サイドバーのデータ経路が `snowflake-sdk` の場合）。

---

## 2. Snowflake Postgres（`hr` スキーマ）

| 区分 | テーブル | 役割 |
|---|---|---|
| 組織・社員 | `departments` | 部署（本部・部・課の階層） |
| | `positions` | ポジション（等級、空席の有無） |
| | `employees` | 社員マスタ |
| | `employee_profiles` | 社員の補足情報（入社区分など） |
| | `career_history` | 経歴・異動履歴 |
| | `leave_records` | 休暇の記録 |
| スキル | `skills` / `employee_skills` | スキルの一覧と、社員ごとの保有スキル |
| 評価 | `evaluations` | 半期の評価（点数・コメント） |
| | `peer_feedback` | 360 度フィードバック |
| | `evaluation_analysis` | 評価コメントの分析結果（感情など） |
| | `eval_quantified_scores` | 評価コメントの AI 定量化（5 軸スコア） |
| | `eval_axis_overrides` | 上長による 5 軸スコアの修正と理由 |
| | `grade_score_standards` / `grade_score_standards_history` | 等級別の期待水準・重みと、その変更履歴 |
| | `calibration_sessions` / `calibration_adjustments` | 評価調整会議と、グレードの調整内容 |
| 1on1 | `one_on_one_notes` | 1on1 メモ（カテゴリ: performance / career / motivation / concern / other） |
| | `oneonone_analysis` | 1on1 メモの分析結果 |
| 異動 | `transfer_requests` | 異動申請 |
| | `candidate_lists` | 候補者リスト |
| | `whatif_scenarios` / `whatif_scenario_actions` | 異動シナリオと、その中の昇格・異動・退職のアクション |
| | `chain_simulations` / `chain_simulation_steps` | 玉突き人事のシミュレーションと、その各ステップ |
| | `scenario_snapshots` | シナリオ確定時のスナップショット |
| | `simulation_sessions` | 旧方式（DB クローンでの試算）のセッション。今の画面は `whatif_scenarios` / `chain_simulations` を使う |
| | `action_items` | 社員ごとのフォローアップのアクション |
| アプリ | `app_users` | デモ用ログインのユーザーとロール |
| | `agent_threads` | AI エージェントの会話スレッド |
| | `user_feedback` | 画面ごとの評価（点数・コメント） |

---

## 3. Snowflake（`HR_ANALYTICS`）

### 3.1 STAGING（Postgres の写し）

Postgres の次のテーブルを、同じ名前の Iceberg テーブルとして持ちます。

`DEPARTMENTS`, `EMPLOYEES`, `POSITIONS`, `EVALUATIONS`, `ONE_ON_ONE_NOTES`, `SKILLS`, `EMPLOYEE_SKILLS`, `TRANSFER_REQUESTS`, `APP_USERS`, `LEAVE_RECORDS`, `CANDIDATE_LISTS`, `ACTION_ITEMS`, `SIMULATION_SESSIONS`, `CAREER_HISTORY`, `EMPLOYEE_PROFILES`, `PEER_FEEDBACK`, `ONEONONE_ANALYSIS`, `EVALUATION_ANALYSIS`

- 同期はスクリプトで行います（README の手順 4）。Postgres を変えたあとは、同期し直すまで Snowflake 側には反映されません。
- `POSITIONS` と `APP_USERS` は `sync_remaining.py` で同期します。

### 3.2 PUBLIC（特徴量・ML の結果・AI）

| 区分 | テーブル | 役割 |
|---|---|---|
| 離職予測 | `ATTRITION_FEATURES` | 特徴量（社員ごと） |
| | `PREDICTION_RESULTS` | 離職リスクの推論結果 |
| | `SHAP_RESULTS` | 推論の要因（SHAP 値） |
| 上長との相性 | `RELATIONSHIP_FEATURES` / `RELATIONSHIP_RESULTS` | 特徴量と推論結果 |
| 異動適合 | `TRANSFER_FIT_FEATURES` / `TRANSFER_FIT_RESULTS` | 社員 × 異動先ポジションの特徴量と適合スコア |
| | `DEPT_CULTURE_VECTORS` | 部署ごとの傾向（適合スコアの計算に使う） |
| AI の根拠 | `EVIDENCE_STORE` | 推論結果の根拠文 |
| | `SIMILAR_CASES` | 類似ケース |
| | `AI_INSIGHTS` | 社員ごとの AI 分析結果（種類別の JSON） |
| 分析 | `ONEONONE_ANALYSIS` / `EVALUATION_ANALYSIS` | 1on1・評価コメントの分析結果（STAGING にも同名のテーブルがあり、こちらは分析・ML 用に Snowflake で持つもの） |
| 検索 | `SEARCH_TALENT_SOURCE` | 人材検索（`TALENT_SEARCH_SERVICE`）の元データ。手順 3 では空で作り、手順 6 の `setup_search_and_agent.sql` で作り直す |

このほか、`HR_SEMANTIC_VIEW`（Cortex Analyst）、`TALENT_SEARCH_SERVICE`（Cortex Search）、`HR_AGENT`（Cortex Agent）を PUBLIC に作ります。

### 3.3 GOVERNANCE（アクセス制御）

| オブジェクト | 内容 |
|---|---|
| `SALARY_MASK` | 給与。HR_ADMIN 以外には NULL |
| `PII_EMAIL_MASK` | メールアドレス。HR_ADMIN 以外には一部を `***` にする |
| `EVAL_SCORE_MASK` / `EVAL_COMMENT_MASK` | 評価スコア・コメント。HR_ADMIN と HR_MANAGER 以外には隠す |
| `DEPT_ROW_FILTER` | HR_MANAGER に担当部署の行だけを見せるための行アクセスポリシー。**作成のみで、テーブルには付けていない**（部署の絞り込みはアプリ側で行う） |
| `HR_ADMIN_ONLY_POLICY` | 相性スコアなどを HR_ADMIN だけに見せるための行アクセスポリシー。**作成のみで、テーブルには付けていない** |
| `ACCESS_LOG` | アクセス履歴のビュー（ガバナンス画面で使う） |

---

## 4. 注意点

- **SHAP と根拠文の結び付き:** `SHAP_RESULTS` や `EVIDENCE_STORE` は社員 ID で推論結果と結び付きます。データを作り直すときは、README の手順 4・5 を順番どおりに流してください。
- **pg_lake 経路:** アプリには、Postgres の `hr_lake` スキーマ（pg_lake 経由の Iceberg）から ML の結果を読む経路もあります。README の手順では `hr_lake` を作らないため、データ経路は `snowflake-sdk` を使ってください。
