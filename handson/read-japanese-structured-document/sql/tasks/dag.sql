-- tasks/dag.sql — ワークフローの Task グラフ
-- オーナー：<% role_predict %>。ルートは SUSPENDED のまま置き、start.sh が EXECUTE TASK … USING CONFIG で起動する。
--
--   T_S00 → T_S10 ─┬─ T_S20 ─────────┐
--                  └─ T_S30 → T_S40 ─┴→ T_S50 → T_S55 → T_S60 → T_S70     （finalizer：T_FINALIZE）
--
-- CONFIG：{"run_id": "...", "from": "S00", "skip_eval": true}（start.sh が --eval のときだけ false にする）
--   from      … これより前のステップは本体を飛ばす（--resume --from S50）。飛ばしても台帳の完了済みはそのまま
--   skip_eval … true なら S60 を飛ばす
-- 各ステップは (run_id, step, doc_id) 単位で冪等なので、--resume では同じ run_id で最初から起動し直せばよい。

USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;
USE SCHEMA <% db %>.<% schema_ops %>;

-- 変更は root を止めてから（新規作成時は SUSPENDED）
ALTER TASK IF EXISTS <% db %>.<% schema_ops %>.T_S00 SUSPEND;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.RUN_STEP(P_STEP STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  run_id STRING;
  from_step STRING;
  from_pos INTEGER;
  step_pos INTEGER;
  -- ステップの順序表。前後はこの配列の位置で比べる（文字列の大小に頼らない）。jpdocread run の --from と同じ値
  step_order ARRAY DEFAULT ARRAY_CONSTRUCT('S00', 'S10', 'S20', 'S30', 'S40', 'S50', 'S55', 'S60', 'S70');
  skip_eval BOOLEAN;
  res VARIANT;
BEGIN
  run_id := SYSTEM$GET_TASK_GRAPH_CONFIG('run_id')::STRING;
  from_step := COALESCE(SYSTEM$GET_TASK_GRAPH_CONFIG('from')::STRING, 'S00');
  skip_eval := COALESCE(SYSTEM$GET_TASK_GRAPH_CONFIG('skip_eval')::BOOLEAN, TRUE);  -- 既定は評価しない（--eval で false）
  IF (run_id IS NULL) THEN
    LET e EXCEPTION (-20100, 'CONFIG に run_id が無い');
    RAISE e;
  END IF;
  -- run_id は RUN_JOB が EXECUTE IMMEDIATE の文字列に連結する。start.sh を通らない EXECUTE TASK もあり得るのでここでも形を検査する
  IF (NOT REGEXP_LIKE(run_id, '^[A-Za-z0-9_-]{1,128}$')) THEN
    LET bad_run EXCEPTION (-20102, 'CONFIG の run_id の形が不正');
    RAISE bad_run;
  END IF;
  from_pos := ARRAY_POSITION(from_step::VARIANT, step_order);
  IF (from_pos IS NULL) THEN
    LET bad_from EXCEPTION (-20101, 'CONFIG の from が順序表に無い');
    RAISE bad_from;
  END IF;
  step_pos := ARRAY_POSITION(P_STEP::VARIANT, step_order);
  -- S00 は常に実行する（run の状態を RUNNING に戻す）。それ以外は from より前なら飛ばす
  IF (P_STEP NOT IN ('S00', 'S70', 'FINALIZE') AND step_pos < from_pos) THEN
    RETURN OBJECT_CONSTRUCT('step', P_STEP, 'skipped', TRUE);
  END IF;
  IF (P_STEP = 'S60' AND skip_eval) THEN
    RETURN OBJECT_CONSTRUCT('step', P_STEP, 'skipped', TRUE);
  END IF;
  CASE (P_STEP)
    WHEN 'S00' THEN CALL <% db %>.<% schema_ops %>.S00_PREFLIGHT(:run_id) INTO :res;
    WHEN 'S10' THEN CALL <% db %>.<% schema_ops %>.S10_INGEST(:run_id) INTO :res;
    WHEN 'S20' THEN CALL <% db %>.<% schema_ops %>.S20_PARSE_TEXT(:run_id) INTO :res;
    WHEN 'S30' THEN CALL <% db %>.<% schema_ops %>.RUN_JOB(:run_id, 'S30') INTO :res;
    WHEN 'S40' THEN CALL <% db %>.<% schema_ops %>.S40_FIGURES(:run_id) INTO :res;
    WHEN 'S50' THEN CALL <% db %>.<% schema_ops %>.RUN_JOB(:run_id, 'S50') INTO :res;
    WHEN 'S55' THEN CALL <% db %>.<% schema_ops %>.S55_REGISTER(:run_id) INTO :res;
    WHEN 'S60' THEN
      -- S60 は評価ロールのプロシージャ。予測側の台帳には状態だけを書く（評価値は書かない）
      IF (EXISTS (SELECT 1 FROM <% db %>.<% schema_ops %>.STEP_RUNS WHERE run_id = :run_id AND step = 'S60' AND doc_id = '*'
                  AND status = 'SUCCEEDED')) THEN
        RETURN OBJECT_CONSTRUCT('step', 'S60', 'skipped', 'already succeeded');
      END IF;
      MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t USING (SELECT 1) s
      ON t.run_id = :run_id AND t.step = 'S60' AND t.doc_id = '*'
      WHEN MATCHED THEN UPDATE SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP(), ended_at = NULL,
        attempt = t.attempt + 1, error_text = NULL
      WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, attempt)
        VALUES (:run_id, 'S60', '*', 'RUNNING', CURRENT_TIMESTAMP(), 1);
      BEGIN
        CALL <% db %>.<% schema_ops %>.S60_EVALUATE(:run_id) INTO :res;
      EXCEPTION
        WHEN OTHER THEN
          UPDATE <% db %>.<% schema_ops %>.STEP_RUNS SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP(), n_errors = 1,
            error_text = :SQLERRM || '（詳細は評価ロールで <% eval_db %>.<% schema_results %>.EVAL_STEPS を参照）'
          WHERE run_id = :run_id AND step = 'S60' AND doc_id = '*';
          RAISE;
      END;
      UPDATE <% db %>.<% schema_ops %>.STEP_RUNS SET status = 'SUCCEEDED', ended_at = CURRENT_TIMESTAMP(), n_errors = 0,
        output_uri = '<% eval_db %>.<% schema_results %>.EVAL_RUNS'
      WHERE run_id = :run_id AND step = 'S60' AND doc_id = '*';
    WHEN 'S70' THEN CALL <% db %>.<% schema_ops %>.S70_REPORT(:run_id) INTO :res;
    WHEN 'FINALIZE' THEN CALL <% db %>.<% schema_ops %>.FINALIZE_RUN(:run_id) INTO :res;
  END CASE;
  RETURN res;
