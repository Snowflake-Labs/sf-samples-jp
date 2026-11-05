-- procedures/steps.sql — ワークフローのステップ。Task グラフ（sql/tasks/dag.sql）から呼ぶ。
-- 実行ロール：<% role_predict %>（owner's rights）。
--
--   S00 PREFLIGHT  ラン台帳と入力の照合（対象の PDF が入力ステージにあるか）
--   S10 PREDICT    予測ジョブ（段 A〜R。AI はジョブから <% schema_ops %>.AI_CALL を呼ぶ）
--   S20 EVALUATE   評価ジョブ（評価の構成を作るまでは、評価を指定した run を失敗にする）
--   S30 REPORT     完了記録
USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S00_PREFLIGHT(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_docs INT;
  n_missing INT;
  missing STRING;
  bad_run EXCEPTION (-20002, 'S00: run が RUNS 台帳に無いか、対象の PDF が 0 件');
  no_input EXCEPTION (-20001, 'S00: 入力ステージに無い PDF がある（upload を先に実行する）');
BEGIN
  SELECT COALESCE(MAX(ARRAY_SIZE(docs)), 0) INTO :n_docs FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  IF (n_docs = 0) THEN
    RAISE bad_run;
  END IF;
  UPDATE <% db %>.<% schema_ops %>.RUNS SET status = 'RUNNING', message = NULL,
    started_at = COALESCE(started_at, CURRENT_TIMESTAMP()) WHERE run_id = :P_RUN_ID;
  WITH d AS (SELECT v.value::STRING AS pdf_id, r.corpus, r.config:revision::STRING AS rev
             FROM <% db %>.<% schema_ops %>.RUNS r, LATERAL FLATTEN(input => r.docs) v
             WHERE r.run_id = :P_RUN_ID),
       f AS (SELECT relative_path FROM DIRECTORY(@<% db %>.<% schema_raw %>.PDFS))
  SELECT COUNT(*), LISTAGG(d.pdf_id, ',') INTO :n_missing, :missing FROM d
  WHERE NOT EXISTS (SELECT 1 FROM f WHERE f.relative_path = d.corpus || '/' || d.rev || '/' || d.pdf_id || '.pdf');
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t USING (SELECT 1) s
  ON t.run_id = :P_RUN_ID AND t.step = 'S00' AND t.doc_id = '*'
  WHEN MATCHED THEN UPDATE SET status = IFF(:n_missing = 0, 'SUCCEEDED', 'FAILED'),
    started_at = CURRENT_TIMESTAMP(), ended_at = CURRENT_TIMESTAMP(), attempt = t.attempt + 1,
    n_errors = :n_missing, error_text = IFF(:n_missing = 0, NULL, 'missing: ' || :missing)
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, ended_at, attempt, n_errors, error_text)
    VALUES (:P_RUN_ID, 'S00', '*', IFF(:n_missing = 0, 'SUCCEEDED', 'FAILED'), CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP(), 1, :n_missing, IFF(:n_missing = 0, NULL, 'missing: ' || :missing));
  IF (n_missing > 0) THEN
    RAISE no_input;
  END IF;
  RETURN OBJECT_CONSTRUCT('step', 'S00', 'n_docs', n_docs);
END;
$$;

