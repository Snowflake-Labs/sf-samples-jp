"""P6 — 意味層（参照・脚注・定義語・列挙）を予測木から導く（V4）。

W14 までの `out/*.json` は `refs` / `footnotes` / `enumerations` が空配列で、
`term_uses` はキーも無かった。参照解決は
採点側（`eval/metrics_structure.resolve_refs`）にしか無く、成果物に出ていなかった。

**入力は予測木（と予測経路のページテキスト）だけ。gold を読まない。**
すべての出力は引用パスで表す（成果物の主語は引用である）。
"""

from __future__ import annotations

import re
import unicodedata

from .tree import Tree, canonical_citation

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")


def _flat(s: str) -> str:
    return "".join(unicodedata.normalize("NFKC", s or "").split())


def _ancestor(tree: Tree, n, kinds: tuple[str, ...]):
    cur = n
    for _ in range(10):
        par = tree.nodes.get(cur.parent_id) if cur.parent_id else None
        if par is None:
            return None
        if par.kind in kinds:
            return par
        cur = par
    return None


# ---------------------------------------------------------------- 参照

# 直後が助詞・句読点のときだけ参照とみなす（W19 N2a）。`（２）監査役…` は列挙の見出しで参照ではない
REF_FOLLOW = r"(?=[のにをはがでと、。，,もやへおま又若及並]|$)"
RE_REF_PARA = re.compile(r"[（(]([0-9０-９]{1,2})[）)]" + REF_FOLLOW)
RE_REF_KOU = re.compile(r"第([0-9０-９]{1,2})項(?:第([0-9０-９]{1,2})号)?")
RE_REF_APPENDIX = re.compile(
    r"((?:別表|付表)[0-9０-９]{1,2})(?:第([0-9０-９]{1,2})(?![条章項号表区]))?"
)
RE_REF_CHAPTER = re.compile(r"第([0-9０-９]{1,2})章")
RE_REF_PART = re.compile(r"第([0-9０-９]{1,2})編")
# `５．の貸付` のような `N．` 形の項・号への参照（W19 N2c）。小数（`１．５倍`）は除く
RE_REF_DOT = re.compile(r"(?<![0-9０-９.．第])([0-9０-９]{1,2})[．.](?![0-9０-９])" + REF_FOLLOW)
RE_REF_PATH = re.compile(
    r"(?:第(?P<part>[0-9０-９]{1,2})編)?"
    r"(?:第(?P<ch>[0-9０-９]{1,2})章)?"
    r"(?:第(?P<sec>[0-9０-９]{1,2})節)?"
    r"第(?P<art>[0-9０-９]{1,3})条(?:の(?P<sub>[0-9０-９]+))?"
    # 題名の括弧（`（告知義務）`）。**数字だけの括弧は題名ではなく項番号**なので食わない（W18 M1）
    r"(?:[（(](?![0-9０-９]{1,2}[）)])[^）)]{1,30}[）)])?"
    r"(?:[（(](?P<para>[0-9０-９]{1,2})[）)]|第(?P<kou>[0-9０-９]{1,2})項|(?P<dot>[0-9０-９]{1,2})[．.](?![0-9０-９]))?"
    r"(?:第(?P<gou>[0-9０-９]{1,2})号)?"
)
"""複合参照。名前付きの群：編・章・節（W19 N1）・条・条の枝番・項（括弧）・項（第N項）・号。

W18（V9）で、題名の括弧が項番号 `（２）` を食べて条に解決していた欠陥（dev FP 116 件）を直し、
`第N項` / `第N号` / `第N編` を足した。
"""


RE_HEADING_LINE = re.compile(
    r"^(?:第[0-9０-９]{1,3}(?:編|章|節|条(?:の[0-9０-９]+)?)|(?:別表|付表)[0-9０-９]{1,2})"
    r"(?![にのをはがでとへやもまからより、。，．.（(0-9０-９第])"
)
"""段落に取り込まれた見出し行（`第3章保険料の払込み`・`第4条備考`・`別表１後遺障害の区分…`）。

R4 の段落は、次の章・別表・備考の見出し行を末尾に取り込むことがある（W18 M3：dev FP の約 4 割）。
見出しの番号は参照ではないので、**その行だけ**参照の走査から伏せる。
番号トークンの直後が助詞・句読点・括弧なら本文の参照（`第１章第１条により…`）として残す。
句点を含む行と 40 字を超える行は見出しとみなさない。
"""


