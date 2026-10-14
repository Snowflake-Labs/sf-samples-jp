"""出力 JSON 1 件を、登録表（`<DB>.<OUTPUT>.*`）の行に変換する。

S55（`sql/procedures/s55_register.sql`）はステージの JSON を `FLATTEN` して同じ行を作る。ここはその**仕様**であり、
単体テストで規則を確かめ、結合テスト（`-m integration`）で SQL の結果と突き合わせる。

- 全表の先頭列は `(run_id, corpus, doc_id)`。配列を展開する表は、配列内の位置 `seq`（0 始まり）を持つ。
- 字形は変えない（`第一条`・`（１）`・`甲` をそのまま入れる）。
- 値の型は出力 JSON のまま。配列は ARRAY、入れ子のオブジェクトは VARIANT として扱う（ここでは Python の list / dict）。
"""

from __future__ import annotations

from typing import Any

# 表名 → (出力 JSON のキー, 取り出す列)。列は JSON のフィールド名と同じ（別名を付けたものだけ下の _RENAME）
ARRAY_TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "PAGES": ("pages", ("number", "class", "text", "text_with_furniture")),
    "OUTLINE": (
        "outline",
        ("id", "depth", "node_kind", "label", "title", "parent_id", "citation", "page", "flags"),
    ),
    "ELEMENTS": (
        "elements",
        (
            "element_id",
            "kind",
            "node_kind",
            "label",
            "citation",
            "parent_id",
            "text",
            "pages",
            "refs_to",
        ),
    ),
    # fragments・stitch はページ・段をまたぐ表をつないだときだけある（read/stitch.py）。無ければ NULL
    "TABLES": (
        "tables",
        ("id", "pages", "source", "n_rows", "n_cols", "grid", "fragments", "stitch"),
    ),
    "FIGURES": (
        "figures",
        ("id", "pages", "bbox", "source", "nodes", "edges", "paths", "crop", "query_id"),
    ),
    "REFS": ("refs", ("from_citation", "to_citation")),
    "PARTIES": ("parties", ("alias", "name", "role", "declared_in", "page")),
    "DEFINED_TERMS": ("defined_terms_detail", ("term", "defined_in", "source")),
    "TERM_USES": ("term_uses", ("term", "in_citation")),
    "REPAIR_QUEUE": ("repair_queue", ("kind", "locus", "evidence", "resolution")),
}
# SQL の予約語・紛らわしい名前を避けるための列名（JSON のキー → 列名）
_RENAME = {"class": "page_class", "id": "item_id", "number": "page"}

# DOCUMENTS に VARIANT のまま入れる、展開しないキー
EXTRA_KEYS = ("enumerations", "footnotes", "table_regions", "figure_regions")

TABLES = ("DOCUMENTS", *ARRAY_TABLES)


def column_name(field: str) -> str:
    return _RENAME.get(field, field)


def columns(table: str) -> tuple[str, ...]:
    """表の列（キー列を含む）。SQL の列順と同じ。"""
    if table == "DOCUMENTS":
        return (
            "run_id", "corpus", "doc_id", "schema_version", "title", "numbering_scheme",
            "n_pages", "n_elements", "n_errors", "n_null_outputs", "image_tag", "output_uri",
            "meta", "provenance", "extras",
        )  # fmt: skip
    _, fields = ARRAY_TABLES[table]
    return ("run_id", "corpus", "doc_id", "seq", *(column_name(f) for f in fields))


def document_row(out: dict, *, run_id: str, corpus: str, output_uri: str) -> dict[str, Any]:
    prov = out.get("provenance") or {}
    meta = out.get("meta") or {}
    return {
        "run_id": run_id,
        "corpus": corpus,
        "doc_id": out["doc_id"],
        "schema_version": out["schema_version"],
        "title": meta.get("title"),
        "numbering_scheme": out.get("numbering_scheme"),
        "n_pages": len(out.get("pages") or []),
        "n_elements": len(out.get("elements") or []),
        "n_errors": prov.get("n_errors"),
        "n_null_outputs": prov.get("n_null_outputs"),
        "image_tag": prov.get("image_tag"),
        "output_uri": output_uri,
        "meta": meta,
        "provenance": prov,
        "extras": {k: out.get(k) for k in EXTRA_KEYS},
    }


def array_rows(out: dict, table: str, *, run_id: str, corpus: str) -> list[dict[str, Any]]:
    key, fields = ARRAY_TABLES[table]
    rows = []
    for seq, item in enumerate(out.get(key) or []):
        row = {"run_id": run_id, "corpus": corpus, "doc_id": out["doc_id"], "seq": seq}
        row.update({column_name(f): item.get(f) for f in fields})
        rows.append(row)
    return rows


def to_rows(
    out: dict, *, run_id: str, corpus: str, output_uri: str
) -> dict[str, list[dict[str, Any]]]:
    """出力 JSON 1 件 → {表名: 行の配列}。"""
    rows = {"DOCUMENTS": [document_row(out, run_id=run_id, corpus=corpus, output_uri=output_uri)]}
    for table in ARRAY_TABLES:
        rows[table] = array_rows(out, table, run_id=run_id, corpus=corpus)
    return rows


def row_counts(out: dict) -> dict[str, int]:
    """表ごとの行数（S55 の結果との照合に使う）。"""
    counts = {"DOCUMENTS": 1}
    counts.update({t: len(out.get(k) or []) for t, (k, _) in ARRAY_TABLES.items()})
    return counts
