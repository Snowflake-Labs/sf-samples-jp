"""印刷された目次を「照合表」として構築する（T8）。

**gold の見出し表を目次の代用にしてはならない**（§1.4 の gold-blind）。
ここが読むのは予測経路のページテキストだけである。

目次は大域デコード（T9）で最も強い制約になる。理由は 2 つある。

1. **期待される見出しの列が分かる。** 番号の飛びが「読み落とし」なのか
   「元々無い」のかを、番号制約だけでは区別できない。目次があれば区別できる。
2. **開始ページが印字されている。** `life` の `第２編` は本文に現れる前に
   目次で「8 ページから」と分かる。編の境界はこれで確定できる。

**目次が無い文書もある。** その場合は照合表が空になるだけで、T9 は番号制約のみで動く。
空を「目次が読めなかった」と混同しないよう、`has_toc` を別に返す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 目次行 = 「番号付き見出し ＋ 題名 ＋ 末尾の裸のページ番号」。
# 本文の見出しが裸の数字で終わることはない（`tree.RE_TOC_ENTRY` と同じ前提）。
# **題名を捕まえる点が `tree.RE_TOC_ENTRY` との違いである。** あちらは落とすだけ、
# こちらは保持する。
RE_TOC_NUMBERED = re.compile(
    r"^(?P<label>第(?P<num>[0-9０-９]+)(?P<kind>編|章|節|条))"
    r"(?P<title>.*?)"
    r"(?P<page>[0-9０-９]{1,3})$"
)
# 別表・付表は番号体系が本体と独立なので別に扱う（引用木では根になる）。
RE_TOC_APPENDIX = re.compile(
    r"^(?P<label>(?:別表|付表)(?P<num>[0-9０-９]+))(?P<title>.*?)(?P<page>[0-9０-９]{1,3})$"
)
# 特約は番号を持たないことがある。`鑑定特約12` のような形。
RE_TOC_RIDER = re.compile(r"^(?P<title>\S{2,30}?特約(?:条項)?)(?P<page>[0-9０-９]{1,3})$")

# **目次には 2 形式ある（T8 の実測）。**
#
# 1. **ページ形式** — `第１編ご契約のしおり4`。`life`・`teikan`・`group`。
#    末尾が開始ページ番号。
# 2. **引用形式** — `保険金の請求第5章第4節第1条`。`auto`。
#    末尾がページ番号ではなく**引用パス**である。目的別もくじがこの形を取る。
#
# **引用形式のほうが T9 には強い制約である。** ページ番号は「どこから始まるか」しか
# 言わないが、引用パスは「章・節・条の組が存在する」ことを直接言う。
# 当初はページ形式だけを実装し、`auto` で目次項目 0 件になって気づいた。
RE_TOC_CITATION = re.compile(
    r"^(?P<title>.{2,40}?)"
    r"(?P<cit>(?:第(?P<ch>[0-9０-９]+)章)?(?:第(?P<sec>[0-9０-９]+)節)?第(?P<art>[0-9０-９]+)条"
    r"|(?:別表|付表)(?P<apx>[0-9０-９]+))$"
)

KIND_BY_CHAR = {"編": "part", "章": "chapter", "節": "section", "条": "article"}

ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def to_int(s: str) -> int:
    return int(s.translate(ZEN))


@dataclass(frozen=True)
class TocEntry:
    kind: str  # part / chapter / section / article / appendix / rider
    label: str  # **逐語で保持する**（`第１編`。§1.11：全角を畳まない）
    num: int | None  # 番号制約に使う整数。特約は None
    title: str
    page: int | None  # 目次に印字された開始ページ。引用形式では None
    src_page: int  # この目次行が載っていたページ
    raw: str
    # 引用形式のときだけ入る。`(章, 節, 条)` の組。欠けている段は None。
    cit_chapter: int | None = None
    cit_section: int | None = None
    cit_article: int | None = None

    @property
    def form(self) -> str:
        """**`page` と `citation` のどちらを持つ目次かを明示する。**

        片方しか無いのに両方あるかのように扱うと、T9 の制約が黙って空になる。
        """
        return "citation" if self.cit_article is not None else "page"


def _clean_title(t: str) -> str:
    """題名から目次特有の飾りを落とす。**本文は変えない。**

    点リーダ（`……`）と中黒の連打、および末尾の空白を落とす。
    """
    t = re.sub(r"[.\u2026\u30fb\uff65]{2,}", "", t)
    return t.strip()


def parse_toc_lines(lines: list[tuple[int, str]]) -> list[TocEntry]:
    """`(ページ番号, 行)` の列から目次項目を取り出す。

    **1 行 1 項目**とみなす。折り返した目次行は扱わない（本コーパスでは折り返しが
    観測されていない。観測されたら `n_unparsed` が増えて気づける形にしてある）。
    """
    out: list[TocEntry] = []
    for src_page, raw in lines:
        s = raw.strip()
        if not s or "。" in s:
            continue  # 句点を含む行は本文である
        m = RE_TOC_NUMBERED.match(s)
        if m:
            out.append(
                TocEntry(
                    kind=KIND_BY_CHAR[m.group("kind")],
                    label=m.group("label"),
                    num=to_int(m.group("num")),
                    title=_clean_title(m.group("title")),
                    page=to_int(m.group("page")),
                    src_page=src_page,
                    raw=s,
                )
            )
            continue
        m = RE_TOC_APPENDIX.match(s)
        if m:
            out.append(
                TocEntry(
                    kind="appendix",
                    label=m.group("label"),
                    num=to_int(m.group("num")),
                    title=_clean_title(m.group("title")),
                    page=to_int(m.group("page")),
                    src_page=src_page,
                    raw=s,
                )
            )
            continue
        m = RE_TOC_RIDER.match(s)
        if m:
            out.append(
                TocEntry(
                    kind="rider",
                    label=_clean_title(m.group("title")),
                    num=None,
                    title=_clean_title(m.group("title")),
                    page=to_int(m.group("page")),
                    src_page=src_page,
                    raw=s,
                )
            )
            continue
        # 引用形式。**ページ形式より後に試す。** `第1章総則2` は両方に一致しうるが、
        # 末尾が裸の数字ならページ形式として読むのが正しい。
        m = RE_TOC_CITATION.match(s) if len(s) <= 40 else None
        if m and m.group("art"):
            out.append(
                TocEntry(
                    kind="article",
                    label=m.group("cit"),
                    num=to_int(m.group("art")),
                    title=_clean_title(m.group("title")),
                    page=None,
                    src_page=src_page,
                    raw=s,
                    cit_chapter=to_int(m.group("ch")) if m.group("ch") else None,
                    cit_section=to_int(m.group("sec")) if m.group("sec") else None,
                    cit_article=to_int(m.group("art")),
                )
            )
    return out


def outline_pages(pages: list) -> list[int]:
    """**第 3 の目次形式：裸の見出し列**が載るページを見つける（T7 の実測で発覚）。

    `auto-0001` の 4 ページ目は `第1節契約手続と義務` / `第1条（告知義務）` … と
    見出しだけを並べた「約款の構成」ページで、**ページ番号も引用も付かない**。
    よって `RE_TOC_NUMBERED` も `RE_TOC_CITATION` も一致せず、
    `_toc_pages` は目次と判定できなかった。その結果、このページの見出しが
    本文の見出し候補として立ち、gold には構造ノードが無いので
    **すべて偽陽性になっていた**。

    判定は密度で行う。**gold を使わない。**

    実測（PILOT 先頭 4 文書）：

    | ページ | 見出し率 | 散文率 | gold の構造ノード |
    |---|---:|---:|---:|
    | auto p3（構成） | 0.26 | 0.12 | 0 |
    | auto p4（構成） | 0.40 | 0.01 | 0 |
    | auto p5（本文） | 0.03 | 0.32 | 4 |
    | group p2（目次） | 0.12 | 0.00 | 0 |
    | group p3（本文） | 0.06 | 0.25 | 3 |

    **散文率（句点を含む行の割合）が本文と前付けを分ける。**
    見出し率だけでは分けられない（group の本文 p5 は見出し率 0.16 ある）。

    表だけのページも散文率が低くなるので、**見出しを実際に産むページに限って**
    適用する（`n_head_ratio >= 0.10`）。表のページは見出し率が 0 なので影響しない。
    """
    from .candidates_rules import HEAD_RULES

    out: list[int] = []
    for p in pages:
        lines = [x.strip() for x in p.text.split("\n") if x.strip()]
        if not lines:
            continue
        n_head = sum(1 for s in lines if any(rx.match(s) for rx in HEAD_RULES))
        n_prose = sum(1 for s in lines if "。" in s)
        if n_head / len(lines) >= 0.10 and n_prose / len(lines) < 0.15:
            out.append(p.page)
    return out


def _toc_pages(pages: list) -> list[int]:
    """目次が載っているページを決める。

    **目次は先頭付近にしか無い**という前提は置かない（`life` は 2〜3 ページだが
    約款集では後ろに特約目次が出ることがある）。代わりに
    **「目次らしい行が 3 行以上あるページ」**を目次ページとする。
    3 行という下限は、本文中の偶然の一致（表の行など）を落とすためである。
    """
    hits: list[int] = []
    for p in pages:
        n = 0
        for line in p.text.split("\n"):
            s = line.strip()
            if not s or "。" in s:
                continue
            if RE_TOC_NUMBERED.match(s) or RE_TOC_APPENDIX.match(s) or RE_TOC_RIDER.match(s):
                n += 1
            # 引用形式は本文にも偶然一致する（実測：`…その程度が別表１` が拾われた）。
            # **長さで縛る。** 目次行は題名＋引用なので短い。本文の文断片は長い。
            elif len(s) <= 40 and RE_TOC_CITATION.match(s):
                n += 1
        if n >= 3:
            hits.append(p.page)
    return hits


@dataclass
class TocTable:
    doc_id: str
    entries: list[TocEntry]
    toc_pages: list[int]
    outline_pages: list[int]  # 裸の見出し列が載るページ（第 3 の目次形式）
    n_lines_seen: int
    n_unparsed: int

    @property
    def has_toc(self) -> bool:
        """**目次が無いことと、目次が読めなかったことを区別する。**"""
        return bool(self.entries)

    def by_kind(self, kind: str) -> list[TocEntry]:
        return [e for e in self.entries if e.kind == kind]

    def expected_nums(self, kind: str) -> list[int]:
        return [e.num for e in self.by_kind(kind) if e.num is not None]

    def start_page(self, kind: str, num: int) -> int | None:
        for e in self.entries:
            if e.kind == kind and e.num == num:
                return e.page
        return None


def build_toc(doc_id: str) -> TocTable:
    """予測経路のページテキストから目次照合表を作る。"""
    from ..parse.r4_local import read_pages_text

    pages = read_pages_text(doc_id)
    tp = _toc_pages(pages)
    op = [x for x in outline_pages(pages) if x not in tp]
    lines: list[tuple[int, str]] = []
    n_seen = 0
    for p in pages:
        if p.page not in tp:
            continue
        for line in p.text.split("\n"):
            if line.strip():
                n_seen += 1
                lines.append((p.page, line))
    entries = parse_toc_lines(lines)
    return TocTable(
        doc_id=doc_id,
        entries=entries,
        toc_pages=tp,
        outline_pages=op,
        n_lines_seen=n_seen,
        n_unparsed=n_seen - len(entries),
    )