RE_FN_START = re.compile(r"^[（(](?:\*|注)[0-9０-９]{1,2}[）)]")
"""脚注本文の行頭（`脚注` 節の `RE_FN_BODY` と同じ形）。W18 M4。

脚注本文は条の末尾に刷られ、R4 の段落に取り込まれる。gold は脚注本文の中の参照を
**脚注を参照元**として持つので、段落から出すと参照元を取り違える。**最初の脚注行から段落末まで**を伏せる
（脚注は条の末尾にまとまって刷られ、本文に戻らない）。
"""


RE_TABLE_CAPTION = re.compile(r"^表[0-9０-９]{1,2}(?:[-－‐][0-9０-９]{1,2})?(?![0-9０-９にのをは])")
"""段落に取り込まれた表の表題行（`表1この約款に用いる用語`）。W19 N4（試行）。表の中の参照の参照元は gold では表セル。"""


def _heading_line_spans(lines: list[str]) -> list[tuple[int, int]]:
    """`"".join(lines)` 上の、参照の走査から伏せる範囲（見出し行・脚注本文）。"""
    spans, pos = [], 0
    for i, ln in enumerate(lines):
        st = ln.strip()
        if RE_FN_START.match(st) or RE_TABLE_CAPTION.match(st):
            spans.append((pos, pos + sum(len(x) for x in lines[i:])))
            break
        if st and len(st) <= 40 and "。" not in st and RE_HEADING_LINE.match(st):
            spans.append((pos, pos + len(ln)))
        pos += len(ln)
    return spans


def _art_num(label: str) -> str:
    return _flat(label).replace("第", "").replace("条", "").strip()


def _num(label: str, unit: str) -> str:
    return _flat(label).replace("第", "").replace(unit, "").strip()


def _paragraph_children(tree: Tree, node) -> list:
    return [tree.nodes[c] for c in node.children if tree.nodes[c].kind == "paragraph"]


def _item_by_number(tree: Tree, node, k: int):
    """号（`N．` などのラベルを持つ item）を番号で探す。外れたら位置。"""
    kids = [tree.nodes[c] for c in node.children if tree.nodes[c].kind == "item"]
    for c in kids:
        if re.fullmatch(rf"[（(]?{k}[）)．.]?", _flat(c.label)):
            return c
    return kids[k - 1] if 1 <= k <= len(kids) else None


def _paragraph_by_number(kids: list, k: int):
    """項をラベル照合、外れたら位置で引く（第1項は無番号で印字される慣行）。"""
    for sp in kids:
        lab = _flat(sp.label)
        if lab and re.fullmatch(rf"[（(]?{k}[）)．.]?", lab):
            return sp
    return kids[k - 1] if 1 <= k <= len(kids) else None


