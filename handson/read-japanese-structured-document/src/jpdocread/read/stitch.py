"""ページ・段をまたぐ表を 1 つにつなぐ（S50 の後処理。予測側のモジュールで、正解を開かない）。

`AI_PARSE_DOCUMENT` を `page_split => TRUE` で呼ぶと、ページをまたぐ表はページの境界で切れて返る。
2 段組の段をまたぐ表も、左段と右段の 2 つの表として返ることがある。`tables_for_doc` はそれを
ページごとの別々の表にするので、ここで「同じ表の続き」と判定できる隣り合う断片だけをつなぐ。

**入力は LAYOUT のページごとの Markdown と、そこから作った表のレコードだけ。** 正解・ページ画像は読まない。

判定は 3 段で、どれも満たしたときだけつなぐ（誤ってつなぐと 2 つの表をまとめて壊すので、迷ったらつながない）。

1. **候補（読み順で隣り合う）**
   - ページまたぎ：前の断片がページ p の最後の表で、そのあとに本文の行が無い。後の断片がページ p+1 の
     最初の表で、その前に本文の行が無い。
   - 段またぎ：同じページで隣り合う 2 つの表の間に本文の行が無い。
   「本文の行」は柱以外の行。柱は次のどちらかの行（`is_body_line`）。
   - 短く（30 字以下）句読点を持たない行（ページ番号・文書番号・柱の章名）。表題（`表N …`）と見出し（`#`）は除く
   - テキスト層から検出した柱の行（`read_pages_text` の `furniture`。ページの上下の帯に 3 ページ以上同じ形で出る
     行とページ番号で、正解は使わない）と空白を除いて同じ行。長い柱（文書名と年版など）をここで拾う
   検出した柱だけに頼ると、テキスト層と LAYOUT で行の区切りが違うページ番号などを本文とみなしてしまう
   （開発用の評価で、ページまたぎの 1 つで読めた表が 18 → 9 に減った）ので、形の規則に足す形で使う。
   - ページの先頭の表の前に 1 行だけある走りヘッダ（`第N章 …`・`第N編 …`・`別表N …`・`付表N …`）
   表題（`表N …`）・条の見出し・句点を含む文は本文の行で、間にあれば別の表とみなす。
2. **形（列数が同じ）**
3. **続きの証拠**（どちらか）
   - 後の断片の 1 行目が、前の断片の 1 行目と正規化後に同じ（見出しの再掲）
   - 両方の 1 行目の左端が列挙記号で、後の断片の先頭の番号が前の断片の末尾の番号の次（`⑤` → `⑥`）

つないだ表は、後の断片の再掲の見出しを外して行を連ねる（正解の格子は見出しを 1 回だけ持ち、
ページで割れた行は持たない）。元の断片は `fragments` に、判定の根拠は `stitch` に残す。
"""

from __future__ import annotations

import re
import unicodedata

from .tables_r2 import grid_from_pipe

# 柱とみなす行：短く、句点・読点を持たない。ページ番号（`- 3 -`・`16`）・文書番号（`H261001`）・
# 柱の章名（`第2章 賠償責任条項`）がこれに当たる。表題（`表3 …`）と見出し（`#`）は本文の行として扱う
_RE_TABLE_TITLE = re.compile(r"^(?:#+\s*)?(?:別\s*)?表\s*[0-9０-９]")
_RE_HEADING = re.compile(r"^#+\s")
# 走りヘッダ（ページの先頭に出る、そのページが属する編・章・別表・付表の名前）。ページの先頭の 1 行だけに使う。
# `表N …`（本物の表題）はここに含めない。開発用の pilot で、続きの断片の直前にこの形の行が 7 件あった
_RE_RUNNING_HEADER = re.compile(
    r"^(?:#+\s*)?(?:第\s*[0-9０-９一二三四五六七八九十]+\s*[編章]|(?:別|付)\s*表\s*[0-9０-９]+)"
)
FURNITURE_MAX_CHARS = 30

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_RE_ENUM = re.compile(r"^(?:([①-⑳])|[（(]([0-9０-９]{1,2})[）)])")


