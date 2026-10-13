-- views/output_views.sql — 登録表の照会用ビュー（ハンズオン）
-- 新規（移植元には無い）。オーナー：<% role_predict %>。照会例は sql/examples/queries.sql。
--
-- 登録表は出力 JSON の字形をそのまま持つ（`第３条 ４ （１）`）。一方、参照（REFS.to_citation）は
-- 半角で書かれることがある（`第3条 3`）。突き合わせはここで「照合キー」（全角の数字・括弧・空白を畳んだもの）を
-- 作って行う。照合キーは照会のためだけの値で、表には保存しない。

USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

-- 照合キー：全角数字・括弧・空白を半角に、続く空白を 1 個に畳む。空白は消さない
-- （消すと「第1条 1 2」（項＋号）と「第1条 12」（第12項）が同じキーになる）
CREATE OR REPLACE FUNCTION <% db %>.<% schema_output %>.CITATION_KEY(C STRING)
RETURNS STRING
AS $$ REGEXP_REPLACE(TRIM(TRANSLATE(C, '０１２３４５６７８９（）　', '0123456789() ')), ' +', ' ') $$;

-- 条項の一覧（章・条・項・号・別紙）。見出し（OUTLINE）に本文（ELEMENTS）を付ける
CREATE OR REPLACE VIEW <% db %>.<% schema_output %>.V_PROVISIONS AS
SELECT o.run_id, o.corpus, o.doc_id, d.title AS doc_title, o.seq, o.node_kind, o.label, o.citation,
       o.title, o.depth, o.page, e.text,
       <% db %>.<% schema_output %>.CITATION_KEY(o.citation) AS citation_key
FROM <% db %>.<% schema_output %>.OUTLINE o
JOIN <% db %>.<% schema_output %>.DOCUMENTS d ON d.run_id = o.run_id AND d.doc_id = o.doc_id
LEFT JOIN <% db %>.<% schema_output %>.ELEMENTS e
  ON e.run_id = o.run_id AND e.doc_id = o.doc_id AND e.element_id = o.item_id
WHERE o.citation <> '';

-- 参照（「第N条第M項」等）を参照先に解決する。参照先が無いものは to_title・to_text が NULL
CREATE OR REPLACE VIEW <% db %>.<% schema_output %>.V_REFS_RESOLVED AS
SELECT r.run_id, r.corpus, r.doc_id, r.from_citation, r.to_citation,
       p.citation AS to_citation_in_doc, p.title AS to_title, p.text AS to_text
FROM <% db %>.<% schema_output %>.REFS r
LEFT JOIN <% db %>.<% schema_output %>.V_PROVISIONS p
  ON p.run_id = r.run_id AND p.doc_id = r.doc_id
 AND p.citation_key = <% db %>.<% schema_output %>.CITATION_KEY(r.to_citation)
QUALIFY ROW_NUMBER() OVER (PARTITION BY r.run_id, r.doc_id, r.seq ORDER BY p.seq) = 1;

-- run の最新の登録（同じ文書を複数の run で読んだときに 1 件を選ぶ）
CREATE OR REPLACE VIEW <% db %>.<% schema_output %>.V_LATEST_DOCUMENTS AS
SELECT * FROM <% db %>.<% schema_output %>.DOCUMENTS
QUALIFY ROW_NUMBER() OVER (PARTITION BY corpus, doc_id ORDER BY registered_at DESC) = 1;
