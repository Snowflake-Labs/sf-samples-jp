"""few-shot の手本を作る（評価側。正解を読む。予測側から呼ばない）。

手本は DEV の shots の PDF（pilot と元文書を共有しない PDF）の正解から機械的に作り、work/shots/<corpus>/ に書く
（git 管理外）。予測側は作られたファイルだけを読む。手で打ち直さない。写せない規則は手本から外す（推測で補わない）。

入力側は予測時と同じ形にする：
  - 根拠の単位：正解の根拠（layout.json の要素 ID）を、ページと bbox の重なりが最大の pdoc の単位（項・号）に写す
  - 文脈：写した単位から d_spec.doc_context で作る（予測時と同じ関数）
  - カード：正解の仕様の関数名・入力・出力から、段 K の出力と同じ形に写す
出力側（D の手本）は正解の仕様の steps を LLM の出力の形に写す：
  - param：根拠の pdoc の単位の中で、値（数値と単位）が一致する値スパンのキー（無ければ文書全体で 1 つに決まるもの）
  - 表：正解の表の要素に重なる pdoc の表のブロック
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..fetch.adapters import render
from ..predict import d_spec, k_cards
from ..predict.context import resolve_const
from ..predict.policy_index import PolicyIndex
from .read_score import _boxes_by_page, _overlap_ratio, layout_path

MIN_OVERLAP = 0.5
MAX_CONTEXT = 1600  # K の手本の文脈の上限（文字）
BODY_KINDS = ("paragraph", "item")


class ShotsError(ValueError):
    pass


@dataclass
class DocShot:
    pdf_id: str
    d_shot: dict | None = None
    k_shot: dict | None = None
    kept: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)  # 関数名 → 外した理由
    renamed: dict[str, str] = field(
        default_factory=dict
    )  # pilot の正解と重なった関数名 → 置き換えた名前


# ---- 対象の検査
# 手本の PDF が DEV に属し pilot と base を共有しないことは、選定（fetch.select の slice=shots）が公開索引の
# split_group で確かめる。ここでは文書 ID の形から元文書を推測しない。


def doc_of(pdf_id: str) -> str:
    return pdf_id.partition("--")[0]


def check_names_disjoint(shots: list[dict], pilot_functions: set[str]) -> None:
    """手本のどこにも pilot の正解の関数名が現れないこと（例の名前を正解の答えにしない）。

    関数名だけでなく、題名・段の説明・問題文に語として現れることも禁じる（文字列として検査する）。
    """
    blob = json.dumps(shots, ensure_ascii=False)
    clash = sorted(
        f for f in pilot_functions if re.search(rf"(?<![a-z0-9_]){re.escape(f)}(?![a-z0-9_])", blob)
    )
    if clash:
        raise ShotsError(f"手本に pilot の正解の関数名が現れます: {clash}")


def rename_clashes(shots: list[DocShot], pilot_functions: set[str]) -> dict[str, str]:
    """pilot の正解と重なる手本の関数名を、中立の名前（example_fn_NN）に置き換える。

    関数名・規則の参照（{"rule": 名前}）・カードの関数名・問題文のカードをそろえて変える。返り値は 旧 → 新。
    """
    clash = sorted({f for s in shots for f in s.kept} & pilot_functions)
    ren = {f: f"example_fn_{i:02d}" for i, f in enumerate(clash, 1)}
    if not ren:
        return ren

    pat = re.compile(r"(?<![a-z0-9_])(" + "|".join(map(re.escape, ren)) + r")(?![a-z0-9_])")

    def sub(o):
        # 文字列の中の語としての出現（関数名・規則の参照・題名・説明）をすべて置き換える
        if isinstance(o, list):
            return [sub(x) for x in o]
        if isinstance(o, dict):
            return {k: sub(v) for k, v in o.items()}
        if isinstance(o, str):
            return pat.sub(lambda m: ren[m.group(1)], o)
        return o

    for s in shots:
        if s.d_shot is None:
            continue
        s.d_shot["answer"] = sub(s.d_shot["answer"])
        cards = [sub(c) for c in json.loads(s.d_shot["problem"]["CARDS"])]
        s.d_shot["problem"]["CARDS"] = json.dumps(cards, ensure_ascii=False, indent=1)
        s.k_shot = sub(s.k_shot)  # 規則と文脈（本文の抜粋）の両方
        s.kept = [ren.get(f, f) for f in s.kept]
        s.renamed = {k: v for k, v in ren.items() if v in s.kept}
    return ren


# ---- 正解の要素 → pdoc の単位


def _pdoc_units(doc: dict) -> dict[str, tuple[str, dict[int, list[float]]]]:
    """pdoc の単位 id → (種類, ページ → 和の bbox)。項・号・表・算式・図。"""
    out: dict[str, tuple[str, dict[int, list[float]]]] = {}

    def blocks(bs):
        for b in bs:
            t = b.get("type")
            if t in ("table", "formula", "figure") and b.get("id"):
                bb = b.get("bbox")
                boxes = (
                    {int(b["page"]): list(bb)}
                    if bb and b.get("page") is not None
                    else _boxes_by_page(b.get("src", []))
                )
                out[b["id"]] = (t, boxes)
            blocks(b.get("blocks", []))

    def walk(ns):
        for n in ns:
            if n.get("kind") in BODY_KINDS and n.get("id"):
                out[n["id"]] = (n["kind"], _boxes_by_page(n.get("src", [])))
            blocks(n.get("blocks", []))
            walk(n.get("children", []))

    walk(doc.get("body", []) + doc.get("front_matter", []) + doc.get("appendices", []))
    return out


def _gold_boxes(layout: dict, element_id: str) -> dict[int, list[float]]:
    e = layout.get("elements", {}).get(element_id)
    if e is None:
        return {}
    return _boxes_by_page([f for f in e.get("fragments", []) if not f.get("repeated")])


def map_unit(layout: dict, units: dict, element_id: str, kinds: tuple[str, ...]) -> str | None:
    """正解の要素に最も重なる pdoc の単位（kinds のもの）。重なりが閾値未満なら None。"""
    g = _gold_boxes(layout, element_id)
    best, best_id = 0.0, None
    for uid, (k, boxes) in units.items():
        if k not in kinds:
            continue
        r = max((_overlap_ratio(gb, boxes[pg]) for pg, gb in g.items() if pg in boxes), default=0.0)
        if r > best:
            best, best_id = r, uid
    return best_id if best >= MIN_OVERLAP else None


def _element_of_source(unit: str) -> str:
    # 正解の根拠には「図の代替文」（<要素>__alt）のような派生の id がある。要素の id に戻す
    return unit.split("__", 1)[0]


# ---- 値スパンの対応


def _const_keys_in(ix: PolicyIndex, uid: str) -> list[str]:
    n = ix.by_id.get(uid) or {}
    text = json.dumps(n, ensure_ascii=False)
    return list(dict.fromkeys(k for k in ix.constants if f"{{const:{k}}}" in text))


def _value_of(surface: str) -> tuple | None:
    c = resolve_const(surface)
    return None if c.get("value") is None else (c["value"], c.get("unit"))


def map_param(ix: PolicyIndex, surface: str, near: list[str]) -> str | None:
    """印字の表記が surface の値と一致する値スパンのキー。根拠の単位の中を先に見て、無ければ文書全体で 1 つに決まるもの。"""
    want = _value_of(surface)
    if want is None:
        return None
    same = lambda k: _value_of(ix.constants[k]) == want  # noqa: E731
    local = list(dict.fromkeys(k for u in near for k in _const_keys_in(ix, u) if same(k)))
    if len(local) == 1:
        return local[0]
    if local:
        return None  # 根拠の中に同じ値が複数ある（どれか決められない）
    glob = [k for k in ix.constants if same(k)]
    return glob[0] if len(glob) == 1 else None


# ---- 正解の仕様 → 手本


def _gold_param_surface(name: str, p: dict, policy_constants: dict) -> str | None:
    if p.get("surface"):
        return str(p["surface"])
    if p.get("from_const") and p["from_const"] in policy_constants:
        return str(policy_constants[p["from_const"]])
    return None


def _card_from_gold(pdf_id: str, r: dict, units: list[str]) -> dict:
    """正解の規則 → 段 K の出力と同じ形のカード（K の interpret で検査する）。"""
    ins = []
    for name, i in (r.get("inputs") or {}).items():
        x = {"name": name, "type": i["type"], "unit": i.get("unit"), "desc": i.get("desc", "")}
        if i.get("origin") in k_cards.ORIGINS:
            x["origin"] = i["origin"]
        if i.get("exclusion") is True:
            x["exclusion"] = True
        if i["type"] == "list":
            x["fields"] = [
                {"name": fn, "type": f["type"], "unit": f.get("unit"), "desc": f.get("desc", "")}
                for fn, f in (i.get("fields") or {}).items()
            ]
        ins.append(x)
    return {
        "function": r["interface"]["function"],
        "title": r.get("title", ""),
        "kind": "decision" if r["kind"] in ("decision", "determination") else "calculation",
        "inputs": ins,
        "output": {"type": r["output"]["type"]},
        "units": units,
    }


class _Unmappable(Exception):
    pass


def _conv_expr(e, pmap: dict, tmap: dict, id2fn: dict):
    if isinstance(e, list):
        return [_conv_expr(x, pmap, tmap, id2fn) for x in e]
    if not isinstance(e, dict):
        return e
    if "op" in e:
        out = {"op": e["op"]}
        if e["op"] == "lookup":
            if e.get("table") not in tmap:
                raise _Unmappable(f"表 {e.get('table')!r} を pdoc の表に写せない")
            out["table"], out["mode"] = tmap[e["table"]]
        for k in ("rounding", "func", "over"):
            if k in e:
                out[k] = e[k]
        out["args"] = _conv_expr(e.get("args", []), pmap, tmap, id2fn)
        return out
    if "param" in e:
        if e["param"] not in pmap:
            raise _Unmappable(f"定数 {e['param']!r} を pdoc の値スパンに写せない")
        return {"param": pmap[e["param"]]}
    if "rule" in e:
        if e["rule"] not in id2fn:
            raise _Unmappable(f"規則 {e['rule']!r} が手本に無い")
        return {"rule": id2fn[e["rule"]]}
    if "lit" in e:
        return {"lit": e["lit"], **({"note": e["note"]} if e.get("note") else {})}
    return dict(e)


def build_doc_shot(
    pdf_id: str, pdoc: dict, layout: dict, spec: dict, policy_constants: dict
) -> DocShot:
    """1 PDF の手本。写せない規則は dropped に理由つきで残す。"""
    ix = PolicyIndex(pdoc)
    units = _pdoc_units(pdoc)
    out = DocShot(pdf_id)

    # 根拠の単位の写像（規則ごと）
    rule_units: dict[str, list[str]] = {}
    for r in spec["rules"]:
        fn = r["interface"]["function"]
        mapped = []
        for s in r.get("sources") or []:
            el = _element_of_source(s["unit"])
            u = map_unit(layout, units, el, BODY_KINDS + ("table", "formula", "figure"))
            if u:
                mapped.append(u)
        rule_units[fn] = list(dict.fromkeys(mapped))

    # 定数の写像（根拠の単位の中を優先）
    pmap: dict[str, str] = {}
    for name, p in (spec.get("params") or {}).items():
        surface = _gold_param_surface(name, p, policy_constants)
        if surface is None:
            continue
        el = _element_of_source((p.get("source") or {}).get("unit", ""))
        near = [u for u in [map_unit(layout, units, el, BODY_KINDS)] if u]
        k = map_param(ix, surface, near)
        if k:
            pmap[name] = k

    # 表の写像
    tmap: dict[str, tuple[str, str]] = {}
    for name, t in (spec.get("tables") or {}).items():
        u = map_unit(layout, units, t.get("from_block", ""), ("table",))
        if u:
            tmap[name] = (u, t["mode"])

    # 規則ごとに写す。写せない規則は外し、それを参照する規則も外す
    id2fn = {r["id"]: r["interface"]["function"] for r in spec["rules"]}
    kept_rules, cards_raw = [], []
    for r in spec["rules"]:
        fn = r["interface"]["function"]
        if not rule_units[fn]:
            out.dropped[fn] = "根拠の単位を pdoc に写せない"
            continue
        try:
            steps = [
                {
                    "name": s["name"],
                    "label": s.get("label"),
                    "expr": _conv_expr(s["expr"], pmap, tmap, id2fn),
                }
                for s in r["steps"]
            ]
        except _Unmappable as e:
            out.dropped[fn] = str(e)
            continue
        kept_rules.append(
            {
                "function": fn,
                "kind": "decision" if r["kind"] in ("decision", "determination") else "calculation",
                "steps": steps,
                "output": r["output"]["step"],
                "explicit": {o: True for o in r.get("obligations", [])},
                "unresolved": [],
            }
        )
        cards_raw.append(_card_from_gold(pdf_id, r, rule_units[fn]))

    # 外した規則を参照する規則を外す（繰り返し）
    while True:
        gone = set(out.dropped)
        refs = {
            r["function"]: {x["rule"] for x in _walk_refs(r["steps"])} & gone for r in kept_rules
        }
        newly = {f: sorted(v) for f, v in refs.items() if v}
        if not newly:
            break
        for f, v in newly.items():
            out.dropped[f] = f"外した規則 {v} を参照する"
        kept_rules = [r for r in kept_rules if r["function"] not in newly]
        cards_raw = [c for c in cards_raw if c["function"] not in newly]

    if not kept_rules:
        return out

    # カードは段 K と同じ検査を通す（候補は写した単位）
    cands = [
        {"id": u, "kind": units[u][0], "container": u, "text": ""}
        for c in cards_raw
        for u in c["units"]
    ]
    cards, _, probs = k_cards.interpret(doc_of(pdf_id), {"rules": cards_raw}, cands)
    ok_fns = {c["function"] for c in cards}
    for c in cards_raw:
        if c["function"] not in ok_fns:
            out.dropped[c["function"]] = "カードの検査に落ちた: " + "; ".join(
                p for p in probs if p.startswith(c["function"])
            )
    kept_rules = [r for r in kept_rules if r["function"] in ok_fns]
    if not kept_rules:
        return out

    ctx = d_spec.doc_context(ix, list(dict.fromkeys(u for c in cards for u in c["evidence_units"])))
    answer = {"rules": kept_rules}
    _, aprobs = d_spec.assemble(doc_of(pdf_id), answer, ctx, cards)
    bad = {p.split(":", 1)[0].split(".", 1)[0] for p in aprobs}
    if bad:
        for f in sorted(bad & ok_fns):
            out.dropped[f] = (
                "仕様の検査に落ちた: " + "; ".join(p for p in aprobs if p.startswith(f))[:300]
            )
        kept_rules = [r for r in kept_rules if r["function"] not in bad]
        cards = [c for c in cards if c["function"] not in bad]
        if not kept_rules:
            return out
        ctx = d_spec.doc_context(
            ix, list(dict.fromkeys(u for c in cards for u in c["evidence_units"]))
        )
        answer = {"rules": kept_rules}
        _, aprobs = d_spec.assemble(doc_of(pdf_id), answer, ctx, cards)
        if aprobs:
            raise ShotsError(f"{pdf_id}: 外した後も仕様の検査に落ちる: {aprobs[:3]}")

    out.kept = [r["function"] for r in kept_rules]
    out.d_shot = {"doc_id": pdf_id, "problem": d_spec.render_problem(ctx, cards), "answer": answer}
    text = ctx["text"]
    out.k_shot = {
        "doc_id": pdf_id,
        "context": text[:MAX_CONTEXT] + ("…" if len(text) > MAX_CONTEXT else ""),
        "rules": [
            {k: c[k] for k in ("function", "title", "kind", "inputs") if k in c}
            | {"output": {"type": c["output"]["type"]}}
            for c in cards
        ],
    }
    return out


def _walk_refs(e):
    if isinstance(e, list):
        for x in e:
            yield from _walk_refs(x)
    elif isinstance(e, dict):
        if "rule" in e and "op" not in e:
            yield e
        for v in e.values():
            yield from _walk_refs(v)


def _load_gold(cfg, eval_root: Path, doc_id: str) -> tuple[dict, dict]:
    """正解の仕様と、保険約款の定数（policy.json の meta.constants。契約書は空）。"""
    spec_p = eval_root / render(cfg.paths.gold_root, doc_id=doc_id) / "spec.json"
    if not spec_p.is_file():
        raise ShotsError(
            f"正解の仕様がありません: {spec_p}（jpcalc fetch-gold --corpus {cfg.name} --docs {doc_id}）"
        )
    spec = json.loads(spec_p.read_text(encoding="utf-8"))
    consts: dict = {}
    for tpl in cfg.paths.gold:
        if tpl.endswith("/policy.json"):
            pj = eval_root / render(tpl, doc_id=doc_id)
            if pj.is_file():
                consts = (
                    json.loads(pj.read_text(encoding="utf-8")).get("meta", {}).get("constants", {})
                )
    return spec, consts


def gold_functions(cfg, eval_root: Path, doc_ids: list[str]) -> set[str]:
    """文書の正解の関数名（取得済みの文書だけ。未取得なら ShotsError）。"""
    return {
        r["interface"]["function"]
        for d in doc_ids
        for r in _load_gold(cfg, eval_root, d)[0]["rules"]
    }


def make_shots(
    cfg, eval_root: Path, pdoc_dir: Path, shot_pdfs: list[str], pilot_pdfs: list[str]
) -> list[DocShot]:
    """shots の PDF の手本を作る。shot_pdfs は選定（DEV・pilot と別の base）を通したものを渡す。"""
    out = []
    for pdf in shot_pdfs:
        p = pdoc_dir / f"{pdf}.json"
        if not p.is_file():
            raise ShotsError(
                f"pdoc がありません: {p}（jpcalc pdoc --corpus {cfg.name} --slice shots）"
            )
        pdoc = json.loads(p.read_text(encoding="utf-8"))
        layout = json.loads(layout_path(cfg, eval_root, pdf).read_text(encoding="utf-8"))
        spec, consts = _load_gold(cfg, eval_root, doc_of(pdf))
        out.append(build_doc_shot(pdf, pdoc, layout, spec, consts))
    pilot_fns = gold_functions(cfg, eval_root, sorted({doc_of(x) for x in pilot_pdfs}))
    rename_clashes(out, pilot_fns)
    check_names_disjoint([x for s in out for x in (s.d_shot, s.k_shot) if x], pilot_fns)
    return out


def write_shots(corpus: str, shots: list[DocShot], out_dir: Path) -> dict:
    d = out_dir / corpus
    d.mkdir(parents=True, exist_ok=True)
    ds = [s.d_shot for s in shots if s.d_shot]
    ks = [s.k_shot for s in shots if s.k_shot]
    if not ds:
        raise ShotsError(f"{corpus}: 手本にできる規則が 1 つもない")
    (d / "d_spec.json").write_text(json.dumps(ds, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "k_cards.json").write_text(json.dumps(ks, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "corpus": corpus,
        "dir": str(d),
        "docs": [
            {"pdf_id": s.pdf_id, "kept": s.kept, "dropped": s.dropped, "renamed": s.renamed}
            for s in shots
        ],
    }


__all__ = [
    "DocShot",
    "ShotsError",
    "build_doc_shot",
    "check_names_disjoint",
    "rename_clashes",
    "gold_functions",
    "make_shots",
    "doc_of",
    "layout_path",
    "map_param",
    "map_unit",
    "write_shots",
]
