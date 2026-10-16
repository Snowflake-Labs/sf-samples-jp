"""見出し候補に**スコア**を付ける（T7）。

現行の `tree.Builder` は行を見て**採用か却下かの二値**で決める。
大域デコード（T9）は「候補集合とスコア `s_i`」を必要とするので、その層をここに作る。

**この層は木を作らない。** 作るのは
`(位置, レベル, ラベル, 番号, 題名, 特徴量, スコア)` の列だけである。
木の組み立ては T9 の仕事であり、分離しておかないと
「規則で決めた木」と「最適化で決めた木」の区別が付かなくなる。

**設計上の注意：** スコアは確率ではない。順位付けのための単調な量である。
係数は P20 で調整し PILOT で報告する（選択バイアスを避ける。§10）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .candidates_rules import HEAD_RULES_BY_KIND
from .tree import RE_APPENDIX, RE_RIDER, _n

# 参照除外。**最も重要な否定規則**（§5.6(4)）。約款は条項参照で飽和しており、
# 「第5条（保険金の支払）の規定にかかわらず…」が行頭に来ると偽陽性になる。
# `lines.RE_REF_SUFFIX` と同じ語彙を使うが、ここでは**減点**として扱う
# （二値で落とさない。落とすとデコーダが選び直せない）。
RE_REF_SUFFIX = re.compile(
    r"^(?:の規定|に定め|に規定|および|又は|または|、|から|まで|の定め|"
    r"に掲げ|による|に基づ|の適用|の場合|とあるのは|に準じ|を準用|ただし|の規定中|により|を除)"
)
# 題名が括弧で囲まれている見出しは確度が高い（`第1条（用語の定義）`）。
RE_PAREN_TITLE = re.compile(r"^[（(]\S.*[）)]$")
_Z2H = str.maketrans("０１２３４５６７８９", "0123456789")

LEVEL_OF = {"part": 1, "chapter": 2, "section": 3, "article": 4}

# 行から候補を作る規則。**上位から順に試す**（`第1編` は `第1条` と競合しない）。
_RULES = HEAD_RULES_BY_KIND


@dataclass
class Candidate:
    """1 つの見出し候補。**同じ位置に複数の候補が立ってよい。**"""

    pos: int  # 文書内の行通し番号。位置順 DP の軸になる
    page: int
    kind: str  # part / chapter / section / article / appendix / rider
    level: int  # 1..4。appendix/rider は 0（根）
    num: int | None
    label: str  # 逐語（§1.11）
    title: str
    line: str
    feats: dict[str, float] = field(default_factory=dict)
    score: float = 0.0


# 特徴量の重み。**P20 で調整する。ここは初期値である。**
# 符号の意味だけは動かさない（参照らしさは必ず負、括弧題名は必ず正）。
WEIGHTS = {
    "has_title": 0.8,  # 番号の後に題名がある
    "paren_title": 0.6,  # 題名が括弧で囲まれている
    "short_line": 0.5,  # 行が短い（見出しは短い）
    "ref_suffix": -2.5,  # 番号の直後が参照の語（最重要の減点）
    "has_sentence_mark": -1.2,  # 句点・読点を含む（本文である）
    "line_start": 0.3,  # 行頭から始まる（字下げされていない）
    "toc_confirmed": 1.5,  # 印刷目次に同じ (種別, 番号) がある（T8。適合率 1.0）
    "toc_page_match": 1.0,  # 目次の開始ページと一致する
    # **柱（走りヘッダ）への減点。** T7 の実測で、残った偽陽性の主因は参照ではなく柱だった。
    # `第１編ご契約のしおり` が各ページ上端に刷られており、字面が見出しと完全に同じなので
    # 語彙・長さ・括弧では区別できない（スコア 2.98 と高く出ていた）。
    # **複数ページに同一行が反復するかどうかだけが区別する信号である。**
    "repeated_line": -2.0,
}

SENTENCE_MARKS = "。、，．"


def _repeated_lines(pages: list, min_pages: int = 2) -> set[str]:
    """**複数ページに現れる行**を柱の候補とみなす（gold の `repeated` は使わない）。

    **必ず候補と同じ分割後テキストで数えること。** 最初は分割前の `p.text` で
    数えたため、この特徴量は一度も発火しなかった。`第１編ご契約のしおり` は
    分割前には `第１編ご契約のしおり第１章このしおりの読み方` という連結行の
    一部なので、分割前の集計では「1 ページにしか出ない」と見える。
    分割後に数えると、柱として 2 ページ以上に現れることが見える。

    **文字列単位で一律に減点してはならない。** それを試したら正例の中央値が
    2.00 → 0.08 に落ち、正例と負例が逆転した。理由は、柱が反復しているのは
    **本物の見出しと同じ文字列**だからである。見出しが p6 に現れ、p7 以降の柱に
    同じ文字列が刷られる。文字列で罰すると p6 の本物も一緒に罰する。

    したがってこの集合は「反復する文字列」を返すだけにし、**減点は
    `candidates_for_doc` 側で「最初の出現以外」に限って与える**（位置依存）。
    柱は先に現れた見出しの再掲なので、最初の出現が本物である。
    """
    from collections import Counter

    from .lines import split_page_text

    c: Counter[str] = Counter()
    for p in pages:
        uniq = {x.strip() for x in split_page_text(p.text).split("\n") if x.strip()}
        for s in uniq:
            c[s] += 1
    return {s for s, n in c.items() if n >= min_pages}


def _norm_title(t: str) -> str:
    """題名の比較用。**空白と全角/半角の差は組版差**なので畳む。

    畳むのは比較層だけである。格納するラベルは逐語のまま（§1.11）。
    """
    return "".join(t.split()).translate(_Z2H)


def _features(
    kind: str, num: int | None, title: str, line: str, toc, repeated: set[str] | None = None
) -> dict[str, float]:
    f: dict[str, float] = {}
    f["has_title"] = 1.0 if title.strip() else 0.0
    f["paren_title"] = 1.0 if RE_PAREN_TITLE.match(title.strip()) else 0.0
    # 見出しは短い。40 字を境に線形に落とす（実測の見出し長は概ね 30 字以下）。
    f["short_line"] = max(0.0, 1.0 - len(line) / 40.0)
    f["ref_suffix"] = 1.0 if RE_REF_SUFFIX.match(title) else 0.0
    # **条の候補には句読点の減点を課さない（W3 A4）。**
    # この特徴量の意図は「この行は本文である」だが、**条ラベルと本文が同一行に
    # 刷られる体裁**（group：`第5条当会社は、…支払いません。`）では見出しが本文と
    # 行を共有するので、意図どおりに働かない。実測では本物の条見出しが −0.10、
    # 同じページの表キャプション `第2条備考` が 1.54 となり、**DP は
    # キャプションを選んで本物を捨てた**（group の条 recall 0.750 → 0.361）。
    # 参照（`第5条の規定にかかわらず…`）を弾くのは `ref_suffix`（−2.5）の役割であり、
    # そちらは行を共有する体裁でも正しく働く。
    f["has_sentence_mark"] = (
        1.0 if (kind != "article" and any(c in line for c in SENTENCE_MARKS)) else 0.0
    )
    f["line_start"] = 1.0 if line[:1] not in ("　", " ") else 0.0
    # `repeated` には「2 ページ以上に現れる行」が入る。**この時点では減点しない。**
    # 最初の出現かどうかは行単体では分からないので、呼び出し側が上書きする。
    f["repeated_line"] = 0.0
    f["toc_confirmed"] = 0.0
    f["toc_page_match"] = 0.0
    if toc is not None and num is not None:
        # **番号だけでなく題名も一致させる（W3 A5）。**
        # `(種別, 番号)` だけで照合すると、**本文中の参照が目次で裏付けられてしまう**。
        # 実測：`第２編第１章第２条に、お支払いできない場合は…` という本文行が、
        # 目次に 第2編 が存在するだけで +1.5 を得て合計 1.41 になり、
        # 句読点の減点（−1.2）を打ち消して採用された。その結果 第2編 が p5 で開き、
        # **第1編 配下の章がすべて第2編に付き替わった**（life の条 recall 0.136）。
        # 目次が裏付けるのは「その番号の見出しが存在する」ことであって
        # 「この行がそれである」ことではない。題名の一致がその橋を架ける。
        t = _norm_title(title)
        for e in toc.entries:
            if (e.kind, e.num) != (kind, num):
                continue
            et = _norm_title(e.title)
            if not et or not t or t.startswith(et[:6]) or et.startswith(t[:6]):
                f["toc_confirmed"] = 1.0
            break
    return f


def score_of(feats: dict[str, float], weights: dict[str, float] | None = None) -> float:
    w = weights or WEIGHTS
    return sum(w.get(k, 0.0) * v for k, v in feats.items())


def candidates_for_doc(
    doc_id: str,
    use_toc: bool = True,
    weights: dict[str, float] | None = None,
    extra_cut: dict[int, int] | None = None,
) -> list[Candidate]:
    """文書から見出し候補を**すべて**出す。却下しない。

    `tree.Builder` と違って、ここでは参照らしい行も候補として残す
    （**スコアを低く付ける**）。T9 が全体最適の中で捨てるかどうかを決める。
    """
    from ..parse.r4_local import read_pages_text
    from .lines import split_page_text, toc_block_end
    from .toc import build_toc

    toc = build_toc(doc_id) if use_toc else None
    # **目次ページと「構成」ページの両方を除外する。**
    # 構成ページ（裸の見出し列）を残すと、そこの見出しが全部偽陽性になる（T7 の実測）。
    toc_pages = set(toc.toc_pages) | set(toc.outline_pages) if toc else set()

    all_pages = read_pages_text(doc_id)
    # **抑止は目次ブロック単位（W8）。** 組み立て側（`tree.Builder`）と
    # **同じ関数**を使う。ページ単位で飛ばすと、目次と本文が同居するページの
    # 本文見出しが候補に出ず、`heading_allow` に無いので組み立て側が本文化する
    # — 実測：teikan-0001 の `第１条（商号）`〜`第３条` が
    # 「大域デコードが非採用」で落ち、gold の `第1章 第1〜5条` を失っていた。
    from .tree import merge_cut

    toc_cut = merge_cut(
        toc_block_end({p.page: split_page_text(p.text) for p in all_pages}, toc_pages),
        extra_cut,
    )
    # W17-B：組み立て側と同じ追加の抑止区間（本文を持たない容器の見出し区間）
    toc_pages = set(toc_pages) | set(extra_cut or {})
    repeated = _repeated_lines(all_pages)
    seen_once: set[str] = set()  # 反復行のうち既に 1 回通した行
    # **組み立て側と同じ柱判定を使う（W16-A）。** 「最初の出現は本物」の既定は、
    # 柱が本物の見出しより上に刷られるページで逆になる。幾何で柱と判定した行は候補にしない。
    from .tree import _furniture_upper_lines

    furn = _furniture_upper_lines(doc_id, {p.page: split_page_text(p.text) for p in all_pages})

    out: list[Candidate] = []
    pos = 0
    for p in all_pages:
        cut = toc_cut.get(p.page, -1)
        for j, raw in enumerate(split_page_text(p.text).split("\n")):
            s = raw.strip()
            pos += 1
            if not s:
                continue
            # **目次ブロックと構成ページは候補を出さない。** そこの見出しは
            # 本文の見出しではなく、見出しの索引である。
            # ブロックの外（同じページの本文側）は候補を出す。
            # **免除：ページ内で 2 回以上現れる行は本文（W14 T50 第 2 案）。**
            # 目次は各項目を 1 回だけ並べるので、重複は「柱 ＋ 本物の見出し」の対である。
            # **組み立て側と同じ関数を使う**（`page_repeated_keys`）。
            # 第 1 版は組み立て側だけを免除したため、見出しは開くのに候補が無く
            # `大域デコードが非採用` に変わっただけで数値が 1 つも動かなかった
            # — W8 と同じ食い違いを 2 度踏んだことになる。
            if p.page in toc_pages and j <= cut:
                continue
            if (p.page, j) in furn:
                continue
            for kind, rx in _RULES:
                m = rx.match(s)
                if not m:
                    continue
                num = _n(m.group(1))
                title = m.group(m.lastindex or 1) if m.lastindex and m.lastindex > 1 else ""
                if kind == "article" and m.lastindex and m.lastindex >= 3:
                    title = m.group(3) or ""
                feats = _features(kind, num, title, s, toc, repeated)
                # **最初の出現は本物、2 回目以降は柱**として扱う（位置依存の減点）。
                #
                # **ただし条には課さない（W3 A4 で修正）。** 条番号は特約ごとに 1 に
                # 戻るので、`第１条（この特約の適用条件）` のような行は**設計上
                # 複数の特約で再出現する**。柱として罰すると 2 本目以降の特約の条が
                # すべて 0.03 点に落ち、大域デコードがそれらを捨てた
                # （実測：golf の条 recall 0.862 → 0.172。採用集合の F1 では
                #  見えず、引用木を測って初めて分かった）。
                # 柱が運ぶのは編・章・節・特約の名前であって、条見出しではない。
                if s in repeated and kind != "article":
                    if s in seen_once:
                        feats["repeated_line"] = 1.0
                    else:
                        seen_once.add(s)
                if toc is not None and feats["toc_confirmed"] and toc.start_page(kind, num):
                    sp = toc.start_page(kind, num)
                    if sp is not None and abs(sp - p.page) <= 1:
                        feats["toc_page_match"] = 1.0
                c = Candidate(
                    pos=pos,
                    page=p.page,
                    kind=kind,
                    level=LEVEL_OF[kind],
                    num=num,
                    label=m.group(0)[: len(m.group(0)) - len(title)].strip() or m.group(0),
                    title=title,
                    line=s,
                    feats=feats,
                )
                c.score = score_of(feats, weights)
                out.append(c)
                break  # 1 行 1 候補（上位種別を優先）
            else:
                for kind, rx in (("appendix", RE_APPENDIX), ("rider", RE_RIDER)):
                    m = rx.match(s)
                    if not m:
                        continue
                    feats = _features(kind, None, "", s, toc, repeated)
                    c = Candidate(
                        pos=pos,
                        page=p.page,
                        kind=kind,
                        level=0,
                        num=None,
                        label=m.group(1),
                        title="",
                        line=s,
                        feats=feats,
                    )
                    c.score = score_of(feats, weights)
                    out.append(c)
                    break
    return out
