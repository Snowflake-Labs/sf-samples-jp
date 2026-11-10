-- procedures/ai_call.sql — AI の呼び出しの共通プロシージャ。
-- 実行ロール：<% role_predict %>（owner's rights）。予測（ローカル または ジョブ）が <% schema_work %>.AI_REQUESTS に
-- 要求を書き、CALL <% schema_ops %>.AI_CALL(run_id, batch_id) で一括処理する。
--
-- 守ること：
--   - キャッシュ：<% schema_work %>.AI_CACHE に err IS NULL の行があるキーは呼ばない（同じ要求に二重に課金しない）
--   - 集合演算で呼ぶ（行ごとのループをしない）。モデル名は検査してから動的 SQL に埋め込む（インジェクション対策）
--   - prompt は PROMPT() のテンプレートではなく文字列で渡す（テンプレートの { の解釈を避ける）
--   - response_format を使わない。expect='json' はコードフェンスを除いてから TRY_PARSE_JSON で検査する
--   - NULL・空出力・解析失敗は err 付きの行として残す。解析失敗は 1 回だけ再試行する（上限 max_attempts）
--   - 空出力（推論のトークンで max_tokens を使い切った）は再試行しない（temperature 0 で同じ結果になる）
USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

CREATE OR REPLACE PROCEDURE <% db %>.<% schema_ops %>.AI_CALL(P_RUN_ID STRING, P_BATCH_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_req INT;
  n_called INT := 0;
  n_attempt INT := 0;
  max_attempts INT := 2;
  n_todo INT;
  m STRING;
  ins_sql STRING;
  bad_model EXCEPTION (-20101, 'AI_CALL: モデル名が不正');
  c1 CURSOR FOR SELECT DISTINCT model FROM AI_TODO;
BEGIN
  SELECT COUNT(*) INTO :n_req FROM <% db %>.<% schema_work %>.AI_REQUESTS WHERE run_id = :P_RUN_ID AND batch_id = :P_BATCH_ID;
  WHILE (n_attempt < max_attempts) DO
    n_attempt := n_attempt + 1;
    CREATE OR REPLACE TEMPORARY TABLE AI_TODO AS
    SELECT r.*
    FROM <% db %>.<% schema_work %>.AI_REQUESTS r
    WHERE r.run_id = :P_RUN_ID AND r.batch_id = :P_BATCH_ID
      AND NOT EXISTS (SELECT 1 FROM <% db %>.<% schema_work %>.AI_CACHE c WHERE c.cache_key = r.cache_key
                      AND (c.err IS NULL OR c.err = 'empty_output'))
      AND (SELECT COUNT(*) FROM <% db %>.<% schema_work %>.AI_CACHE c WHERE c.cache_key = r.cache_key AND c.run_id = :P_RUN_ID) < :max_attempts
    QUALIFY ROW_NUMBER() OVER (PARTITION BY r.cache_key ORDER BY r.created_at) = 1;
    SELECT COUNT(*) INTO :n_todo FROM AI_TODO;
    IF (n_todo = 0) THEN
      BREAK;
    END IF;
    FOR rec IN c1 DO
      m := rec.model;
      IF (NOT REGEXP_LIKE(m, '^[a-z0-9][a-z0-9._-]{1,63}$')) THEN
        RAISE bad_model;
      END IF;
      ins_sql := 'INSERT INTO <% db %>.<% schema_work %>.AI_CACHE '
        || '(cache_key, stage, doc_id, unit, model, max_tokens, prompt_version, raw_out, n_chars, err, query_id, run_id, called_at) '
        || 'WITH called AS (SELECT t.*, AI_COMPLETE(model => ''' || m || ''', prompt => t.prompt, '
        || 'model_parameters => OBJECT_CONSTRUCT(''temperature'', 0, ''max_tokens'', t.max_tokens)) AS raw_out '
        || 'FROM AI_TODO t WHERE t.model = ?) '
        || 'SELECT cache_key, stage, doc_id, unit, model, max_tokens, prompt_version, raw_out, LENGTH(raw_out), '
        || 'CASE WHEN raw_out IS NULL THEN ''null_output'' WHEN LENGTH(TRIM(raw_out)) = 0 THEN ''empty_output'' '
        || 'WHEN expect = ''json'' AND TRY_PARSE_JSON(REGEXP_REPLACE(TRIM(raw_out), ''^```[a-zA-Z]*\\s*|\\s*```$'', '''')) IS NULL '
        || 'THEN ''parse_error'' END, LAST_QUERY_ID(), ?, CURRENT_TIMESTAMP() FROM called';
      EXECUTE IMMEDIATE :ins_sql USING (m, P_RUN_ID);
      n_called := n_called + SQLROWCOUNT;
    END FOR;
  END WHILE;
  RETURN (SELECT OBJECT_CONSTRUCT('n_requests', :n_req, 'n_called', :n_called, 'attempts', :n_attempt,
          'n_ok', COUNT_IF(c.cache_key IS NOT NULL AND c.err IS NULL), 'n_missing', COUNT_IF(c.cache_key IS NULL), 'n_null_output', COUNT_IF(c.err = 'null_output'),
          'n_parse_error', COUNT_IF(c.err = 'parse_error'), 'n_empty_output', COUNT_IF(c.err = 'empty_output'))
          FROM (SELECT DISTINCT cache_key FROM <% db %>.<% schema_work %>.AI_REQUESTS WHERE run_id = :P_RUN_ID AND batch_id = :P_BATCH_ID) r
          LEFT JOIN (SELECT cache_key, err FROM <% db %>.<% schema_work %>.AI_CACHE
                     QUALIFY ROW_NUMBER() OVER (PARTITION BY cache_key ORDER BY IFF(err IS NULL, 0, 1), called_at DESC) = 1) c
          ON c.cache_key = r.cache_key);
END;
$$;
