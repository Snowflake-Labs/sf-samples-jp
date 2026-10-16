-- procedures/steps.sql — S00（preflight）・S10（入力の確認）・RUN_JOB（S30・S50 のジョブ起動）・S70・FINALIZE_RUN
-- 実行ロール：<% role_predict %>（owner's rights）。Task グラフ（sql/tasks/dag.sql）から呼ぶ（個別に CALL して確かめることもできる）。
-- すべて (run_id, step, doc_id) 単位で冪等。失敗は STEP_RUNS・JOBS に理由付きで残し、例外で呼び出し元を止める。
-- ユーザー定義の例外は -20001 以降。

USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

-- ---------------------------------------------------------------- S00 preflight
-- ラン台帳の整合と、入力台帳の照合（予測ロールは正解に触れない）
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
  bad_run EXCEPTION (-20002, 'S00: run が RUNS 台帳に無いか、対象文書が 0 件');
  no_input EXCEPTION (-20001, 'S00: 入力 PDF が RAW.FILES に無い文書がある（jpdocread deploy docs を実行すること）');
BEGIN
  SELECT COALESCE(MAX(ARRAY_SIZE(docs)), 0) INTO :n_docs
  FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  IF (n_docs = 0) THEN
    RAISE bad_run;
  END IF;
  UPDATE <% db %>.<% schema_ops %>.RUNS SET status = 'RUNNING', message = NULL WHERE run_id = :P_RUN_ID;
  -- 対象と供出元の両方が、run のコーパスの入力台帳にあること
  SELECT COUNT(*), LISTAGG(x.doc_id, ',') INTO :n_missing, :missing
  FROM (SELECT DISTINCT r.corpus, d.value::STRING AS doc_id
        FROM <% db %>.<% schema_ops %>.RUNS r, LATERAL FLATTEN(input => ARRAY_CAT(r.docs, COALESCE(r.donors, [])) ) d
        WHERE r.run_id = :P_RUN_ID) x
  WHERE NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_raw %>.FILES f
                    WHERE f.corpus = x.corpus AND f.doc_id = x.doc_id);
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

-- ---------------------------------------------------------------- S10 入力の確認
-- PUT は jpdocread deploy docs が行う。ここでは run の各文書（と供出元）が、台帳と同じ md5 でステージにあることを確かめる
CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S10_INGEST(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_bad INT;
  step_failed EXCEPTION (-20010, 'S10: ステージに PDF が無い、または台帳と md5 が一致しない文書がある');
BEGIN
  ALTER STAGE <% db %>.<% schema_raw %>.DOCS REFRESH;
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t
  USING (
    -- LATERAL FLATTEN を JOIN の左に置けないので CTE に持ち上げる（移植元 F20）
    WITH d AS (SELECT DISTINCT r.corpus, v.value::STRING AS doc_id
               FROM <% db %>.<% schema_ops %>.RUNS r, LATERAL FLATTEN(input => ARRAY_CAT(r.docs, COALESCE(r.donors, []))) v
               WHERE r.run_id = :P_RUN_ID),
         f AS (SELECT corpus, doc_id, rel_path, md5 FROM <% db %>.<% schema_raw %>.FILES
               QUALIFY ROW_NUMBER() OVER (PARTITION BY corpus, doc_id ORDER BY loaded_at DESC) = 1),
         s AS (SELECT relative_path, md5 FROM DIRECTORY(@<% db %>.<% schema_raw %>.DOCS))
    SELECT d.doc_id, f.rel_path, f.md5 AS md5_ledger, s.md5 AS md5_stage
    FROM d LEFT JOIN f ON f.corpus = d.corpus AND f.doc_id = d.doc_id
           LEFT JOIN s ON s.relative_path = f.rel_path) x
  ON t.run_id = :P_RUN_ID AND t.step = 'S10' AND t.doc_id = x.doc_id
  WHEN MATCHED THEN UPDATE SET
    status = IFF(x.md5_stage IS NOT NULL AND x.md5_stage = x.md5_ledger, 'SUCCEEDED', 'FAILED'),
    started_at = CURRENT_TIMESTAMP(), ended_at = CURRENT_TIMESTAMP(), attempt = t.attempt + 1,
    n_errors = IFF(x.md5_stage IS NOT NULL AND x.md5_stage = x.md5_ledger, 0, 1),
    error_text = IFF(x.md5_stage IS NULL, 'ステージに無い', IFF(x.md5_stage <> x.md5_ledger, 'md5 不一致', NULL)),
    output_uri = '@<% db %>.<% schema_raw %>.DOCS/' || x.rel_path
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, ended_at, attempt, n_errors, error_text, output_uri)
    VALUES (:P_RUN_ID, 'S10', x.doc_id,
            IFF(x.md5_stage IS NOT NULL AND x.md5_stage = x.md5_ledger, 'SUCCEEDED', 'FAILED'),
            CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1,
            IFF(x.md5_stage IS NOT NULL AND x.md5_stage = x.md5_ledger, 0, 1),
            IFF(x.md5_stage IS NULL, 'ステージに無い', IFF(x.md5_stage <> x.md5_ledger, 'md5 不一致', NULL)),
            '@<% db %>.<% schema_raw %>.DOCS/' || x.rel_path);
  SELECT COUNT(*) INTO :n_bad FROM <% db %>.<% schema_ops %>.STEP_RUNS
  WHERE run_id = :P_RUN_ID AND step = 'S10' AND status = 'FAILED';
  IF (n_bad > 0) THEN
    RAISE step_failed;
  END IF;
  RETURN OBJECT_CONSTRUCT('step', 'S10', 'n_failed', n_bad);