def furniture_key(line: str) -> str:
    """柱の照合キー：Markdown の見出し記号と空白を除き NFKC で正規化する（テキスト層と LAYOUT の差を吸収）。"""
    s = re.sub(r"^#+\s*", "", line.strip())
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def is_body_line(line: str, furniture: set[str] | None = None) -> bool:
    """柱でない（表と表の間にあれば別の表とみなす）行か。空行は本文ではない。

    `furniture` は柱の照合キー（`furniture_key`）の集合。それに一致する行も柱とみなす（形の規則に足す）。
    """
    s = line.strip()
    if not s or set(s) <= set("-—―ー_ "):
        return False
    if furniture and furniture_key(s) in furniture:
        return False
    if _RE_TABLE_TITLE.match(s) or _RE_HEADING.match(s):
        return True
    if "。" in s or "、" in s:
        return True
    return len(s) > FURNITURE_MAX_CHARS


def _is_pipe_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def pipe_table_context(text: str, furniture: set[str] | None = None) -> list[dict]:
    """ページの Markdown の各パイプ表について、前後に本文の行があるかを返す（`parse_pipe_tables` と同じ区切り）。

    戻り値は表ごとの `{"body_before": bool, "body_after": bool}` で、`body_before` は直前の表（無ければページの先頭）
    との間、`body_after` は直後の表（無ければページの末尾）との間に本文の行があるか。
    `parse_pipe_tables` が捨てる 1 行だけの表は、ここでも表として数えない（その行は本文の行として扱う）。
    """
    segs: list[tuple[str, list[str]]] = []  # ("T", 行) か ("L", [行])
    cur: list[str] = []
    for line in text.split("\n"):
        if _is_pipe_row(line):
            cur.append(line)
            continue
        if cur:
            segs.append(("T", cur))
            cur = []
        segs.append(("L", [line]))
    if cur:
        segs.append(("T", cur))

    def n_rows(rows: list[str]) -> int:
        return sum(1 for r in rows if not re.match(r"^\|[\s:\-|]+\|$", r.strip()))

    # 1 行だけの表は表として数えない（parse_pipe_tables と同じ）
    segs = [
        ("T", r) if k == "T" and n_rows(r) >= 2 else ("L", ["本文" * 20] if k == "T" else r)
        for k, r in segs
    ]
    idx = [i for i, (k, _) in enumerate(segs) if k == "T"]
    out = []
    for j, i in enumerate(idx):
        lo = idx[j - 1] + 1 if j > 0 else 0
        hi = idx[j + 1] if j + 1 < len(idx) else len(segs)
        lines_before = [r[0] for k, r in segs[lo:i] if k == "L" and r[0].strip()]
        if j == 0 and len(lines_before) == 1 and _RE_RUNNING_HEADER.match(lines_before[0].strip()):
            # ページの先頭の表の前にある 1 行だけの走りヘッダは柱とみなす
            lines_before = []
        before = any(is_body_line(x, furniture) for x in lines_before)
        after = any(is_body_line(r[0], furniture) for k, r in segs[i + 1 : hi] if k == "L")
        out.append({"body_before": before, "body_after": after})
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def _rows(table: dict) -> list[list[str]]:
    rows: dict[int, dict[int, str]] = {}
    for c in table.get("grid") or []:
        rows.setdefault(c["row"], {})[c["col"]] = c.get("text") or ""
    width = table.get("n_cols") or 0
    return [[r.get(ci, "") for ci in range(width)] for _, r in sorted(rows.items())]


def _enum_no(cell: str) -> int | None:
    m = _RE_ENUM.match(cell.strip())
    if not m:
        return None
    if m.group(1):
        return _CIRCLED.index(m.group(1)) + 1
    return int(unicodedata.normalize("NFKC", m.group(2)))


def continuation(prev: dict, nxt: dict) -> str | None:
    """形と続きの証拠（判定の 2・3）。続きなら根拠の名前、そうでなければ None。"""
    if not prev.get("grid") or not nxt.get("grid") or prev.get("n_cols") != nxt.get("n_cols"):
        return None
    a, b = _rows(prev), _rows(nxt)
    if not a or not b:
        return None
    if [_norm(x) for x in a[0]] == [_norm(x) for x in b[0]] and any(_norm(x) for x in a[0]):
        return "repeated_header"
    last = next((_enum_no(r[0]) for r in reversed(a) if _enum_no(r[0]) is not None), None)
    first = _enum_no(b[0][0])
    if _enum_no(a[0][0]) is not None and last is not None and first == last + 1:
        return "enum_sequence"
    return None


