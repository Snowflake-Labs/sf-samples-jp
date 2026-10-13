"""S4 (B) — 行分割の作り直し。

構造抽出の入力は「行」である。行が間違っていれば、どんな見出し規則を足しても
構造は直らない。ここは**行の側**を直す。

**見つかった機構：柱（走りヘッダ）で編と章が 1 行に連結される。**
```
p9 L0 '第２編普通保険約款第２章保険契約の締結および維持'
```
この行は先頭が `第２編` なので編の見出しとして食われ、**中に埋まった `第２章` が
章として認識されない**。life 文書の条 recall が 0.000 だったのはこれが主因で、
「見出し規則の不足」ではなく「行の作り方の不足」だった。
"""

from __future__ import annotations

import re

# 構造見出しの語尾。条まで含めるのは、柱に条が入る体裁があるため。
RE_HEAD_TOKEN = re.compile(r"第[0-9０-９]+(?:編|章|節|条)")
# 文末・列挙の記号。これがある行は**本文**なので分割しない
# （例：`第２編第１章第２条に、お支払いできない場合は第２編第１章第３条に定めています。`）。
SENTENCE_MARKS = "。、，．？！"
# 連結見出し行の長さの上限。これを超える行は本文とみなす。
MAX_JOINED_LEN = 70
# **参照の否定規則を行分割にも当てる。** 番号トークンの直後がこれらで始まるなら、
# それは見出しではなく本文中の参照である。
# これが無いと `第10条の規定により第12条を準用する` を 2 行に刻んでしまう
# （句点が無く短いので、長さと文末記号の条件では守れない）。
RE_REF_SUFFIX = re.compile(
    r"^(?:の規定|に定め|に規定|および|又は|または|、|から|まで|の定め|に掲げ|による|"
    r"に基づ|の適用|の場合|とあるのは|に準じ|を準用|ただし|の規定中|により|を除)"
)


def split_joined_headings(line: str) -> list[str]:
    """連結された構造見出し行を分割する。分割しない場合は 1 要素で返す。

    **分割する条件（すべて満たすとき）：**
    1. 行に文末記号（`。`『、』など）が無い — あれば本文である
    2. 行が十分短い（`MAX_JOINED_LEN` 以下）
    3. 見出しトークンが 2 個以上あり、**行の先頭がトークンで始まる**
    4. 分割後の各断片が「トークン ＋ 短い題名」の形になる

    条件 1・2 が本文中の参照を守る。約款の本文は参照で飽和しているので、
    ここを緩めると `第5条の規定にかかわらず…` のような行を刻んでしまう
    （本文中の参照を見出しにしない否定規則と同じ発想を、行の側に置いたもの）。
    """
    s = line.strip()
    if not s or len(s) > MAX_JOINED_LEN:
        return [line]
    if any(ch in s for ch in SENTENCE_MARKS):
        return [line]
    hits = list(RE_HEAD_TOKEN.finditer(s))
    if len(hits) < 2 or hits[0].start() != 0:
        return [line]
    # 2 個目以降のトークン位置で切る
    cuts = [h.start() for h in hits]
    parts = [s[a:b].strip() for a, b in zip(cuts, cuts[1:] + [len(s)], strict=False)]
    parts = [p for p in parts if p]
    # 各断片が「トークンで始まる」ことを確認。崩れていたら触らない。
    if not all(RE_HEAD_TOKEN.match(p) for p in parts):
        return [line]
    # どれか 1 つでもトークン直後が参照の言い回しなら、行全体が本文である。
    for p in parts:
        m = RE_HEAD_TOKEN.match(p)
        if m and RE_REF_SUFFIX.match(p[m.end() :]):
            return [line]
    return parts


def split_page_text(text: str) -> str:
    """ページ本文の各行に `split_joined_headings` を当てて返す。"""
    out: list[str] = []
    for line in text.split("\n"):
        out.extend(split_joined_headings(line))
    return "\n".join(out)


