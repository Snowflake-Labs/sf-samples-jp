"""出力 JSON → 登録表の行（load/rows.py）の規則。SQL（S55）との一致は tests/integration/test_s55_register.py。"""

from __future__ import annotations

import re

import pytest

from jpdocread.common.paths import HOME
from jpdocread.load import rows as spec

OUT = {
    "schema_version": "1.2",
    "doc_id": "d1",
    "meta": {"title": "業務委託契約書"},
    "numbering_scheme": "contract-standard",
    "pages": [{"number": 1, "class": ["body"], "text": "第一条", "text_with_furniture": "第一条"}],
    "outline": [],
    "elements": [
        {"element_id": "e1", "kind": "article", "node_kind": "article", "label": "第一条", "citation": "第一条",
         "parent_id": "root", "text": "甲は乙に（１）を委託する。", "pages": [1], "refs_to": ["第二条"]},
        {"element_id": "e2", "kind": "paragraph", "node_kind": "paragraph", "label": "２", "citation": "第一条 ２",
         "parent_id": "e1", "text": "前項", "pages": [1], "refs_to": []},
    ],
    "tables": [],
    "figures": [],
    "refs": [{"from_citation": "第一条", "to_citation": "第二条"}],
    "parties": [{"alias": "甲", "name": "株式会社ア", "role": "委託者", "declared_in": None, "page": 1}],
    "defined_terms_detail": [],
    "term_uses": [],
    "repair_queue": [],
    "enumerations": [],
    "footnotes": [],
    "table_regions": [],
    "figure_regions": [],
    "provenance": {"n_errors": 0, "n_null_outputs": 0, "image_tag": "t1", "run_id": "r1"},
}  # fmt: skip


def _rows():
    return spec.to_rows(OUT, run_id="r1", corpus="contract", output_uri="@x/r1/contract/d1.json")


def test_every_table_has_key_columns_and_one_document_row():
    rows = _rows()
    assert set(rows) == set(spec.TABLES)
    assert len(rows["DOCUMENTS"]) == 1
    for table, rs in rows.items():
        for r in rs:
            assert (r["run_id"], r["corpus"], r["doc_id"]) == ("r1", "contract", "d1")
            assert list(r) == list(spec.columns(table))


def test_arrays_keep_order_in_seq():
    els = _rows()["ELEMENTS"]
    assert [(r["seq"], r["element_id"]) for r in els] == [(0, "e1"), (1, "e2")]


def test_text_is_kept_verbatim():
    """字形を正規化しない。"""
    el = _rows()["ELEMENTS"][0]
    assert el["text"] == "甲は乙に（１）を委託する。" and el["label"] == "第一条"
    assert _rows()["PARTIES"][0]["alias"] == "甲"


def test_renamed_columns_and_document_summary():
    page = _rows()["PAGES"][0]
    assert (page["page"], page["page_class"]) == (1, ["body"])
    doc = _rows()["DOCUMENTS"][0]
    assert (doc["title"], doc["n_pages"], doc["n_elements"], doc["n_errors"]) == (
        "業務委託契約書",
        1,
        2,
        0,
    )
    assert set(doc["extras"]) == set(spec.EXTRA_KEYS)


def test_row_counts_match_rows():
    rows = _rows()
    assert spec.row_counts(OUT) == {t: len(rs) for t, rs in rows.items()}


def test_missing_arrays_give_no_rows():
    out = {k: v for k, v in OUT.items() if k not in ("refs", "parties")}
    rows = spec.to_rows(out, run_id="r1", corpus="yakkan", output_uri="u")
    assert rows["REFS"] == [] and rows["PARTIES"] == []


def _ddl_columns(table: str) -> list[str]:
    ddl = (HOME / "sql" / "setup" / "01_objects.sql").read_text(encoding="utf-8")
    m = re.search(
        rf"CREATE TABLE IF NOT EXISTS <% db %>\.<% schema_output %>\.{table} \((.*?)\);", ddl, re.S
    )
    assert m, table
    return [c.strip().split()[0] for c in m.group(1).split(",") if c.strip()]


@pytest.mark.parametrize("table", spec.TABLES)
def test_sql_ddl_columns_match_spec(table):
    cols = [c for c in _ddl_columns(table) if c != "registered_at"]
    assert cols == list(spec.columns(table))


@pytest.mark.parametrize("table", spec.TABLES)
def test_s55_insert_columns_match_spec(table):
    sql = (HOME / "sql" / "procedures" / "s55_register.sql").read_text(encoding="utf-8")
    m = re.search(rf"INSERT INTO <% db %>\.<% schema_output %>\.{table} \(([^)]*)\)", sql)
    assert m, table
    assert [c.strip() for c in m.group(1).split(",")] == list(spec.columns(table))
