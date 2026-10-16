-- examples/queries.sql — ハンズオンの照会例（登録表を SQL で引く）
-- 実行ロール：<% role_predict %>。最初の SET で、流した run の run_id と文書を指定する（scripts/start.sh が表示する）。
-- <% … %> はオブジェクト名のテンプレート変数。実際の名前は `uv run jpdocread names` で表示できる（README「照会例」）。
-- 条項の引用パスは文書の字形のまま（`第３条 ４ （１）`）。半角で書いても引けるよう、照合キー CITATION_KEY で比べる。

USE ROLE <% role_predict %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% warehouse %>;

SET run_id = 'm5-contract-e2e';                  -- ← 自分の run_id に置き換える
SET doc_id = 'nda-0003--ct-a4-1col-form';        -- ← 照会する文書

-- 1. 条項の本文を引用パスで引く（「第３条第４項第１号」）
SELECT citation, title, text
FROM <% db %>.<% schema_output %>.V_PROVISIONS
WHERE run_id = $run_id AND doc_id = $doc_id
  AND citation_key = <% db %>.<% schema_output %>.CITATION_KEY('第3条 4 (1)');

-- 2. ある条を参照している条項の一覧（「第４条を参照しているのはどこか」）と、参照先の見出し
SELECT from_citation, to_citation, to_title
FROM <% db %>.<% schema_output %>.V_REFS_RESOLVED
WHERE run_id = $run_id AND doc_id = $doc_id
  AND <% db %>.<% schema_output %>.CITATION_KEY(to_citation) LIKE <% db %>.<% schema_output %>.CITATION_KEY('第4条') || '%'
ORDER BY from_citation;

-- 3. 当事者（「甲は誰か」）。契約書だけに値がある（約款では 0 行）
SELECT doc_id, alias, name, role
FROM <% db %>.<% schema_output %>.PARTIES
WHERE run_id = $run_id
ORDER BY doc_id, seq;

-- 4. 定義語の定義箇所と、その定義語が使われている条項の数（契約書）
SELECT d.doc_id, d.term, d.defined_in, COUNT(u.seq) AS n_uses
FROM <% db %>.<% schema_output %>.DEFINED_TERMS d
LEFT JOIN <% db %>.<% schema_output %>.TERM_USES u
  ON u.run_id = d.run_id AND u.doc_id = d.doc_id AND u.term = d.term
WHERE d.run_id = $run_id
GROUP BY d.doc_id, d.term, d.defined_in
ORDER BY d.doc_id, n_uses DESC;

-- 5. 参照の解決状況（参照先が文書内に見つかった割合）
SELECT doc_id, COUNT(*) AS n_refs, COUNT(to_citation_in_doc) AS n_resolved
FROM <% db %>.<% schema_output %>.V_REFS_RESOLVED
WHERE run_id = $run_id
GROUP BY doc_id
ORDER BY doc_id;
