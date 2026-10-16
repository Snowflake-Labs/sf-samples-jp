-- views/eval_views.sql — 評価結果の集計ビュー
-- オーナー：<% role_eval %>。値はすべて S60 が EVAL_RUNS / DOC_METRICS / PAGE_METRICS / ELEMENT_ERRORS に書いたもの。

USE ROLE <% role_eval %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

-- run ごとの主要指標（start.sh が表示する）
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_RUN_SUMMARY AS
SELECT
  e.pred_run_id,
  e.eval_run_id,
  e.corpus,
  e.image_tag,
  e.payload:summary:n_docs::INT                                   AS n_docs,
  e.payload:summary:n_missing_predictions::INT                    AS n_missing_predictions,
  e.payload:summary:coverage::FLOAT                               AS coverage,
  e.payload:summary:excluded_shot_donors                          AS excluded_shot_donors,
  e.payload:summary:citation:citation_error_rate::FLOAT           AS citation_error_rate,
  e.payload:summary:citation:n_wrong::INT                         AS citation_n_wrong,
  e.payload:summary:citation:n_elements::INT                      AS citation_n_elements,
  e.payload:summary:citation:coverage::FLOAT                      AS citation_coverage,
  e.payload:summary:parties:f1::FLOAT                             AS parties_f1,
  e.payload:summary:parties:n_alias_swapped::INT                  AS parties_n_alias_swapped,
  e.payload:summary:terms:recall::FLOAT                           AS terms_recall,
  e.payload:summary:terms:precision::FLOAT                        AS terms_precision,
  e.payload:summary:terms:f1::FLOAT                               AS terms_f1,
  e.payload:summary:text:cer::FLOAT                               AS text_cer,
  e.payload:summary:text:cer_normalized::FLOAT                    AS text_cer_normalized,
  e.payload:summary:text:char_f1::FLOAT                           AS text_char_f1,
  e.payload:summary:text:cer_worst_decile::FLOAT                  AS text_cer_worst_decile,
  e.payload:summary:text:n_missing_pages::INT                     AS text_n_missing_pages,
  e.payload:summary:structure:article:recall::FLOAT               AS article_recall,
  e.payload:summary:structure:article:precision::FLOAT            AS article_precision,
  e.payload:summary:structure:paragraph:recall::FLOAT             AS paragraph_recall,
  e.payload:summary:structure:paragraph:precision::FLOAT          AS paragraph_precision,
  e.payload:summary:structure:item:recall::FLOAT                  AS item_recall,
  e.payload:summary:structure:item:precision::FLOAT               AS item_precision,
  e.payload:summary:structure:nted_mean::FLOAT                    AS nted_mean,
  e.payload:summary:structure:nted_doc_mean::FLOAT                AS nted_doc_mean,
  e.payload:summary:structure:nted_doc_zero_docs::INT             AS nted_doc_zero_docs,
  e.payload:summary:structure:number_violations_intrinsic::INT    AS number_violations_intrinsic,
  e.payload:summary:structure:number_violations_gold_origin::INT  AS number_violations_gold_origin,
  e.payload:summary:tables:cell_f1::FLOAT                         AS table_cell_f1,
  e.payload:summary:tables:header_path_acc::FLOAT                 AS table_header_path_acc,
  e.payload:summary:tables:n_gold_tables::INT                     AS n_gold_tables,
  e.payload:summary:figures:node_f1::FLOAT                        AS figure_node_f1,
  e.payload:summary:figures:edge_f1::FLOAT                        AS figure_edge_f1,
  e.payload:summary:figures:containment70:edge_f1::FLOAT          AS figure_edge_f1_c70,
  e.payload:summary:figures:containment70:n::INT                  AS n_figures_c70,
  e.payload:summary:figures:n_gold_figures::INT                   AS n_gold_figures,
  e.payload:summary:refs:recall_reachable::FLOAT                  AS refs_recall_reachable,
  e.payload:summary:refs:precision::FLOAT                         AS refs_precision,
  e.payload:summary:refs:f1_reachable::FLOAT                      AS refs_f1_reachable,
  e.payload:summary:refs:recall_all::FLOAT                        AS refs_recall_all,
  e.payload:summary:refs:gold_unreachable::INT                    AS refs_gold_unreachable,
  e.payload:summary:style_pairs:style_divergence_mean::FLOAT      AS style_divergence_mean,
  e.payload:summary:style_pairs:n_pairs::INT                      AS n_style_pairs,
  e.created_at
FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS e;

-- 部分集合別（コーパス設定の slices。例：pilot）
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_RUN_SUBSET AS
WITH s AS (
  SELECT e.pred_run_id, e.eval_run_id, e.corpus, f.key AS subset, f.value AS v
  FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS e,
       LATERAL FLATTEN(input => e.payload:summary:subsets) f
)
SELECT
  pred_run_id, eval_run_id, corpus, subset,
  v:n_docs::INT                                   AS n_docs,
  v:n_missing_predictions::INT                    AS n_missing_predictions,
  v:citation:citation_error_rate::FLOAT           AS citation_error_rate,
  v:citation:n_wrong::INT                         AS citation_n_wrong,
  v:citation:n_elements::INT                      AS citation_n_elements,
  v:citation:coverage::FLOAT                      AS citation_coverage,
  v:parties:f1::FLOAT                             AS parties_f1,
  v:terms:f1::FLOAT                               AS terms_f1,
  v:text:cer::FLOAT                               AS text_cer,
  v:text:cer_worst_decile::FLOAT                  AS text_cer_worst_decile,
  v:text:n_pages::INT                             AS text_n_pages,
  v:structure:article:recall::FLOAT               AS article_recall,
  v:structure:article:precision::FLOAT            AS article_precision,
  v:structure:paragraph:recall::FLOAT             AS paragraph_recall,
  v:structure:paragraph:precision::FLOAT          AS paragraph_precision,
  v:structure:item:recall::FLOAT                  AS item_recall,
  v:structure:item:precision::FLOAT               AS item_precision,
  v:structure:nted_mean::FLOAT                    AS nted_mean,
  v:structure:nted_doc_mean::FLOAT                AS nted_doc_mean,
  v:structure:number_violations_intrinsic::INT    AS number_violations_intrinsic,
  v:tables:cell_f1::FLOAT                         AS table_cell_f1,
  v:tables:header_path_acc::FLOAT                 AS table_header_path_acc,
  v:tables:n_gold_tables::INT                     AS n_gold_tables,
  v:figures:edge_f1::FLOAT                        AS figure_edge_f1,
  v:figures:containment70:edge_f1::FLOAT          AS figure_edge_f1_c70,
  v:figures:n_gold_figures::INT                   AS n_gold_figures,
  v:refs:recall_reachable::FLOAT                  AS refs_recall_reachable,
  v:refs:precision::FLOAT                         AS refs_precision,
  v:refs:f1_reachable::FLOAT                      AS refs_f1_reachable,
  v:refs:recall_all::FLOAT                        AS refs_recall_all,
  v:style_pairs:n_pairs::INT                      AS n_style_pairs
FROM s;

-- 文書別
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_DOC AS
SELECT pred_run_id, corpus, doc_id, style_id, genre,
       payload:metrics:citation:citation_error_rate::FLOAT       AS citation_error_rate,
       payload:metrics:citation:n_wrong::INT                     AS citation_n_wrong,
       payload:metrics:citation:n_elements::INT                  AS citation_n_elements,
       payload:metrics:text:cer::FLOAT                           AS cer,
       payload:metrics:text:cer_worst_decile::FLOAT              AS cer_worst_decile,
       payload:metrics:structure:article:recall::FLOAT          AS article_recall,
       payload:metrics:structure:paragraph:recall::FLOAT        AS paragraph_recall,
       payload:metrics:structure:nted:nted::FLOAT               AS nted,
       payload:metrics:structure:nted_doc:nted_doc::FLOAT       AS nted_doc,
       payload:metrics:structure:number_violations_intrinsic::INT AS number_violations_intrinsic,
       payload:metrics:refs:tp::INT                              AS refs_tp,
       payload:metrics:refs:pred::INT                            AS refs_pred,
       payload:metrics:refs:gold_reachable::INT                  AS refs_gold_reachable,
       payload:metrics:refs:gold_unreachable::INT                AS refs_gold_unreachable