-- 予測ジョブの起動。ひな型（@<% schema_app %>.SPECS/predict.yaml）に値を埋めて EXECUTE JOB SERVICE（同期）で実行する。
-- 全 PDF が成功済みなら起動しない（再開）。ジョブが非 0 で終わっても、ログを JOBS に残してから失敗にする。
CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S10_PREDICT(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  job STRING;
  img STRING;
  tag STRING;
  sql_text STRING;
  logs STRING;
  msg STRING;
  n_docs INT;
  n_done INT;
BEGIN
  SELECT image_tag, ARRAY_SIZE(docs) INTO :tag, :n_docs FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  SELECT COUNT(*) INTO :n_done FROM <% db %>.<% schema_ops %>.STEP_RUNS
    WHERE run_id = :P_RUN_ID AND step = 'P' AND status = 'SUCCEEDED';
  IF (n_docs IS NULL) THEN
    LET e0 EXCEPTION (-20013, 'S10: run が RUNS 台帳に無い');
    RAISE e0;
  END IF;
  IF (n_done = n_docs) THEN
    RETURN OBJECT_CONSTRUCT('step', 'S10', 'skipped', 'all PDFs already succeeded');
  END IF;
  IF (tag IS NULL OR NOT REGEXP_LIKE(tag, '^[0-9]{14}$')) THEN
    LET e EXCEPTION (-20011, 'S10: イメージタグが不正（UTC の日時 14 桁）');
    RAISE e;
  END IF;
  IF (P_RUN_ID IS NULL OR NOT REGEXP_LIKE(:P_RUN_ID, '^[A-Za-z0-9_-]{1,64}$')) THEN
    LET e2 EXCEPTION (-20012, 'S10: run_id に使えない文字がある');
    RAISE e2;
  END IF;
  img := '/' || LOWER('<% db %>/<% schema_app %>/IMAGES/<% image_name %>:') || tag;
  job := '<% db %>.<% schema_ops %>.JOB_PREDICT_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISSFF3');
  INSERT INTO <% db %>.<% schema_ops %>.JOBS (run_id, step, job_name, status, started_at)
    VALUES (:P_RUN_ID, 'S10', :job, 'RUNNING', CURRENT_TIMESTAMP());
  sql_text := 'EXECUTE JOB SERVICE IN COMPUTE POOL <% compute_pool %> NAME = ' || job ||
              ' QUERY_WAREHOUSE = <% warehouse %>' ||
              ' FROM @<% db %>.<% schema_app %>.SPECS SPECIFICATION_TEMPLATE_FILE = ''predict.yaml''' ||
              ' USING (run_id => ''"' || :P_RUN_ID || '"'', image => ''"' || img || '"'', image_tag => ''"' || tag || '"''' ||
              ', stage_pdfs => ''"@<% db %>.<% schema_raw %>.PDFS"''' ||
              ', stage_results => ''"@<% db %>.<% schema_output %>.RESULTS"'')';
  BEGIN
    EXECUTE IMMEDIATE :sql_text;
    msg := 'DONE';
  EXCEPTION
    WHEN OTHER THEN
      msg := SQLERRM;
  END;
  BEGIN
    logs := SYSTEM$GET_SERVICE_LOGS(:job, 0, 'main', 300);
  EXCEPTION
    WHEN OTHER THEN
      logs := 'ログを取得できない: ' || SQLERRM;
  END;
  UPDATE <% db %>.<% schema_ops %>.JOBS SET status = IFF(:msg = 'DONE', 'SUCCEEDED', 'FAILED'),
    ended_at = CURRENT_TIMESTAMP(), message = :msg, logs = :logs WHERE job_name = :job;
  IF (msg <> 'DONE') THEN
    LET e3 EXCEPTION (-20010, '予測ジョブが失敗した（JOBS と STEP_RUNS を参照）');
    RAISE e3;
  END IF;
  RETURN OBJECT_CONSTRUCT('step', 'S10', 'job', job, 'status', msg);
END;
$$;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S30_REPORT(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_docs INT;
  n_ok INT;
  n_fail INT;
BEGIN
  SELECT ARRAY_SIZE(docs) INTO :n_docs FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  SELECT COUNT_IF(status = 'SUCCEEDED'), COUNT_IF(status = 'FAILED') INTO :n_ok, :n_fail
  FROM <% db %>.<% schema_ops %>.STEP_RUNS WHERE run_id = :P_RUN_ID AND step = 'P';
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t
  USING (SELECT OBJECT_CONSTRUCT('n_docs', :n_docs, 'n_modules', :n_ok, 'n_failed', :n_fail) AS detail) s
  ON t.run_id = :P_RUN_ID AND t.step = 'S30' AND t.doc_id = '*'
  WHEN MATCHED THEN UPDATE SET status = 'SUCCEEDED', started_at = CURRENT_TIMESTAMP(), ended_at = CURRENT_TIMESTAMP(),
    attempt = t.attempt + 1, detail = s.detail
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, ended_at, attempt, detail)
    VALUES (:P_RUN_ID, 'S30', '*', 'SUCCEEDED', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, s.detail);
  UPDATE <% db %>.<% schema_ops %>.RUNS SET status = IFF(:n_ok = :n_docs, 'SUCCEEDED', 'INCOMPLETE'),
    ended_at = CURRENT_TIMESTAMP(), message = :n_ok || ' / ' || :n_docs || ' modules'
  WHERE run_id = :P_RUN_ID;
  RETURN OBJECT_CONSTRUCT('step', 'S30', 'n_modules', n_ok, 'n_docs', n_docs);
END;
$$;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.FINALIZE_RUN(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_failed INT;
BEGIN
  SELECT COUNT(*) INTO :n_failed FROM <% db %>.<% schema_ops %>.STEP_RUNS
    WHERE run_id = :P_RUN_ID AND status IN ('FAILED', 'RUNNING');
  -- 台帳に行を書く前に落ちたステップも失敗として数える：S30 が成功していなければ失敗
  IF (NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_ops %>.STEP_RUNS
                  WHERE run_id = :P_RUN_ID AND step = 'S30' AND status = 'SUCCEEDED')) THEN
    n_failed := GREATEST(n_failed, 1);
  END IF;
  UPDATE <% db %>.<% schema_ops %>.STEP_RUNS SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP(),
    error_text = COALESCE(error_text, '中断（上流の失敗で止まった）')
  WHERE run_id = :P_RUN_ID AND status = 'RUNNING';
  UPDATE <% db %>.<% schema_ops %>.RUNS SET status = IFF(:n_failed > 0, 'FAILED', status),
    ended_at = COALESCE(ended_at, CURRENT_TIMESTAMP()),
    message = IFF(:n_failed > 0, :n_failed || ' 件の失敗（TASK_HISTORY も参照）。同じ run_id で再開できる', message)
  WHERE run_id = :P_RUN_ID AND (status = 'RUNNING' OR :n_failed > 0);
  RETURN OBJECT_CONSTRUCT('n_failed', n_failed);
END;
$$;