RE_TOC_ENTRY = re.compile(
    # 目次行 = 「見出し ＋ 末尾の裸のページ番号」。本文の見出しが裸の数字で終わることはない。
    # **`編` と特約名を含めること。** 当初は `章|節|条` と `別表` だけだったため
    # `第２編普通保険約款8` が目次行として落ちず、編の番号が本文に入る前に進んでいた
    # （life 文書の条 recall 0.136 の主因。見出し規則ではなく除外語彙の穴だった）。
    # **撤回した拡張（W8）：** `（重大な事由があるときの解除）12` のような
    # 「括弧付き題名＋ページ番号」を目次行に加える案を試したが、
    # **39 文書すべてで数値が 1 つも動かなかった**（括弧行は上位見出しの候補を
    # 作らないので、目次ブロックの外に残っても害が無い）。再試行しないこと。
    #
    # **`附則` を追加した（W13 T45）。** `編` と同じ形の語彙の穴だった。
    # `teikan-0001/2/3` の p2（目次）にある `附則11` が目次行と判定されず、
    # **p2 で `附則` の容器が開いて本文 p11 の `附則` が `_dup` に吸収され**、
    # 配下の `第1 施行期日`〜`第3 定款の変更の経過` が容器を持てなかった
    # （`appendix_section` 欠落 13 件のうち 9 件・W12 T38 機構 1）。
    # **`附則` は番号を持たないので、番号の連続性では目次側と本文側を区別できない。**
    # 区別できるのは「末尾に裸のページ番号があるか」だけである。
    r"^(?:第[0-9０-９]+(?:編|章|節|条)|別表[0-9０-９]+|付表[0-9０-９]+|附則|\S{2,30}?特約(?:条項)?)"
    r".*?[0-9０-９]{1,3}$"
)

# **目次行の否定記号（W12 T36）。** `RE_TOC_ENTRY` は「見出しの形＋末尾の裸の数字」しか
# 見ないので、**段の右端で文の途中で折り返し、たまたま数字で終わった本文行**を目次行として
# 落としていた。実例（`group-0001` p6・`item` 欠落 9 件すべての原因）：
#
#     第7条保険金は、その請求に必要な書類が当会社に到着した日の翌営業日からその日を含めて5
#                                                                     ~~~~~~~~~~~~^ 「5営業日」の 5
#
# 行頭が `第7条` で末尾が `5` なので一致する。落とされた結果 `第7条` が開かず、
# 配下の項と号が前条（`第6条`）に吸収されていた。
#
# **分布を数えてから入れた規則である**（規律 8）。ALL 39 で目次行として
# 落としている 535 行のうち `、` を含むのは **8 行だけで、8 行すべてが本文の誤判定**だった。
# 真の目次行 527 行に `、` は 1 件も無い。`，` `？` `！` は真偽どちらにも現れない（0 件）ので
# 併せて否定に入れても挙動は変わらないが、記号集合の意図を明示する意味で含める。
#
# **`．` は意図的に除外する。** `1．` は号のラベル体裁であり、`1．総則5` のような
# 目次行が存在し得る。実測 0 件なので今は効かないが、入れると将来静かに壊れる。
TOC_NEGATIVE_MARKS = "。、，？！"


def is_toc_line(s: str, pattern: re.Pattern[str] = RE_TOC_ENTRY) -> bool:
    """`s` が目次行か。**判定はここ 1 箇所に置く。**

    以前は呼び出し 4 箇所が `pattern.match(s) and "。" not in s` を各々書いていた。
    決定点が 2 箇所ある設計で、実際 W8 では
    組み立て側だけを直してデコーダ側が取り残される食い違いが起きている。

    `pattern` は文法ごとの目次行規則（`grammars.Grammar.toc_entry`）を差し替えるため。
    """
    return bool(pattern.match(s)) and not any(m in s for m in TOC_NEGATIVE_MARKS)


# **分離した目次（F16・D-024）。** 2 段組みの目次では、見出しの列とページ番号の列が別の行の塊として
# 取り出される（`auto-0010` p2：`もくじ` / `第１章用語の定義` … `第３章人身傷害条項` / `4` `4` `5` … `6`）。
# 見出し行の末尾に数字が付かないので `RE_TOC_ENTRY` に一致せず、ページも目次ページと判定されない。
# 前の容器は W17-B（本文を持たない容器）で抑止されるが、**最後の章だけは本物の本文の条を
# 配下に吸って本文を持つ**ので漏れ、本文の同じ章見出しが `_dup` で捨てられて、
# 配下の条が 1 つ前の章に付く（dev の auto・golf で引用誤りの大半）。
RE_TOC_HEAD = re.compile(
    r"^(?:第[0-9０-９]+(?:編|章|節|条)|別表[0-9０-９]+|付表[0-9０-９]+|附則|\S{2,30}?特約(?:条項)?)"
)
RE_BARE_PAGE_NO = re.compile(r"^[0-9０-９]{1,3}$")
RE_TOC_TITLE = re.compile(r"^(?:も\s*く\s*じ|目\s*次)$")
SPLIT_TOC_MIN = 3


