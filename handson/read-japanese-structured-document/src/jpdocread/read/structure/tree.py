"""P5 — 構造（引用木）の組み立て。

入力は**行の列**（ページ番号つき）。行構造が要るので、背骨が R2 のときも
ここでは R4 の行を使う。理由は 2 つある。

1. `AI_PARSE_DOCUMENT(LAYOUT)` は全角括弧を半角に寄せるので、`（1）` と `(1)` を
   区別できない。引用の同一性はこの区別に依存する（S2 §3.4）。
2. gold のページ本文は改行を落としているので、行の根拠にできない。

出力は木。各ノードは kind / label / citation / pages / text を持つ。

**設計の要点は「見出しに見えるものを見出しと認めない規則」である。**
条番号は見出しでもあり本文中の参照でもある。区別できなければ木が壊れる。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .lines import is_toc_line, toc_block_end

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"

_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
RE_CHAPTER = re.compile(r"^第([0-9０-９]+)章[　 ]*(.*)$")
RE_ARTICLE = re.compile(r"^第([0-9０-９]+)条(?:の([0-9０-９]+))?[　 ]*(.*)$")
RE_APPENDIX = re.compile(r"^((?:別表|付表)[0-9０-９]+)[　 ]*(.*)$")
# 附則は番号を持たない根。条番号の体系も本則と別（gold の citation は `附則 第１ １`）。
RE_SUPPL = re.compile(r"^(附則)[　 ]*(.*)$")
RE_APP_SEC = re.compile(r"^第([0-9０-９]+)[　 ]*(\S.*)$")
"""別表の中の節（`別表1 第1 等級と支払割合`）。

**空白を必須にしてはならない（W10 の訂正）。** 元は `[　 ]+` と書いていたため
**39 文書すべてで一度も一致しなかった**（gold 77 件に対し予測 0 件）。
印刷面は `第1　等級と支払割合` だが、行の供給元（`pdfplumber` の行結合）は
空白を落とすので、届く文字列は `第1等級と支払割合` である。

**規則の唯一の足場を、入力が保持しない文字に置いてはならない。**
兄弟規則の `RE_APPENDIX` は同じ位置を `[　 ]*` と書いていて正しく動いていた
— 同じ性質の 2 規則が `+` と `*` で分かれていたのが誤りの実体である。

この欠落は条・段落の指標には現れない（`appendix_section` は別種別だから）。
**9 種の混同行列を実装した初回の実行で現れた**。
"""
JYUSETSU_BADGES = ("契約概要", "注意喚起情報")
"""重要事項説明書の条見出しに刷られる法定表示（W10）。

**条と号がどちらも丸数字である**という jyusetsu 固有の曖昧性を、これが解く。
実測（jyusetsu 4 文書・丸数字で始まる全行）：

    gold=条  標識あり 96 / 96      gold=号  標識あり 0 / 68

**96 対 0 の完全分離**である。W7 の「号は文末を『。』で閉じない」と同じ形
— 幾何でも番号の単調性でもなく、**編集上の慣行**が分ける。

番号の単調性では原理的に解けない。条 `②` を開いた直後の号の走査 `①②③④` では
③ が `expect_article`（=3）と一致するので、**曖昧性が条の側に倒れる**。
実測：`jyusetsu-0001` で `2 (2) ③` が条として 2 回出力され、
号 `2 (2) ② ③`・`④` が失われていた。

**文書内に標識が 1 つも無ければこの規則を使わない**（`_uses_badges`）。
標識を持たない重要事項説明書があり得るので、
規則の適用条件をその文書自身の証拠に結びつける。
"""
RE_APP_SEC_VALUE_TAIL = re.compile(r"[0-9０-９]+(?:[％%]|円|万円)$")
"""別表の節の見出しが**金額・割合で終わる**なら、それは節ではなく表の行（W11 T29）。

後遺障害等級表は `等級 / 後遺障害の程度 / 支払割合` の 3 列で、行結合の結果
**支払割合の値が行末に連結される**：

    第1級両眼の視力を全く失ったもの、または起居100%
    第12級局部に強い神経症状が続くもの9%

一方、真の `appendix_section` の見出しは**短い名詞句**である
（`等級と支払割合`・`既経過期間に応じる短期率`・`等級および支払割合`）。

実測（ALL 39・予測 `appendix_section` 107 件）：

    末尾が 数値＋%/円     偽 38 / 39      正 3 / 68

**分離する。** 落ちる正 3 件はいずれも**同一引用のノードが他にもある重複**なので、
引用集合の指標には影響しない（実測で確認済み）。

`級` の否定規則（W10）で取り切れなかったのは、
**`級` が別カラムに分かれる版では行が `第2両眼の視力が…` となり助数詞が届かない**ためである。
**助数詞は行結合の仕方で消えるが、値の列は消えない。**
"""
RE_SECTION = re.compile(r"^第([0-9０-９]+)節[　 ]*(.*)$")
RE_PART = re.compile(r"^第([0-9０-９]+)編[　 ]*(.*)$")
RE_APP_SEC_EXCLUDE = re.compile(r"^第[0-9０-９]+(?:条|章|節|編|項|号|級)")
"""`RE_APP_SEC` の否定規則（W10）。

`RE_APP_SEC` は番号の直後の空白を要求しないので、**番号の直後に助数詞・構造接尾辞が
来る行を明示的に外さないと、別表の中の行を別表の節として食う。**

- `条|章|節|編|項|号` — 別表の中の構造見出し
- **`級`** — 後遺障害等級表の行（`第1級両眼の視力を全く失ったもの`）。
  空白必須を外した最初の実測で、`auto-0001` に `第1級`〜`第12級` の
  **12 件の偽 `appendix_section`** が生えた。`級` は助数詞であって節番号ではない。

**同じ字面が 2 つの役割を持つ**という形は本プロジェクトで 3 度目である
（`第N条`＝見出しと参照、丸数字＝条と号、`第N`＝節と等級）。
順序でも幾何でもなく**助数詞**が分ける。

正規表現は肯定例と否定例を対で書くので、
`tests/test_w10_metrics.py` に両方のテストを置いた。
"""
# 特約は独立した番号体系を持つ。ここで条番号が 1 に戻る。
# **W16-A 試行 2：特約名の後ろの愛称（`〈すこやかケア〉`）を許す。** 許さないと
# `こども治療給付特約〈すこやかケア〉` が特約として開かず、その第1〜4条が直前の特約の
# 下に入っていた（life-0003）。ALL で該当する行は 2 行だけ（本物 1・柱 1）。
RE_RIDER = re.compile(
    r"^(?:[○◯・]?[　 ]*)?(\S{2,30}?特約(?:条項)?(?:[〈《][^〉》\s]{1,20}[〉》])?)[　 ]*$"
)
# **見出し文字列に現れてはならないもの**（本文中の参照を見出しにしない否定規則）。
# 上位見出しは*名前*であって文ではない。`RE_RIDER` は「空白の無い 30 字以内で
# 特約で終わる行」に一致するので、`この表に定める意味は、特約において別に定める
# 場合を除き、特約` という本文の一部が特約見出しになっていた（auto-0002 で実測）。
# 偽の上位見出しは**その配下の全段落の引用を外す**ので、1 件の誤りが 20 件以上の
# 段落 FP を生む（実測：8 件の偽見出しが段落 FP 451 件のうち 43 件を汚染）。
RE_PROSE_REF = re.compile(r"^第[0-9０-９]+(?:条|節)")
"""見出しの本体がこれで始まるなら、その行は見出しではなく本文中の参照である。

