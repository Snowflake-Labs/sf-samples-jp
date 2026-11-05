-- tasks/dag.sql — ワークフローの Task グラフ。オーナー：<% role_predict %>。
-- ルートは SUSPENDED のまま置き、起動は EXECUTE TASK … USING CONFIG で行う。
--
--   T_S00 → T_S10 → T_S20 → T_S30     （finalizer：T_FINALIZE）
--
-- CONFIG：{"run_id": "...", "skip_eval": true}（--eval の run は skip_eval を false にする）
-- 予測は (run_id, P, pdf_id) が SUCCEEDED の PDF を飛ばすので、再開は同じ run_id で起動し直せばよい。
USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;
USE SCHEMA <% db %>.<% schema_ops %>;

ALTER TASK IF EXISTS <% db %>.<% schema_ops %>.T_S00 SUSPEND;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.RECORD_STEP(P_RUN_ID STRING, P_STEP STRING, P_STATUS STRING, P_DETAIL VARIANT)
RETURNS STRING
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
BEGIN
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t USING (SELECT 1) s
  ON t.run_id = :P_RUN_ID AND t.step = :P_STEP AND t.doc_id = '*'
  WHEN MATCHED THEN UPDATE SET status = :P_STATUS, started_at = CURRENT_TIMESTAMP(), ended_at = CURRENT_TIMESTAMP(),
    attempt = t.attempt + 1, detail = :P_DETAIL, error_text = IFF(:P_STATUS = 'FAILED', :P_DETAIL:error::STRING, NULL)
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, ended_at, attempt, detail, error_text)
    VALUES (:P_RUN_ID, :P_STEP, '*', :P_STATUS, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, :P_DETAIL,
            IFF(:P_STATUS = 'FAILED', :P_DETAIL:error::STRING, NULL));
  RETURN P_STATUS;
END;
$$;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.RUN_STEP(P_STEP STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  run_id STRING;
  skip_eval BOOLEAN;
  res VARIANT;
BEGIN
  run_id := SYSTEM$GET_TASK_GRAPH_CONFIG('run_id')::STRING;
  skip_eval := COALESCE(SYSTEM$GET_TASK_GRAPH_CONFIG('skip_eval')::BOOLEAN, TRUE);
  IF (run_id IS NULL) THEN
    LET e EXCEPTION (-20100, 'CONFIG に run_id が無い');
    RAISE e;
  END IF;
  CASE (P_STEP)
    WHEN 'S00' THEN CALL <% db %>.<% schema_ops %>.S00_PREFLIGHT(:run_id) INTO :res;
    WHEN 'S10' THEN CALL <% db %>.<% schema_ops %>.S10_PREDICT(:run_id) INTO :res;
    WHEN 'S20' THEN
      IF (skip_eval) THEN
        RETURN OBJECT_CONSTRUCT('step', 'S20', 'skipped', TRUE);
      END IF;
      -- 評価ロールの所有のプロシージャで評価ジョブを起動する。戻り値は eval_run_id と状態だけ
      BEGIN
        CALL <% db %>.<% schema_ops %>.S20_EVALUATE(:run_id) INTO :res;
        CALL <% db %>.<% schema_ops %>.RECORD_STEP(:run_id, 'S20', 'SUCCEEDED', :res);
      EXCEPTION
        WHEN OTHER THEN
          CALL <% db %>.<% schema_ops %>.RECORD_STEP(:run_id, 'S20', 'FAILED', OBJECT_CONSTRUCT('error', SQLERRM));
          RAISE;
      END;
    WHEN 'S30' THEN CALL <% db %>.<% schema_ops %>.S30_REPORT(:run_id) INTO :res;
    WHEN 'FINALIZE' THEN CALL <% db %>.<% schema_ops %>.FINALIZE_RUN(:run_id) INTO :res;
  END CASE;
  RETURN res;
END;
$$;

CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S00
  WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 600000
  CONFIG = $${"run_id": null, "skip_eval": true}$$
  AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S00');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S10 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 14400000
  AFTER <% db %>.<% schema_ops %>.T_S00 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S10');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S20 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 7200000
  AFTER <% db %>.<% schema_ops %>.T_S10 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S20');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_S30 WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 600000
  AFTER <% db %>.<% schema_ops %>.T_S20 AS CALL <% db %>.<% schema_ops %>.RUN_STEP('S30');
CREATE OR REPLACE TASK <% db %>.<% schema_ops %>.T_FINALIZE WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = 600000
  FINALIZE = <% db %>.<% schema_ops %>.T_S00
  AS CALL <% db %>.<% schema_ops %>.RUN_STEP('FINALIZE');

ALTER TASK <% db %>.<% schema_ops %>.T_FINALIZE RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S30 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S20 RESUME;
ALTER TASK <% db %>.<% schema_ops %>.T_S10 RESUME;
