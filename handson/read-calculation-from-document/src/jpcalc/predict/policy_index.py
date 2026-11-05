"""pdoc の索引と本文の展開（予測側）。

- 全ノード・ブロックを id で引けるようにし、親子関係（祖先の条・特約）を持つ
- {const:key} を meta.constants の値に、{term:key} を定義語に、{ref:...} を参照先の見出しに、{fn:...} を脚注番号に展開する
"""

from __future__ import annotations

import re

SECTIONS = ("front_matter", "body", "appendices", "back_matter")
MARK = re.compile(r"\{(const|term|ref|fn|b):([^}]*)\}")


class PolicyIndex:
    def __init__(self, policy: dict):
        self.policy = policy
        self.constants: dict[str, str] = dict(policy.get("meta", {}).get("constants") or {})
        self.by_id: dict[str, dict] = {}
        self.parent: dict[str, str | None] = {}
        self.order: list[str] = []
        for sec in SECTIONS:
            v = policy.get(sec)
            for it in v if isinstance(v, list) else [v] if isinstance(v, dict) else []:
                self._walk(it, None)
        self.terms = self._terms(policy.get("defined_terms"))
        self.labels = policy.get("derived", {}).get("labels", {}) or {}
        self.dtables = policy.get("derived", {}).get("tables", {}) or {}
        self.dfigures = policy.get("derived", {}).get("figures", {}) or {}

    def _walk(self, o, parent):
        if isinstance(o, dict):
            oid = o.get("id")
            if oid:
                self.by_id[oid] = o
                self.parent[oid] = parent
                self.order.append(oid)
                parent = oid
            for k in ("children", "blocks", "items", "rows"):
                for c in o.get(k) or []:
                    if isinstance(c, dict):
                        self._walk(c, parent)
        elif isinstance(o, list):
            for c in o:
                self._walk(c, parent)

    @staticmethod
    def _terms(dt) -> dict[str, str]:
        out = {}
        items = (
            dt
            if isinstance(dt, list)
            else (dt or {}).get("terms", [])
            if isinstance(dt, dict)
            else []
        )
        for t in items:
            if isinstance(t, dict):
                key = t.get("key") or t.get("id")
                if key:
                    out[key] = t.get("term") or t.get("label") or t.get("text") or key
        return out

    def expand(self, text: str | None) -> str:
        if not text:
            return ""

        def rep(m):
            kind, key = m.group(1), m.group(2)
            if kind == "const":
                return self.constants.get(key, m.group(0))
            if kind == "term":
                return self.terms.get(key, key)
            if kind == "ref":
                tgt = key.split("|")[0]
                lab = self.labels.get(tgt, {})
                return lab.get("citation") or tgt
            if kind == "fn":
                return ""
            return key

        return MARK.sub(rep, text)

    def ancestors(self, uid: str) -> list[str]:
        out = []
        p = self.parent.get(uid)
        while p:
            out.append(p)
            p = self.parent.get(p)
        return out

    def resolve(self, uid: str) -> str:
        """脚注の注の id（`<ブロック>__n<番号>`）はブロックの id に寄せる。"""
        if uid not in self.by_id and "__n" in uid and uid.split("__n")[0] in self.by_id:
            return uid.split("__n")[0]
        return uid

    def container(
        self, uid: str, kinds=("article", "appendix_section", "appendix", "rider")
    ) -> str | None:
        uid = self.resolve(uid)
        for a in [uid, *self.ancestors(uid)]:
            n = self.by_id.get(a, {})
            if n.get("kind") in kinds:
                return a
        return None

    def citation(self, uid: str) -> str:
        return (self.labels.get(uid) or {}).get("citation") or ""
