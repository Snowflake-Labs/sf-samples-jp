-- procedures/s60_evaluate.sql — S60：評価ジョブを起動する（オーナー：評価ロール）
-- 予測ロールはこのプロシージャの USAGE だけを持つ（正解・評価結果の表やステージには触れない）。
-- プロシージャは run_id を受け取り、評価ジョブの状態だけを返す（評価値も正解も返さない）。
-- 評価対象：run の文書。供出元と評価除外（RUNS.eval_excluded）は依頼に入れ、採点から外したことを評価結果に残す。

USE ROLE <% role_eval %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S60_EVALUATE(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  job STRING;
  img STRING;
  tag STRING;
  corpus STRING;
  n_gold INT;
  sql_text STRING;
  msg STRING;
  logs STRING;
  bad_arg EXCEPTION (-20061, 'S60: run が無い、または run_id・image_tag・corpus の形が不正');
  no_gold EXCEPTION (-20062, 'S60: 評価ステージに正解が無い（start.sh --eval で置く）');
  failed EXCEPTION (-20060, 'S60: 評価ジョブが失敗した（評価ロールで RESULTS.EVAL_STEPS を参照）');
BEGIN
  SELECT MAX(image_tag), MAX(corpus) INTO :tag, :corpus FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  IF (NOT COALESCE(REGEXP_LIKE(P_RUN_ID, '^[A-Za-z0-9_-]{1,128}$') AND REGEXP_LIKE(tag, '^[A-Za-z0-9_.-]{1,64}$')
                   AND REGEXP_LIKE(corpus, '^[a-z][a-z0-9_]{0,31}$'), FALSE)) THEN
    RAISE bad_arg;
  END IF;
  ALTER STAGE <% eval_db %>.<% schema_gold %>.FILES REFRESH;
  SELECT COUNT(*) INTO :n_gold FROM DIRECTORY(@<% eval_db %>.<% schema_gold %>.FILES)
  WHERE relative_path = :corpus || '/manifest.json';
  IF (n_gold = 0) THEN
    RAISE no_gold;
  END IF;
  DELETE FROM <% eval_db %>.<% schema_results %>.EVAL_REQUESTS WHERE run_id = :P_RUN_ID;
  INSERT INTO <% eval_db %>.<% schema_results %>.EVAL_REQUESTS (run_id, corpus, docs, eval_excluded, image_tag)
    SELECT run_id, corpus, docs, ARRAY_DISTINCT(ARRAY_CAT(COALESCE(eval_excluded, []), COALESCE(donors, []))), image_tag
    FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  MERGE INTO <% eval_db %>.<% schema_results %>.EVAL_STEPS t USING (SELECT 1) s ON t.run_id = :P_RUN_ID
  WHEN MATCHED THEN UPDATE SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP(), ended_at = NULL, error_text = NULL
  WHEN NOT MATCHED THEN INSERT (run_id, status, started_at) VALUES (:P_RUN_ID, 'RUNNING', CURRENT_TIMESTAMP());
  img := '/' || LOWER('<% db %>/<% schema_app %>/IMAGES/<% image_name %>:') || tag;
  job := '<% eval_db %>.<% schema_results %>.JOB_S60_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISSFF3');
  sql_text := 'EXECUTE JOB SERVICE IN COMPUTE POOL <% compute_pool %> NAME = ' || job ||
              ' QUERY_WAREHOUSE = <% warehouse %>' ||
              ' FROM @<% db %>.<% schema_app %>.SPECS SPECIFICATION_TEMPLATE_FILE = ''evaluate.yaml''' ||
              ' USING (run_id => ''"' || P_RUN_ID || '"'', image => ''"' || img || '"''' ||
              ', image_tag => ''"' || tag || '"'', warehouse => ''"<% warehouse %>"''' ||
              ', docs_dir => ''"/stage/gold/' || corpus || '"''' ||
              ', out_dir => ''"/stage/results/' || P_RUN_ID || '/' || corpus || '"''' ||
              ', stage_gold => ''"@<% eval_db %>.<% schema_gold %>.FILES"''' ||
              ', stage_results => ''"@<% db %>.<% schema_output %>.RESULTS"'')';
  BEGIN
    EXECUTE IMMEDIATE :sql_text;
    msg := 'DONE';
  EXCEPTION
    WHEN OTHER THEN
      msg := SQLERRM;
  END;
  BEGIN
    logs := SYSTEM$GET_SERVICE_LOGS(:job, 0, 'main', 200);
  EXCEPTION
    WHEN OTHER THEN
      logs := NULL;
  END;
  IF (msg <> 'DONE') THEN
    -- ログ末尾（Python の例外）を残す。評価値や正解の内容は予測側に返さない
    UPDATE <% eval_db %>.<% schema_results %>.EVAL_STEPS SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP(),
      error_text = LEFT(:msg || CHR(10) || RIGHT(COALESCE(:logs, ''), 4000), 8000)
    WHERE run_id = :P_RUN_ID;
    RAISE failed;
  END IF;
  UPDATE <% eval_db %>.<% schema_results %>.EVAL_STEPS SET status = 'SUCCEEDED', ended_at = CURRENT_TIMESTAMP()
  WHERE run_id = :P_RUN_ID;
  RETURN OBJECT_CONSTRUCT('step', 'S60', 'job', job, 'status', msg);
END;
$$;

GRANT USAGE ON PROCEDURE <% db %>.<% schema_ops %>.S60_EVALUATE(STRING) TO ROLE <% role_predict %>;
