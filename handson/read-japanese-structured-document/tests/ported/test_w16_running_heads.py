"""W16-A — 分割された柱と、愛称付きの特約名。肯定例と否定例を対で書く。"""

from jpdocread.read.structure.tree import RE_RIDER


def test_rider_with_nickname_opens():
    m = RE_RIDER.match("こども治療給付特約〈すこやかケア〉")
    assert m and m.group(1) == "こども治療給付特約〈すこやかケア〉"


def test_rider_plain_still_opens():
    assert RE_RIDER.match("育英年金特約").group(1) == "育英年金特約"


def test_rider_nickname_negative_prose():
    # 本文中の参照（句読点や空白を含む）は特約見出しではない
    assert not RE_RIDER.match("この特約〈すこやかケア〉の規定により、支払います。")
    assert not RE_RIDER.match("こども治療給付特約〈すこやか ケア〉を付加した場合")


def test_split_running_head_is_furniture(monkeypatch):
    """柱 `第２編…第２章X`（幾何の 1 行）が分割されて先頭の 2 行になり、
    同じページの後方に本物の `第２章X` があるとき、柱側の章行だけを落とす。"""
    import types

    import jpdocread.read.geometry as G
    from jpdocread.read.structure import tree as T

    line = types.SimpleNamespace(
        page=10, y0=20.0, y1=28.0, text="第２編普通保険約款第２章保険契約の締結"
    )
    pg = types.SimpleNamespace(page=10, height=700.0)
    monkeypatch.setattr(G, "read_lines", lambda d: [line])
    monkeypatch.setattr(G, "read_pages", lambda d: [pg])
    text = "\n".join(
        [
            "第２編普通保険約款",
            "第２章保険契約の締結",
            "第３条（支払わない場合）",
            "本文",
            "第２章保険契約の締結",
        ]
    )
    assert T._furniture_upper_lines("x", {10: text}) == {(10, 1)}


def test_split_running_head_without_real_heading_is_kept(monkeypatch):
    """本物が同じページに無いとき、柱は唯一の章情報源であり得るので落とさない。"""
    import types

    import jpdocread.read.geometry as G
    from jpdocread.read.structure import tree as T

    line = types.SimpleNamespace(
        page=10, y0=20.0, y1=28.0, text="第２編普通保険約款第２章保険契約の締結"
    )
    pg = types.SimpleNamespace(page=10, height=700.0)
    monkeypatch.setattr(G, "read_lines", lambda d: [line])
    monkeypatch.setattr(G, "read_pages", lambda d: [pg])
    text = "\n".join(
        ["第２編普通保険約款", "第２章保険契約の締結", "第３条（支払わない場合）", "本文"]
    )
    assert T._furniture_upper_lines("x", {10: text}) == set()


def test_part_reference_prose_does_not_open_part():
    from jpdocread.read.structure.tree import build_tree

    t = build_tree(
        None,
        {
            1: "第１編ご契約のしおり\n第４章保険料\n詳しくは第2編第2章第2条をご覧ください。\n第2編第2章第2条をご覧ください。",
            2: "第２編普通保険約款\n第１章支払\n第１条（支払）\n本文",
        },
    )
    parts = [n.label for n in t.nodes.values() if n.kind == "part"]
    assert parts == ["第1編", "第2編"]
    ch4 = [n for n in t.nodes.values() if n.kind == "chapter" and n.label == "第4章"][0]
    assert t.nodes[ch4.parent_id].label == "第1編"


def test_part_heading_name_still_opens():
    from jpdocread.read.structure.tree import build_tree

    t = build_tree(None, {1: "第２編　普通保険約款\n第１章支払\n第１条（支払）\n本文"})
    assert [n.label for n in t.nodes.values() if n.kind == "part"] == ["第2編"]