def resolve_refs(tree: Tree) -> set[tuple[str, str]]:
    """予測木の上で相互参照を解決する（P6）。

    **W12 まで採点側（`eval/metrics_structure.py`）に置いていたものを移した（V4）。**
    採点側は本関数を呼ぶ。規則の由来と実測は W11 T31・W12 T34・W18 を参照：

    1. 複合参照（`第2編第1章第2条`・`第3章第1条（1）`・`第4条（告知義務）第1項第2号`）を先に消費する
       — 編・章が明示されればその中から探す
    2. `第N項`（`第N項第N号`）は**位置で解く**（第1項は無番号で印字される慣行）
    3. `（N）` はラベル照合、外れたら位置
    4. `N．` は同じ親の号・項
    5. `第N章` / `第N編` / 6. `別表N`（`別表N第N`）

    見出し行の番号を参照と数えないよう、走査は本文ノード（paragraph / item）に限る。
    """
    appendix: dict[str, object] = {}
    chapter_nodes: dict[str, list] = {}
    part_nodes: dict[str, object] = {}
    for n in tree.nodes.values():
        if n.kind == "appendix":
            appendix.setdefault(_flat(n.label), n)
        elif n.kind == "chapter":
            num = _num(n.label, "章")
            if num:
                chapter_nodes.setdefault(num, []).append(n)
        elif n.kind == "part":
            num = _num(n.label, "編")
            if num:
                part_nodes.setdefault(num, n)
    articles_by_num: dict[str, list] = {}
    for n in tree.nodes.values():
        if n.kind == "article":
            articles_by_num.setdefault(_art_num(n.label), []).append(n)

    def descendants(root):
        stack, acc = list(root.children), []
        while stack:
            cur = tree.nodes[stack.pop()]
            acc.append(cur)
            stack.extend(cur.children)
        return acc

    def chapter_of(num: str, part_node, own_part, own_rider=None):
        """章を引く。編が明示されればその編の章。無ければ参照元と同じ編、次に同じ特約の章を優先する
        （レビュー指摘 4：本約款と特約の両方に同じ番号の章があるとき、文書先頭の章へ解決しない）。"""
        cands = chapter_nodes.get(num) or []
        for want in (part_node or own_part, None if part_node else own_rider):
            if want is None:
                continue
            inside = {x.node_id for x in descendants(want)}
            for c in cands:
                if c.node_id in inside:
                    return c
            if part_node is not None:
                return None
        return cands[0] if cands else None

    out: set[tuple[str, str]] = set()
    for n in tree.nodes.values():
        if n.kind not in ("paragraph", "item"):
            continue
        src = canonical_citation(n.citation)
        body = n.text
        art = _ancestor(tree, n, ("article",))
        scope = _ancestor(tree, n, ("chapter", "rider", "part", "appendix", "appendix_section"))
        own_part = _ancestor(tree, n, ("part",))
        own_rider = _ancestor(tree, n, ("rider",))
        own_section = _ancestor(tree, n, ("section",))
        own_chapter = _ancestor(tree, n, ("chapter",))

        def add(target: str, _src: str = src) -> None:
            if target and target != _src:
                out.add((_src, target))

        sib = _paragraph_children(tree, art) if art is not None else []

        def in_pool(want: str, pool) -> object | None:
            for c in pool:
                if c.kind == "article" and _art_num(c.label) == want:
                    return c
            return None

        def section_in(container, num: str):
            if container is None:
                return None
            for c in descendants(container):
                if c.kind == "section" and _num(c.label, "節") == num:
                    return c
            return None

        def find_article(
            want: str,
            ch_num: str | None,
            pt_num: str | None,
            sec_num: str | None = None,
            _scope=scope,
            _own=own_part,
            _rider=own_rider,
            _sec=own_section,
            _ch=own_chapter,
        ):
            """条を引く（W19 N1）。明示された編・章・節があればその中だけを探す。
            明示が無ければ **参照元と同じ節 → 同じ章・特約など（scope）→ 文書全体（その番号の条が一つだけのとき）**。
            定款は章をまたぐ連番なので、章の中に無ければ文書全体の一意な条に当たる（U-5）。"""
            part_node = part_nodes.get(pt_num) if pt_num else None
            if pt_num and part_node is None:
                return None
            if ch_num:
                node = chapter_of(ch_num, part_node, _own, _rider)
                if node is None:
                    return None
                if sec_num:
                    node = section_in(node, sec_num)
                    if node is None:
                        return None
                return in_pool(want, descendants(node))
            if sec_num:
                node = section_in(_ch or _scope, sec_num)
                return in_pool(want, descendants(node)) if node is not None else None
            if part_node is not None:
                return in_pool(want, descendants(part_node))
            for container in (_sec, _scope):
                if container is not None:
                    hit = in_pool(want, descendants(container))
                    if hit is not None:
                        return hit
            # 文書全体は**一意のときだけ**（W19 レビュー 1：曖昧なときに先頭を返すのは黙った代替）
            cands = articles_by_num.get(want) or []
            return cands[0] if len(cands) == 1 else None

        masked = list(body)
        for a, b in _heading_line_spans(n.lines):
            masked[a:b] = ["\u3000"] * (b - a)

        def mask(m, _masked=masked) -> None:
            for i in range(m.start(), m.end()):
                _masked[i] = "\u3000"

        for m in RE_REF_PATH.finditer("".join(masked)):
            g = {k: (v.translate(Z2H) if v else None) for k, v in m.groupdict().items()}
            want = g["art"] + (f"の{g['sub']}" if g["sub"] else "")
            target_art = find_article(want, g["ch"], g["part"], g["sec"])
            if target_art is None:
                continue
            para = g["para"] or g["kou"]
            target = target_art
            if para:
                target = _paragraph_by_number(_paragraph_children(tree, target_art), int(para))
            elif g["dot"]:
                # `第３条（題名）６．`：`N．` 形の項（life）を先に、無ければ号を引く（W19 N2c）
                k = int(g["dot"])
                target = next(
                    (
                        c
                        for c in _paragraph_children(tree, target_art)
                        if re.fullmatch(rf"{k}[．.]", _flat(c.label))
                    ),
                    None,
                ) or _item_by_number(tree, target_art, k)
            if target is not None and g["gou"]:
                target = _item_by_number(tree, target, int(g["gou"]))
            add(canonical_citation(target.citation) if target is not None else "")
            mask(m)
        rest = "".join(masked)

        for m in RE_REF_KOU.finditer(rest):
            hit = _paragraph_by_number(sib, int(m.group(1).translate(Z2H))) if sib else None
            if hit is not None and m.group(2):
                hit = _item_by_number(tree, hit, int(m.group(2).translate(Z2H)))
            if hit is not None:
                add(canonical_citation(hit.citation))
            mask(m)
        rest = "".join(masked)

        for m in RE_REF_PARA.finditer(rest):
            hit = _paragraph_by_number(sib, int(m.group(1).translate(Z2H)))
            if hit is not None:
                add(canonical_citation(hit.citation))

        parent = tree.nodes.get(n.parent_id) if n.parent_id else None
        for m in RE_REF_DOT.finditer(rest):
            num = m.group(1).translate(Z2H)
            pool2 = ([tree.nodes[c] for c in parent.children] if parent is not None else []) + sib
            for cand in pool2:
                lab = _flat(cand.label)
                if lab and re.fullmatch(rf"{num}[．.]", lab):
                    add(canonical_citation(cand.citation))
                    break

        for m in RE_REF_CHAPTER.finditer(rest):
            node = chapter_of(m.group(1).translate(Z2H), None, own_part, own_rider)
            if node is not None:
                add(canonical_citation(node.citation))

        for m in RE_REF_PART.finditer(rest):
            node = part_nodes.get(m.group(1).translate(Z2H))
            if node is not None:
                add(canonical_citation(node.citation))

        for m in RE_REF_APPENDIX.finditer(rest):
            node = appendix.get(_flat(m.group(1)))
            if node is None:
                continue
            target = node
            if m.group(2):
                k = m.group(2).translate(Z2H)
                # 区分が見つからなければ別表本体へ落とさず、解決しない（レビュー指摘 3：黙った代替は FP と FN を同時に作る）
                target = next(
                    (
                        tree.nodes[c]
                        for c in node.children
                        if tree.nodes[c].kind == "appendix_section"
                        and _num(tree.nodes[c].label, "") == k
                    ),
                    None,
                )
            if target is not None:
                add(canonical_citation(target.citation))
    return out