END;
$$;

-- ---------------------------------------------------------------- S30・S50：ジョブの起動
-- テンプレート（@APP.SPECS/predict.yaml）に値を埋めて EXECUTE JOB SERVICE（同期）で実行する。
-- ジョブが非 0 で終わると EXECUTE JOB SERVICE 自体が失敗する（移植元の実測）。その場合もログを JOBS に残して失敗させる。
CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.RUN_JOB(P_RUN_ID STRING, P_STEP STRING)
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
  fail_docs STRING;
  sql_text STRING;
  logs STRING;
  msg STRING;
  bad_arg EXCEPTION (-20031, 'RUN_JOB: step・run_id・image_tag・corpus の形が不正');
BEGIN
  SELECT image_tag, corpus, COALESCE(config:fail_docs::STRING, '') INTO :tag, :corpus, :fail_docs
  FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  -- 動的 SQL に埋め込む値の形を検査する（SQL インジェクション対策）
  IF (NOT COALESCE(P_STEP IN ('S30', 'S50') AND REGEXP_LIKE(P_RUN_ID, '^[A-Za-z0-9_-]{1,128}$')
           AND REGEXP_LIKE(tag, '^[A-Za-z0-9_.-]{1,64}$') AND REGEXP_LIKE(corpus, '^[a-z][a-z0-9_]{0,31}$')
           AND REGEXP_LIKE(fail_docs, '^[A-Za-z0-9_.,:-]*$'), FALSE)) THEN  -- NULL（run が無い等）も不正
    RAISE bad_arg;
  END IF;
  img := '/' || LOWER('<% db %>/<% schema_app %>/IMAGES/<% image_name %>:') || tag;
  job := '<% db %>.<% schema_ops %>.JOB_' || P_STEP || '_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISSFF3');
  INSERT INTO <% db %>.<% schema_ops %>.JOBS (run_id, step, job_name, status, started_at)
    VALUES (:P_RUN_ID, :P_STEP, :job, 'RUNNING', CURRENT_TIMESTAMP());
  -- USING の値は JSON リテラルとしてテンプレートに差し込まれる（文字列は引用符ごと入る）
  sql_text := 'EXECUTE JOB SERVICE IN COMPUTE POOL <% compute_pool %> NAME = ' || job ||
              ' QUERY_WAREHOUSE = <% warehouse %>' ||
              ' FROM @<% db %>.<% schema_app %>.SPECS SPECIFICATION_TEMPLATE_FILE = ''predict.yaml''' ||
              ' USING (step => ''"' || LOWER(P_STEP) || '"'', run_id => ''"' || P_RUN_ID || '"''' ||
              ', image => ''"' || img || '"'', image_tag => ''"' || tag || '"''' ||
              ', warehouse => ''"<% warehouse %>"''' ||
              ', docs_dir => ''"/stage/docs/' || corpus || '"''' ||
              ', stage_docs => ''"@<% db %>.<% schema_raw %>.DOCS"''' ||
              ', stage_work => ''"@<% db %>.<% schema_raw %>.WORK"''' ||
              ', stage_results => ''"@<% db %>.<% schema_output %>.RESULTS"''' ||
              ', fail_docs => ''"' || fail_docs || '"'')';
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
      logs := 'ログを取得できない: ' || SQLERRM;
  END;
  UPDATE <% db %>.<% schema_ops %>.JOBS SET status = IFF(:msg = 'DONE', 'SUCCEEDED', 'FAILED'),
    ended_at = CURRENT_TIMESTAMP(), message = :msg, logs = :logs WHERE job_name = :job;
  IF (msg <> 'DONE') THEN
    LET e EXCEPTION (-20030, 'ジョブが失敗した（OPS.JOBS と STEP_RUNS を参照）');
    RAISE e;
  END IF;
  RETURN OBJECT_CONSTRUCT('step', :P_STEP, 'job', job, 'status', msg);
