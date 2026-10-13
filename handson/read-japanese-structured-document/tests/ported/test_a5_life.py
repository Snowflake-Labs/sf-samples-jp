"""A5 — 編をまたぐ章の重複と、目次照合の題名一致。

`life` の条 recall 0.136 は**見出し規則の不足ではなく 2 つの照合の誤り**だった。
"""

from __future__ import annotations

from jpdocread.read.structure.candidates import _features, _norm_title
from jpdocread.read.structure.tree import build_tree


class TestChapterDedupIsScopedByPart:
    def test_chapter_numbers_restart_in_a_new_part(self):
        """`life` の gold は 第1編 に 章1〜2、第2編 に 章1〜2 を置く。

        文書全体で重複を弾くと **第2編 の 章2 が開かず、配下の全条が
        `第2編 第1章` に積み上がる**（条 recall 0.136 の主因）。
        """
        pages = {
            1: "第１編ご契約のしおり\n"
            "第１章このしおりの読み方\n"
            "第２章保険金のお支払い\n"
            "第２編普通保険約款\n"
            "第１章用語の定義\n"
            "第１条（用語の定義）\n"
            "本文です。\n"
            "第２章保険金の支払\n"
            "第１条（支払事由）\n"
            "本文です。"
        }
        t = build_tree("l", pages)
        chapters = [(n.citation) for n in t.nodes.values() if n.kind == "chapter"]
        assert chapters == ["第1編 第1章", "第1編 第2章", "第2編 第1章", "第2編 第2章"]
        arts = [n.citation for n in t.nodes.values() if n.kind == "article"]
        assert arts == ["第2編 第1章 第1条", "第2編 第2章 第1条"]

    def test_running_head_repetition_is_still_rejected(self):
        """否定例：同じ親のもとで同じ章が再出現するのは柱。二重に生やさない。"""
        pages = {
            1: "第１編ご契約のしおり\n第１章読み方\n本文です。",
            2: "第１編ご契約のしおり\n第１章読み方\n続きの本文です。",
        }
        t = build_tree("l2", pages)
        assert [n.citation for n in t.nodes.values() if n.kind == "chapter"] == ["第1編 第1章"]


class TestTocConfirmationRequiresTitleAgreement:
    """目次が裏付けるのは「その番号の見出しが存在する」ことだけである。"""

    class _Toc:
        def __init__(self, entries):
            self.entries = entries

    class _E:
        def __init__(self, kind, num, title):
            self.kind, self.num, self.title = kind, num, title

    def test_real_heading_is_confirmed(self):
        toc = self._Toc([self._E("part", 2, "普通保険約款")])
        f = _features("part", 2, "普通保険約款", "第２編普通保険約款", toc)
        assert f["toc_confirmed"] == 1.0

    def test_body_reference_is_not_confirmed(self):
        """否定例：本文中の参照。番号だけの照合では +1.5 を得て採用されてしまった。"""
        toc = self._Toc([self._E("part", 2, "普通保険約款")])
        line = "第２編第１章第２条に、お支払いできない場合は第２編第１章第３条に定めています。"
        f = _features("part", 2, "第１章第２条に、お支払いできない場合は…", line, toc)
        assert f["toc_confirmed"] == 0.0
        assert f["has_sentence_mark"] == 1.0  # 条以外では句読点の減点が残る

    def test_title_comparison_folds_typesetting_differences(self):
        """比較層でだけ全角/半角と空白を畳む。"""
        assert _norm_title("普通　保険約款") == _norm_title("普通保険約款")
        assert _norm_title("第２編") == _norm_title("第2編")