`第2章` ＋ `第4条(2)の算式は、…` は柱と本文が 1 行に出たもので、章見出しではない。
**`章`・`編` は含めない** — 柱の連結（S4 (B)）で `第２編普通保険約款第２章…` を
分割する処理が正当に使うためである。
"""


def _is_prose(head: str) -> bool:
    """見出し本体が散文か。句点を含む、または条・節の参照で始まるなら散文。

    **「、を含む」は使えない。** teikan の `監査役、監査役会および会計監査人` は
    正当な章見出しである。読点は日本語の見出しに普通に現れる。
    """
    return "。" in head or bool(RE_PROSE_REF.match(head.strip()))


def _fold(s: str) -> str:
    return re.sub(r"[ 　\t]+", "", unicodedata.normalize("NFKC", s))


def _furniture_upper_lines(
    doc_id: str | None, pages: dict[int, str], band: float = 0.07
) -> set[tuple[int, int]]:
    """柱（running head/footer）の上位見出しの (ページ, ページ内行番号) を返す（W8）。

    **位置だけでは決められない。** 同じ上位見出しがページ内に 2 回現れるとき、
    どちらが柱かは版面による：

        teikan p3   0: 第２章社員（柱）/ 1: 第４条 / … / 25: 第２章社員（本物）
        フッタ版面   0: 弁護士費用特約（本物）/ 1: 第1条 / … / n: 弁護士費用特約（柱）

    先着を柱と決める実装を試したところ、**フッタ版面の本物を落とした**
    （`tests/test_s4_structure.py::test_repeated_rider_name_does_not_duplicate` が失敗）。
    そこで**余白帯の幾何で決める**：柱は上端または下端の余白帯にあるので、

    - 上端の帯にある反復行 → **最初の**出現が柱
    - 下端の帯にある反復行 → **最後の**出現が柱

    幾何が無いとき（合成テスト・`doc_id=None`）は**何も落とさない。**
    幾何に依存する判断を、幾何の無い経路に持ち込まないためである。

    **柱を丸ごと落としてはならない**（`drop_repeated_headers` は実測で棄却済み。
    auto の条 recall 0.875 → 0.400）。ここで落とすのは
    **同じページに本物が別に居る場合の上位見出し 1 行だけ**である。
    """
    if not doc_id:
        return set()
    try:
        from ..geometry import read_lines, read_pages
    except Exception:
        return set()
    try:
        geo_pages = {p.page: p for p in read_pages(doc_id)}
        lines = read_lines(doc_id)
    except Exception:
        return set()
    # 余白帯にある行の文字列を、帯（top/bottom）ごとに集める。
    band_text: dict[int, dict[str, str]] = {}
    for ln in lines:
        pg = geo_pages.get(ln.page)
        if pg is None or not pg.height:
            continue
        t = ln.text.strip()
        if not t:
            continue
        if ln.y0 <= pg.height * band:
            band_text.setdefault(ln.page, {}).setdefault(t, "top")
        elif ln.y1 >= pg.height * (1.0 - band):
            band_text.setdefault(ln.page, {}).setdefault(t, "bottom")
    out: set[tuple[int, int]] = set()
    for pg, text in pages.items():
        marks = band_text.get(pg)
        if not marks:
            continue
        # **幅を畳んで照合する（V1）。** 幾何（`pdfplumber`）は `第２章`、R2 は `第2章` を返す。
        # 完全一致では R2 経路で柱が 1 つも見つからず、柱が章として開いた（teikan）。
        # R4 経路では両辺が同一文字列なので結果は変わらない。
        rows = [_fold(ln) for ln in text.split("\n")]
        for t, where in marks.items():
            t = _fold(t)
            idx = [j for j, r in enumerate(rows) if r == t]
            if len(idx) >= 2:
                out.add((pg, idx[0] if where == "top" else idx[-1]))
                continue
            # **W16-A：分割された柱。** 柱は編と章が 1 行につながって刷られ
            # （`第２編普通保険約款第２章保険契約の締結および維持`）、構造の入力では
            # `split_page_text` が 2 行に分ける。幾何の行（結合形）と完全一致しないので、
            # 柱の側の `第２章…` が落ちず、同じページの本物（後出）より先に章を開いていた
            # （life：第1章の最終条が第2章の下に入る。群 B の条の取りこぼしの主因）。
            # 上端帯の柱が**先頭から連続する 2〜3 行の連結**と一致し、そのうち上位見出しの
            # 行がページ内の後方に**もう一度**現れるときだけ、柱側の上位見出し行を落とす。
            if where != "top" or idx:
                continue
            for k in (2, 3):
                for s0 in range(0, min(3, len(rows))):
                    if "".join(rows[s0 : s0 + k]) != t:
                        continue
                    for j in range(s0, s0 + k):
                        r = rows[j]
                        if (RE_CHAPTER.match(r) or RE_SECTION.match(r)) and r in rows[s0 + k :]:
                            out.add((pg, j))
    return out


def _infer_chapter_resets(seq: list[tuple[int, str]], toc: set[int]) -> bool:
    """章境界で条番号が 1 に戻る体裁かを、**印字された番号列だけ**から推定する。

    正解（gold）は読まない。各章境界の直後に現れる最初の条番号を
    見て、1 なら「リセットする」、直前の章の最大条番号 +1 なら「連番」と数え、
    **章境界の多数決**で決める。証拠が無ければ既定（リセットする）。

    リセットしない体裁で期待値を 1 に戻すと、`第6条` が
    「不連続かつ見出し無し」で本文化されて条が丸ごと落ちる（teikan の
    条 recall が 0.694 で止まっていた一因・U-5）。
    """
    reset = cont = 0
    chapters = 0
    prev_max = 0
    first_after: int | None = None

    def vote() -> None:
        nonlocal reset, cont
        # **最初の章は投票しない。** どの体裁でも最初の章の条は 1 から始まるので、
        # 入れると常に「リセットする」側に 1 票入って連番の体裁を隠す。
        if chapters < 2 or first_after is None:
            return
        if first_after == 1:
            reset += 1
        elif first_after > 1:
            cont += 1

    for pg, line in seq:
        if pg in toc:
            continue
        t = line.strip()
        if RE_CHAPTER.match(t):
            vote()
            chapters += 1
            first_after = None
            continue
        m = RE_ARTICLE.match(t)
        if not m or chapters == 0:
            continue
        num = str(_n(m.group(1)))
        if not num.isdigit():
            continue
        n = int(num)
        if first_after is None:
            # 直前の章の最大番号から続いているか、1 に戻ったか。
            first_after = 1 if n == 1 else (n if n == prev_max + 1 else 0)
        prev_max = max(prev_max, n)
    vote()
    return reset >= cont


def _split_prose_head(rest: str) -> tuple[str, str]:
    """`第○章` の後ろが散文なら、見出し名を空にして本文として返す。

    **行ごと捨ててはならない。** 高密度 2 段組（`nl-b5-2col-dense`）では柱が
    継続ページで**唯一の章情報源**であり、`第2章第4条(2)の算式は、…` を捨てると
    以後の条が `第2章` を失う（実測：auto-0001 b5-dense で条 TP 28 → 27、
    段落 TP 56 → 52）。ラベルは採り、散文は本文へ回すのが正しい。
    """
    return ("", rest) if _is_prose(rest) else (rest, "")


# 目次の開始マーカー（W14 T49）。`もくじ`・`目次`・`CONTENTS` の単独行。
RE_TOC_MARKER = re.compile(r"^(?:もくじ|目次|目\s*次|CONTENTS|Contents)$")
RE_ART1 = re.compile(r"^第[1１]条")
# **目次行の否定規則。** 目次は本文と同じ見出し文字列を並べるので、除外しないと
# 章・条が二重に生える（実測：章 4 → 14）。ページ単位で外すのは粗すぎる
# （目次と本文が同一ページに同居する。実測：group 文書の p3 に目次と第1章）。
# R4 は点線リーダーの空白を畳むので「見出し＋末尾のページ番号」の形で捕まえる。
# 本文の見出しが裸の数字で終わることはない。
# 段落ラベルは **印字されたままの形**で捕まえる（group(1) がラベル全体）。
# gold は文書ごとの表記をそのまま保持する：auto は半角 `(1)`、golf は全角 `（１）`、
# teikan は `１`、life は `１．`。`（N）` に正規化すると全段落の引用が外れる
# （実測：段落パス完全一致 0.1263）。字形は逐語で持つ。
RE_PARA_CIRCLED = re.compile(rf"^([{CIRCLED}])[　 ]*(.*)$")
RE_PARA_PAREN_W = re.compile(r"^(（[0-9０-９]+）)[　 ]*(.*)$")
RE_PARA_PAREN_H = re.compile(r"^(\([0-9０-９]+\))[　 ]*(.*)$")
RE_PARA_DOT = re.compile(r"^([0-9０-９]+[．.])[　 ]*(.*)$")
# **空白を必須にしてはならない。** teikan の項は `２事故その他やむを得ない事由によって…`
# の形で、番号と本文の間に空白が無い（組版で字間を詰めている）。空白必須の版では
# 1 件も当たらず、**teikan の gold 段落 119 件が丸ごと落ちていた**（段落パス 0.000）。
# 数字は 1〜2 桁に限り、直後に数字が続く場合は除く（`２０２６年…` を段落にしない）。
RE_PARA_BARE = re.compile(r"^([0-9０-９]{1,2})(?![0-9０-９])[　 ]*(\S.*)$")
# 見出しの題名に句読点は現れない（gold の条見出し 1,222 件すべてで 0 件・最長 26 字）。
# 逆に条ラベルと本文が同一行に刷られる体裁（group）では、ラベルの直後が本文である。
# **この 1 文字で「題名」と「本文」を分けられる。** 長さの閾値は要らない。
SENTENCE_MARKS = "。、"

# **参照除外の否定規則。** 行頭が条番号でも、直後がこれらなら見出しではない。
# 実文書から採った言い回し（「…の規定により」「…および…」「…から…まで」）。
# **W17-B 試行 2：段落・号の見出しに対する参照の否定。** 本文の折り返しで参照が行頭に来ると
# `(1)の書類に事実と異なる記載をし…` が新しい項 `(1)` を開き、同じ引用の段落が gold より多くなる
# （成果物の段落の誤りで最大の型「同一引用の超過」66 件の一因）。**番号の直後が助詞で始まる
# 段落見出しの形の行は ALL で 64 行、64 行すべてが gold の段落・号の頭ではない。**
# `REF_SUFFIX` をそのまま使うと、`②第1項の…` のように参照から書き始まる本物の項 34 件を落とす。
RE_PARA_REF_TAIL = re.compile(r"^(?:の|に|を|が|と|から|まで|および|または|、)")
REF_SUFFIX = re.compile(
    r"^(?:の規定|に定め|に規定|および|又は|または|、|から|まで|の定め|に掲げ|による|"
    r"に基づ|の適用|第[0-9０-９]+項|の場合|とあるのは|に準じ|を準用|ただし|の規定中)"
)


def _after_paren_title(rest: str) -> str:
    """`（題名）` で始まる文字列の、**対応する閉じ括弧より後ろ**を返す。

    括弧で始まらない、または閉じ括弧が見つからない場合は空文字を返す
    （＝「括弧見出しの後ろ」という判定対象ではない）。

    入れ子と全角半角の混在に耐えるよう深さを数える。約款の条見出しには
    `第6条（保険金の請求（死亡の場合））` のような入れ子が現れるため、
    最初に出会った `）` で切ってはならない。
    """
    if not rest.startswith(("（", "(")):
        return ""
    depth = 0
    for i, ch in enumerate(rest):
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth -= 1
            if depth == 0:
                return rest[i + 1 :].strip()
    return ""


PARA_STYLES = (
    ("circled", RE_PARA_CIRCLED),
    ("paren_w", RE_PARA_PAREN_W),
    ("paren_h", RE_PARA_PAREN_H),
    ("dot", RE_PARA_DOT),
    ("bare", RE_PARA_BARE),
)
DEPTH = [
    "part",
    "rider",
    "appendix",
    "appendix_section",
    "chapter",
    "section",
    "article",
    "paragraph",
    # **`item` は項の下の番号付き細分**（gold の実測 55 件）。
    # 当初の計画では 9 種目として挙げていたが未実装だった。
    # group の引用は `第1章 第5条 第5条 1．` で、条ラベルの重複は
    # 無番号第一段落（§A1）が担うので、item 自身は 1 段深いだけである。
    "item",
]
ARTICLE_KIND = "article"
PARAGRAPH_KIND = "paragraph"
ITEM_KIND = "item"


def _n(s: str) -> int:
    return int(s.translate(Z2H))


def canonical_citation(c: str) -> str:
    """引用を比較可能な正規形にする。

    数字の全角/半角は**組版の差**であって別の条ではない（gold は文書により
    `第１条` と `第1条` が混在する）。一方で `（1）` と `(1)` の括弧の差は
    段落ラベルの流儀を区別する情報なので**潰さない**。
    """
    return re.sub(r"[　 ]+", " ", c.translate(Z2H)).strip()


@dataclass
class Node:
    node_id: str
    kind: str
    label: str = ""
    heading: str = ""
    citation: str = ""
    parent_id: str | None = None
    pages: list[int] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    # 見出しとして開いた元の行（`heading_allow` と同じ strip 済みの文字列・W16-B）
    heading_line: str = ""

    @property
    def text(self) -> str:
        return "".join(self.lines)


@dataclass
class Tree:
    doc_id: str
    nodes: dict[str, Node] = field(default_factory=dict)
    roots: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)  # 見出しに見えたが認めなかった行
    resyncs: list[str] = field(default_factory=list)  # 番号が飛んだが受け入れた箇所

    def add(self, node: Node) -> Node:
        self.nodes[node.node_id] = node
        if node.parent_id is None:
            self.roots.append(node.node_id)
        else:
            self.nodes[node.parent_id].children.append(node.node_id)
        return node

    def of_kind(self, kind: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.kind == kind]

    def number_violations(self) -> list[str]:
        """同じ親・同じ種別のもとで番号が単調増加していないものを挙げる。

        **★訂正（2026-09-25・D-15 の実装）。** 元は「番号が減ったらすべて違反」としており、
        **正当なリセットを違反として数えていた。**

        番号のリセットは「**親境界が開いた直後のみ**」とする。
        章が特約ごとに 1 から始まる、項が条ごとに 1 から始まる、というのは
        約款の正しい体裁であって違反ではない。

        **検出器の誤りは gold を通すことで露見した。** 同じ検出器を gold の
        `elements.jsonl` に当てると、**gold 自身が 224 回引っかかった**（ALL 39）：

            appendix 8  chapter 23  article 11  paragraph 182

        中身は `chapter 第1章: 5 → 1` のような正当なリセットである。
        **「→ 1 への減少はリセットであって違反ではない」という 1 行を入れると
        gold 側の件数は 224 → 16 に落ちる。** 残る 16（article 11・chapter 3・paragraph 2）が
        印刷面に実在する飛び・重複であり、§1.10 により**直さず記録する**対象である。

        > **教訓：指標の検出器は gold に当てて校正する。**
        > gold が引っかかるなら、それは gold の誤りではなく検出器の誤りである。
        """
        bad = []
        groups: dict[tuple[str | None, str], list[Node]] = {}
        for n in self.nodes.values():
            groups.setdefault((n.parent_id, n.kind), []).append(n)
        for (_, kind), ns in groups.items():
            prev = 0
            for n in ns:
                # **無番号第一段落のラベルは連番ではない（W11 T30）。**
                # group 系の gold は条の直下の無番号段落に**条ラベルを再掲する**
                # （`第1章 第5条 第5条 1．`）。我々もそれに合わせて label に `第3条` を
                # 入れているので、素朴に数字を拾うと **条番号が項の連番として読まれる**：
                #     paragraph 第1章 第3条 ②: 3 → 2   ← prev=3 は `第3条` から来ている
                # **`prev` が毎回その条の番号と一致していたのが手掛かりだった。**
                # 実測（ALL 39）：この 1 行で我々の違反 112 → 28、gold 自身 16 → 5。
                # **条ノード自身の連番検査は殺さない。** 除外は「条ラベルの再掲」に限る
                # ので、`kind != "article"` の系列だけに適用する。
                # （最初の実装は種別を問わず除外したため、条の番号の逆行を
                #  一切検査しなくなり `tests/test_w10_metrics.py` が落ちた。
                #  **落ちたテストは現実の反例だった。**）
                if kind != ARTICLE_KIND and RE_ART_LABEL_ONLY.match(n.label or ""):
                    continue
                m = re.search(r"([0-9]+)", n.label)
                if not m:
                    if kind == "paragraph" and n.label in CIRCLED:
                        cur = CIRCLED.index(n.label) + 1
                    else:
                        continue
                else:
                    cur = int(m.group(1))
                # **`→ 1` はリセットであって違反ではない**（§5.6(5)。上の docstring）。
                if cur <= prev and cur != 1:
                    bad.append(f"{kind} {n.citation}: {prev} → {cur}")
                prev = cur
        return bad


class Builder:
    """行を順に食わせて木を建てる。状態は「いま開いている祖先」だけ。"""

    def __init__(
        self,
        doc_id: str,
        heading_allow: set[tuple[int, str]] | None = None,
        region_lines: set[tuple[int, str]] | None = None,
        grammar: str = "yakkan",
    ) -> None:
        # **体裁ごとの見出し文法**（T11/T12）。`yakkan` 以外は `_feed_jyusetsu` へ。
        self.grammar = grammar
        self._expect_item = 1
        # 合成テストは `build` を経ずに `feed` を直接呼ぶので既定値を置く。
        self._uses_badges = False
        # **表・図領域の内側にある行（`item` の抑止だけに使う）。**
        # 領域検出器は表と図を分離できないので、**本文を落とす用途には使えない**
        # （`build_tree_for_doc` の docstring に退行の実測値）。
        # ただし「この行は表の中にある」という弱い信号としてなら、
        # **損失を `item` 指標だけに限定して**使える。行は必ず本文として残す。
        self.region_lines = region_lines or set()
        # **大域デコード（T9）の採用集合を受け取る口。** `None` なら従来の規則だけで動く。
        # 渡された場合、構造見出しの形をしていても採用集合に無い行は**本文として扱う**。
        # 却下ではなく本文化であることが重要で、却下すると段落が失われる。
        self.heading_allow = heading_allow
        self.t = Tree(doc_id)
        self.cur: dict[str, Node | None] = dict.fromkeys(DEPTH)
        self.seq = 0
        self.expect_article = 1
        self._jy_chapter: int | None = None  # 重要事項説明書の直前の章番号（F17）
        # **章が条番号をリセットするかは体裁によって逆である**（U-5）：
        #   golf / auto   第2章 条1,2,3 ／ 第3章 条1,2,3   ← 章ごとにリセット
        #   teikan        第1章 条1〜5   ／ 第2章 条6〜9    ← 章をまたいで連番
        # 既定は「リセットする」だが、`build` の前処理で**印字された番号列から
        # 推定して上書きする**（gold は見ない・§1.4）。
        self.chapter_resets = True
        # **段落ラベルの流儀は「親の種別ごと」に一貫する。文書単位ではない。**
        # gold を全 41 文書で数えて分かった：
        #   auto  条の下 `(1)` 76 件 ／ 別表節の下 `1.` 3 件
        #   group 条の下 `①` 58 件 ／ 別表節の下 `1.` 5 件
        #   life  条の下 `1.` 54 件 ／ 別表節の下 `1.` 3 件
        #   teikan 条の下 裸の数字 のみ
        # **どの体裁でも 2 つの流儀が共存する。** 文書単位で 1 つに固定すると、
        # 先に現れた方が後を全部拒否する。teikan では条中の列挙 `（１）取締役会` が
        # 先に当たって `paren_w` にラッチし、真の流儀である裸の数字を以後すべて拒否した。
        # 規則そのもの（混在を許さない）は正しく、**誤っていたのはスコープである。**
        self.para_style: dict[str, str] = {}
        self._rider_ok = False  # 先読みで確定した特約見出しかどうか
        self._seen: set[tuple[str, str, str]] = set()

    @staticmethod
    def _structural(s: str) -> bool:
        """編・章・節・条の見出しの形をしているか。**採用集合の照合対象を絞るため。**

        別表・特約・附則は大域デコードの番号制約の対象外（根になる）なので含めない。
        """
        return bool(
            RE_PART.match(s) or RE_CHAPTER.match(s) or RE_SECTION.match(s) or RE_ARTICLE.match(s)
        )

    def _dup(self, key: tuple[str, str]) -> bool:
        """同じ (種別, ラベル) を既に開いていれば True。柱の再出現を弾く。

        **判定は「いま開いている親」のもとで行う（W3 A5）。** 文書全体で 1 回しか
        許さない実装だと、編をまたいで章番号が振り直される体裁が壊れる。
        `life` の gold は 第1編 に 章1〜6、第2編 に 章1〜3 を置くが、文書全体で
        重複を弾いたため **第2編 の 章2・章3 が開かず、配下の全条が
        `第2編 第1章` に積み上がった**（条 recall 0.136。抽出した 22 条の引用が
        同じ 3 つの繰り返しになる形で現れる）。
        柱の再出現は同じ親のもとで起きるので、親で区切っても弾ける。
        """
        scope = ""
        if key[0] == "chapter":
            p = self.cur["part"]
            scope = p.node_id if p else ""
        elif key[0] == "section":
            c = self.cur["chapter"]
            scope = c.node_id if c else ""
        full = (scope, *key)
        if full in self._seen:
            return True
        self._seen.add(full)
        return False

    def _open(self, kind: str, label: str, heading: str, page: int, parent: Node | None) -> Node:
        self.seq += 1
        n = Node(
            node_id=f"{kind[:3]}{self.seq}",
            kind=kind,
            label=label,
            heading=heading,
            parent_id=parent.node_id if parent else None,
            pages=[page],
            heading_line=getattr(self, "_cur_line", ""),
        )
        path: list[str] = []
        p: Node | None = n
        while p is not None:
            if p.label:
                path.append(p.label)
            p = self.t.nodes.get(p.parent_id) if p.parent_id else None
        n.citation = " ".join(reversed(path))
        self.t.add(n)
        for k in DEPTH[DEPTH.index(kind) + 1 :]:
            self.cur[k] = None
        self.cur[kind] = n
        return n

    def _attach(self, line: str, page: int) -> None:
        for k in reversed(DEPTH):
            n = self.cur.get(k)
            if n is None:
                continue
            # **無番号の第一段落（gold の慣習・全 41 文書で確認）。**
            # 条の本文は `第４条（公告方法）` の次行から始まり、最初の項には番号が
            # 印字されない（2 番目が `２` なので、最初は暗黙の 1 である）。
            # gold はこれを **label が空の段落ノード**として持ち、引用は条の引用と同一。
            # 実測：空ラベル段落は PILOT の 10 文書すべてに存在し、合計 130 件超。
            # `_open` は空ラベルを引用パスに足さないので、これだけで引用が一致する。
            if k == ARTICLE_KIND and not n.children and not n.lines:
                p = self._open("paragraph", "", "", page, n)
                p.lines.append(line)
                return
            n.lines.append(line)
            if page not in n.pages:
                n.pages.append(page)
            return

    def _feed_jyusetsu(self, line: str, page: int, toc_page: bool, furniture: bool = False) -> None:
        """重要事項説明書の文法（T11/T12）。**約款の経路には一切触れない。**

        約款経路は枝番・附則・特約の番号リセットまで作り込まれており、共通化すると
        両方が壊れる。ここは別の言語だと割り切って独立に書く。

        階層は `1` → `(1)` → `①` → 散文。**`article` と `item` は同じ丸数字**なので、
        区別できるのは番号の単調性だけである：
        期待している条番号と一致すれば条、そうでなく 1 に戻っていれば条の下の細分。
        """
        from .grammars import JYUSETSU, load_grammar

        s = line.strip()
        if not s:
            return
        g = load_grammar(JYUSETSU)
        # 目次行。`もくじ` は本文と同じ見出しを並べ、末尾にページ番号を置く。
        if is_toc_line(s, g.toc_entry):
            self.t.rejected.append(f"p{page} 目次行: {s[:30]}")
            return
        # **柱（running head）の章見出しは開かない（W9）。**
        # W8 で約款経路に入れた判定が**この経路には届いていなかった**
        # （`feed` の文法分岐より後ろに書いたため）。実測：`jyusetsu-0002` の p6 は
        #   0: 3契約締結後におけるご注意事項（柱・上端帯 y0=18.7）
        #   1: (4)保険金をお支払いできない主な場合   ← gold では章 2 の配下
        #  19: 3契約締結後におけるご注意事項（本物・y0=407.4）
        # という並びで、柱で章 3 を開くと節 (4) 以下が章 3 の配下に落ちる。
        # **決定点が 2 箇所ある設計では、片方だけ直すと直したつもりになる**
        # （今回は同じ波の中で 2 度踏んだ）。
        if furniture and (g.chapter.match(s) or g.section.match(s)):
            self.t.rejected.append(f"p{page} 柱の上位見出し: {s[:30]}")
            return

        # 章：裸の数字 ＋ 題名。**句読点を含む行は本文である**（A1 と同じ 1 文字判定）。
        m = g.chapter.match(s)
        if m and not any(c in s for c in SENTENCE_MARKS) and len(s) <= 30:
            label = m.group(1)
            # **章の番号は直前の章から 1 か 2 だけ進む（F17・D-026）。** 表の行 `３０歳未満４，３００円…` は
            # 行頭が裸の数字で句読点を持たないので章の形に一致し、章 `３０` を開いて以降の節と条を吸っていた。
            # 2 まで許すのは、章見出しを 1 つ取りこぼしても後続の章が開けるように
            num = int(label.translate(_FW_DIGITS))
            last = self._jy_chapter
            # 題名に数字があれば表の行である（`3日まで3,200円2,600円…`）。本物の章の題名に数字は無い
            if (
                self._dup(("chapter", label))
                or (last is not None and not 1 <= num - last <= 2)
                or (last is None and num > 2)
                or re.search(r"[0-9０-９]", m.group(2))
            ):
                self._attach(line, page)
                return
            self._jy_chapter = num
            self._open("chapter", label, m.group(2), page, None)
            self.expect_article = 1
            self._expect_item = 1
            return

        m = g.section.match(s)
        if m and not any(c in s for c in SENTENCE_MARKS) and len(s) <= 40:
            label = m.group(1)
            if self.cur["chapter"] is None or self._dup(("section", label)):
                self._attach(line, page)
                return
            self._open("section", label, m.group(2), page, self.cur["chapter"])
            self.expect_article = 1
            self._expect_item = 1
            return

        m = g.article.match(s)
        if m and not toc_page:
            num = CIRCLED.index(m.group(1)) + 1
            parent = self.cur["section"] or self.cur["chapter"]
            art = self.cur["article"]
            # **標識の無い丸数字行は条ではない（W10）。** `JYUSETSU_BADGES` 参照。
            # 番号の単調性だけでは、条の直下の号の走査が条番号の期待値と衝突する。
            has_badge = any(b in s for b in JYUSETSU_BADGES)
            if self._uses_badges and not has_badge and art is not None:
                node = self._open("item", m.group(1), "", page, art)
                node.lines.append(m.group(2))
                self._expect_item = num + 1
                return
            if num == self.expect_article or art is None:
                if parent is None:
                    self._attach(line, page)
                    return
                self._open("article", m.group(1), m.group(2), page, parent)
                self.expect_article = num + 1
                self._expect_item = 1
                return
            # 番号が条の期待値と合わない。1 に戻っていれば条の下の細分である。
            if num == self._expect_item:
                node = self._open("item", m.group(1), "", page, art)
                node.lines.append(m.group(2))
                self._expect_item = num + 1
                return
            self.t.resyncs.append(f"p{page} 丸数字 {self.expect_article}→{num}")
            self._open("article", m.group(1), m.group(2), page, parent)
            self.expect_article = num + 1
            self._expect_item = 1
            return

        # 散文。条が開いていれば無番号の段落になる（`_attach` が作る）。
        self._attach(line, page)

    def feed(self, line: str, page: int, toc_page: bool = False, furniture: bool = False) -> None:
        if self.grammar != "yakkan":
            self._feed_jyusetsu(line, page, toc_page, furniture)
            return
        s = line.strip()
        if not s:
            return
        self._cur_line = s
        # **上位見出し（編・章・節・特約・別表）の目次由来の重複を位置で弾く。**
        # 目次はこれらを列挙するので、木に入れると以降の祖先ラベルが全部ずれる
        # （実測：life の本文が `第2編 第1章` ではなく `第3編 第6章` になった。
        #  golf の段落が `第2章 第1条` ではなく `ゴルフ用具新価特約 第1条` に付いた）。
        #
        # 目次と本文は同一ページに同居するので、ページごと抑止すると本文の章見出しも
        # 落ちる。そのため**条・段落は抑止せず、上位見出しだけ**を抑止する。
        #
        # **出現回数による判定も試したが最悪だった**（目次項目は 2 回・柱は 3 回以上、
        # という仮定で「2 回なら後を採る」とした結果：条 0.630 → 0.457、
        # 段落 0.360 → 0.104）。仮定が成り立たない文書が多い。
        #
        # 採用するのはページ単位の抑止である。条 recall は 0.688 → 0.630 と下がるが、
        # **段落パス完全一致（構造の主指標）が 0.130 → 0.360 と
        # 2.8 倍になる**ので、こちらを採る。上位見出しが 1 つ余計に入ると
        # 以降の全段落の祖先ラベルがずれるため、影響が段落側に集中する。
        # **★ 棄却した案（W14 T50 第 2 案）：ページ内で 2 回以上現れる上位見出しを
        # 抑止から免除する。** 動機は正しかった（抑止範囲内・上位見出しの形・ページ内
        # 2 回以上に当たる 25 行は **25 行すべてが gold の見出し**で非 gold は 0 件）。
        # 組み立て側とデコーダ側の両方に入れると `chapter` recall 0.9733 → **0.9893**、
        # 条 recall 0.9785 → 0.9794、条 recall=1.0 の文書 26 → 27 と動く。
        #
        # **しかし条 precision が 0.9913 → 0.9718 と宣言線（≥ 0.9782）を割るので棄却した。**
        # 原因は「構成ページ（裸の見出し列）でも見出しがページ内で重複する」ことである
        # — `golf-0001-wide` p3 は `第１章用語の定義`・`第４章基本条項` が並ぶ純粋な
        # 構成ページで、そこを免除すると配下の目次項目が条として生え、
        # **偽の条が 6 件**出た（`第1条`〜`第3条` が章の親を持たずに立つ）。
        #
        # **ページ内重複だけでは「柱＋本物」と「構成ページの重複」を分離できない。**
        # 句点率・長行率でも分離しない（殺す側 0.027〜0.119 に対し無害側は中央値 0.117・
        # 最大 0.457 で**逆向き**）。再試行するなら別の特徴量を先に見つけること。
        if toc_page and self._upper_key(s):
            self.t.rejected.append(f"p{page} 目次ブロックの上位見出し: {s[:30]}")
            return
        # **柱（running head）の上位見出しは開かない（W8 第 2 案）。**
        # 同じ上位見出しがページ内に 2 回現れ、一方がページ先頭にあるなら、
        # **先頭側が柱で、後ろ側が本物の見出しである。** teikan の p3 は
        #   0: 第２章社員（柱）/ 1: 第４条（公告方法）/ … / 25: 第２章社員（本物）
        # という並びで、先着を採ると gold の `第1章 第4/5条` が `第2章` 配下になる。
        # 候補スコア層の「最初の出現は本物、2 回目以降は柱」という既定は、
        # **柱が本文見出しより前に刷られる版面で逆になる。**
        if furniture and self._upper_key(s):
            self.t.rejected.append(f"p{page} 柱の上位見出し: {s[:30]}")
            return
        # **見出し行は句読点を含まない。** 約款の本文は条項参照で飽和しているので、
        # `第２編第１章第２条に、お支払いできない場合は…` のような**本文の 1 行が
        # 行頭から編・章・条の形を持つ**。`RE_PART` などは行頭一致で後続を題名として
        # 飲み込むため、これを見出しとして採用してしまう。
        # 実測：life 文書でこの 1 行が `第２編` を p5 で開き、第1編配下の第3〜6章が
        # 第2編に付き替わっていた（条 recall 0.136。抽出した 22 条の引用が
        # `第2編 第1章 第1条` の繰り返しになる形で現れる）。
        # 逆対照：本物の見出し `第２編　普通保険約款` `第1条（責任開始期）` は
        # 句読点を含まないので落ちない。
        # **撤回した規則：** `self._upper_key(s) and ("。" in s or "、" in s)` で
        # 上位見出しを落とす案を試したが、**集計は悪化した**
        # （条 0.6302 → 0.6109、teikan は 0.694 → 0.556）。本文の 1 行が行頭から
        # 編・章の形を持つ例（life p5）は確かに存在するが、それを落としても life は
        # 0.136 で動かず、代わりに句読点を含む正当な見出し（teikan の附則見出しなど）を
        # 失った。**再試行しないこと。**
        if is_toc_line(s):
            self.t.rejected.append(f"p{page} 目次行: {s[:34]}")
            return

        # **大域デコードの採用集合による抑止（T9）。**
        # 採用集合が渡されているときは、構造見出しの形をしていても集合に無い行を
        # 本文として扱う。これが逐次規則に対する大域最適化の効き口である。
        # **本文化するだけで、行を捨てない。** 捨てると段落が失われる。
        if (
            self.heading_allow is not None
            and self._structural(s)
            and (page, s) not in self.heading_allow
        ):
            self.t.rejected.append(f"p{page} 大域デコードが非採用: {s[:30]}")
            self._attach(line, page)
            return

        m = RE_APPENDIX.match(s)
        if m:
            label = m.group(1)
            # **参照除外を `別表`/`付表` にも当てる（W13 T44）。**
            # この分岐は `RE_CHAPTER`・`RE_SECTION`・`RE_PART`（`_split_prose_head` を通す）と
            # `RE_RIDER`（句読点を見る）と違い、**否定規則を 1 つも通していなかった。**
            # そのため本文中の参照が容器を開いていた：
            #
            #     付表1に定める短期率により計算した既経過期間      ← auto-0001-b5 p12（gold の付表1 は p16）
            #     別表１に掲げる状態に該当されたときです。          ← life-0001-b5
            #     別表2に掲げる物は携行品に当たらないため、…      ← travel-0002
            #
            # **偽の容器 1 件の代償は配下の全部である。** auto-0001-b5 ではこの 1 行のせいで
            # `第5章 第3節`〜`第6節` が開けず、配下の段落が章・節を失った（W12 T37 の「深さが違う」34 件）。
            #
            # **数えてから入れた**（規律 8）。ALL 39 で `別表N`/`付表N` 始まりの行のうち
            # `REF_SUFFIX` に一致するのは **3 行で、3 行すべてが gold の見出しではない。**
            # gold の見出し 136 行は 1 件も一致しない。**完全に分離する。**
            if REF_SUFFIX.match(m.group(2) or "") or _is_prose(m.group(2) or ""):
                self.t.rejected.append(f"p{page} 参照（別表/付表）: {s[:34]}")
                self._attach(line, page)
                return
            if self._dup(("appendix", label)):
                self._attach(line, page)
                return
            self._open("appendix", label, m.group(2), page, None)
            self.expect_article = 1
            return

        m = RE_SUPPL.match(s)
        if m and len(s) <= 12:
            if self._dup(("appendix", "附則")):
                self._attach(line, page)
                return
            self.cur["chapter"] = None
            self.cur["rider"] = None
            self._open("appendix", "附則", m.group(2), page, None)
            self.expect_article = 1
            return

        if self.cur["appendix"] is not None and self.cur["chapter"] is None:
            m = RE_APP_SEC.match(s)
            # **空白を任意にしたぶん、否定規則を明示する（W10）。** この分岐は
            # `RE_PART` / `RE_CHAPTER` / `RE_SECTION` / `RE_ARTICLE` より**前**に
            # 置かれているので、空白必須を外すと `第2章…` を別表の節として食う。
            # 番号の直後に来る構造接尾辞をすべて除外する。
            # **値で終わる行は節ではない（W11 T29）。** `RE_APP_SEC_VALUE_TAIL` 参照。
            if m and not RE_APP_SEC_EXCLUDE.match(s) and not RE_APP_SEC_VALUE_TAIL.search(s):
                self._open(
                    "appendix_section",
                    f"第{_n(m.group(1))}",
                    m.group(2),
                    page,
                    self.cur["appendix"],
                )
                return

        m = RE_PART.match(s)
        # **W16-C：残りが散文なら編を開かない。** しおり本文の参照
        # `第2編第2章第2条をご覧ください。` が `第2編` を開き、第1編の第4〜6章が
        # 第2編の下に付け替わっていた（life-0002）。ALL で `第N編`＋散文の行は 4 行、
        # 4 行すべてが本文中の参照。gold の編見出し 12 件に句点を含むものは 0。
        # 柱の連結 `第２編普通保険約款第２章…` は句点を含まないので影響しない。
        if m and _is_prose(m.group(2) or ""):
            self.t.rejected.append(f"p{page} 参照（編）: {s[:34]}")
            self._attach(line, page)
            return
        if m:
            label = f"第{_n(m.group(1))}編"
            if self._dup(("part", label)):
                self._attach(line, page)
                return
            head, body = _split_prose_head(m.group(2))
            self._open("part", label, head, page, None)
            self.expect_article = 1
            if body:
                self._attach(body, page)
            return

        m = RE_RIDER.match(s)
        # **特約名に句読点は現れない。** 名前であって文ではないので、
        # `、`・`。` を含む一致は本文の一部である（上の `RE_PROSE_REF` の注）。
        if m and self._rider_ok and not any(c in m.group(1) for c in "、。"):
            name = m.group(1)
            # 同じ特約名が連続で現れるのは柱（running head）。木を二重に生やさない。
            if self._dup(("rider", name)):
                self._attach(line, page)
                return
            # 特約に入ると条番号は 1 から振り直される。**再同期ではなく正常な境界**。
            self.cur["appendix"] = None
            self.cur["chapter"] = None
            self.cur["section"] = None
            # **特約は編の配下に置く（W9）。** 親を `None` に固定していたため、
            # 編を持つ体裁で編ラベルが落ちていた。gold（`life-0002`）は
            # `第3編 入院一時金特約 第1条` で、出力は `入院一時金特約 第1条` だった
            # （この 1 点で life-0002 の条 8 件・全 25 件の 32% が外れる）。
            # 編を持たない体裁（golf・auto）では `cur["part"]` が `None` なので
            # 従来と同じ `ゴルフ用具新価特約 第1条` になる。
            # **ただし特約の編に限る（F17・D-026）。** v7 の life には `第2編 普通保険約款` の後に特約を直に並べる体裁があり、
            # gold は特約を根に置く（`保険料払込免除特約 第1条`）。編の題名に `特約` を含むとき（`第3編 特約条項`）だけ配下にする
            part = self.cur["part"]
            parent = part if part is not None and "特約" in (part.heading or "") else None
            self._open("rider", name, "", page, parent)
            self.expect_article = 1
            return

        m = RE_CHAPTER.match(s)
        if m:
            label = f"第{_n(m.group(1))}章"
            # 柱で同じ章名が再出現しても新しい章を生やさない。
            if self._dup(("chapter", label)):
                self._attach(line, page)
                return
            # 章は根に置く。gold の citation が `第1章 第1条` であって
            # `付帯特約 第1章 第1条` ではないので、章に入った時点で特約を閉じる。
            self.cur["appendix"] = None
            self.cur["rider"] = None
            head, body = _split_prose_head(m.group(2))
            self._open("chapter", label, head, page, self.cur["part"])
            # 章をまたいで条が連番の体裁では期待値を戻してはならない（U-5）。
            if self.chapter_resets:
                self.expect_article = 1
            if body:
                self._attach(body, page)
            return

        m = RE_SECTION.match(s)
        if m and self.cur["chapter"] is not None:
            label = f"第{_n(m.group(1))}節"
            if self._dup(("section", label)):
                self._attach(line, page)
                return
            head, body = _split_prose_head(m.group(2))
            self._open("section", label, head, page, self.cur["chapter"])
            if body:
                self._attach(body, page)
            return

        m = RE_ARTICLE.match(s)
        if m:
            rest, num, sub = m.group(3), _n(m.group(1)), m.group(2)
            # 否定規則 1：直後が参照表現なら見出しではない
            if REF_SUFFIX.match(rest):
                self.t.rejected.append(f"p{page} 参照: {s[:34]}")
                self._attach(line, page)
                return
            # **否定規則 1b：括弧見出しの「後ろ」にも参照規則を当てる（W12 T35）。**
            # 否定規則 1 は `rest` の先頭しか見ないので、`（…）` で始まる行を素通しし、
            # さらに否定規則 2 の `has_paren` が番号の不連続も免除していた。その結果
            # **行頭に来た条項参照が条見出しとして開いていた**：
            #
            #     第５条（機関）により置く取締役会は、法令に定める事項のほか、…   ← teikan 第4章 第5条: 20 → 5
            #     第2条（入院保険金および通院保険金）の保険金を支払いません。…   ← travel-0002 第2条: 7 → 2
            #
            # 本物の条見出しは**閉じ括弧で行が終わる**。判定は「閉じ括弧の後ろに
            # 本文が続くか」であり、本文中の参照の否定語彙をその尾部に当てる。
            #
            # **分布を数えてから入れた**（規律 8）。ALL 39 で `第N条（…）＋尾部` の形は
            # 411 行あり、うち尾部に句読点を含むのは 7 行。**7 行すべてが本文中の参照**で、
            # 条見出しは 1 件も含まれない（gold の条見出し 1,222 件は句読点 0 件・§5.6）。
            # 尾部に句読点が無い 404 行は目次行と折り返し本文で、ここでは触らない
            # （触ると `第1条（用語の定義）(1)の表に…` のような行の扱いが変わる）。
            tail = _after_paren_title(rest)
            if tail and (REF_SUFFIX.match(tail) or any(ch in tail for ch in "。、")):
                self.t.rejected.append(f"p{page} 参照（括弧見出しの後）: {s[:34]}")
                self._attach(line, page)
                return
            # 否定規則 2：番号が飛んでいて、かつ見出し括弧も無いなら見出しではない
            has_paren = rest.startswith(("（", "("))
            if not has_paren and num != self.expect_article and sub is None:
                self.t.rejected.append(f"p{page} 不連続かつ見出し無し: {s[:34]}")
                self._attach(line, page)
                return
            if num != self.expect_article and sub is None:
                self.t.resyncs.append(f"p{page} 条 {self.expect_article}→{num}")
            label = f"第{num}条" + (f"の{_n(sub)}" if sub else "")
            parent = self.cur["section"] or self.cur["chapter"] or self.cur["rider"]
            # **条ラベルと本文が同一行に刷られる体裁がある**（group：
            # `第5条当会社は、次の各号のいずれかに該当するときは、保険金を支払いません。`）。
            # gold はこれを「題名の無い条」＋「**条ラベルを負う第一段落**」に分ける
            # （引用は `第1章 第5条 第5条` で、条ラベルが 2 回重なる）。
            # 当初はこの重複を `item` の性質と考えていたが、実際は
            # **無番号第一段落の性質**である。
            #
            # 判定は句読点 1 文字で足りる。**gold の条見出し 1,222 件のうち句読点を
            # 含むものは 0 件**で、最長でも 26 字である。長さの閾値は要らない。
            inline_body = any(ch in rest for ch in SENTENCE_MARKS)
            art = self._open("article", label, "" if inline_body else rest, page, parent)
            if inline_body:
                p = self._open("paragraph", label, "", page, art)
                p.lines.append(rest)
            if sub is None:
                self.expect_article = num + 1
            return

        parent = (
            self.cur["article"]
            or self.cur["appendix_section"]
            or self.cur["section"]
            or self.cur["chapter"]
        )
        # **項の下の番号付き細分（`item`）。**
        # group：項の流儀は `②`（circled）で、その下に `1．`（dot）が並ぶ。
        # **流儀が項と違うことが「1 段深い」ことの信号である**（gold 実測 55 件）。
        # 条の下の流儀と一致する行は項なので、ここでは弾く。
        pa = self.cur["paragraph"]
        if (
            pa is not None
            and self.cur["article"] is not None
            and (page, s) not in self.region_lines
        ):
            art_style = self.para_style.get(ARTICLE_KIND)
            for style, rx in PARA_STYLES:
                m = rx.match(s)
                if not m:
                    continue
                if style == art_style:
                    break  # 項である。下の段落分岐に任せる
                if RE_PARA_REF_TAIL.match(m.group(2) or ""):
                    break  # 行頭に来た参照（W17-B）
                if PARAGRAPH_KIND not in self.para_style:
                    self.para_style[PARAGRAPH_KIND] = style
                elif style != self.para_style[PARAGRAPH_KIND]:
                    break
                node = self._open("item", m.group(1), "", page, pa)
                if m.group(2):
                    node.lines.append(m.group(2))
                return
        if parent is not None:
            pkind = parent.kind
            for style, rx in PARA_STYLES:
                m = rx.match(s)
                if not m:
                    continue
                # 否定規則 3：**親の種別ごとに**最初に確定した流儀以外は段落ラベルにしない。
                # `（1）` と `(1)` の混在は、片方が本文中の参照か表の見出しである。
                if RE_PARA_REF_TAIL.match(m.group(2) or ""):
                    break  # 行頭に来た参照（W17-B）。本文として直前の段落に付ける
                if pkind not in self.para_style:
                    self.para_style[pkind] = style
                elif style != self.para_style[pkind]:
                    break
                node = self._open("paragraph", m.group(1), "", page, parent)
                if m.group(2):
                    node.lines.append(m.group(2))
                return

        self._attach(line, page)

    UPPER = (RE_PART, RE_CHAPTER, RE_SECTION, RE_APPENDIX, RE_SUPPL, RE_RIDER)

    @classmethod
    def _upper_key(cls, s: str) -> str | None:
        for rx in cls.UPPER:
            m = rx.match(s)
            if m:
                return f"{rx.pattern[:12]}|{m.group(1)}"
        return None

    @staticmethod
    def _dominant_article_para_style(seq: list[tuple[int, str]], toc: set[int]) -> str | None:
        """条の下の段落ラベルの流儀を「その流儀が現れた条の数」で選ぶ。

        **件数で数えてはならない。** 1 つの条に長い列挙が 10 個並ぶと、
        3 条にしか出ない列挙が 30 条に出る項を件数で上回る。
        数えるのは**条の数**である（列挙は一部の条にしか出ない）。
        """
        from collections import defaultdict

        arts: defaultdict[str, set[int]] = defaultdict(set)
        idx = -1
        for pg, line in seq:
            s = line.strip()
            if not s or pg in toc:
                continue
            if is_toc_line(s):
                continue
            if RE_ARTICLE.match(s):
                idx += 1
                continue
            if idx < 0:  # 最初の条より前（表紙・目次・前文）は数えない
                continue
            for style, rx in PARA_STYLES:
                if rx.match(s):
                    arts[style].add(idx)
                    break
        if not arts:
            return None
        return max(arts, key=lambda k: len(arts[k]))

    def build(
        self,
        pages: dict[int, str],
        toc_pages: set[int] | None = None,
        extra_cut: dict[int, int] | None = None,
    ) -> Tree:
        toc = set(toc_pages or set()) | set(extra_cut or {})
        seq: list[tuple[int, str]] = [
            (pg, line) for pg in sorted(pages) for line in pages[pg].split("\n")
        ]
        # **上位見出しの抑止は「ページ」ではなく「目次ブロック」を単位にする（W8）。**
        # 目次と本文が同居するページがある。teikan の p2 は
        #   [柱] 第１章総則 / もくじ / 第１章総則2 …（目次 9 行）/ 附則11
        #   / 第１章総則（本文の章見出し）/ 第１条（商号）/ 本文…
        # という構造で、**ページ全体を抑止すると第1章と第1〜5条が丸ごと落ちる**
        # （実測：teikan-0001 で gold の `第1章 第1〜5条` が出力に無い）。
        # 目次行は末尾に裸のページ番号を持つ（`RE_TOC_ENTRY`）ので、
        # **そのページで最後に目次行が現れた位置**より後は本文と判断できる。
        self._toc_cut = merge_cut(toc_block_end(pages, toc_pages or set()), extra_cut)
        self._furniture = _furniture_upper_lines(self.t.doc_id, pages)
        # **標識を使うかは文書自身の証拠で決める（W10）。** 下の `_feed_jyusetsu` 参照。
        self._uses_badges = any(b in text for text in pages.values() for b in JYUSETSU_BADGES)
        # **条の下の段落の流儀は、出現の先着ではなく多数決で決める。**
        # 先着だと teikan が壊れる：条 5 の中の列挙 `（１）取締役会` が真の流儀である
        # 裸の数字より先に現れるので、以後の `２`〜 が全部拒否される。
        # 列挙（号）は一部の条にしか出ないが、項はほぼ全条に出る。
        # **したがって「その流儀が現れた条の数」で選ぶと分離する**
        # （実測・PILOT：teikan bare 36 対 paren_w 3、auto paren_h 30 対 circled 9、
        #  group circled 27 対 dot 7、golf paren_w 20 対 circled 6、life dot 17 対 paren_w 4。
        #  5 体裁すべてで gold の条下流儀と一致した）。
        dom = self._dominant_article_para_style(seq, toc)
        if dom:
            self.para_style[ARTICLE_KIND] = dom
        self.chapter_resets = _infer_chapter_resets(seq, toc)
        # **特約見出しは先読みで確定する。** 行だけを見ると `付帯特約` のような
        # 総称（gold では part であって rider ではない）と実際の特約名を区別できない。
        # 実際の特約は直後に `第1条` が来る、という文書の作りに頼る。
        ok: set[int] = set()
        for i, (_, line) in enumerate(seq):
            if not RE_RIDER.match(line.strip()):
                continue
            for _, nxt in seq[i + 1 : i + 12]:
                t = nxt.strip()
                if RE_ART1.match(t):
                    ok.add(i)
                    break
                # **先読みは最初の構造見出しで打ち切る。** 章や別の特約を跨いで
                # 第1条を見つけてしまうと、`付帯特約` のような総称（gold では part）を
                # 特約と誤認する。特約の直下に章が挟まる文書はこの系統には無い。
                if RE_CHAPTER.match(t) or RE_PART.match(t) or RE_RIDER.match(t):
                    break
        li: dict[int, int] = {}
        for i, (pg, line) in enumerate(seq):
            self._rider_ok = i in ok
            j = li.get(pg, 0)
            li[pg] = j + 1
            # 目次ブロックの内側だけ上位見出しを抑止する。
            self.feed(
                line,
                pg,
                toc_page=(pg in toc and j <= self._toc_cut.get(pg, -1)),
                furniture=(pg, j) in self._furniture,
            )
        return self.t


ITEM_UNIT_HEADS = "万億千百円年月日か個名回度割％%）)、"
"""裸番号の直後に来たら「番号は数量表現の一部」と判断する文字。