def split_toc_cut(pages: dict[int, str]) -> dict[int, int]:
    """分離した目次の見出し列の最後の行番号を返す（ページ → 行番号。`toc_block_end` と同じ意味）。

    条件（すべて満たすときだけ）：
      1. 裸のページ番号の行が SPLIT_TOC_MIN 行以上続き、値が減らない。
      2. その直前に、目次の見出しの形（`RE_TOC_HEAD`）で否定記号を含まない行が SPLIT_TOC_MIN 行以上続く。
      3. その見出し列の直前が目次の題（`もくじ`・`目次`）。ページの先頭から始まる列（目次の続きのページ）は
         対象にしない。`health-0003` p4 では区間が短く切れ、W17-B の抑止と食い違って偽の条が 4 件出た。
    本文の見出しの後に裸の数字が 3 行以上、昇順で続くことは無い。3 は目次の題で始まる見出し列だけに当てる。
    """
    out: dict[int, int] = {}
    for pg, text in pages.items():
        rows = [x.strip() for x in (text or "").split("\n")]
        j = 0
        while j < len(rows):
            if not RE_BARE_PAGE_NO.match(rows[j]):
                j += 1
                continue
            k = j
            while k < len(rows) and RE_BARE_PAGE_NO.match(rows[k]):
                k += 1
            nums = [
                int(x.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
                for x in rows[j:k]
            ]
            h = j
            while (
                h > 0
                and RE_TOC_HEAD.match(rows[h - 1])
                and not any(m in rows[h - 1] for m in TOC_NEGATIVE_MARKS)
            ):
                h -= 1
            titled = h > 0 and bool(RE_TOC_TITLE.match(rows[h - 1]))
            if (
                k - j >= SPLIT_TOC_MIN
                and nums == sorted(nums)
                and j - h >= SPLIT_TOC_MIN
                and titled
            ):
                out[pg] = max(out.get(pg, -1), j - 1)
            j = k
    return out


def toc_block_end(pages: dict[int, str], toc: set[int]) -> dict[int, int]:
    """目次抑止ページごとに「最後の目次行のページ内行番号」を返す（W8）。

    戻り値の行番号**以下**が目次ブロック、それより後は本文である。

    **ページ単位で抑止してはならない。** 目次と本文が同居するページがある。
    teikan の p2 は

        [柱] 第１章総則 / もくじ / 第１章総則2 …（目次 9 行）/ 附則11
        / 第１章総則（本文の章見出し）/ 第１条（商号）/ 本文…

    という構造で、ページ全体を抑止すると **gold の `第1章 第1〜5条` が丸ごと落ちる**。
    目次行は末尾に裸のページ番号を持つ（`RE_TOC_ENTRY`）ので、そのページで
    最後に目次行が現れた位置より後は本文と判断できる。

    目次行が 1 行も無いページは**ページ末尾**を返す（＝従来どおり全体を抑止）。
    呼び出し側の `toc` には「裸の見出し列ページ」（auto の p3–4、番号もページ番号も
    持たない見出しだけが並ぶページ）も含まれるので、そこは目次行に一致しない。

    **この関数は組み立て側（`tree.Builder`）とデコーダ側
    （`candidates.build_candidates`）の両方が使う。** 片方だけ直すと、
    見出しは開くのに採用集合に無い（またはその逆）という食い違いが起きる
    — 実際 W8 の第 1 案では組み立て側だけを直し、teikan の第1条〜第3条が
    「大域デコードが非採用」で落ち続けた。
    """
    out: dict[int, int] = {}
    for pg in toc:
        lines = (pages.get(pg) or "").split("\n")
        last = -1
        for j, ln in enumerate(lines):
            s = ln.strip()
            if is_toc_line(s):
                last = j
        if last < 0:
            out[pg] = len(lines)
            continue
        out[pg] = last
    return out
