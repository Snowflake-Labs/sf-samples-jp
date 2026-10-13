"""構造の追加指標（W9 まで未実装だったもの）。

W9 終了時点で §10.2 の 10 要求のうち充足は 4 件だった。ここで残りを実装する。

| 関数 | §10.2 の要求 | なぜ要るか |
|---|---|---|
| `leakage` | **漏出率** | W7〜W9 で直した 5 件の誤りは**すべて漏出・混入の形**だった。指標が無かったので原因が数値で見えなかった |
| `number_integrity` | 番号整合性 | 実装済み（`Tree.number_violations`）だが**一度も報告されていない** |
| `nted` | nTED | 条・段落の recall は「個々の引用が当たったか」しか見ない。**木の形が崩れていても高く出る** |
| `pk_windowdiff` | P_k / WindowDiff | 境界の誤りを「近いか遠いか」で区別する。完全一致率は距離を見ない |
| `kind_confusion` | `node_kind` 混同行列（9 種） | どの種別を**どの種別と**間違えたかが分かる |
| `reading_order_tau` | 読み順 Kendall τ | 2 段組の読み順崩れを構造側から測る |
| `ref_resolution` | 参照解決 P/R | 未解決の参照は見出し欠落か番号誤りの兆候（§5.7） |
| `heading_pr_by_level` | 見出し P/R/F1（レベル別） | 従来は採用集合でしか測っていなかった |

**設計上の約束**

1. **すべて gold の citation 文字列を介して対応づける。** 予測側の `node_id` と gold の
   `element_id` は別の体系なので、id で突き合わせると偽の失敗を報告する
   （`fewshot_img` F9 が図の id で踏んだのと同じ罠）。
2. **対応づけ率（`*_coverage`）を必ず併記する。** 対応づかなかったぶんを黙って
   分母から落とすと、指標が「対応づいたものだけ」の話になって実態より良く見える。
3. **退化ケースを必ずテストする**（`tests/test_w10_metrics.py`）。全一致で 0、
   全不一致で 1 になることを確認しないと、指標は静かに壊れる。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from ..read.structure.tree import DEPTH, RE_ART_LABEL_ONLY, Tree, canonical_citation
from .gold import load_elements, load_layout, load_source

NULL = "∅"  # 混同行列で「対応相手が無い」を表す
CIRCLED_GOLD = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"
KINDS = tuple(DEPTH)  # 9 種（part…item）


def _flat(s: str) -> str:
    """比較用の平坦化。空白と全半角の差は組版の差であって別の文字列ではない。"""
    return "".join(unicodedata.normalize("NFKC", s or "").split())


# ---------------------------------------------------------------- 漏出率


@dataclass
class Leakage:
    """漏出率 — 柱・ページ番号が本文ノードに混入した割合。

    **柱とフッタを分けて報告する。** 理由は非対称である：

    - **フッタは曖昧でない。** `2 Ｈ２６１００１`（ページ番号＋帳票コード）は
      本文に現れ得ない文字列なので、一致したら確実に漏出である。
    - **柱は曖昧である。** teikan の柱 `第１章　総則` は**正当な章見出しと同一文字列**
      なので、章ノードがそれを持っているのは漏出ではない。よって柱の漏出は
      **本文ノード（paragraph / item）に限って**数え、その限定を明記する。

    `heading_leak` は別枠である。柱が上位見出しとして採用された件数 — W8 で直した
    誤りの形そのものであり、**最も高くつく漏出**（章境界がずれると配下の全引用が外れる）。
    """

    n_nodes: int = 0
    n_body_nodes: int = 0
    footer_leak: int = 0
    header_leak: int = 0
    heading_leak: int = 0
    n_chars: int = 0
    leak_chars: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        """本文ノードのうち漏出を含むものの割合。"""
        return (
            (self.footer_leak + self.header_leak) / self.n_body_nodes if self.n_body_nodes else 0.0
        )

    @property
    def rate_chars(self) -> float:
        return self.leak_chars / self.n_chars if self.n_chars else 0.0

    def as_metrics(self) -> dict:
        return {
            "leakage_rate": round(self.rate, 6),
            "leakage_rate_chars": round(self.rate_chars, 6),
            "leakage_footer": self.footer_leak,
            "leakage_header": self.header_leak,
            "leakage_heading": self.heading_leak,
            "leakage_body_nodes": self.n_body_nodes,
            "leakage_nodes": self.n_nodes,
            # 文字単位のマイクロ平均を後段で取れるように、分子・分母をそのまま出す。
            "leakage_leak_chars": self.leak_chars,
            "leakage_chars": self.n_chars,
        }


BODY_KINDS = ("paragraph", "item")
UPPER_KINDS = tuple(k for k in DEPTH if k not in BODY_KINDS)


def furniture_strings(doc_id: str) -> dict[int, dict[str, set[str]]]:
    """ページごとの柱・フッタの文字列を gold から取る（**採点側のみ**）。

    `layout.json.pages[].header` / `.footer` がそのまま柱・フッタである。
    フッタは `2 Ｈ２６１００１` のようにページ番号と帳票コードの連結なので、
    **連結形とページ番号を除いた残り**の両方を候補に入れる。ページ番号だけの
    一致は本文の数字と衝突するので**入れない**。
    """
    out: dict[int, dict[str, set[str]]] = {}
    for p in load_layout(doc_id)["pages"]:
        cur: dict[str, set[str]] = {"header": set(), "footer": set()}
        for slot in ("header", "footer"):
            f = p.get(slot)
            if not f or not (f.get("text") or "").strip():
                continue
            t = _flat(f["text"])
            if t:
                cur[slot].add(t)
            # 先頭のページ番号を落とした残り（帳票コード）も漏出の徴候になる。
            tail = re.sub(r"^[0-9]+", "", t)
            if len(tail) >= 4:
                cur[slot].add(tail)
        out[p["number"]] = cur
    return out


def leakage(doc_id: str, tree: Tree) -> Leakage:
    fur = furniture_strings(doc_id)
    lk = Leakage()
    for n in tree.nodes.values():
        lk.n_nodes += 1
        pages = n.pages or []
        cand_h: set[str] = set()
        cand_f: set[str] = set()
        for pg in pages:
            cand_h |= fur.get(pg, {}).get("header", set())
            cand_f |= fur.get(pg, {}).get("footer", set())
        if n.kind in UPPER_KINDS:
            # 上位見出しの漏出：柱がそのまま見出しになった件数。
            # **見出し文字列が柱と一致しても、それが本物の見出しであることはあり得る。**
            # よって「柱と一致し、かつ同じ文書内に同一 citation の重複がある」ものに限る
            # ような強い条件は置かず、件数だけを報告して帰属は §6.3 に委ねる。
            head = _flat(f"{n.label}{n.heading}")
            if head and head in cand_h:
                lk.heading_leak += 1
            continue
        if n.kind not in BODY_KINDS:
            continue
        lk.n_body_nodes += 1
        body = _flat(n.text)
        lk.n_chars += len(body)
        hit = ""
        for s in cand_f:
            if s and s in body:
                lk.footer_leak += 1
                hit = s
                break
        if not hit:
            for s in cand_h:
                if s and s in body:
                    lk.header_leak += 1
                    hit = s
                    break
        if hit:
            lk.leak_chars += len(hit)
            if len(lk.examples) < 5:
                lk.examples.append(f"{n.citation}: …{hit}…")
    return lk


# ---------------------------------------------------------------- 番号整合性


def _violation_keys(viol: list[str]) -> set[tuple[str, str]]:
    """違反の記述 `"<kind> <citation>: prev → cur"` を `(kind, citation)` に落とす。"""
    out: set[tuple[str, str]] = set()
    for v in viol:
        head = v.split(":", 1)[0].strip()
        kind, _, cit = head.partition(" ")
        if kind:
            out.add((kind, canonical_citation(cit)))
    return out


def gold_number_violations(doc_id: str) -> list[str]:
    """**gold 自身**の番号違反を、予測側と同一の検出器で数える。

    `Tree.number_violations` と同じ規則（同じ親のもとでの単調増加）を gold の
    `elements.jsonl` に当てる。gold 側にも同じ飛びがあるなら、
    **それは我々の組み立ての誤りではなく印刷面の事実である**。
    """
    els = {e["element_id"]: e for e in load_elements(doc_id) if e.get("node_kind")}
    groups: dict[tuple[str | None, str], list[dict]] = {}
    for e in els.values():
        groups.setdefault((e.get("parent_id"), e["node_kind"]), []).append(e)
    bad: list[str] = []
    for (_, kind), ns in groups.items():
        prev = 0
        for e in ns:
            lab = (e.get("label") or "").translate(Z2H)
            # **予測側と同一規則**（`RE_ART_LABEL_ONLY`。W11 T30）。
            # 条ノード自身の連番検査は殺さない（条ラベルの再掲だけを除外する）。
            if kind != "article" and RE_ART_LABEL_ONLY.match(lab):
                continue
            m = re.search(r"([0-9]+)", lab)
            if not m:
                if kind == "paragraph" and lab in CIRCLED_GOLD:
                    cur = CIRCLED_GOLD.index(lab) + 1
                else:
                    continue
            else:
                cur = int(m.group(1))
            # **予測側と同一規則にする**（`Tree.number_violations` と 1 行ずつ対応させる）。
            # 揃えていないと、検出器の差が「gold 由来かどうか」の分類に化ける。
            if cur <= prev and cur != 1:
                bad.append(f"{kind} {canonical_citation(e.get('citation') or '')}: {prev} → {cur}")
            prev = cur
    return bad


def number_integrity(doc_id: str, tree: Tree) -> dict:
    """番号の飛び・重複・リセット違反。

    **番号を「整えない」のが規約である**（§1.10）。よってここは**修復ではなく計測**である。

    > **★ D-15 の決定（2026-09-25・「番号を捏造しない」）に従って分離する。**
    > §10.2 は当初「修復後の目標は 0」と書いていたが、§1.10 と矛盾していた。
    > `第10条` の次が `第12条` と印刷されているなら我々は `第11条` を捏造しないので、
    > **gold 由来の飛びは違反として残り続け、総数が 0 になることは原理的にあり得ない。**
    > よって 2 つに分ける：
    >
    > - **`number_violations_intrinsic`** — gold 側に同じ飛びが**無い**もの。
    >   **我々の組み立てが作った違反であり、目標は 0。**
    > - **`number_violations_gold_origin`** — gold 側にも同じ飛びが**ある**もの。
    >   **目標を置かない。** 件数と位置を報告する。
    >
    > **総数だけを報告してはならない** — W10 は総数 159 件しか出せず、
    > そのうちどれが我々の誤りかを言えなかった。
    """
    viol = tree.number_violations()
    gold_keys = _violation_keys(gold_number_violations(doc_id))
    intrinsic = [v for v in viol if _violation_keys([v]) - gold_keys]
    gold_origin = [v for v in viol if _violation_keys([v]) & gold_keys]
    return {
        "number_violations": len(viol),
        # **D-15：目標 0 はこちらだけに掛かる。**
        "number_violations_intrinsic": len(intrinsic),
        # **D-15：こちらに目標を置かない**（§1.10 により捏造しないので残る）。
        "number_violations_gold_origin": len(gold_origin),
        "number_violations_gold_total": len(gold_keys),
        "number_violations_by_kind": dict(Counter(v.split()[0] for v in viol)),
        "n_resyncs": len(tree.resyncs),
        "violation_examples_intrinsic": intrinsic[:5],
        "violation_examples_gold_origin": gold_origin[:5],
    }


# ---------------------------------------------------------------- 木の編集距離


@dataclass
class LabeledTree:
    """Zhang–Shasha 用の左から右への後行順（postorder）表現。"""

    labels: list[tuple[str, str]] = field(default_factory=list)
    lmld: list[int] = field(default_factory=list)  # leftmost leaf descendant（postorder index）

    def __len__(self) -> int:
        return len(self.labels)

    def keyroots(self) -> list[int]:
        seen: set[int] = set()
        kr = []
        for i in range(len(self) - 1, -1, -1):
            if self.lmld[i] not in seen:
                seen.add(self.lmld[i])
                kr.append(i)
        return sorted(kr)


def _postorder(
    children: dict[str, list[str]], roots: list[str], label: dict[str, tuple[str, str]]
) -> LabeledTree:
    t = LabeledTree()
    index: dict[str, int] = {}

    def walk(nid: str) -> int:
        left = None
        for c in children.get(nid, []):
            got = walk(c)
            if left is None:
                left = got
        i = len(t.labels)
        t.labels.append(label[nid])
        t.lmld.append(left if left is not None else i)
        index[nid] = i
        return t.lmld[i]

    # 仮想の根を置かない。複数根は forest として扱い、根を 1 つの仮想ノードで束ねる
    # と編集距離が根の rename で 1 増えるだけなので、**両側に同じ仮想根を置く**。
    for r in roots:
        walk(r)
    vi = len(t.labels)
    t.labels.append(("__root__", ""))
    t.lmld.append(t.lmld[0] if t.lmld else vi)
    return t


def tree_edit_distance(a: LabeledTree, b: LabeledTree) -> int:
    """Zhang–Shasha。挿入・削除・rename のコストはすべて 1。"""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return max(n, m)
    td = [[0] * m for _ in range(n)]
    for i in a.keyroots():
        for j in b.keyroots():
            ai, bj = a.lmld[i], b.lmld[j]
            w, h = i - ai + 2, j - bj + 2
            fd = [[0] * h for _ in range(w)]
            for x in range(1, w):
                fd[x][0] = fd[x - 1][0] + 1
            for y in range(1, h):
                fd[0][y] = fd[0][y - 1] + 1
            for x in range(1, w):
                for y in range(1, h):
                    ii, jj = ai + x - 1, bj + y - 1
                    if a.lmld[ii] == ai and b.lmld[jj] == bj:
                        cost = 0 if a.labels[ii] == b.labels[jj] else 1
                        fd[x][y] = min(fd[x - 1][y] + 1, fd[x][y - 1] + 1, fd[x - 1][y - 1] + cost)
                        td[ii][jj] = fd[x][y]
                    else:
                        p, q = a.lmld[ii] - ai, b.lmld[jj] - bj
                        fd[x][y] = min(
                            fd[x - 1][y] + 1,
                            fd[x][y - 1] + 1,
                            fd[p][q] + td[ii][jj],
                        )
    return td[n - 1][m - 1]


def gold_labeled_tree(doc_id: str) -> LabeledTree:
    els = [e for e in load_elements(doc_id) if e.get("node_kind")]
    ids = {e["element_id"] for e in els}
    children: dict[str, list[str]] = {}
    label: dict[str, tuple[str, str]] = {}
    roots = []
    for e in els:
        eid = e["element_id"]
        label[eid] = (e["node_kind"], _flat(e.get("label") or ""))
        pid = e.get("parent_id")
        if pid in ids:
            children.setdefault(pid, []).append(eid)
        else:
            roots.append(eid)
    return _postorder(children, roots, label)


def pred_labeled_tree(tree: Tree) -> LabeledTree:
    children = {nid: list(n.children) for nid, n in tree.nodes.items()}
    label = {nid: (n.kind, _flat(n.label)) for nid, n in tree.nodes.items()}
    return _postorder(children, list(tree.roots), label)


def nted(doc_id: str, tree: Tree) -> dict:
    """ノード数で正規化した木編集距離。

    正規化は `max(|gold|, |pred|)` で割る。**和で割らない** — 和で割ると
    空の木を出しただけで 0.5 に収まってしまい、「何も出さない」実装が有利になる。
    """
    g, p = gold_labeled_tree(doc_id), pred_labeled_tree(tree)
    d = tree_edit_distance(g, p)
    denom = max(len(g), len(p)) or 1
    return {
        "nted": round(d / denom, 6),
        "ted": d,
        "nted_gold_nodes": len(g) - 1,  # 仮想根を除く
        "nted_pred_nodes": len(p) - 1,
    }


# ---------------------------------------------------------------- 境界（P_k / WindowDiff）


def _gold_paragraph_sequence(doc_id: str) -> list[tuple[str, str]]:
    """gold の段落を文書順に並べ、`(平坦化本文, 所属条の citation)` を返す。"""
    els = {e["element_id"]: e for e in load_elements(doc_id)}
    out = []
    for e in load_elements(doc_id):
        if e.get("node_kind") not in ("paragraph", "item"):
            continue
        # 所属条：祖先を上がって最初の article（無ければ最も近い上位ノード）
        cur, owner = e, ""
        for _ in range(8):
            pid = cur.get("parent_id")
            par = els.get(pid) if pid else None
            if par is None:
                break
            if par.get("node_kind") in ("article", "appendix_section", "chapter", "appendix"):
                owner = canonical_citation(par.get("citation") or "")
                break
            cur = par
        txt = _flat(e.get("text") or "")
        if txt:
            out.append((txt, owner))
    return out


def _pred_owner_index(tree: Tree) -> list[tuple[str, str]]:
    els = []
    for n in tree.nodes.values():
        if n.kind not in ("paragraph", "item"):
            continue
        owner = ""
        cur = n
        for _ in range(8):
            par = tree.nodes.get(cur.parent_id) if cur.parent_id else None
            if par is None:
                break
            if par.kind in ("article", "appendix_section", "chapter", "appendix"):
                owner = canonical_citation(par.citation)
                break
            cur = par
        t = _flat(n.text)
        if t:
            els.append((t, owner))
    return els


def _boundaries(owners: list[str]) -> list[int]:
    """隣接する単位の所属が変わる位置に 1 を立てる（長さ n-1）。"""
    return [1 if owners[i] != owners[i + 1] else 0 for i in range(len(owners) - 1)]


def pk_windowdiff(doc_id: str, tree: Tree) -> dict:
    """境界の誤りを P_k と WindowDiff で測る。

    単位は**論理段落**、`k` は gold の平均区間長の半分（§10.2 の指定どおり）。

    **対応づけが必要である。** gold の段落列と予測の段落列は長さが違うので、
    gold の各段落を予測の段落へ**平坦化本文の一致**で対応づける。対応づかなかった
    gold 段落は直前の所属を引き継ぐ（境界を立てない）。
    **対応づけ率を必ず併記する** — これが低いまま P_k が良く出ても意味がない。
    """
    gseq = _gold_paragraph_sequence(doc_id)
    pseq = _pred_owner_index(tree)
    if len(gseq) < 3:
        return {"pk": 0.0, "windowdiff": 0.0, "pk_k": 0, "pk_units": len(gseq), "pk_coverage": 0.0}
    # 予測本文 → 所属。同一本文が複数あるときは最初のものを使う。
    pmap: dict[str, str] = {}
    for t, owner in pseq:
        pmap.setdefault(t, owner)
    # 部分一致も許す（予測は行の連結なので gold より長いことがある）。
    long_pred = sorted(pmap.items(), key=lambda kv: -len(kv[0]))[:400]
    g_owners = [o for _, o in gseq]
    p_owners: list[str] = []
    matched = 0
    for txt, _ in gseq:
        owner = pmap.get(txt)
        if owner is None:
            for pt, po in long_pred:
                if txt and (txt in pt or pt in txt):
                    owner = po
                    break
        if owner is None:
            owner = p_owners[-1] if p_owners else ""
        else:
            matched += 1
        p_owners.append(owner)
    gb, pb = _boundaries(g_owners), _boundaries(p_owners)
    n = len(gb)
    n_seg = max(1, sum(gb) + 1)
    k = max(2, int(round(len(g_owners) / (2 * n_seg))))
    if k >= n:
        k = max(1, n - 1)
    pk_err = wd_err = 0
    windows = 0
    for i in range(n - k + 1):
        windows += 1
        g_in = sum(gb[i : i + k])
        p_in = sum(pb[i : i + k])
        if (g_in > 0) != (p_in > 0):
            pk_err += 1
        if g_in != p_in:
            wd_err += 1
    return {
        "pk": round(pk_err / windows, 6) if windows else 0.0,
        "windowdiff": round(wd_err / windows, 6) if windows else 0.0,
        "pk_k": k,
        "pk_units": len(g_owners),
        "pk_coverage": round(matched / len(gseq), 4),
    }


# ---------------------------------------------------------------- 混同行列


def kind_confusion(doc_id: str, tree: Tree) -> dict:
    """`node_kind` の 9 種混同行列。

    **citation を鍵に対応づける。** 同じ citation に複数の種別が付くことがある
    （jyusetsu は条ノードと無番号段落が同じ citation を持つ）ので、citation ごとに
    種別の多重集合を突き合わせ、**同種を先に消費してから**残りを取り違えとして数える。

    対応相手が無いものは `∅` 行 / `∅` 列に入る。**これが漏れ（gold 側 → `∅`）と
    幻覚（`∅` → 予測側）を同じ表の中で見せる。**
    """
    g: dict[str, Counter] = {}
    for e in load_elements(doc_id):
        k = e.get("node_kind")
        if not k:
            continue
        g.setdefault(canonical_citation(e.get("citation") or ""), Counter())[k] += 1
    p: dict[str, Counter] = {}
    for n in tree.nodes.values():
        p.setdefault(canonical_citation(n.citation), Counter())[n.kind] += 1
    cm: Counter = Counter()
    for cit in set(g) | set(p):
        gc, pc = Counter(g.get(cit, {})), Counter(p.get(cit, {}))
        for k in list(gc):
            same = min(gc[k], pc.get(k, 0))
            if same:
                cm[(k, k)] += same
                gc[k] -= same
                pc[k] -= same
        gl = [k for k, c in gc.items() for _ in range(c)]
        pl = [k for k, c in pc.items() for _ in range(c)]
        for i in range(max(len(gl), len(pl))):
            gk = gl[i] if i < len(gl) else NULL
            pk = pl[i] if i < len(pl) else NULL
            cm[(gk, pk)] += 1
    total = sum(cm.values())
    diag = sum(v for (a, b), v in cm.items() if a == b and a != NULL)
    per: dict[str, dict] = {}
    for k in KINDS:
        tp = cm.get((k, k), 0)
        gtot = sum(v for (a, _), v in cm.items() if a == k)
        ptot = sum(v for (_, b), v in cm.items() if b == k)
        if not (gtot or ptot):
            continue
        per[k] = {
            "gold": gtot,
            "pred": ptot,
            "tp": tp,
            "recall": round(tp / gtot, 4) if gtot else 0.0,
            "precision": round(tp / ptot, 4) if ptot else 0.0,
        }
    off = {f"{a}->{b}": v for (a, b), v in cm.most_common() if a != b}
    return {
        "kind_accuracy": round(diag / total, 6) if total else 0.0,
        "kind_per_kind": per,
        "kind_confusions": dict(list(off.items())[:12]),
        "kind_pairs_total": total,
    }


# ---------------------------------------------------------------- 読み順


def reading_order_tau(doc_id: str, tree: Tree) -> dict:
    """gold の `reading_order` と予測のノード列の Kendall τ。

    gold は `element_id` の列なので、**構造ノードだけを citation に写してから**
    比較する（§10.2 の「内容単位に揃える」）。
    予測側の順序は `Tree.nodes` の挿入順 — Builder は行を文書順に食わせるので
    これが読み順である。
    """
    els = {e["element_id"]: e for e in load_elements(doc_id)}
    gold_seq: list[str] = []
    seen: set[str] = set()
    for p in load_layout(doc_id)["pages"]:
        for eid in p.get("reading_order") or []:
            e = els.get(eid)
            if not e or not e.get("node_kind"):
                continue
            c = canonical_citation(e.get("citation") or "")
            if c and c not in seen:
                seen.add(c)
                gold_seq.append(c)
    pred_rank: dict[str, int] = {}
    for i, n in enumerate(tree.nodes.values()):
        pred_rank.setdefault(canonical_citation(n.citation), i)
    common = [c for c in gold_seq if c in pred_rank]
    if len(common) < 2:
        return {
            "reading_order_tau": 0.0,
            "reading_order_coverage": 0.0,
            "reading_order_n": len(common),
        }
    ranks = [pred_rank[c] for c in common]
    conc = disc = 0
    for i in range(len(ranks)):
        for j in range(i + 1, len(ranks)):
            if ranks[i] < ranks[j]:
                conc += 1
            elif ranks[i] > ranks[j]:
                disc += 1
    tot = conc + disc
    return {
        "reading_order_tau": round((conc - disc) / tot, 6) if tot else 0.0,
        "reading_order_coverage": round(len(common) / len(gold_seq), 4) if gold_seq else 0.0,
        "reading_order_n": len(common),
    }


# ---------------------------------------------------------------- 参照解決

RE_REF_PARA = re.compile(r"[（(]([0-9０-９]{1,2})[）)]")
RE_REF_KOU = re.compile(r"第([0-9０-９]{1,2})項")
RE_REF_APPENDIX = re.compile(r"((?:別表|付表)[0-9０-９]{1,2})")
RE_REF_ARTICLE = re.compile(r"第([0-9０-９]{1,3})条(?:の([0-9０-９]+))?")
RE_REF_CHAPTER = re.compile(r"第([0-9０-９]{1,2})章")
RE_REF_DOT = re.compile(r"(?:^|[、。（(])([0-9０-９]{1,2})[．.]")
# 複合参照：`第3章第1条（1）` / `第1条（見出し）(1)` / `第3章第4条`。
# **章・条・項を 1 つのパスとして読む**（W12 T34 試行 2。単独規則で解くと
# 参照元自身のスコープで条を探してしまい、別の章の条を誤って当てる）。
RE_REF_PATH = re.compile(
    r"(?:第([0-9０-９]{1,2})章)?"
    r"第([0-9０-９]{1,3})条(?:の([0-9０-９]+))?"
    r"(?:[（(][^）)]{0,30}[）)])?"
    r"(?:[（(]([0-9０-９]{1,2})[）)])?"
)
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")


def _art_num(label: str) -> str:
    """条ラベルから番号部分だけを取り出す（`第12条の2` → `12の2`）。"""
    return _flat(label).replace("第", "").replace("条", "").strip()


def _paragraph_children(tree: Tree, node) -> list:
    """条（等）の直下の項を**印字順**で返す。"""
    return [tree.nodes[c] for c in node.children if tree.nodes[c].kind == "paragraph"]


def resolve_refs(tree: Tree) -> set[tuple[str, str]]:
    """予測側 `read.structure.semantics.resolve_refs` を呼ぶ（V4 で移設）。

    規則の本体は予測側にある。採点側が独自に解決すると、成果物に出る参照と
    採点される参照が別物になる（W14 まで成果物の `refs` は空だった）。
    """
    from ..read.structure.semantics import resolve_refs as _resolve

    return _resolve(tree)


def ref_resolution(doc_id: str, tree: Tree) -> dict:
    """参照解決の P/R。

    **到達可能な部分集合を分けて報告する。** gold の参照元には `cell` / `footnote` が
    含まれるが、我々の木は表セルと脚注をノードにしていないので**原理的に出せない**。
    これを分母に入れたままの recall は「実装の不足」と「設計上の対象外」を混ぜる。
    よって `ref_recall`（全 gold）と `ref_recall_reachable`（参照元・先がともに
    構造ノードのもの）の 2 つを出す。
    """
    els = {e["element_id"]: e for e in load_elements(doc_id)}
    gold_all: set[tuple[str, str]] = set()
    gold_reach: set[tuple[str, str]] = set()
    for r in load_source(doc_id)["derived"].get("refs") or []:
        f, t = els.get(r["from_id"]), els.get(r["to_id"])
        if not f or not t:
            continue
        fc, tc = (
            canonical_citation(f.get("citation") or ""),
            canonical_citation(t.get("citation") or ""),
        )
        if not fc or not tc or fc == tc:
            continue
        gold_all.add((fc, tc))
        if f.get("node_kind") in ("paragraph", "item") and t.get("node_kind") in (
            "paragraph",
            "item",
            "article",
            "appendix",
            "chapter",
        ):
            gold_reach.add((fc, tc))
    pred = resolve_refs(tree)
    tp_all = len(gold_all & pred)
    tp_r = len(gold_reach & pred)
    return {
        "ref_gold": len(gold_all),
        "ref_gold_reachable": len(gold_reach),
        "ref_pred": len(pred),
        "ref_recall": round(tp_all / len(gold_all), 4) if gold_all else 0.0,
        "ref_precision": round(tp_all / len(pred), 4) if pred else 0.0,
        "ref_recall_reachable": round(tp_r / len(gold_reach), 4) if gold_reach else 0.0,
        "ref_tp": tp_all,
    }


# ---------------------------------------------------------------- 見出し P/R/F1（レベル別）


def heading_pr_by_level(doc_id: str, tree: Tree) -> dict:
    """引用木の上でのレベル別 見出し P/R/F1。

    従来は**採用集合**（どの行を見出しとして採ったか）でしか測っていなかった。
    採用集合は引用木の代理指標として機能しない（W3 A4 で `global > greedy` と
    逆順を付けた）。よってここでは**引用パス完全一致**で数える。
    """
    g: dict[str, set[str]] = {}
    for e in load_elements(doc_id):
        k = e.get("node_kind")
        if k:
            g.setdefault(k, set()).add(canonical_citation(e.get("citation") or ""))
    p: dict[str, set[str]] = {}
    for n in tree.nodes.values():
        p.setdefault(n.kind, set()).add(canonical_citation(n.citation))
    out = {}
    for k in KINDS:
        gs, ps = g.get(k, set()), p.get(k, set())
        if not (gs or ps):
            continue
        tp = len(gs & ps)
        rec = tp / len(gs) if gs else 0.0
        pre = tp / len(ps) if ps else 0.0
        f1 = 2 * rec * pre / (rec + pre) if (rec + pre) else 0.0
        out[k] = {
            "gold": len(gs),
            "pred": len(ps),
            "tp": tp,
            "recall": round(rec, 4),
            "precision": round(pre, 4),
            "f1": round(f1, 4),
        }
    return out