`１`＋`億円を限度とします` は号ではなく `１億円` の行分割である
（golf・auto で実測）。本文中の参照の除外と同じ種類の否定規則で、
**番号トークンの直後に何が来るかで見出しか否かを決める。**
"""


_Z2H_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _item_num(label: str) -> int | None:
    s = (label or "").strip("．.（）() 　")
    if s[:1] in CIRCLED:
        return CIRCLED.index(s[0]) + 1
    s = s.translate(_Z2H_DIGITS)
    return int(s) if s.isdigit() else None


RE_ART_LABEL_ONLY = re.compile(r"^第[0-9０-９]+条(?:の[0-9０-９]+)?$")
"""条ラベルそのもの。**番号整合性の検査ではこれを連番から除外する**（W11 T30）。

条の直下の無番号段落は、gold の流儀に合わせて**条ラベルを再掲する**
（`第1章 第5条 第5条 1．`）。これは項の連番ではないので、
番号の単調性の検査に混ぜてはならない。詳細は `Tree.number_violations`。
"""
RE_ITEM_PAREN_LABEL = re.compile(r"^[（(][0-9０-９]+[）)]$")
"""**括弧付きの番号は `item` のラベルになり得ない**（W11 T28）。

gold の `node_kind` ラベルを全数集計した（ALL 39）：

    item      丸数字 79 / 数字ドット 91 / **括弧 0**
    paragraph 括弧全角 987 / 括弧半角 795 / 空 724 / 数字ドット 354 / 丸数字 252 / 裸数字 202

