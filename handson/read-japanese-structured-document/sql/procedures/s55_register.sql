-- procedures/s55_register.sql — S55：出力 JSON を登録表に展開する（「Snowflake への登録」）
-- 新規（移植元には無い）。実行ロール：<% role_predict %>（owner's rights）。
--
-- 入力：@OUTPUT.RESULTS/<run_id>/<corpus>/<doc_id>.json（S50 が書いた正本）。この run で S50 が成功し、S55 が未完了の文書。
-- 出力：<% db %>.<% schema_output %> の DOCUMENTS と、配列を展開した 10 表（PAGES・OUTLINE・ELEMENTS・TABLES・FIGURES・
--       REFS・PARTIES・DEFINED_TERMS・TERM_USES・REPAIR_QUEUE）。列と変換規則は src/jpdocread/load/rows.py と同じ
--       （本ファイルの表ごとの INSERT は rows.py の ARRAY_TABLES から生成した。列の一致はテストで照合する）。
-- 冪等：(run_id, doc_id) の行を DELETE してから INSERT する。字形は変えない。
-- ステージのパスは定数でなければならないので動的 SQL で読む。埋め込む run_id と corpus は形を検査してから使う。

USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S55_REGISTER(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  corpus STRING;
  n_target INT;
  n_found INT;
  n_failed INT;
  read_sql STRING;
  bad_arg EXCEPTION (-20051, 'S55: run_id か corpus の形が不正、または run が無い');
  step_failed EXCEPTION (-20050, 'S55: 出力 JSON が無い文書がある（STEP_RUNS を参照）');
BEGIN
  SELECT MAX(corpus) INTO :corpus FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID;
  IF (NOT COALESCE(REGEXP_LIKE(P_RUN_ID, '^[A-Za-z0-9_-]{1,128}$')
                   AND REGEXP_LIKE(corpus, '^[a-z][a-z0-9_]{0,31}$'), FALSE)) THEN
    RAISE bad_arg;
  END IF;

  -- 対象：S50 が成功し、S55 が未完了の文書
  CREATE OR REPLACE TEMPORARY TABLE S55_TARGET AS
  SELECT s.doc_id FROM <% db %>.<% schema_ops %>.STEP_RUNS s
  WHERE s.run_id = :P_RUN_ID AND s.step = 'S50' AND s.status = 'SUCCEEDED'
    AND NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_ops %>.STEP_RUNS t WHERE t.run_id = :P_RUN_ID
                    AND t.step = 'S55' AND t.doc_id = s.doc_id AND t.status = 'SUCCEEDED');
  SELECT COUNT(*) INTO :n_target FROM S55_TARGET;

  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t USING S55_TARGET s
  ON t.run_id = :P_RUN_ID AND t.step = 'S55' AND t.doc_id = s.doc_id
  WHEN MATCHED THEN UPDATE SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP(), ended_at = NULL,
    attempt = t.attempt + 1, error_text = NULL
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, attempt)
    VALUES (:P_RUN_ID, 'S55', s.doc_id, 'RUNNING', CURRENT_TIMESTAMP(), 1);

  -- ステージの JSON を読む（1 ファイル 1 オブジェクト）。ファイル名から doc_id を取り、対象だけを残す
  read_sql := 'CREATE OR REPLACE TEMPORARY TABLE S55_RAW AS SELECT METADATA$FILENAME AS path, $1 AS j '
           || 'FROM @<% db %>.<% schema_output %>.RESULTS/' || P_RUN_ID || '/' || corpus || '/ '
           || '(FILE_FORMAT => ''<% db %>.<% schema_output %>.JSON_DOC'', PATTERN => ''.*[.]json'')';
  EXECUTE IMMEDIATE :read_sql;
  CREATE OR REPLACE TEMPORARY TABLE S55_SRC AS
  SELECT :P_RUN_ID AS run_id, :corpus AS corpus, t.doc_id, r.j,
         '@<% db %>.<% schema_output %>.RESULTS/' || r.path AS output_uri
  FROM S55_TARGET t JOIN S55_RAW r
    ON r.path = :P_RUN_ID || '/' || :corpus || '/' || t.doc_id || '.json' AND r.j:doc_id::STRING = t.doc_id;
  SELECT COUNT(*) INTO :n_found FROM S55_SRC;

  DELETE FROM <% db %>.<% schema_output %>.DOCUMENTS WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.DOCUMENTS (run_id, corpus, doc_id, schema_version, title, numbering_scheme, n_pages, n_elements, n_errors, n_null_outputs, image_tag, output_uri, meta, provenance, extras)
  SELECT s.run_id, s.corpus, s.doc_id, s.j:schema_version::STRING, s.j:meta:title::STRING,
         s.j:numbering_scheme::STRING, ARRAY_SIZE(COALESCE(s.j:pages, [])), ARRAY_SIZE(COALESCE(s.j:elements, [])),
         s.j:provenance:n_errors::INT, s.j:provenance:n_null_outputs::INT, s.j:provenance:image_tag::STRING,
         s.output_uri, s.j:meta, s.j:provenance,
         OBJECT_CONSTRUCT_KEEP_NULL('enumerations', s.j:enumerations, 'footnotes', s.j:footnotes,
                                    'table_regions', s.j:table_regions, 'figure_regions', s.j:figure_regions)
  FROM S55_SRC s;
  DELETE FROM <% db %>.<% schema_output %>.PAGES WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.PAGES (run_id, corpus, doc_id, seq, page, page_class, text, text_with_furniture)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:number::INT,
         f.value:class::ARRAY,
         f.value:text::STRING,
         f.value:text_with_furniture::STRING
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:pages) f;
  DELETE FROM <% db %>.<% schema_output %>.OUTLINE WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.OUTLINE (run_id, corpus, doc_id, seq, item_id, depth, node_kind, label, title, parent_id, citation, page, flags)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:id::STRING,
         f.value:depth::INT,
         f.value:node_kind::STRING,
         f.value:label::STRING,
         f.value:title::STRING,
         f.value:parent_id::STRING,
         f.value:citation::STRING,
         f.value:page::INT,
         f.value:flags::ARRAY
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:outline) f;
  DELETE FROM <% db %>.<% schema_output %>.ELEMENTS WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.ELEMENTS (run_id, corpus, doc_id, seq, element_id, kind, node_kind, label, citation, parent_id, text, pages, refs_to)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:element_id::STRING,
         f.value:kind::STRING,
         f.value:node_kind::STRING,
         f.value:label::STRING,
         f.value:citation::STRING,
         f.value:parent_id::STRING,
         f.value:text::STRING,
         f.value:pages::ARRAY,
         f.value:refs_to::ARRAY
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:elements) f;
  DELETE FROM <% db %>.<% schema_output %>.TABLES WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.TABLES (run_id, corpus, doc_id, seq, item_id, pages, source, n_rows, n_cols, grid)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:id::STRING,
         f.value:pages::ARRAY,
         f.value:source::STRING,
         f.value:n_rows::INT,
         f.value:n_cols::INT,
         f.value:grid
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:tables) f;
  DELETE FROM <% db %>.<% schema_output %>.FIGURES WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.FIGURES (run_id, corpus, doc_id, seq, item_id, pages, bbox, source, nodes, edges, paths, crop, query_id)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:id::STRING,
         f.value:pages::ARRAY,
         f.value:bbox::ARRAY,
         f.value:source::STRING,
         f.value:nodes,
         f.value:edges,
         f.value:paths,
         f.value:crop::STRING,
         f.value:query_id::STRING
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:figures) f;
  DELETE FROM <% db %>.<% schema_output %>.REFS WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.REFS (run_id, corpus, doc_id, seq, from_citation, to_citation)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:from_citation::STRING,
         f.value:to_citation::STRING
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:refs) f;
  DELETE FROM <% db %>.<% schema_output %>.PARTIES WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.PARTIES (run_id, corpus, doc_id, seq, alias, name, role, declared_in, page)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:alias::STRING,
         f.value:name::STRING,
         f.value:role::STRING,
         f.value:declared_in::STRING,
         f.value:page::INT
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:parties) f;
  DELETE FROM <% db %>.<% schema_output %>.DEFINED_TERMS WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.DEFINED_TERMS (run_id, corpus, doc_id, seq, term, defined_in, source)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:term::STRING,
         f.value:defined_in::STRING,
         f.value:source::STRING
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:defined_terms_detail) f;
  DELETE FROM <% db %>.<% schema_output %>.TERM_USES WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.TERM_USES (run_id, corpus, doc_id, seq, term, in_citation)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:term::STRING,
         f.value:in_citation::STRING
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:term_uses) f;
  DELETE FROM <% db %>.<% schema_output %>.REPAIR_QUEUE WHERE run_id = :P_RUN_ID AND doc_id IN (SELECT doc_id FROM S55_SRC);
  INSERT INTO <% db %>.<% schema_output %>.REPAIR_QUEUE (run_id, corpus, doc_id, seq, kind, locus, evidence, resolution)
  SELECT s.run_id, s.corpus, s.doc_id, f.index,
         f.value:kind::STRING,
         f.value:locus::STRING,
         f.value:evidence::STRING,
         f.value:resolution::STRING
  FROM S55_SRC s, LATERAL FLATTEN(input => s.j:repair_queue) f;

  -- 台帳：JSON があって展開できた文書は SUCCEEDED（行数を detail に残す）、無い文書は FAILED
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t
  USING (
    SELECT g.doc_id, s.output_uri,
           IFF(s.doc_id IS NULL, NULL,
               OBJECT_CONSTRUCT('DOCUMENTS', 1,
                                   'PAGES', ARRAY_SIZE(COALESCE(s.j:pages, [])),
                                   'OUTLINE', ARRAY_SIZE(COALESCE(s.j:outline, [])),
                                   'ELEMENTS', ARRAY_SIZE(COALESCE(s.j:elements, [])),
                                   'TABLES', ARRAY_SIZE(COALESCE(s.j:tables, [])),
                                   'FIGURES', ARRAY_SIZE(COALESCE(s.j:figures, [])),
                                   'REFS', ARRAY_SIZE(COALESCE(s.j:refs, [])),
                                   'PARTIES', ARRAY_SIZE(COALESCE(s.j:parties, [])),
                                   'DEFINED_TERMS', ARRAY_SIZE(COALESCE(s.j:defined_terms_detail, [])),
                                   'TERM_USES', ARRAY_SIZE(COALESCE(s.j:term_uses, [])),
                                   'REPAIR_QUEUE', ARRAY_SIZE(COALESCE(s.j:repair_queue, [])))) AS counts
    FROM S55_TARGET g LEFT JOIN S55_SRC s ON s.doc_id = g.doc_id) x
  ON t.run_id = :P_RUN_ID AND t.step = 'S55' AND t.doc_id = x.doc_id
  WHEN MATCHED THEN UPDATE SET
    status = IFF(x.counts IS NOT NULL, 'SUCCEEDED', 'FAILED'), ended_at = CURRENT_TIMESTAMP(),
    n_errors = IFF(x.counts IS NOT NULL, 0, 1),
    error_text = IFF(x.counts IS NOT NULL, NULL, '出力 JSON がステージに無い'),
    output_uri = x.output_uri, detail = x.counts;

  SELECT COUNT(*) INTO :n_failed FROM <% db %>.<% schema_ops %>.STEP_RUNS
  WHERE run_id = :P_RUN_ID AND step = 'S55' AND status = 'FAILED';
  IF (n_failed > 0) THEN
    RAISE step_failed;
  END IF;
  RETURN OBJECT_CONSTRUCT('step', 'S55', 'n_target', n_target, 'n_registered', n_found);
EXCEPTION
  WHEN step_failed THEN
    RAISE;
  WHEN OTHER THEN
    UPDATE <% db %>.<% schema_ops %>.STEP_RUNS SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP(), n_errors = 1,
      error_text = :SQLERRM
    WHERE run_id = :P_RUN_ID AND step = 'S55' AND status = 'RUNNING';
    RAISE;
END;
$$;
