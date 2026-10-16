"""当事者と定義語（F3・T3.5・T3.6・C-007）。

**予測側のモジュールである。** 入力は条項木（PDF テキスト層から組んだもの）と LAYOUT の生テキストだけで、gold を開かない。

当事者（`parties`）
  前文の段落から `<名称>（以下「<呼称>」という。）` を拾う。名称は宣言の直前の、句読点・助詞で区切られた語。
  当事者欄（前文の前の `委託者株式会社…` の行）があれば役割名（`委託者`）を付ける。
  同じ呼称の宣言が複数あれば最初のものを採る。`以下「本契約」という` のような当事者でない宣言は、
  名称が会社・団体・人の形をしていないので落とす（役割欄か法人の語を持つ名称だけを当事者とする）。

定義語（`defined_terms`）
  1. 号・段落の先頭の `<語>とは、…をいう` （標準・様式型の定義条）
  2. 号の先頭の `<語>　…をいう`（漢数字方式の定義条。語の後に全角空白）。テキスト層の行では CJK の語の間の
     空白が消えるので（geometry._join_words）、doc.pdf の語の切れ目（`item_lead_words`）から語を取る
  3. 段落中の `「<語>」とは、…をいう`
  4. LAYOUT の定義表の行（移植元の `semantics.defined_terms`）
  語の列挙（辞書）は使わない。
"""

from __future__ import annotations

import re

from .structure.contract import PARTY_ROLES, RE_PARTY_FIELD
from .structure.tree import Tree

RE_DECL = re.compile(r"([^、。（）()「」\s]{2,40}?)[　 ]*[（(]以下「([^」]{1,10})」という。?[）)]")
# 法人・団体・人の名称の手掛かり（当事者でない宣言 `本契約` `本件業務` を落とす）
RE_ORG = re.compile(
    r"(?:株式会社|有限会社|合同会社|合資会社|合名会社|法人|組合|協会|機構|財団|社団|学校|病院|"
    r"医療|福祉|事務所|商店|町|市|村|県|都|府|国)"
)
RE_LEAD = re.compile(r"^(?:甲|乙|丙|丁|および|及び|ならびに|並びに|と|は|が|、)+")
RE_DEF_TOWA = re.compile(r"^[「]?([^、。「」（）()\s]{2,20}?)[」]?[　 ]*とは[、，]")
RE_DEF_SPACE = re.compile(r"^([^、。「」（）()\s]{2,20})[　]+\S.*(?:をいう|を意味する|とする)。?$")
RE_DEF_QUOTE = re.compile(r"「([^」]{2,20})」とは[、，]")


def _clean_name(raw: str) -> str:
    s = RE_LEAD.sub("", raw.strip())
    return s.strip("　 ")


def parties(tree: Tree, header_lines: list[str] | None = None) -> list[dict]:
    """前文の宣言から当事者を拾う。`header_lines` は前文より前の当事者欄の行（役割名を付けるのに使う）。"""
    roles: dict[str, str] = {}
    for s in (header_lines or [])[:40]:
        if RE_DECL.search(s):
            break  # 当事者欄は前文の宣言より前にある
        m = RE_PARTY_FIELD.match(s.strip())
        if not m:
            continue
        for r in sorted(PARTY_ROLES, key=len, reverse=True):
            if s.strip().startswith(r):
                roles[s.strip()[len(r) :].strip("　 ")] = r
                break
    out: list[dict] = []
    seen: set[str] = set()
    pre = [n for n in tree.nodes.values() if n.kind == "preamble"]
    nodes = []
    for p in pre:
        nodes += [tree.nodes[c] for c in p.children]
    if not nodes:  # 前文が取れなかった文書は本文の先頭の段落で代える
        nodes = [n for n in tree.nodes.values() if n.kind == "paragraph"][:2]
    for n in nodes:
        for m in RE_DECL.finditer(n.text):
            name, alias = _clean_name(m.group(1)), m.group(2)
            if alias in seen:
                continue
            role = roles.get(name)
            if role is None and not RE_ORG.search(name) and not any(name == v for v in roles):
                # 名称に法人の語が無く、当事者欄にも無い（`本契約`・個人名で欄が取れなかった場合）
                if not _is_person_like(name):
                    continue
            seen.add(alias)
            out.append(
                {
                    "alias": alias,
                    "name": name,
                    "role": role,
                    "declared_in": n.citation,
                    "page": (n.pages or [None])[0],
                }
            )
    if not out:
        # 宣言の無い文書（様式型の emp-0002）：当事者欄の役割名を呼称とする（gold の呼称も役割名）
        for name, role in roles.items():
            out.append({"alias": role, "name": name, "role": role, "declared_in": None, "page": 1})
    return out


def _is_person_like(name: str) -> bool:
    """個人名らしいか（労働者の氏名など）。漢字・かなだけで 2〜8 文字、契約の語（本・件・契約）を含まない。"""
    return bool(re.fullmatch(r"[一-龥ぁ-んァ-ヶ々ー　 ]{2,10}", name)) and not re.search(
        r"本|件|契約|業務|書", name
    )


RE_ITEM_HEAD = re.compile(r"^[（(][0-9０-９]{1,2}[）)]$")


def item_lead_words(doc_id: str) -> set[str]:
    """号の番号の直後にあり、次の語との間に 1 字以上の空きがある語（定義条の語の候補）。doc.pdf だけを読む。"""
    import pdfplumber

    from ..common.paths import doc_pdf

    out: set[str] = set()
    with pdfplumber.open(doc_pdf(doc_id)) as pdf:
        for page in pdf.pages:
            ws = page.extract_words(x_tolerance=1.5)
            for i, w in enumerate(ws[:-2]):
                if not RE_ITEM_HEAD.match(w["text"]):
                    continue
                a, b = ws[i + 1], ws[i + 2]
                same = abs(a["top"] - w["top"]) < 2 and abs(b["top"] - w["top"]) < 2
                gap = b["x0"] - a["x1"]
                size = (a["x1"] - a["x0"]) / max(1, len(a["text"]))
                if same and gap >= 0.8 * size and 2 <= len(a["text"]) <= 20:
                    out.add(a["text"])
    return out


def defined_terms(
    tree: Tree, table_terms: list[str] | None = None, lead_words: set[str] | None = None
) -> list[dict]:
    """定義語と定義箇所の引用。表由来（`table_terms`）は定義箇所を持たない。"""
    out: dict[str, dict] = {}
    for n in tree.nodes.values():
        if n.kind not in ("paragraph", "item"):
            continue
        text = n.text.strip()
        hits: list[str] = []
        m = RE_DEF_TOWA.match(text)
        if m:
            hits.append(m.group(1))
        elif n.kind == "item":
            m = RE_DEF_SPACE.match(text)
            if m:
                hits.append(m.group(1))
            elif re.search(r"(?:をいう|を意味する)。?$", text):
                hits += [
                    w for w in (lead_words or ()) if text.startswith(w) and len(text) > len(w)
                ][:1]
        hits += RE_DEF_QUOTE.findall(text)
        for t in hits:
            t = t.strip("「」　 ")
            if t and t not in out:
                out[t] = {"term": t, "defined_in": n.citation, "source": "text"}
    for t in table_terms or []:
        out.setdefault(t, {"term": t, "defined_in": None, "source": "table"})
    return list(out.values())
