"""契約書の条項木（F3・T3.1・T3.2・C-006）。

`tree.py`（約款の組み立て器）とは**別の組み立て器**である。約款の規則には、括弧付きの号を本文に併合する
（`drop_paren_items`。約款の gold の号に括弧付きは 0 件）、条番号は算用数字だけ（`第[0-9]+条`）といった
約款に固有の前提があり、契約書ではそれが号・漢数字の条を丸ごと消していた（B0：号 R 0.000、contracting の要素 0 件）。
約款の経路に分岐を足すと約款の結果が動く恐れがあるので、体裁を印字形から判定し（`detect_contract_scheme`）、
契約書と判定した文書だけをここで組む。出力は同じ `Tree`/`Node` なので、意味層・統合・採点はそのまま使える。

**gold を読まない。** 規則は dev の印字形と gold の構造の観察から作った（dev のみ）。
ラベルは印字されたまま持つ（`第一条`・`２`・`（１）`・`(1)`・`①`・`ｱ`）。

3 つの体裁（numbering scheme）：
  standard : `第１章 総則` → `第１条（題名）` → 項 `２本文` → 号 `（１）本文`／`(1)本文`
  kanji    : `（題名）` の行の次に `第一条本文…` → 項 `2本文` → 号 `(1)本文`
  form     : `１題名`（章）→ `（１）題名`（条）→ `①本文`（段落）→ `ｱ本文`（号）

共通の外枠：
  前文     : 最初の見出しより前の本文（`以下「甲」という` を含む段落）。引用は空。form では `①` ラベル付き
  頭書     : 前文の後・第 1 条の前の `１題名` の並び（standard のみ）。`頭書` → 号 `１` → 無番号段落
  署名欄   : `本契約の成立を証するため` で始まる段落。引用は空
  別紙     : `別紙１`・`別表１`・`様式１` の見出し。その下に appendix_section（ラベル空）と段落 `１本文`

木の形（gold に合わせる）：
  号は**段落の子**。条の第 1 項は無番号段落（ラベル空・引用は条と同じ）で、その下の号の引用は `第三条 (1)`、
  第 2 項以降の下の号は `第六条 3 (1)` になる。
"""

from __future__ import annotations

import re