# ---------------------------------------------------------------- 脚注

RE_FN_BODY = re.compile(r"^[（(](?:\*|注)([0-9０-９]{1,2})[）)](.+)$")
"""脚注本文：行頭の `（*N）` または `（注N）`。本文中の参照（`…をいいます（*1）。`）は行頭に来ない。

gold の注番号は 3 系統（`（*N）` 740・`（注N）` 71・`❶❷` 113）。**`❶` 系は扱わない** —
行頭に来る `❶` は表の項目番号（`❶証券番号`）でもあり、行の形では脚注と区別できない。
"""
RE_FN_REF = re.compile(r"[（(]\*([0-9０-９]{1,2})[）)]")


def footnotes(tree: Tree) -> list[dict]:
    """脚注本文を、それを持つ条（の引用）と注番号で返す。

    脚注本文は条の末尾に刷られるので、木の上では**その条の配下のノード**に入る。
    所有者は祖先の条（無ければ直近の容器）とする。注番号は条ごとに振り直される。
    """
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for n in tree.nodes.values():
        owner = (
            n
            if n.kind == "article"
            else _ancestor(tree, n, ("article", "appendix_section", "appendix", "rider", "chapter"))
        )
        if owner is None:
            continue
        for ln in n.lines:
            m = RE_FN_BODY.match(ln.strip())
            if not m:
                continue
            num = int(m.group(1).translate(Z2H))
            key = (canonical_citation(owner.citation), num)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "article_citation": key[0],
                    "n": num,
                    "marker": m.group(0)[: m.group(0).index("）") + 1]
                    if "）" in m.group(0)
                    else f"（*{num}）",
                    "text": m.group(2).strip(),
                    "page": (n.pages or [None])[0],
                }
            )
    return out


