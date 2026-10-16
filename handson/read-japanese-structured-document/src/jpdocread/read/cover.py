"""表紙から `meta`（題名・商品名・愛称・発行者・版）を取る（S7）。予測側・R2 キャッシュのみ。

W14 まで `meta` は `{}` だった（「推測で埋めない」）。商品名は `scoped` クエリ（118 件）の
絞り込みに要るので、**行の性質だけ**から取る — 語彙の列挙はしない（V2 の禁則）：

- 発行者：`…株式会社` / `…相互会社` / `…組合` で終わる行
- 愛称：`<…>`（LAYOUT は `&lt;…&gt;` とエスケープする）
- 版：`YYYY年M月D日` を含む行
- 題名：残りの最初の行。題名末尾の文書種別（`約款`・`ご契約のしおり` 等）を外したものを商品名とする
"""

from __future__ import annotations

import html
import re

RE_ISSUER = re.compile(r"(?:株式会社|相互会社|組合)$")
RE_NICK = re.compile(r"^<\s*(.+?)\s*>$")
RE_EDITION = re.compile(r"[0-9０-９]{4}年[0-9０-９]{1,2}月[0-9０-９]{1,2}日")
RE_DOCTYPE = re.compile(
    r"\s*(?:普通保険約款(?:および特約条項)?|ご契約のしおり[・･]?約款|ご契約のしおり|約款集?|定款|重要事項等?説明書)\s*$"
)


def cover_meta(first_page: str) -> dict:
    lines = [html.unescape(ln).strip().lstrip("#").strip() for ln in first_page.split("\n")]
    lines = [ln for ln in lines if ln]
    meta = {"title": "", "product_name": "", "nickname": "", "issuer": "", "edition_date": ""}
    for ln in lines[:12]:
        m = RE_NICK.match(ln)
        if m and not meta["nickname"]:
            meta["nickname"] = m.group(1)
        elif RE_ISSUER.search(ln) and not meta["issuer"]:
            meta["issuer"] = ln
        elif RE_EDITION.search(ln) and not meta["edition_date"]:
            meta["edition_date"] = RE_EDITION.search(ln).group(0)
        elif not meta["title"] and not ln.endswith(("。", "）")):
            meta["title"] = ln
    t = meta["title"]
    if meta["issuer"] and t.startswith(meta["issuer"]):
        t = t[len(meta["issuer"]) :]
    t = re.sub(r"[〈<].+?[〉>]$", "", RE_DOCTYPE.sub("", t)).strip()  # 題名末尾の愛称
    meta["product_name"] = t or meta["nickname"]
    return meta


def meta_for_doc(doc_id: str) -> dict:
    from .parse.r12_cortex import parse_doc

    parsed = parse_doc(doc_id, reader="R2", cache_only=True)
    first = parsed.pages.get(min(parsed.pages)) if parsed.pages else ""
    return cover_meta(first or "")
