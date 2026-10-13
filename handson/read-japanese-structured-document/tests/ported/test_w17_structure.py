"""W17-B — 本文を持たない容器の共有抑止と、段落見出しの参照否定。肯定例と否定例を対で書く。"""

from jpdocread.read.structure.tree import (
    RE_PARA_REF_TAIL,
    Node,
    Tree,
    bodyless_container_cut,
    build_tree,
    merge_cut,
)


def test_para_ref_tail_rejects_wrapped_reference():
    t = build_tree(
        None,
        {
            1: "第１章総則\n第１条（義務）\n(1)保険契約者は、義務を負う。\n(2)正当な理由がなく\n(1)の書類に偽りを記載した場合も同様とします。\n(3)次の場合は除く。"
        },
    )
    labels = [n.label for n in t.nodes.values() if n.kind == "paragraph"]
    assert labels == ["(1)", "(2)", "(3)"]
    p2 = [n for n in t.nodes.values() if n.label == "(2)"][0]
    assert "(1)の書類" in p2.text  # 本文として直前の段落に付く（失われない）


def test_para_ref_tail_keeps_real_heads():
    # 本物の項が参照から書き始まる形（`②第1項の…`）は落とさない
    assert not RE_PARA_REF_TAIL.match("第1項の高度障害保険金を支払ったときは")
    assert not RE_PARA_REF_TAIL.match("保険契約者または被保険者は")
    assert RE_PARA_REF_TAIL.match("の書類に事実と異なる記載をし")


def test_merge_cut_takes_max():
    assert merge_cut({2: 5}, {2: 9, 3: 4}) == {2: 9, 3: 4}
    assert merge_cut({2: 5}, None) == {2: 5}


def _tree_with(rider_body: str) -> Tree:
    t = Tree("x")
    r = Node(
        "rid1",
        "rider",
        label="競技会中の事故に関する特約",
        pages=[3],
        heading_line="競技会中の事故に関する特約",
    )
    a = Node(
        "art1",
        "article",
        label="第1条",
        parent_id="rid1",
        pages=[3],
        heading_line="第１条（この特約の適用条件）",
    )
    r.children = ["art1"]
    t.nodes = {"rid1": r, "art1": a}
    if rider_body:
        p = Node("par1", "paragraph", label="", parent_id="art1", pages=[3], lines=[rider_body])
        a.children = ["par1"]
        t.nodes["par1"] = p
    return t


def test_bodyless_container_cut_marks_heading_run():
    pages = {
        3: "第１１条（準拠法）\n競技会中の事故に関する特約\n第１条（この特約の適用条件）\n本文"
    }
    assert bodyless_container_cut(_tree_with(""), pages) == {3: 2}


def test_container_with_body_is_not_cut():
    pages = {3: "競技会中の事故に関する特約\n第１条（この特約の適用条件）\nこの特約は適用します。"}
    assert bodyless_container_cut(_tree_with("この特約は適用します。"), pages) == {}


def test_citation_use_by_genre():
    from jpdocread.read.integrate import citation_use_for

    assert citation_use_for("teikan-0001--teikan-a4-1col-mincho")["citation_use"] == "evidence"
    assert citation_use_for("health-0001--nl-a4-2col-mincho")["citation_use"] == "verify"
    assert citation_use_for("travel-0001--nl-a4-1col-gothic")["citation_use"] == "candidate"
    # 測っていない系統は根拠にしない
    assert citation_use_for("pet-0001--x")["citation_use"] == "candidate"