END;
$$;

-- ジョブ待ちがあるので、タスクのタイムアウトは長めに取る（全量の S50 で数十分）
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S00
  WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 600000
  CONFIG = $${"run_id": null, "from": "S00", "skip_eval": true}$$
  AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S00');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S10 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 600000
  AFTER <% db %>.<% schema_ops %>.T_S00 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S10');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S20 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 7200000
  AFTER <% db %>.<% schema_ops %>.T_S10 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S20');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S30 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 7200000
  AFTER <% db %>.<% schema_ops %>.T_S10 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S30');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S40 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 7200000
  AFTER <% db %>.<% schema_ops %>.T_S30 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S40');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S50 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 7200000
  AFTER <% db %>.<% schema_ops %>.T_S20, <% db %>.<% schema_ops %>.T_S40 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S50');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S55 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 3600000
  AFTER <% db %>.<% schema_ops %>.T_S50 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S55');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S60 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 7200000
  AFTER <% db %>.<% schema_ops %>.T_S55 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S60');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S70 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 600000
  AFTER <% db %>.<% schema_ops %>.T_S60 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S70');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_FINALIZE WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 600000
  FINALIZE = <% db %>.<% schema_ops %>.T_S00
  AS CALL <% db %>.<% schema_ops %>.RUN_STEP('FINALIZE');

-- 子と finalizer を有効化する。root（T_S00）は SUSPENDED のまま（EXECUTE TASK で手動起動）
ALTER TASK <% db %>.<% schema_ops %>.T_FINALIZE RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S70 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S60 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S55 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S50 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S40 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S30 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S20 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S10 RESUME;