END;
$$;

-- ---------------------------------------------------------------- S70 完了記録
CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S70_REPORT(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_json INT;
  n_docs INT;
  corpus STRING;
BEGIN
  SELECT ARRAY_SIZE(docs), corpus INTO :n_docs, :corpus FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  ALTER STAGE <% db %>.<% schema_output %>.RESULTS REFRESH;
  SELECT COUNT(*) INTO :n_json FROM DIRECTORY(@<% db %>.<% schema_output %>.RESULTS)
  WHERE STARTSWITH(relative_path, :P_RUN_ID || '/' || :corpus || '/') AND ENDSWITH(relative_path, '.json');
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t
  USING (SELECT OBJECT_CONSTRUCT('n_json', :n_json, 'n_docs', :n_docs) AS detail) s
  ON t.run_id = :P_RUN_ID AND t.step = 'S70' AND t.doc_id = '*'
  WHEN MATCHED THEN UPDATE SET status = 'SUCCEEDED', started_at = CURRENT_TIMESTAMP(), ended_at = CURRENT_TIMESTAMP(),
    attempt = t.attempt + 1, detail = s.detail
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, ended_at, attempt, detail)
    VALUES (:P_RUN_ID, 'S70', '*', 'SUCCEEDED', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, s.detail);
  UPDATE <% db %>.<% schema_ops %>.RUNS SET status = IFF(:n_json = :n_docs, 'SUCCEEDED', 'INCOMPLETE'),
    ended_at = CURRENT_TIMESTAMP(), message = :n_json || ' / ' || :n_docs || ' JSON'
  WHERE run_id = :P_RUN_ID;
  RETURN OBJECT_CONSTRUCT('step', 'S70', 'n_json', n_json, 'n_docs', n_docs);
END;
$$;

-- ---------------------------------------------------------------- 失敗時の記録（Task グラフの finalizer から呼ぶ）
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
  UPDATE <% db %>.<% schema_ops %>.STEP_RUNS SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP(),
    error_text = COALESCE(error_text, '中断（上流の失敗で止まった）')
  WHERE run_id = :P_RUN_ID AND status = 'RUNNING';
  UPDATE <% db %>.<% schema_ops %>.RUNS SET status = IFF(:n_failed > 0, 'FAILED', status),
    ended_at = COALESCE(ended_at, CURRENT_TIMESTAMP()),
    message = IFF(:n_failed > 0, :n_failed || ' 件の失敗。scripts/start.sh --resume ' || :P_RUN_ID || ' で再実行', message)
  WHERE run_id = :P_RUN_ID AND (status = 'RUNNING' OR :n_failed > 0);
  RETURN OBJECT_CONSTRUCT('n_failed', n_failed);
END;
$$;
