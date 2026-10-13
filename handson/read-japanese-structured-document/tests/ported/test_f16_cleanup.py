"""F16・F17：分離した目次・重要事項説明書（jyusetsu）・特約・表の行の号（読み取りの規則）と、設定の受け口。

名前の直書きは tests/guard/test_naming.py が本リポジトリの規則（接頭辞 JA_DOC_STRUCTURED_）で検査している。
"""

from __future__ import annotations

import pytest
import yaml

from jpdocread.common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "pipeline.yaml").read_text(encoding="utf-8"))


def test_figure_model_comes_from_pipeline_yaml():
    from jpdocread.read.figures import MODEL_DEFAULT

    assert CFG["figure"]["model"] == MODEL_DEFAULT


@pytest.mark.parametrize("corpus", ["yakkan", "contract"])
def test_known_limits_from_corpus_config_and_no_numbers_in_code(corpus):
    """移植元 T16.8：known_limits は設定から読み、コードに数値を書かない（本ハンズオンではコーパス設定に置く）。"""
    import re

    from jpdocread.config import load_corpus_config
    from jpdocread.read.integrate import ReadOptions

    c = load_corpus_config(corpus)
    assert ReadOptions.from_corpus(c).known_limits == c.known_limits and c.known_limits["source"]
    src = (CONFIGS.parent / "src" / "jpdocread" / "read" / "integrate.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"0\.033951|0\.0035\b|0\.0615|0\.023406|0\.8411", src)


# ---------------------------------------------------------------- T16.6 分離した目次（A ラウンド 1）


def _split(rows: list[str]) -> dict[int, int]:
    from jpdocread.read.structure.lines import split_toc_cut

    return split_toc_cut({2: "\n".join(rows)})


SPLIT_TOC = [
    "前書きの本文です。",
    "もくじ",
    "第１章用語の定義",
    "第１条（用語の意味）",
    "第２章賠償責任条項",
    "第１条（この条項の補償内容）",
    "第３章人身傷害条項",
    "4",
    "4",
    "5",
    "6",
]


def test_split_toc_cut_covers_last_heading_before_page_numbers():
    assert _split(SPLIT_TOC) == {2: 6}  # 最後の `第３章人身傷害条項` まで目次ブロック


@pytest.mark.parametrize(
    "rows",
    [
        SPLIT_TOC[:1] + SPLIT_TOC[2:],  # 目次の題が無い
        SPLIT_TOC[2:],  # ページ先頭から（目次の続き。health-0003 p4）
        SPLIT_TOC[:7] + ["6", "5", "4"],  # ページ番号が減る
        SPLIT_TOC[:7] + ["4", "5"],  # 番号が 2 行だけ
        ["もくじ", "第１章総則", "第１条（商号）", "4", "5", "6"],  # 見出しが 2 行だけ
        [
            "もくじ",
            "第１章総則",
            "第１条（商号）当会社は、",
            "第２条",
            "4",
            "5",
            "6",
        ],  # 句読点を含む本文行で切れる
    ],
)
def test_split_toc_cut_negative_controls(rows):
    assert _split(rows) == {}


# ---------------------------------------------------------------- F17（D-026）


def _jy(lines: list[str]):
    from jpdocread.read.structure.tree import build_tree

    t = build_tree("jyusetsu-test", {2: "\n".join(lines)}, grammar="jyusetsu")
    return {
        (n.kind, n.citation)
        for n in t.nodes.values()
        if n.kind in ("chapter", "section", "article")
    }


def test_jyusetsu_fullwidth_section_opens():
    got = _jy(
        [
            "１用語のご説明",
            "①この書面で使う用語",
            "本文です。",
            "２契約締結前におけるご確認事項",
            "（１）商品の仕組み",
            "①この保険の型",
            "本文です。",
        ]
    )
    assert ("section", "２ （１）") in got and ("article", "２ （１） ①") in got


def test_jyusetsu_table_row_does_not_open_chapter():
    got = _jy(
        [
            "１用語のご説明",
            "①用語",
            "本文です。",
            "２契約締結前",
            "３０歳未満４，３００円５，６００円",
            "３日まで3,200円2,600円",
            "６０歳未満５，６００円",
            "①告知",
            "本文です。",
        ]
    )
    chapters = {c for k, c in got if k == "chapter"}
    assert chapters == {"１", "２"} and ("article", "２ ①") in got


def test_jyusetsu_chapter_skip_of_two_is_allowed_but_not_more():
    got = _jy(
        ["１用語", "①用語", "本文です。", "３その他", "①窓口", "本文です。", "７表の行の題名"]
    )
    assert {c for k, c in got if k == "chapter"} == {"１", "３"}


def _rider_parent(part_title: str) -> str:
    from jpdocread.read.structure.tree import build_tree

    t = build_tree(
        "life-test",
        {
            3: "\n".join(
                [
                    f"第２編{part_title}",
                    "第１条（目的）",
                    "この約款は定めます。",
                    "保険料払込免除特約",
                    "第１条（適用）",
                    "この特約は定めます。",
                ]
            )
        },
    )
    r = next(n for n in t.nodes.values() if n.kind == "rider")
    return r.citation


def test_rider_is_root_unless_part_is_for_riders():
    assert _rider_parent("普通保険約款") == "保険料払込免除特約"
    assert _rider_parent("特約条項") == "第2編 保険料払込免除特約"


def test_outline_drops_table_row_items_only_under_table_reference():
    from jpdocread.read.integrate import _outline
    from jpdocread.read.structure.tree import Node, Tree

    t = Tree("x")
    for nid, kind, label, parent, text in [
        ("a", "article", "第1条", None, ""),
        ("p1", "paragraph", "（１）", "a", "被保険者は、下表に掲げる方とします。"),
        ("i1", "item", "①", "p1", "記名被保険者"),
        ("p2", "paragraph", "（２）", "a", "次に掲げる書類を添えてください。"),
        ("i2", "item", "①", "p2", "請求書"),
    ]:
        n = Node(
            node_id=nid,
            kind=kind,
            label=label,
            heading="",
            citation=nid,
            parent_id=parent,
            pages=[1],
        )
        n.lines.append(text)
        t.add(n)
    rows = {"記名被保険者", "請求書"}
    from jpdocread.read import integrate

    rows = {integrate._norm_row(x) for x in rows}
    ids = {o["id"] for o in _outline(t, rows)}
    assert "i1" not in ids and "i2" in ids  # 下表の行は外す・次に掲げるの号は残す
    assert {o["id"] for o in _outline(t, None)} >= {"i1", "i2"}


def test_jyusetsu_first_chapter_above_two_is_rejected():
    got = _jy(["３０歳未満の方", "１用語", "①用語", "本文です。"])
    assert {c for k, c in got if k == "chapter"} == {"１"}


def test_outline_keeps_table_row_item_with_children():
    from jpdocread.read import integrate
    from jpdocread.read.integrate import _outline
    from jpdocread.read.structure.tree import Node, Tree

    t = Tree("x")
    for nid, kind, label, parent, text in [
        ("a", "article", "第1条", None, ""),
        ("p1", "paragraph", "（１）", "a", "下表に掲げる方とします。"),
        ("i1", "item", "①", "p1", "記名被保険者"),
        ("i2", "item", "ア", "i1", "子"),
    ]:
        n = Node(
            node_id=nid,
            kind=kind,
            label=label,
            heading="",
            citation=nid,
            parent_id=parent,
            pages=[1],
        )
        n.lines.append(text)
        t.add(n)
    ids = {o["id"] for o in _outline(t, {integrate._norm_row("記名被保険者")})}
    assert "i1" in ids and "i2" in ids