# ---------------------------------------------------------------- 定義語

RE_CELLS = re.compile(r"\s*\|\s*|[ 　]{2,}")
RE_DEFINITION = re.compile(r"(?:をいい(?:ます|、)|とします。|を指します。)")
RE_TERM = re.compile(r"^[一-龥ぁ-んァ-ヶー・（）()A-Za-z0-9０-９]{2,24}$")


def defined_terms(r2_pages: dict[int, str]) -> list[str]:
    """定義表の行から定義語を拾う。入力は **R2（LAYOUT）の生テキスト**（Markdown 除去前後どちらでも可）。

    LAYOUT は表の行をパイプ表で出す（`| ア | 運転者 | 被保険自動車の…をいいます。… |`）。
    Markdown 除去後はセル間の連続空白になる。どちらも区切りとして扱う。
    **最後のセルが定義文（`…をいいます` 等）を含む行の、直前のセルを定義語とする。**
    語彙の列挙は使わない（評価集合に合わせた語の列挙は標本内楽観を作る。V2）。

    表の格子抽出（P3）は PILOT の対応づいた領域にしか無いので、ここでは行の形から取る。
    **取れた定義語だけが使用箇所の索引に載る**ので、再現率は定義語の抽出率で頭打ちになる。
    """
    terms: dict[str, None] = {}
    for text in r2_pages.values():
        for ln in text.split("\n"):
            cells = [c.strip(" |") for c in RE_CELLS.split(ln.strip(" |")) if c.strip(" |")]
            if len(cells) < 2 or not RE_DEFINITION.search(cells[-1]):
                continue
            t = cells[-2]
            if RE_TERM.match(t) and not RE_DEFINITION.search(t):
                terms.setdefault(t, None)
    return list(terms)


def term_uses(tree: Tree, terms: list[str]) -> list[dict]:
    """定義語が本文ノードに現れた箇所を (定義語, 引用) で返す。

    **最長一致**（W15 R4）：長い語から照合し、一致した文字範囲を塞ぐ。
    `被保険者` の中の `保険者` のように、長い定義語に含まれる短い定義語は使用に数えない
    （V4 の部分一致は精度 0.6273、最長一致で 0.6366）。

    **残る偽陽性の主因は表の中の使用である**（W15 R4：1,913 件中 1,028 件）。R4 の段落は
    後続の罫線なし表の行を本文に取り込み、gold は表内の使用を表セルに帰属させる。
    表セルの文字を段落から除く試行 2 は精度 0.6677 だが再現率が 0.045 落ち、宣言した
    許容 0.02 を超えたので棄却した（段落の境界そのものを直すのが本筋・V6）。
    """
    out = []
    ordered = sorted({t for t in terms if t}, key=len, reverse=True)
    for n in tree.nodes.values():
        if n.kind not in ("paragraph", "item"):
            continue
        body = _flat(n.text)
        taken = [False] * len(body)
        for t in ordered:
            hit = False
            for m in re.finditer(re.escape(t), body):
                a, b = m.span()
                if not any(taken[a:b]):
                    taken[a:b] = [True] * (b - a)
                    hit = True
            if hit:
                out.append({"term": t, "in_citation": canonical_citation(n.citation)})
    return out


# ---------------------------------------------------------------- 列挙


def enumerations(tree: Tree) -> list[dict]:
    """番号付きの子（項・号）を 2 つ以上持つノードを、順序付きの列挙として返す。"""
    out = []
    for n in tree.nodes.values():
        kids = [tree.nodes[c] for c in n.children if tree.nodes[c].kind in ("paragraph", "item")]
        kids = [k for k in kids if k.label]
        if len(kids) >= 2:
            out.append(
                {
                    "owner_citation": canonical_citation(n.citation),
                    "items": [
                        {
                            "index": i + 1,
                            "label": k.label,
                            "citation": canonical_citation(k.citation),
                        }
                        for i, k in enumerate(kids)
                    ],
                }
            )
    return out