from .tree import Node, Tree

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
KANJI_DIGIT = {
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
DIGITS = "0-9０-９"
KANJI_NUM = "一二三四五六七八九十百〇"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
KATAKANA_HALF = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎ"
IROHA_FULL = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホ"

STANDARD, KANJI, FORM = "contract-standard", "contract-kanji", "contract-form"

# 体裁の判定に使う印字形（行頭）
RE_ART_STD = re.compile(rf"^第([{DIGITS}]+)条(?:の([{DIGITS}]+))?[（(]")
RE_ART_KANJI = re.compile(rf"^第([{KANJI_NUM}]+)条(\S.*)$")
RE_PARTY_DECL = re.compile(r"以下「[^」]{1,10}」という")
# 冒頭の当事者欄（`委託者株式会社…`・`事業主有限会社…`）。役割名は一般的な契約の語彙で、gold を見て決めたものではない
PARTY_ROLES = (
    "委託者",
    "受託者",
    "発注者",
    "受注者",
    "注文者",
    "請負者",
    "事業主",
    "労働者",
    "貸主",
    "借主",
    "賃貸人",
    "賃借人",
    "許諾者",
    "実施権者",
    "使用権者",
    "委任者",
    "受任者",
    "開示者",
    "受領者",
    "売主",
    "買主",
    "甲",
    "乙",
    "丙",
    "保証人",
    "家賃債務保証業者",
)
RE_PARTY_FIELD = re.compile(rf"^(?:{'|'.join(sorted(PARTY_ROLES, key=len, reverse=True))})[　 ]*\S")
RE_CIRCLED_LINE = re.compile(rf"^[{CIRCLED}]\S")

# 見出しと番号
RE_CHAPTER = re.compile(rf"^第([{DIGITS}]+)章[　 ]*(\S.*)$")
RE_ARTICLE_STD = re.compile(rf"^第([{DIGITS}]+)条(?:の([{DIGITS}]+))?[　 ]*[（(](.+?)[）)][　 ]*$")
RE_KANJI_TITLE = re.compile(r"^[（(]([^（）()]{1,30})[）)]$")
RE_APPENDIX = re.compile(rf"^((?:別紙|別表|様式)[{DIGITS}]+)[　 ]*(\S.*)?$")
# 項：`２本文`。数字の直後が日付・時刻・番号の単位なら項ではない（`２０２６年…`・`5日以内に…`・`3月1日`）。
# `月`・`時`・`分` は後ろに数字か `間` が続くときだけ日付・時刻とみなす（`2月額報酬の…`・`1分担は…` は項。dev の csl・lea で項が途切れていた）
RE_PARA_NUM = re.compile(
    rf"^([{DIGITS}]{{1,2}})(?![{DIGITS}年日条項号章．.%％]|月[{DIGITS}]|か月|ヶ月|箇月|時[{DIGITS}間]|分[{DIGITS}間])[　 ]*(\S.*)$"
)
RE_ITEM_PAREN = re.compile(rf"^([（(][{DIGITS}]{{1,2}}[）)])[　 ]*(\S.*)$")
RE_FORM_CHAPTER = re.compile(rf"^([{DIGITS}]{{1,2}})(?![{DIGITS}])[　 ]*([^\s、。]\S*)$")
RE_FORM_ARTICLE = re.compile(rf"^([（(][{DIGITS}]{{1,2}}[）)])[　 ]*([^\s、。]{{1,30}})$")
RE_FORM_PARA = re.compile(rf"^([{CIRCLED}])[　 ]*(\S.*)$")
RE_FORM_ITEM = re.compile(rf"^([{KATAKANA_HALF}{IROHA_FULL}])[　 ]*(\S.*)$")
RE_SIGNATURE = re.compile(r"^本(?:契約|約款|書|覚書)の(?:締結|成立)を証するため")
RE_TOC = re.compile(r"^(?:目次|目\s*次)$")
RE_TOC_LINE = re.compile(
    rf"^(?:第[{DIGITS}{KANJI_NUM}]+[章条]|(?:別紙|別表|様式)[{DIGITS}]+).*[{DIGITS}]{{1,3}}$"
)
RE_TABLE_CAPTION = re.compile(rf"^(?:表|図)[{DIGITS}]+(?:[-－][{DIGITS}]+)?\S")

# 行頭に来た参照（「第2項の…」「(1)の書類」）は見出しではない。tree.py の RE_PARA_REF_TAIL と同じ語
RE_REF_TAIL = re.compile(r"^(?:の|に|を|が|と|から|まで|および|または|、|項|号)")
SENTENCE_END = ("。", "）", ")")


def kanji_to_int(s: str) -> int:
    """`十五`・`二十四`・`百` を整数にする。条番号の連番検査だけに使う（ラベルは印字のまま持つ）。"""
    total, cur = 0, 0
    for ch in s:
        if ch == "百":
            total += (cur or 1) * 100
            cur = 0
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            cur = KANJI_DIGIT.get(ch, 0)
    return total + cur


def _int(s: str) -> int:
    return int(re.sub(r"\D", "", s.translate(Z2H)) or 0)


def detect_contract_scheme(lines: list[str]) -> str | None:
    """印字形から契約書の体裁を推定する。契約書でなければ None（約款の組み立て器を使う）。

    契約書であることの手掛かりは、当事者の呼称の宣言（`以下「甲」という`）が冒頭近くにあるか、
    冒頭の 12 行に当事者欄（`事業主…`・`労働者…`）が 2 つ以上あること（宣言の無い様式型がある：emp-0002）。
    約款は当事者を宣言しない（「保険契約者」等は用語の定義表で定める）。
    """
    head = [s.strip() for s in lines[:80]]
    n_fields = sum(1 for s in head[:12] if RE_PARTY_FIELD.match(s))
    if not any(RE_PARTY_DECL.search(s) for s in head) and n_fields < 2:
        return None
    n_kanji = sum(1 for s in lines if RE_ART_KANJI.match(s.strip()))
    n_std = sum(1 for s in lines if RE_ART_STD.match(s.strip()))
    n_circ = sum(1 for s in lines if RE_CIRCLED_LINE.match(s.strip()))
    if n_kanji >= 3 and n_kanji > n_std:
        return KANJI
    if n_std >= 2:
        return STANDARD
    if n_circ >= 3:
        return FORM
    return None


class ContractBuilder:
    def __init__(self, doc_id: str, scheme: str):
        self.doc_id = doc_id
        self.scheme = scheme
        self.t = Tree(doc_id=doc_id)
        self.seq = 0
        self.cur: dict[str, Node | None] = {}
        self.reset_below("root")
        self.pending_kanji_title: str | None = None
        self.in_toc = False
        self.seen_article = False
        self.state = "preamble"  # preamble → (head) → body → signature → appendix
        self.last_para_num = 0
        self.last_item_num = 0
        self.last_art_num = 0
        self.last_chapter_num = 0
        self.titled: Node | None = None  # 題名だけの号（次の行で見出し付きの項と分かることがある）
        self.titled_run = False
        self.titled_parent: Node | None = None

    # ------------------------------------------------------------ 木の操作
    def reset_below(self, kind: str) -> None:
        order = [
            "root",
            "head_matter",
            "preamble",
            "signature",
            "appendix",
            "appendix_section",
            "chapter",
            "article",
            "paragraph",
            "item",
        ]
        keep = order[: order.index(kind) + 1]
        self.cur = {k: (self.cur.get(k) if k in keep else None) for k in order}

    def _cit(self, parent: Node | None, label: str) -> str:
        base = parent.citation if parent is not None else ""
        return f"{base} {label}".strip() if label else base

    def open(
        self,
        kind: str,
        label: str,
        heading: str,
        page: int,
        parent: Node | None,
        citation: str | None = None,
    ) -> Node:
        self.seq += 1
        n = Node(
            node_id=f"c{self.seq}",
            kind=kind,
            label=label,
            heading=heading,
            citation=self._cit(parent, label) if citation is None else citation,
            parent_id=parent.node_id if parent is not None else None,
            pages=[page],
        )
        self.t.add(n)
        return n

    def body_target(self) -> Node | None:
        for k in ("item", "paragraph"):
            if self.cur.get(k) is not None:
                return self.cur[k]
        return None

    def append(self, s: str, page: int) -> None:
        tgt = self.body_target()
        if tgt is None:
            return
        tgt.lines.append(s)
        if page not in tgt.pages:
            tgt.pages.append(page)

    # ------------------------------------------------------------ 段落と号
    def open_paragraph(self, label: str, text: str, page: int) -> None:
        parent = (
            self.cur["article"]
            or self.cur["appendix_section"]
            or self.cur["preamble"]
            or self.cur["signature"]
        )
        if parent is None:
            return
        self.reset_below(parent.kind if parent.kind != "article" else "article")
        n = self.open("paragraph", label, "", page, parent)
        if text:
            n.lines.append(text)
        self.cur["paragraph"] = n
        self.last_item_num = 0
        self.titled_run, self.titled_parent = False, None

    def open_item(self, label: str, text: str, page: int) -> Node | None:
        pa = self.cur["paragraph"]
        if self.titled_run and self.titled_parent is not None:
            pa = self.titled_parent  # 見出し付きの号の列の続き（付け替えは _promote_titled が行う）
        if pa is None:
            return None
        n = self.open("item", label, "", page, pa)
        if text:
            n.lines.append(text)
        self.cur["item"] = n
        return n

    # ------------------------------------------------------------ 主処理
    def feed(self, page: int, s: str) -> None:  # noqa: C901 — 体裁ごとの分岐を 1 か所に並べる
        s = s.strip()
        if not s:
            return
        if RE_TOC.match(s):
            self.in_toc = True
            return
        if self.in_toc:
            if RE_TOC_LINE.match(s):
                return
            self.in_toc = False
        if RE_TABLE_CAPTION.match(s):
            return

        if RE_SIGNATURE.match(s):
            self.reset_below("root")
            sig = self.open("signature", "", "", page, None, citation="")
            self.cur["signature"] = sig
            self.state = "signature"
            self.open_paragraph("", s, page)
            return

        m = RE_APPENDIX.match(s)
        if (
            m
            and self.state in ("body", "signature", "appendix")
            and not RE_REF_TAIL.match(m.group(2) or "")
        ):
            self.reset_below("root")
            ap = self.open("appendix", m.group(1), m.group(2) or "", page, None)
            sec = self.open("appendix_section", "", "", page, ap, citation=ap.citation)
            self.cur["appendix"], self.cur["appendix_section"] = ap, sec
            self.state = "appendix"
            self.last_para_num = 0
            return

        if self.state == "signature":
            self.append(s, page)  # 日付・住所・記名の行（gold の署名欄の段落は 1 つ）
            return

        if self.state == "appendix":
            m = RE_PARA_NUM.match(s)
            if (
                m
                and not RE_REF_TAIL.match(m.group(2))
                and _int(m.group(1)) == self.last_para_num + 1
            ):
                self.last_para_num += 1
                self.open_paragraph(m.group(1), m.group(2), page)
                return
            self.append(s, page)
            return

        if self.scheme == FORM:
            self.feed_form(page, s)
        elif self.scheme == KANJI:
            self.feed_kanji(page, s)
        else:
            self.feed_standard(page, s)

    def ensure_preamble(self, page: int) -> Node:
        if self.cur["preamble"] is None:
            pre = self.open("preamble", "", "", page, None, citation="")
            self.cur["preamble"] = pre
        return self.cur["preamble"]

    def preamble_line(self, page: int, s: str, label: str = "") -> None:
        """前文：当事者の宣言を含む段落から始める。それより前（当事者表の行）は本文に入れない。"""
        if self.cur["paragraph"] is None:
            if not RE_PARTY_DECL.search(s) and not label:
                return
            self.ensure_preamble(page)
            self.open_paragraph(label, s, page)
            return
        self.append(s, page)

    # standard ----------------------------------------------------------
    def feed_standard(self, page: int, s: str) -> None:
        m = RE_CHAPTER.match(s)
        if m and not RE_REF_TAIL.match(m.group(2)):
            self.reset_below("root")
            ch = self.open("chapter", f"第{m.group(1)}章", m.group(2), page, None)
            self.cur["chapter"] = ch
            self.state = "body"
            return
        m = RE_ARTICLE_STD.match(s)
        if m:
            self.open_article(
                f"第{m.group(1)}条" + (f"の{m.group(2)}" if m.group(2) else ""), m.group(3), page
            )
            return
        if self.state == "preamble":
            # 頭書：前文の後の `１題名` の並び（題名は短く句読点を含まない）
            if self.cur["paragraph"] is not None and self.cur["preamble"] is not None:
                h = RE_FORM_CHAPTER.match(s)
                if h and _int(h.group(1)) == 1 and len(h.group(2)) <= 20:
                    self.state = "head"
                    self.last_chapter_num = 0
            if self.state == "preamble":
                self.preamble_line(page, s)
                return
        if self.state == "head":
            h = RE_FORM_CHAPTER.match(s)
            if h and _int(h.group(1)) == self.last_chapter_num + 1 and len(h.group(2)) <= 20:
                if self.cur["head_matter"] is None:
                    self.reset_below("root")
                    self.cur["head_matter"] = self.open(
                        "head_matter", "", "", page, None, citation="頭書"
                    )
                hm = self.cur["head_matter"]
                self.reset_below("head_matter")
                self.last_chapter_num += 1
                it = self.open("item", h.group(1), h.group(2), page, hm)
                it.lines.append(h.group(2))  # gold の頭書の号は題名を本文として持つ（pur-0005）
                pa = self.open("paragraph", "", "", page, it, citation=it.citation)
                self.cur["item"], self.cur["paragraph"] = None, pa
                return
            self.append(s, page)
            return
        self.body_line(page, s, para_rx=RE_PARA_NUM, item_rx=RE_ITEM_PAREN)

    # kanji -------------------------------------------------------------
    def feed_kanji(self, page: int, s: str) -> None:
        m = RE_KANJI_TITLE.match(s)
        if (
            m
            and self.state != "preamble"
            or (
                m
                and self.cur["paragraph"] is not None
                and self.state == "preamble"
                and self.cur["preamble"] is not None
            )
        ):
            self.pending_kanji_title = m.group(1)
            return
        m = RE_ART_KANJI.match(s)
        if m and self.pending_kanji_title is not None:
            title, self.pending_kanji_title = self.pending_kanji_title, None
            self.open_article(f"第{m.group(1)}条", title, page)
            if m.group(2):
                self.open_paragraph("", m.group(2), page)
            return
        if self.pending_kanji_title is not None:
            # 題名の括弧行の次が条でなかった：題名は本文だった
            self.append(f"（{self.pending_kanji_title}）", page)
            self.pending_kanji_title = None
        if self.state == "preamble":
            self.preamble_line(page, s)
            return
        self.body_line(page, s, para_rx=RE_PARA_NUM, item_rx=RE_ITEM_PAREN)

    # form --------------------------------------------------------------
    def feed_form(self, page: int, s: str) -> None:
        m = RE_FORM_CHAPTER.match(s)
        if (
            m
            and _int(m.group(1)) == self.last_chapter_num + 1
            and len(m.group(2)) <= 24
            and not RE_REF_TAIL.match(m.group(2))
        ):
            self.reset_below("root")
            self.last_chapter_num += 1
            self.cur["chapter"] = self.open("chapter", m.group(1), m.group(2), page, None)
            self.state = "body"
            self.last_art_num = 0
            return
        m = RE_FORM_ARTICLE.match(s)
        if m and self.cur["chapter"] is not None and _int(m.group(1)) == self.last_art_num + 1:
            self.last_art_num += 1
            self.reset_below("chapter")
            self.cur["article"] = self.open(
                "article", m.group(1), m.group(2), page, self.cur["chapter"]
            )
            self.seen_article = True
            self.last_para_num = 0
            return
        if self.state == "preamble":
            m = RE_FORM_PARA.match(s)
            if m and self.cur["paragraph"] is None:
                self.preamble_line(page, m.group(2), label=m.group(1))
                return
            self.preamble_line(page, s)
            return
        m = RE_FORM_PARA.match(s)
        if m and self.cur["article"] is not None and not RE_REF_TAIL.match(m.group(2)):
            num = CIRCLED.index(m.group(1)) + 1
            if num == self.last_para_num + 1:
                self.last_para_num = num
                self.open_paragraph(m.group(1), m.group(2), page)
                return
        m = RE_FORM_ITEM.match(s)
        if m and self.cur["paragraph"] is not None and self._next_kana(m.group(1)):
            self.open_item(m.group(1), m.group(2), page)
            return
        self.append(s, page)

    def _next_kana(self, ch: str) -> bool:
        seq = KATAKANA_HALF if ch in KATAKANA_HALF else IROHA_FULL
        idx = seq.index(ch) + 1
        if idx == self.last_item_num + 1:
            self.last_item_num = idx
            return True
        return False

    # 共通 --------------------------------------------------------------
    def open_article(self, label: str, title: str, page: int) -> None:
        parent = self.cur["chapter"]
        self.reset_below("chapter" if parent is not None else "root")
        if self.state in ("preamble", "head"):
            self.cur["head_matter"] = None
            self.cur["preamble"] = None
        self.state = "body"
        self.cur["article"] = self.open("article", label, title, page, parent)
        self.seen_article = True
        self.last_para_num = 1  # 第 1 項は無番号段落（下の body_line が最初の本文行で開く）

    def body_line(
        self, page: int, s: str, para_rx: re.Pattern[str], item_rx: re.Pattern[str]
    ) -> None:
        if self.cur["article"] is None:
            self.append(s, page)
            return
        m = item_rx.match(s)
        if m and not RE_REF_TAIL.match(m.group(2)) and self.cur["paragraph"] is not None:
            num = _int(m.group(1))
            if num == self.last_item_num + 1:
                self.last_item_num = num
                # 見出し付きの項：括弧番号の行が短い題名だけ（句読点なし）なら、項（段落）を開き、題名は heading に置く。
                # gold は `第3条 （1）` の段落で、本文は次の行から（dlg-0001・dlg-0004 第3条）。
                # 判定は次の行を見ないとできないので、ここでは号として開き、次の行で付け替える
                self.open_item(m.group(1), m.group(2), page)
                self.titled = self.cur["item"] if self._looks_title(m.group(2)) else None
                return
        m = para_rx.match(s)
        if m and not RE_REF_TAIL.match(m.group(2)):
            num = _int(m.group(1))
            if num == self.last_para_num + 1 and self.cur["paragraph"] is not None:
                self.last_para_num = num
                self.open_paragraph(m.group(1), m.group(2), page)
                return
        if self.cur["paragraph"] is None:
            self.open_paragraph("", s, page)
            return
        if self.titled is not None and self.cur["item"] is self.titled:
            self._promote_titled(page, s)
            return
        if self.cur["item"] is not None and self._continues_item(s):
            self.append(s, page)
            return
        if self.cur["item"] is not None:
            # 号が終わった後の本文（「前各号の…」）は段落に戻す
            self.cur["item"] = None
        self.append(s, page)

    @staticmethod
    def _looks_title(text: str) -> bool:
        return len(text) <= 24 and not any(ch in text for ch in "。、")

    def _promote_titled(self, page: int, s: str) -> None:
        """題名だけの号の次に本文が来た：見出し付きの号（dlg-0001・ots-0002 第3条）。

        gold の形は頭書と同じで、号は**条の直下**に置き、題名を号の本文とし、その下に無番号段落
        （引用は号と同じ）を開いて本文を入れる。号を段落の子から条の子へ付け替える。
        同じ列の前の号（`（1）`）も同じ形なら付け替え済み。
        """
        it = self.titled
        self.titled = None
        art = self.cur["article"]
        pa = self.t.nodes[it.parent_id]
        if pa.node_id != art.node_id:
            pa.children.remove(it.node_id)
            art.children.append(it.node_id)
            it.parent_id = art.node_id
            it.citation = self._cit(art, it.label)
        body = self.open("paragraph", "", "", page, it, citation=it.citation)
        body.lines.append(s)
        self.cur["item"], self.cur["paragraph"] = None, body
        self.titled_parent = pa  # 続く括弧番号の号の数え先（元の段落）
        self.titled_run = True

    def _continues_item(self, s: str) -> bool:
        """号の折り返しか。直前の号の行が文末で終わっていなければ続き。"""
        it = self.cur["item"]
        last = (it.lines[-1] if it and it.lines else "").rstrip()
        return not last.endswith(SENTENCE_END) or len(last) >= 38


def build_contract_tree(
    doc_id: str, pages: dict[int, str], scheme: str, skip_pages: set[int] | None = None
) -> Tree:
    b = ContractBuilder(doc_id, scheme)
    for page in sorted(pages):
        if page in (skip_pages or set()):
            continue
        for s in pages[page].split("\n"):
            b.feed(page, s)
    tree = b.t
    tree.rejected.append(f"contract_scheme={scheme}")
    return tree