FROM <% eval_db %>.<% schema_results %>.DOC_METRICS;

-- スタイル別（異スタイル間のばらつき）
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_STYLE AS
SELECT pred_run_id, corpus, style_id, COUNT(*) AS n_docs,
       SUM(citation_n_wrong) / NULLIF(SUM(citation_n_elements), 0) AS citation_error_rate,
       AVG(cer) AS cer_doc_mean, MAX(cer_worst_decile) AS cer_worst_decile_max
FROM <% eval_db %>.<% schema_results %>.V_DOC GROUP BY pred_run_id, corpus, style_id;

-- 同一 content 異スタイル対
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_STYLE_PAIRS AS
SELECT e.pred_run_id, e.corpus, p.value:content_id::STRING AS content_id, p.value:styles AS styles,
       p.value:style_divergence::FLOAT AS style_divergence, p.value:citation_error_rate AS citation_error_rate
FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS e, LATERAL FLATTEN(input => e.payload:summary:style_pairs:pairs) p;

-- ページ別（最悪ページの確認）
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_PAGE AS
SELECT pred_run_id, corpus, doc_id, page, payload:cer::FLOAT AS cer, payload:cer_normalized::FLOAT AS cer_normalized,
       payload:char_f1::FLOAT AS char_f1, payload:missing::BOOLEAN AS missing
FROM <% eval_db %>.<% schema_results %>.PAGE_METRICS;

-- 表・図（1 行 1 表／1 図）
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_TABLE AS
SELECT d.pred_run_id, d.corpus, d.doc_id, t.value:table_id::STRING AS table_id, t.value:matched::BOOLEAN AS matched,
       t.value:cell_f1::FLOAT AS cell_f1, t.value:header_path_acc::FLOAT AS header_path_acc
FROM <% eval_db %>.<% schema_results %>.DOC_METRICS d, LATERAL FLATTEN(input => d.payload:tables) t;
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_FIGURE AS
SELECT d.pred_run_id, d.corpus, d.doc_id, f.value:figure_id::STRING AS figure_id, f.value:matched::BOOLEAN AS matched,
       f.value:has_graph::BOOLEAN AS has_graph, f.value:containment::FLOAT AS containment,
       f.value:node_f1::FLOAT AS node_f1, f.value:edge_f1::FLOAT AS edge_f1, f.value:path_f1::FLOAT AS path_f1,
       f.value:n_crossings_gold::INT AS n_crossings_gold
FROM <% eval_db %>.<% schema_results %>.DOC_METRICS d, LATERAL FLATTEN(input => d.payload:figures) f;

-- doctype 別・番号方式別の引用誤り率と網羅率（契約書）
CREATE OR REPLACE VIEW <% eval_db %>.<% schema_results %>.V_RUN_BY_GROUP AS
WITH g AS (
  SELECT e.pred_run_id, e.eval_run_id, e.corpus, 'doctype' AS axis, f.key AS grp, f.value AS v
  FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS e, LATERAL FLATTEN(input => e.payload:summary:by_doctype) f
  UNION ALL
  SELECT e.pred_run_id, e.eval_run_id, e.corpus, 'scheme' AS axis, f.key AS grp, f.value AS v
  FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS e, LATERAL FLATTEN(input => e.payload:summary:by_scheme) f
)
SELECT pred_run_id, eval_run_id, corpus, axis, grp,
       v:n_docs::INT AS n_docs, v:n_elements::INT AS n_elements, v:n_wrong::INT AS n_wrong,
       v:citation_error_rate::FLOAT AS citation_error_rate, v:coverage::FLOAT AS citation_coverage,
       v:nted_mean::FLOAT AS nted_mean, v:nted_doc_mean::FLOAT AS nted_doc_mean
FROM g;
