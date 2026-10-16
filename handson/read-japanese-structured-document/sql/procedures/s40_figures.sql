-- procedures/s40_figures.sql — S40：図領域ごとに AI_COMPLETE（few-shot 2 例）でノード・辺を抽出
-- 実行ロール：<% role_predict %>（owner's rights）。
--
-- 入力：OPS.REGIONS（S30 が書く。kind = 'figure'）、OPS.FIGURE_PROMPT（setup が jpdocread deploy prompt で書く：コーパスごとの規則本文と shot）
-- キャッシュ：PARSED.FIGURE_RAW。キー = (クロップ画像の md5, prompt_key)。
--   prompt_key = SHA2(model | prompt_version | max_tokens | shot 画像 2 枚の md5 | shot JSON 2 件)
-- 守ること：
--   - プロンプト本文に素の { を書かない（F7）。本文は setup.sh が検査してから FIGURE_PROMPT に入れる
--   - response_format を使わない（F5）。解析はフェンスを除いてから TRY_PARSE_JSON（F19）
--   - max_tokens = max(4096, ノード候補数 × 2 × 180)。ノード候補は S30 が自前の幾何から数える
--   - 解析できない出力は 1 回だけ再試行する（画像入力は temperature 0 でも非決定：F6b）
--   - NULL と解析失敗は err 付きの行として残し、数える

USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.S40_FIGURES(P_RUN_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_regions INT;
  n_called INT := 0;
  n_retry INT := 0;
  n_null INT;
  n_parse_err INT;
  n_failed_docs INT;
  n_attempt INT := 0;
  max_attempts INT;
  model STRING;
  rules_lit STRING;
  ins_sql STRING;
  n_shot_md5 INT;
  no_shots EXCEPTION (-20041, 'S40: shot のクロップが無い（供出元の S30 が未完了）');
  bad_model EXCEPTION (-20042, 'S40: FIGURE_PROMPT のモデル名が不正');
  step_failed EXCEPTION (-20040, 'S40: 失敗した文書がある（STEP_RUNS を参照）');
BEGIN
  SELECT COALESCE(MAX(retry_parse_error), 1) + 1 INTO :max_attempts FROM <% db %>.<% schema_ops %>.FIGURE_PROMPT
  WHERE corpus = (SELECT corpus FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID);

  -- 供出元 PDF のクロップを shot の画像として使う。shot 画像の md5 を REGIONS から引く
  CREATE OR REPLACE TEMPORARY TABLE S40_PROMPT AS
  SELECT p.*, 'runs/' || :P_RUN_ID || '/crops/' || p.shot_a_path AS shot_a_stage,
         'runs/' || :P_RUN_ID || '/crops/' || p.shot_b_path AS shot_b_stage,
         (SELECT MAX(image_md5) FROM <% db %>.<% schema_ops %>.REGIONS WHERE run_id = :P_RUN_ID AND rel_path = p.shot_a_path) AS shot_a_md5,
         (SELECT MAX(image_md5) FROM <% db %>.<% schema_ops %>.REGIONS WHERE run_id = :P_RUN_ID AND rel_path = p.shot_b_path) AS shot_b_md5
  FROM <% db %>.<% schema_ops %>.FIGURE_PROMPT p
  -- 図 few-shot はコーパスごとに違う（供出元が違う）。run のコーパスの行だけを使う
  WHERE p.corpus = (SELECT corpus FROM <% db %>.<% schema_ops %>.RUNS WHERE run_id = :P_RUN_ID)
  QUALIFY ROW_NUMBER() OVER (ORDER BY loaded_at DESC) = 1;
  SELECT COUNT_IF(shot_a_md5 IS NOT NULL AND shot_b_md5 IS NOT NULL), MAX(model),
         -- PROMPT() のテンプレートは定数でなければならない（列を渡せない）ので、文字列リテラルとして
         -- 動的 SQL に埋め込む。単引用符と逆スラッシュをエスケープする
         '''' || REPLACE(REPLACE(MAX(rules), '\\', '\\\\'), '''', '''''') || ''''
  INTO :n_shot_md5, :model, :rules_lit
  FROM S40_PROMPT;
  IF (n_shot_md5 <> 1) THEN
    RAISE no_shots;
  END IF;
  -- AI_COMPLETE の model 引数と PROMPT() のテンプレートは文字列リテラルでなければならない（列を渡せない）ので、
  -- 動的 SQL に埋め込む。埋め込む前に値の形を検査する（SQL インジェクション対策）
  IF (NOT REGEXP_LIKE(model, '^[a-z0-9][a-z0-9._-]{1,63}$')) THEN
    RAISE bad_model;
  END IF;

  -- 対象文書：この run で S30 が成功し、S40 が未完了のもの
  CREATE OR REPLACE TEMPORARY TABLE S40_DOCS AS
  SELECT d.value::STRING AS doc_id
  FROM <% db %>.<% schema_ops %>.RUNS r, LATERAL FLATTEN(input => r.docs) d
  WHERE r.run_id = :P_RUN_ID
    AND EXISTS (SELECT 1 FROM <% db %>.<% schema_ops %>.STEP_RUNS s WHERE s.run_id = :P_RUN_ID AND s.step = 'S30'
                AND s.doc_id = d.value::STRING AND s.status = 'SUCCEEDED')
    AND NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_ops %>.STEP_RUNS s WHERE s.run_id = :P_RUN_ID AND s.step = 'S40'
                    AND s.doc_id = d.value::STRING AND s.status = 'SUCCEEDED');

  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t USING S40_DOCS s
  ON t.run_id = :P_RUN_ID AND t.step = 'S40' AND t.doc_id = s.doc_id
  WHEN MATCHED THEN UPDATE SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP(), ended_at = NULL,
    attempt = t.attempt + 1, error_text = NULL
  WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, attempt)
    VALUES (:P_RUN_ID, 'S40', s.doc_id, 'RUNNING', CURRENT_TIMESTAMP(), 1);

  -- 図領域ごとの max_tokens と prompt_key を確定して REGIONS に書く（S50 が同じキーで引く）
  UPDATE <% db %>.<% schema_ops %>.REGIONS g
  SET max_tokens = GREATEST(p.min_max_tokens, g.n_node_candidates * 2 * p.tokens_per_elem),
      prompt_key = SHA2(p.model || '|' || p.prompt_version || '|'
                        || GREATEST(p.min_max_tokens, g.n_node_candidates * 2 * p.tokens_per_elem) || '|'
                        || p.shot_a_md5 || '|' || p.shot_b_md5 || '|' || SHA2(p.shot_a_json) || '|' || SHA2(p.shot_b_json)
                        || '|' || SHA2(p.rules))
  FROM S40_PROMPT p
  WHERE g.run_id = :P_RUN_ID AND g.kind = 'figure' AND g.doc_id IN (SELECT doc_id FROM S40_DOCS);

  SELECT COUNT(*) INTO :n_regions FROM <% db %>.<% schema_ops %>.REGIONS
  WHERE run_id = :P_RUN_ID AND kind = 'figure' AND doc_id IN (SELECT doc_id FROM S40_DOCS);

  -- 呼び出し：キャッシュに「解析できた出力」が無く、試行回数が上限未満の領域だけ
  WHILE (n_attempt < max_attempts) DO
    n_attempt := n_attempt + 1;
    CREATE OR REPLACE TEMPORARY TABLE S40_TODO AS
    SELECT g.run_id, g.corpus, g.doc_id, g.rel_path, g.stage_path, g.image_md5, g.prompt_key, g.max_tokens
    FROM <% db %>.<% schema_ops %>.REGIONS g
    WHERE g.run_id = :P_RUN_ID AND g.kind = 'figure' AND g.doc_id IN (SELECT doc_id FROM S40_DOCS)
      AND g.prompt_key IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_parsed %>.FIGURE_RAW c
                      WHERE c.image_md5 = g.image_md5 AND c.prompt_key = g.prompt_key AND c.err IS NULL)
      AND (SELECT COUNT(*) FROM <% db %>.<% schema_parsed %>.FIGURE_RAW c
           WHERE c.image_md5 = g.image_md5 AND c.prompt_key = g.prompt_key AND c.run_id = :P_RUN_ID) < :max_attempts
    QUALIFY ROW_NUMBER() OVER (PARTITION BY g.image_md5, g.prompt_key ORDER BY g.rel_path) = 1;
    IF ((SELECT COUNT(*) FROM S40_TODO) = 0) THEN
      BREAK;
    END IF;
    IF (n_attempt > 1) THEN
      n_retry := n_retry + (SELECT COUNT(*) FROM S40_TODO);
    END IF;

    -- 動的 SQL は単引用符の文字列で組む（プロシージャ本体がドル引用符で囲まれているため）。埋め込むのは検査済みの
    -- モデル名だけで、run_id と試行回数はバインド変数（?）で渡す
    ins_sql := 'INSERT INTO <% db %>.<% schema_parsed %>.FIGURE_RAW '
      || '(image_md5, prompt_key, rel_path, stage_path, corpus, doc_id, model, prompt_version, max_tokens, raw_out, '
      || ' n_chars, err, attempt, query_id, run_id) '
      || 'WITH called AS (SELECT t.*, p.model, p.prompt_version, AI_COMPLETE(model => ''' || model || ''', '
      || 'prompt => PROMPT(' || rules_lit || ', TO_FILE(''@<% db %>.<% schema_raw %>.WORK'', p.shot_a_stage), p.shot_a_json, '
      || 'TO_FILE(''@<% db %>.<% schema_raw %>.WORK'', p.shot_b_stage), p.shot_b_json, '
      || 'TO_FILE(''@<% db %>.<% schema_raw %>.WORK'', t.stage_path)), '
      || 'model_parameters => OBJECT_CONSTRUCT(''temperature'', 0, ''max_tokens'', t.max_tokens)) AS raw_out '
      || 'FROM S40_TODO t CROSS JOIN S40_PROMPT p) '
      || 'SELECT image_md5, prompt_key, rel_path, stage_path, corpus, doc_id, model, prompt_version, max_tokens, raw_out, '
      || 'LENGTH(raw_out), CASE WHEN raw_out IS NULL THEN ''null_output'' '
      || 'WHEN TRY_PARSE_JSON(REGEXP_REPLACE(TRIM(raw_out), ''^```(json)?[[:space:]]*|[[:space:]]*```$'', '''')) IS NULL '
      || 'THEN ''parse_error'' END, ?, LAST_QUERY_ID(), ? FROM called';
    EXECUTE IMMEDIATE :ins_sql USING (n_attempt, P_RUN_ID);
    n_called := n_called + SQLROWCOUNT;
  END WHILE;

  SELECT COUNT_IF(err = 'null_output'), COUNT_IF(err = 'parse_error') INTO :n_null, :n_parse_err
  FROM <% db %>.<% schema_parsed %>.FIGURE_RAW WHERE run_id = :P_RUN_ID;

  -- 台帳：全図領域に「解析できた出力」か「上限まで試した失敗」があれば SUCCEEDED（失敗件数は n_errors に残す）。
  -- 失敗した図は S50 で `edges: null`・err 付きで出力し、評価でも数える（図だけの失敗で文書全体を止めない）。
  MERGE INTO <% db %>.<% schema_ops %>.STEP_RUNS t
  USING (
    SELECT d.doc_id,
           COUNT(g.rel_path) AS n_fig,
           COUNT_IF(ok.image_md5 IS NULL) AS n_fig_err,
           COUNT_IF(ok.image_md5 IS NULL AND COALESCE(tried.n, 0) < :max_attempts) AS n_untried
    FROM S40_DOCS d
    LEFT JOIN <% db %>.<% schema_ops %>.REGIONS g ON g.run_id = :P_RUN_ID AND g.doc_id = d.doc_id AND g.kind = 'figure'
    LEFT JOIN (SELECT DISTINCT image_md5, prompt_key FROM <% db %>.<% schema_parsed %>.FIGURE_RAW WHERE err IS NULL) ok
      ON ok.image_md5 = g.image_md5 AND ok.prompt_key = g.prompt_key
    LEFT JOIN (SELECT image_md5, prompt_key, COUNT(*) AS n FROM <% db %>.<% schema_parsed %>.FIGURE_RAW
               WHERE run_id = :P_RUN_ID GROUP BY 1, 2) tried
      ON tried.image_md5 = g.image_md5 AND tried.prompt_key = g.prompt_key
    GROUP BY d.doc_id) s
  ON t.run_id = :P_RUN_ID AND t.step = 'S40' AND t.doc_id = s.doc_id
  WHEN MATCHED THEN UPDATE SET
    status = IFF(s.n_untried = 0, 'SUCCEEDED', 'FAILED'), ended_at = CURRENT_TIMESTAMP(),
    n_errors = s.n_fig_err,
    error_text = IFF(s.n_untried = 0, NULL, s.n_untried || ' 図が未処理'),
    output_uri = '<% db %>.<% schema_parsed %>.FIGURE_RAW',
    detail = OBJECT_CONSTRUCT('n_figure_regions', s.n_fig, 'n_figure_errors', s.n_fig_err);

  SELECT COUNT(*) INTO :n_failed_docs FROM <% db %>.<% schema_ops %>.STEP_RUNS
  WHERE run_id = :P_RUN_ID AND step = 'S40' AND status = 'FAILED';
  IF (n_failed_docs > 0) THEN
    RAISE step_failed;
  END IF;
  RETURN OBJECT_CONSTRUCT('step', 'S40', 'n_regions', n_regions, 'n_called', n_called, 'n_retry', n_retry,
                          'n_null_output', n_null, 'n_parse_error', n_parse_err, 'attempts', n_attempt);
EXCEPTION
  WHEN step_failed THEN
    RAISE;
  WHEN OTHER THEN
    UPDATE <% db %>.<% schema_ops %>.STEP_RUNS SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP(), n_errors = 1,
      error_text = :SQLERRM
    WHERE run_id = :P_RUN_ID AND step = 'S40' AND status = 'RUNNING';
    RAISE;
END;
$$;
