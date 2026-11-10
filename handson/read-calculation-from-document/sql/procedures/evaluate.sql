-- procedures/evaluate.sql — 評価のステップ（S20）。実行ロール：<% role_eval %>（owner's rights）。
--
-- Task グラフの Task はすべて同じオーナー（予測ロール）でなければならないので、評価は Task ではなく
-- 評価ロールが所有するこのプロシージャで起動する。置き場所は予測側の OPS スキーマで、予測ロールには
-- USAGE だけを渡す。予測ロールは評価 DB・正解・評価結果を見ずに、自分の run の採点を起動できるだけになる。
-- 戻り値は eval_run_id と状態だけ（合否の数を予測側へ返さない）。
--
-- 評価ジョブ（evaluate.yaml）は評価ロールで動き、正解のステージと生成物のステージ（読み取り）だけをマウントする。
-- 生成物のステージに評価ロールは READ だけを持つ（書き込めない）。生成コードは正解テストと同じプロセスで動くので、
-- 採点の前に静的検査（ファイル・ネットワーク・import・動的実行の禁止）を通らないモジュールは採点しない。
-- イメージは予測と同じリポジトリのもの（push は管理ロールだけができ、予測ロールは READ だけ）。
USE ROLE <% role_eval %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S20_EVALUATE(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  job STRING;
  img STRING;
  tag STRING;
  eid STRING;
  sql_text STRING;
  logs STRING;
  msg STRING;
  n_rows INT;
BEGIN
  IF (P_RUN_ID IS NULL OR NOT REGEXP_LIKE(:P_RUN_ID, '^[A-Za-z0-9_-]{1,64}$')) THEN
    LET e1 EXCEPTION (-20201, 'S20: run_id に使えない文字がある');
    RAISE e1;
  END IF;
  SELECT COUNT(*), MAX(image_tag) INTO :n_rows, :tag FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  IF (n_rows <> 1) THEN
    LET e2 EXCEPTION (-20202, 'S20: run が RUNS 台帳に無いか重複している');
    RAISE e2;
  END IF;
  IF (tag IS NULL OR NOT REGEXP_LIKE(tag, '^[0-9]{14}$')) THEN
    LET e3 EXCEPTION (-20203, 'S20: イメージタグが不正（UTC の日時 14 桁）');
    RAISE e3;
  END IF;
  eid := :P_RUN_ID || '-e' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISSFF3');
  img := '/' || LOWER('<% db %>/<% schema_app %>/IMAGES/<% image_name %>:') || tag;
  job := '<% eval_db %>.<% schema_results %>.JOB_EVAL_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISSFF3');
  INSERT INTO <% eval_db %>.<% schema_results %>.EVAL_JOBS (eval_run_id, run_id, job_name, status, started_at)
    VALUES (:eid, :P_RUN_ID, :job, 'RUNNING', CURRENT_TIMESTAMP());
  sql_text := 'EXECUTE JOB SERVICE IN COMPUTE POOL <% compute_pool %> NAME = ' || job ||
              ' QUERY_WAREHOUSE = <% warehouse %>' ||
              ' FROM @<% db %>.<% schema_app %>.SPECS SPECIFICATION_TEMPLATE_FILE = ''evaluate.yaml''' ||
              ' USING (run_id => ''"' || :P_RUN_ID || '"'', eval_run_id => ''"' || eid || '"''' ||
              ', image => ''"' || img || '"'', image_tag => ''"' || tag || '"''' ||
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
    logs := SYSTEM$GET_SERVICE_LOGS(:job, 0, 'main', 300);
  EXCEPTION
    WHEN OTHER THEN
      logs := 'ログを取得できない: ' || SQLERRM;
  END;
  UPDATE <% eval_db %>.<% schema_results %>.EVAL_JOBS SET status = IFF(:msg = 'DONE', 'SUCCEEDED', 'FAILED'),
    ended_at = CURRENT_TIMESTAMP(), message = :msg, logs = :logs WHERE job_name = :job;
  IF (msg <> 'DONE') THEN
    LET e4 EXCEPTION (-20210, '評価ジョブが失敗した（評価ロールで EVAL_JOBS を参照）');
    RAISE e4;
  END IF;
  RETURN OBJECT_CONSTRUCT('step', 'S20', 'eval_run_id', eid, 'status', msg);
END;
$$;

GRANT USAGE ON PROCEDURE <% db %>.<% schema_ops %>.S20_EVALUATE(STRING) TO ROLE <% role_predict %>;
