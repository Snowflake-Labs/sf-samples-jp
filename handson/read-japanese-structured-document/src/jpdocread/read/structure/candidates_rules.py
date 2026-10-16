"""見出し行の正規表現を、`toc` と `candidates` の**両方から**使うための小さな層。

`toc.outline_pages` が「見出しばかりのページ」を判定するのに見出し規則を要り、
`candidates` が目次ページを除外するのに `toc` を要る。
**この 2 つを直接 import させると循環する**ので、共通部分だけをここに置く。
"""

from __future__ import annotations

from .tree import RE_ARTICLE, RE_CHAPTER, RE_PART, RE_SECTION

# 上位から順。`第1編` と `第1条` は競合しない。
HEAD_RULES = (RE_PART, RE_CHAPTER, RE_SECTION, RE_ARTICLE)
HEAD_RULES_BY_KIND = (
    ("part", RE_PART),
    ("chapter", RE_CHAPTER),
    ("section", RE_SECTION),
    ("article", RE_ARTICLE),
)