def merge(prev: dict, nxt: dict, reason: str, header: str = "infer") -> dict:
    """2 つの断片を 1 つの表にする。`reason == "repeated_header"` なら後の断片の 1 行目（再掲の見出し）を外す。"""
    a, b = _rows(prev), _rows(nxt)
    rows = a + (b[1:] if reason == "repeated_header" else b)
    frags = list(
        prev.get("fragments") or [{"id": prev["id"], "pages": prev["pages"], "n_rows": len(a)}]
    )
    frags.append({"id": nxt["id"], "pages": nxt["pages"], "n_rows": len(b)})
    reasons = list((prev.get("stitch") or {}).get("reasons") or [])
    reasons.append(reason)
    return {
        "id": prev["id"],
        "pages": sorted(set(prev["pages"]) | set(nxt["pages"])),
        "source": prev.get("source"),
        "n_rows": len(rows),
        "n_cols": prev["n_cols"],
        "grid": grid_from_pipe(rows, header),
        "fragments": frags,
        "stitch": {"reasons": reasons},
    }


def stitch_tables(
    tables: list[dict],
    layout_pages: dict[int, str],
    furniture: dict[int, list[str]] | None = None,
) -> list[dict]:
    """ページ順・ページ内の順に並んだ表の列を受け取り、続きと判定した隣り合う断片をつないだ列を返す。

    パイプ表（`source == "R2_layout_pipe"`）だけを対象にする。列挙表は段落の行から作るので Markdown 上の位置が
    違い、ここでは扱わない。ページの Markdown から数えた表の数が表のレコードと合わないページの表はつながない。
    `furniture` はページ → 柱の行（テキスト層から検出したもの）。柱は文書のどのページにも出うるので、
    全ページの柱を 1 つの集合にして照合する。
    """
    furn = (
        {furniture_key(x) for lines in furniture.values() for x in lines} - {""}
        if furniture is not None
        else None
    )
    ctx: dict[str, dict] = {}
    for page, text in layout_pages.items():
        pipes = [t for t in tables if t["pages"] == [page] and t.get("source") == "R2_layout_pipe"]
        c = pipe_table_context(text, furn)
        if len(c) == len(pipes):
            for t, x in zip(pipes, c, strict=True):
                ctx[t["id"]] = x

    # パイプ表だけの列で隣り合う断片を調べる（`tables_for_doc` はページごとにパイプ表の後へ列挙表を並べるので、
    # 元の列のまま隣を見ると、ページの最後のパイプ表の「次」が同じページの列挙表になってしまう）
    out: list[dict] = []
    last_pipe: int | None = None  # out の中で直前のパイプ表の位置
    for t in tables:
        if t.get("source") == "R2_layout_pipe" and last_pipe is not None:
            prev = out[last_pipe]
            reason = _candidate(prev, t, ctx, tables)
            if reason:
                out[last_pipe] = merge(prev, t, reason)
                continue
        out.append(t)
        if t.get("source") == "R2_layout_pipe":
            last_pipe = len(out) - 1
    return out


def _candidate(prev: dict, nxt: dict, ctx: dict[str, dict], tables: list[dict]) -> str | None:
    """判定の 1（隣り合う）を満たせば、2・3 の判定結果を返す。"""
    last_id = (prev.get("fragments") or [{"id": prev["id"]}])[-1]["id"]
    a, b = ctx.get(last_id), ctx.get(nxt["id"])
    if a is None or b is None:
        return None
    last_page = max(prev["pages"])
    first_page = nxt["pages"][0]
    if first_page == last_page + 1:
        # ページまたぎ：前はページの最後の表、後は次のページの最初の表
        on_last = [t for t in tables if t["pages"] == [last_page] and t["id"] in ctx]
        on_next = [t for t in tables if t["pages"] == [first_page] and t["id"] in ctx]
        if (
            not on_last
            or on_last[-1]["id"] != last_id
            or not on_next
            or on_next[0]["id"] != nxt["id"]
        ):
            return None
    elif first_page != last_page:
        return None
    # 段またぎ（同じページ）とページまたぎに共通：間に本文の行が無い
    if a["body_after"] or b["body_before"]:
        return None
    return continuation(prev, nxt)