**`item` 170 件に括弧付きは 1 件も無く、段落側には 1,782 件ある。**
括弧は**項（paragraph）の流儀**であって号の流儀ではない。

これが `teikan` の偽 `item` 38 件の実体である。gold の teikan は
`第2条` → 無番号 paragraph → `2` paragraph という構造で、
本文中の `（１）生命保険業` は**構造ノードではなく段落内の列挙**である
（gold に対応する `node_kind` が存在しない）。
我々は項の流儀の多数決で「裸数字」を選んだため、余った `（１）` が号に落ちていた。

**字形で決まるので文書ごとの推定が要らない。** W7 が棄却した
「`item` ラベルの流儀の文書内多数決」（閾値が存在しなかった）とは別物である。
"""


def drop_paren_items(t: Tree) -> int:
    """括弧付きラベルの `item` を**ノードごと落として親に併合する**（W11 T28）。

    **項に降格してはならない。** 最初の実装は `kind` を `paragraph` に書き換えたが、

    - ALL 39 の段落適合率が 0.9514 → **0.9393** に落ちて宣言した非回帰線を割った
    - `tests/test_a1_paragraphs.py::test_enumeration_first_does_not_win_over_paragraphs`
      が落ちた（`（１）` が項になってはいけない、と明示している）

    **落ちたテストは古い契約ではなく現実の反例だった。** gold の teikan は
    `第2条` → 無番号 paragraph → `2` paragraph であり、
    **`（１）生命保険業` に対応するノードが存在しない** — 号でも項でもなく、
    段落内の列挙である。よって正しい処理は「別の種別に付け替える」ではなく
    **「ノードを作らず本文として親に残す」**である。

    `RE_ITEM_PAREN_LABEL` の実測（gold item 170 件に括弧付きは 0 件）を参照。
    """
    n = 0
    for node_id in list(t.nodes):
        node = t.nodes[node_id]
        if node.kind != "item" or not RE_ITEM_PAREN_LABEL.match((node.label or "").strip()):
            continue
        parent = t.nodes.get(node.parent_id) if node.parent_id else None
        if parent is None:
            continue  # 親が無いものは触らない（引用が根に付くことは無いが念のため）
        # 子を持つ号は落とさない（構造を壊す）。実測では 0 件だが規則として置く。
        if node.children:
            continue
        parent.lines.append(node.label + node.text)
        parent.children.remove(node_id)
        del t.nodes[node_id]
        t.rejected.append(f"item {node.citation}: 括弧ラベルのため本文へ併合")
        n += 1
    return n


def repair_items(t: Tree, end_frac: float = 0.8) -> int:
    """表セル由来の偽 `item` を降格する（P6 の修復）。

    **`item` 適合率 0.1936 の原因は表セルの混入である**（帰属済み）。gold では
    auto の `①記名被保険者。` は `kind='cell'` / `region='table'` であり、
    同じ golf 系でも `①保険証券の被保険者欄に記載された方` は cell、
    `①事故の発生の日時…を記載した書面` は真の `item` — **gold は一貫している。**
    ところが**罫線の無い 2 段の表**（標識列＋本文列）なので矩形が 1 つも無く、
    `region_lines` による抑止（`drop_regions` 版ではなく号だけの版）が届かない。
    検出器を直すのではなく、**組版の慣行に基づく 3 つの否定規則**で落とす。

    (1) **兄弟走査の文末**。号は文法上、項の文の一部を成す列挙なので
        **各号が「。」で閉じない**（閉じるのは末尾の号だけ）。走査の
        `end_frac` 以上が「。」で終わるなら、それは文が並んだ表である。
    (2) **数量表現**（`ITEM_UNIT_HEADS`）。
    (3) **走査は 1 から始まる**。`③` から始まる走査は号の列挙ではない。

    3 規則はいずれも**再現率を 1 件も落とさない**（held-out 29 文書・ALL 39 文書の
    両方で `item` recall 不変）。閾値 `end_frac` は held-out で掃いて決めた
    （0.5〜0.8 で適合率はほぼ平坦、0.8 未満は ALL の再現率を削るので 0.8）。

    実測（ALL 39 文書・`greedy`）：`item` 適合率 **0.1936 → 0.4033**、
    再現率 0.4294 で不変。戻り値は降格したノード数。
    """
    groups: dict[str | None, list[Node]] = {}
    for n in t.nodes.values():
        if n.kind == ITEM_KIND:
            groups.setdefault(n.parent_id, []).append(n)
    drop: list[Node] = []
    for grp in groups.values():
        bodies = [" ".join(n.lines) for n in grp]
        frac = sum(1 for b in bodies if b.rstrip().endswith("。")) / len(grp)
        first = _item_num(grp[0].label)
        run_ok = first == 1
        for n, b in zip(grp, bodies, strict=True):
            lab = (n.label or "").strip()
            bare = bool(lab.strip("．. ").translate(_Z2H_DIGITS).isdigit())
            if not run_ok:
                drop.append(n)
            elif b.rstrip().endswith("。") and frac >= end_frac:
                drop.append(n)
            elif bare and b[:1] in ITEM_UNIT_HEADS:
                drop.append(n)
    for n in drop:
        # 行は親に返す（本文を失わない）。引用木からノードだけ外す。
        p = t.nodes.get(n.parent_id or "")
        if p is not None:
            p.lines.extend(n.lines)
            if n.node_id in p.children:
                p.children.remove(n.node_id)
        for cid in n.children:
            ch = t.nodes.get(cid)
            if ch is not None and p is not None:
                ch.parent_id = p.node_id
                p.children.append(cid)
        t.nodes.pop(n.node_id, None)
        t.rejected.append(f"item {n.citation}: 表セル由来として降格")
    return len(drop)


def build_tree(
    doc_id: str,
    pages: dict[int, str],
    skip_pages: set[int] | None = None,
    toc_pages: set[int] | None = None,
    heading_allow: set[tuple[int, str]] | None = None,
    region_lines: set[tuple[int, str]] | None = None,
    grammar: str = "yakkan",
    repair_item_runs: bool = True,
    extra_cut: dict[int, int] | None = None,
) -> Tree:
    """`skip_pages` は構造組み立てから外すページ（目次・表紙）。

    **目次を外すのは必須。** 目次は本文と同じ見出し文字列を並べるので、
    入れたままにすると章・条が二重に生える（実測：章 4 → 14、条の重複多数）。

    **★訂正（2026-09-25・D-16）。** 元は「E2 の決定的な目次判定は P=R=1.000 なので、
    ここに頼れる」と続けていた。**ALL 39 では成り立たない**（狭い判定 R 0.9091 / P 1.0000、
    本番経路 R 0.7727 / P 0.9444。W10）。**判定の完全性に頼る設計にしないこと** —
    だから `build_tree_for_doc` は行単位（`RE_TOC_ENTRY`）と
    ブロック単位（`toc_block_end`）の抑止を併用している。
    """
    keep = {p: t for p, t in pages.items() if p not in (skip_pages or set())}
    tree = Builder(
        doc_id, heading_allow=heading_allow, region_lines=region_lines, grammar=grammar
    ).build(keep, toc_pages=toc_pages, extra_cut=extra_cut)
    if repair_item_runs:
        repair_items(tree)
        # **括弧付きは号ではない（W11 T28）。** `RE_ITEM_PAREN_LABEL` の実測を参照。
        drop_paren_items(tree)
    return tree


def _toc_suppress_pages(doc_id: str) -> set[int]:
    """上位見出しを抑止するページ。目次ページ ＋ 裸の見出し列ページ。

    **点線リーダーの数（`pages.toc_pages`）は使わない。** あれはページに目次が
    載っているかを言うだけで、同じページに本文が同居しているかを区別しない。

    **★ 棄却した案（W14 T49）：`もくじ` マーカーのページを抑止対象に足す。**
    目次が本文ページの*途中から*始まる版面では、ページ全体が目次と判定されず、
    目次の 1 行目が本文の容器を先取りしていた：

        health-0002 p2  … 46 行目 `もくじ` / 47 行目 `第1章用語の定義`
                           → `第1章` が p2 で開き、本文 p4 の同じ見出しが `_dup` に吸収された

    gold（`toc*` 要素のページ）に対する判定は **R 0.7727 / P 0.9444** で、
    見落とし 15 ページのうちマーカー行を持つのは 6 ページである。
    **しかしマーカーだけでは足りない** — 6 ページのうち 4 ページ（`jyusetsu` 全部）は
    **マーカーの後に本物の見出し**（`1用語のご説明`）があり、ページごと抑止すると
    群 C の 1.0000 を壊す。

    そこで **「マーカーを持ち、自身は未抑止で、かつ次ページが抑止対象」** に絞る。
    ALL 39 で当たるのは **2 ページだけ**（`health-0002` p2・`life-0001-b5` p2）で、
    **どちらも gold の構造ノードが 0 件**なのでページごと抑止して安全である。
    `jyusetsu` の 4 ページは「次ページが抑止対象でない」ため除外される。

    **それでも棄却した。** 実測すると `chapter` recall が **0.9733 → 0.9679 と下がり**、
    他の指標は 1 つも動かなかった。理由は T50 第 2 案と同じである：
    p2 の偽の `第1章` を消すと、**本文 p4 の本物が「柱の上位見出し」と
    「大域デコードが非採用」で塞がれているので何も残らない。**
    偽の容器が偶然 TP を作っていたぶんだけ純減する。

    > **W14 の結論：目次抑止・柱判定・候補集合の 3 層は結合している。**
    > 1 層だけ直すと、効かない（T50 第 2 案の第 1 版）か、
    > 偶然の TP を失って悪化する（この案）。**3 層を一緒に設計し直すのが W15 の課題。**
    """
    from .toc import build_toc

    t = build_toc(doc_id)
    return set(t.toc_pages) | set(t.outline_pages)


def _region_lines(doc_id: str) -> set[tuple[int, str]]:
    """表・図領域の内側にある行を `(page, 行文字列)` で返す。

    **`item` の抑止だけに使う。** 領域検出器は線で描かれた表を図と誤認するため
    本文の除去には使えないが（`build_tree_for_doc`）、`item` の生成を抑えるだけなら
    **誤りの代償が `item` 指標に限定される**ので使える。
    行は必ず本文として残るので、段落・条の指標には影響しない。
    """
    from ..geometry import read_lines
    from ..parse.r4_local import detect_region_lines

    lines = read_lines(doc_id)
    keys = detect_region_lines(doc_id, lines)
    return {(ln.page, ln.text.strip()) for ln in lines if (ln.page, ln.line_no) in keys}


def build_tree_for_doc(
    doc_id: str,
    # **既定は `greedy`（W3 A4 で決定）。** 候補スコア層（T7）は引用木の上でも
    # 効くが、大域最適化（T9）は効かない。3 方式の実測（PILOT）：
    #   none   条R 0.6817 / 条P 0.7020 / 段落R 0.5747 / 段落P 0.6697
    #   greedy 条R 0.6817 / 条P 0.7709 / 段落R 0.5747 / 段落P 0.6862  ← 採用
    #   global 条R 0.6785 / 条P 0.7701 / 段落R 0.5735 / 段落P 0.6846
    # greedy は再現を落とさずに適合を 6.9pt 上げる。global はそこから何も足さない。
    # **W2 が採用集合の F1 で出した「global > greedy」は引用木では成立しない。**
    decode: str | None = "greedy",
    drop_regions: bool = False,
    suppress_region_items: bool = True,
    builder: str = "auto",
) -> Tree:
    """既定の経路：R4 の行を使い、表紙だけページ単位で外す。

    `builder`（本ハンズオンで追加。コーパス設定の `structure_builder`）：
      auto      … 移植元のまま。印字形から契約書の体裁を判定し、契約書なら契約書の組み立て器、そうでなければ約款の組み立て器
      yakkan    … 判定せず約款の組み立て器で組む
      contract  … 契約書の組み立て器で組む。体裁を判定できなければエラー（黙って約款の経路に回さない）

    目次は**行単位**で落とす（`RE_TOC_ENTRY`）。ページ単位で落とすと、
    目次と本文が同居するページで本文まで失う。

    **★訂正（2026-09-25・D-16）。** 元は「E2 の決定的な目次判定は P=R=1.000 なので、
    ここに頼れる」と書いていた。**ALL 39 では成り立たない** —
    狭い判定が R 0.9091 / P 1.0000、本番経路（`_toc_suppress_pages`）が
    **R 0.7727 / P 0.9444** である（W10）。
    **「ここに頼れる」という前提を置いてはならない。** 行単位で落とす設計が
    必要なのは、まさに判定が完全でないからである。

    `drop_regions` は表・図領域の内側の行を構造の入力から外す。
    **測って棄却した（既定 off）。** 動機は正しい（gold の構造ノードは表セルを
    含まないので、表のセルが項・号として木に生える。実測：偽の `item` が
    auto 48 件・teikan 15 件）。しかし**幾何の検出器が表と図を分離できない**ため、
    正当な本文まで落ちる：

        条 recall    0.6302 → 0.5338
        段落パス     0.5567 → 0.4601
        golf の条    0.931  → 0.690

    これは S0 が本文パスで観測した退行（CER 0.206 → 0.305）と**同じ機構**である。
    線で描かれた表を図と誤認する検出器は、どちらのパスでも使えない。
    表セル由来の偽 `item` は既知の残余誤差として報告する。
    """
    if builder not in ("auto", "yakkan", "contract"):
        raise ValueError(f"structure_builder が不正: {builder!r}")
    from ..parse.r4_local import read_pages_text

    # **柱の除去は使わない。** 構造パスでこそ要ると考えて `drop_repeated_headers=True`
    # を試したが悪化した（auto 文書の条 recall 0.875 → 0.400）。`detect_furniture` は
    # 「3 ページ以上で繰り返す余白帯の行」を柱とみなすので、**章見出しそのもの**を
    # 柱と誤認する。柱による章の重複は、下の「直前と同じ見出しなら無視」で処理する。
    # **連結された構造見出し行を分割する（S4 (B)）。** 柱では編と章が 1 行に
    # つながって出る（`第２編普通保険約款第２章保険契約の締結および維持`）。先頭が
    # `第２編` なので編として食われ、中の `第２章` が失われていた。行の側を直す。
    from .grammars import infer_grammar
    from .lines import split_page_text
    from .pages import cover_pages

    pg = {
        pt.page: split_page_text(pt.text)
        for pt in read_pages_text(doc_id, drop_region_lines=drop_regions)
    }

    # **契約書は別の組み立て器で組む（F3・C-006）。** 印字形（当事者の呼称の宣言と条の形）で判定し、
    # 契約書でなければ None になって以下の約款の経路をそのまま通る（約款の結果は変わらない）。
    from .contract import build_contract_tree, detect_contract_scheme

    scheme = (
        None
        if builder == "yakkan"
        else detect_contract_scheme([ln for t in pg.values() for ln in t.split("\n")])
    )
    if builder == "contract" and scheme is None:
        raise ValueError(
            f"{doc_id}: 契約書の体裁（標準・漢数字・様式型）を判定できない（structure_builder=contract）"
        )
    if scheme is not None:
        return build_contract_tree(doc_id, pg, scheme, skip_pages=cover_pages(doc_id))

    # `decode` が `"global"` / `"greedy"` のとき、採用集合を作って渡す（T9）。
    # **既定は `None`**（従来の逐次規則のみ）。既存の測定値を動かさないため。
    # **分離した目次（F16・D-024）。** 見出し列とページ番号列が別の塊で出る目次の見出し区間を、
    # W17-B と同じ共有の抑止区間として組み立て側と候補側の両方に渡す（`lines.split_toc_cut`）。
    from .lines import split_toc_cut

    split_cut = split_toc_cut(pg) or None
    allow: set[tuple[int, str]] | None = None
    if decode:
        from .decode import decode_for_doc

        r = decode_for_doc(doc_id, decode, extra_cut=split_cut)
        allow = {(c.page, c.line) for c in r.accepted}

    kw = dict(
        skip_pages=cover_pages(doc_id),
        # **上位見出しを抑止するページは、点線リーダー数ではなく目次解析から採る
        # （W3 A5）。** 点線リーダーは「このページに目次がある」しか言わないので、
        # 目次と本文が同居するページ（group の p3）で本文の章見出しまで抑止していた。
        # 結果、第1章 が開かず配下の条の引用が `第1章 第1条` ではなく `第1条` になった。
        # 目次解析は「目次の行が並ぶページ」と「番号もページ番号も持たない裸の見出し列
        # （auto の p3–4）」を分けて返すので、そちらを使う。
        # 実測（PILOT・greedy）：group の条 0.667 → 0.833、段落 0.556 → 0.758。
        toc_pages=set(_toc_suppress_pages(doc_id)),
        region_lines=_region_lines(doc_id) if suppress_region_items else None,
        grammar=infer_grammar([ln for t in pg.values() for ln in t.split("\n")]),
    )
    tree = build_tree(doc_id, pg, heading_allow=allow, extra_cut=split_cut, **kw)
    # **W17-B：本文を持たない容器は見出し列の続きである（4 経路の共有抑止）。**
    # 目次の続きのページで特約・章が開くと、本物は後で `_dup` に吸収され、配下の条が
    # 直前の容器の下に入る（golf-0001 p3 → p8、health-0001 p4）。W16-B は採用集合
    # （1 経路）だけから外して失敗した（条 R 0.9871 → 0.9690）。偽の特約は先読みで開き、
    # 本物は柱として棄却され続けたからである。
    # ここでは偽の容器の見出し区間を**目次ブロックとして**、組み立て側と候補側の
    # 両方が共有する抑止区間に加えて組み直す。目次ブロックの内側では 4 経路すべてが
    # 同じ扱い（上位見出しを本文にする）になる。
    if decode:
        cut = bodyless_container_cut(tree, pg)
        if cut:
            cut = merge_cut(cut, split_cut)
            from .decode import decode_for_doc

            r = decode_for_doc(doc_id, decode, extra_cut=cut)
            allow = {(c.page, c.line) for c in r.accepted}
            tree = build_tree(doc_id, pg, heading_allow=allow, extra_cut=cut, **kw)
    return tree


def merge_cut(base: dict[int, int], extra: dict[int, int] | None) -> dict[int, int]:
    """目次ブロックの行の上限を合成する（ページごとに大きい方）。"""
    out = dict(base)
    for pg, j in (extra or {}).items():
        out[pg] = max(out.get(pg, -1), j)
    return out


def bodyless_container_cut(tree: Tree, pages: dict[int, str]) -> dict[int, int]:
    """条を持ち、配下に本文が 1 文字も無い上位容器の見出し区間を返す（ページ → 最後の行番号）。

    区間は、容器の見出し行から、配下の条見出しのうち同じページにある最後の行まで。
    それより後は本文として残す（目次ブロックと同じくページ単位では抑止しない）。
    """

    def body(nid: str) -> int:
        n = tree.nodes[nid]
        own = len(n.text.strip()) if n.kind in ("paragraph", "item") else 0
        return own + sum(body(c) for c in n.children)

    rows = {pg: [x.strip() for x in t.split("\n")] for pg, t in pages.items()}
    out: dict[int, int] = {}
    for nid, n in tree.nodes.items():
        if n.kind not in ("rider", "chapter", "section", "part", "appendix") or not n.pages:
            continue
        arts = [tree.nodes[c] for c in n.children if tree.nodes[c].kind == ARTICLE_KIND]
        if not arts or body(nid):
            continue
        pg = n.pages[0]
        lines = rows.get(pg) or []
        idx = [j for j, r in enumerate(lines) if r == n.heading_line]
        if not idx:
            continue
        last = idx[0]
        for a in arts:
            if a.pages and a.pages[0] == pg:
                hit = [j for j, r in enumerate(lines) if r == a.heading_line and j > idx[0]]
                if hit:
                    last = max(last, hit[0])
        out[pg] = max(out.get(pg, -1), last)
    return out
