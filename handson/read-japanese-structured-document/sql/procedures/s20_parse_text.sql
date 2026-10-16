-- procedures/s20_parse_text.sql — S20：AI_PARSE_DOCUMENT（LAYOUT）で本文を読む
-- 実行ロール：<% role_predict %>（owner's rights）。冪等：キャッシュキーが一致する文書は呼ばない。
--
-- キャッシュキー = SHA2(corpus | doc_id | 入力ファイルの md5 | 関数 | オプション)。同じ PDF・同じ条件なら別の run でも再課金しない。
-- 失敗（NULL・error）は空文字にせず、err 付きの行として PARSE_RAW に残す。失敗行はキャッシュとして扱わない。
--
-- 故障注入：RUNS.config.fail_docs に `S20:<doc_id>` があれば、その文書は**キャッシュを使わずに実際に呼び**、
-- 返ったページの有無にかかわらず err = 'injected:page_count_mismatch' とする（start.sh の --fail・--resume の実演用）。

USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S20_PARSE_TEXT(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_target INT;
  n_called INT;
  n_err INT;
  qid STRING;
  step_failed EXCEPTION (-20020, 'S20: 失敗した文書がある（STEP_RUNS を参照）');
BEGIN
  -- 対象：この run の文書のうち、S20 が未完了のもの（入力台帳はコーパスで引く）
  CREATE OR REPLACE TEMPORARY TABLE S20_TARGET AS
  SELECT f.corpus, f.doc_id, f.rel_path, f.md5,
         SHA2(f.corpus || '|' || f.doc_id || '|' || f.md5 || '|AI_PARSE_DOCUMENT|{"mode":"LAYOUT","page_split":true}') AS cache_key,
         POSITION(',S20:' || f.doc_id || ',' IN ',' || REPLACE(d.fail_docs, ' ', '') || ',') > 0 AS inj
  FROM <% db %>.<% schema_raw %>.FILES f
  JOIN (SELECT r.corpus, v.value::STRING AS doc_id, COALESCE(r.config:fail_docs::STRING, '') AS fail_docs
        FROM <% db %>.<% schema_ops %>.RUNS r, LATERAL FLATTEN(input => r.docs) v
        WHERE r.run_id = :P_RUN_ID) d ON d.corpus = f.corpus AND d.doc_id = f.doc_id
  WHERE NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_ops %>.STEP_RUNS s WHERE s.run_id = :P_RUN_ID AND s.step = 'S20'
                    AND s.doc_id = f.doc_id AND s.status = 'SUCCEEDED')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY f.corpus, f.doc_id ORDER BY f.loaded_at DESC) = 1;
  SELECT COUNT(*) INTO :n_target FROM S20_TARGET;

  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t
  USING (SELECT doc_id FROM S20_TARGET) s ON t.run_id = :P_RUN_ID AND t.step = 'S20' AND t.doc_id = s.doc_id
  WHEN MATCHED THEN UPDATE SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP(), ended_at = NULL,
    attempt = t.attempt + 1, error_text = NULL
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, attempt)
    VALUES (:P_RUN_ID, 'S20', s.doc_id, 'RUNNING', CURRENT_TIMESTAMP(), 1);

  -- キャッシュに成功行が無いもの（と故障注入の対象）だけ AI_PARSE_DOCUMENT を呼ぶ（集合演算で 1 回）
  CREATE OR REPLACE TEMPORARY TABLE S20_CALLED AS
  SELECT t.corpus, t.doc_id, t.md5, t.cache_key, t.inj,
         AI_PARSE_DOCUMENT(TO_FILE('@<% db %>.<% schema_raw %>.DOCS', t.rel_path),
                           {'mode': 'LAYOUT', 'page_split': TRUE}, TRUE) AS r
  FROM S20_TARGET t
  WHERE t.inj
     OR NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_parsed %>.PARSE_RAW c WHERE c.cache_key = t.cache_key AND c.err IS NULL);
  qid := LAST_QUERY_ID();
  SELECT COUNT(*) INTO :n_called FROM S20_CALLED;

  INSERT INTO <% db %>.<% schema_parsed %>.PARSE_RAW
    (cache_key, corpus, doc_id, file_md5, fn, model, options, options_hash, prompt_version, page_count,
     n_pages_returned, err, query_id, run_id)
  SELECT cache_key, corpus, doc_id, md5, 'AI_PARSE_DOCUMENT', NULL, PARSE_JSON('{"mode":"LAYOUT","page_split":true}'),
         SHA2('{"mode":"LAYOUT","page_split":true}'), NULL,
         r:metadata:pageCount::INT, ARRAY_SIZE(r:value:pages),
         CASE WHEN inj THEN 'injected:page_count_mismatch'
              WHEN r IS NULL THEN 'null_output'
              WHEN r:error IS NOT NULL AND r:error::STRING <> '' THEN r:error::STRING
              WHEN r:value:pages IS NULL THEN 'no_pages'
              -- pageCount が無いと次の比較が UNKNOWN になり err が NULL（成功扱い）になるので、先に失敗にする
              WHEN r:metadata:pageCount IS NULL THEN 'no_page_count'
              WHEN ARRAY_SIZE(r:value:pages) <> r:metadata:pageCount::INT THEN 'page_count_mismatch'
         END,
         :qid, :P_RUN_ID
  FROM S20_CALLED;

  -- ページは err の無い呼び出しの分だけ入れる（失敗した試行のページを入れると、再試行で同じ cache_key に 2 回分が並ぶ）
  INSERT INTO <% db %>.<% schema_parsed %>.PARSE_PAGES (cache_key, doc_id, page, content, err, page_count, query_id)
  WITH c AS (SELECT s.* FROM S20_CALLED s
             JOIN <% db %>.<% schema_parsed %>.PARSE_RAW pr
               ON pr.cache_key = s.cache_key AND pr.query_id = :qid AND pr.err IS NULL)
  SELECT c.cache_key, c.doc_id, p.value:index::INT + 1, p.value:content::STRING, NULL,
         c.r:metadata:pageCount::INT, :qid
  FROM c, LATERAL FLATTEN(input => c.r:value:pages) p;

  -- 台帳：成功行がキャッシュにあれば SUCCEEDED、無ければ最新の err で FAILED。
  -- 故障注入の対象は、キャッシュに以前の成功行があっても今回の呼び出しの失敗として FAILED にする
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t
  USING (
    SELECT tg.doc_id,
           IFF(tg.inj, NULL, MAX(IFF(c.err IS NULL, c.cache_key, NULL))) AS ok_key,
           MAX_BY(c.err, c.created_at) AS last_err,
           MAX_BY(c.page_count, c.created_at) AS page_count,
           MAX_BY(c.query_id, c.created_at) AS query_id,
           COUNT_IF(c.query_id = :qid) AS n_called_now
    FROM S20_TARGET tg LEFT JOIN <% db %>.<% schema_parsed %>.PARSE_RAW c ON c.cache_key = tg.cache_key
    GROUP BY tg.doc_id, tg.inj) s
  ON t.run_id = :P_RUN_ID AND t.step = 'S20' AND t.doc_id = s.doc_id
  WHEN MATCHED THEN UPDATE SET
    status = IFF(s.ok_key IS NOT NULL, 'SUCCEEDED', 'FAILED'), ended_at = CURRENT_TIMESTAMP(),
    n_errors = IFF(s.ok_key IS NOT NULL, 0, 1), error_text = IFF(s.ok_key IS NOT NULL, NULL, s.last_err),
    query_id = s.query_id, output_uri = '<% db %>.<% schema_parsed %>.PARSE_PAGES',
    detail = OBJECT_CONSTRUCT('cache_key', s.ok_key, 'page_count', s.page_count,
                              'from_cache', s.n_called_now = 0);

  SELECT COUNT(*) INTO :n_err FROM <% db %>.<% schema_ops %>.STEP_RUNS
  WHERE run_id = :P_RUN_ID AND step = 'S20' AND status = 'FAILED';
  IF (n_err > 0) THEN
    RAISE step_failed;  -- 呼び出し元（Task）を失敗させ、--resume で拾えるようにする
  END IF;
  RETURN OBJECT_CONSTRUCT('step', 'S20', 'n_target', n_target, 'n_called', n_called, 'n_failed', n_err);
EXCEPTION
  WHEN step_failed THEN
    RAISE;
  WHEN OTHER THEN
    UPDATE <% db %>.<% schema_ops %>.STEP_RUNS SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP(), n_errors = 1,
      error_text = :SQLERRM
    WHERE run_id = :P_RUN_ID AND step = 'S20' AND status = 'RUNNING';
    RAISE;
END;
$$;
