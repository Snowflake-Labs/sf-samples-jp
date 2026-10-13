"""ローカル実行の作業プロセス。`jpdocread local read`・`jpdocread eval` が子プロセスとして起動する。

移植した read/・eval/ は import 時に `JPDOCREAD_DOCS`・`JPDOCREAD_WORK`・`JPDOCREAD_OUT` を読んでパスを決める
（common/paths.py）。呼び出し側のプロセスでは既に別のパスで import されている可能性があるので、
入出力の場所を環境変数で渡した新しいプロセスで動かす（`run_worker`）。

  read   … doc.pdf から幾何・領域・図の候補を作り、条項木・参照・当事者・定義語を組んで出力 JSON を書く。
           AI 関数は呼ばない。`layout_from` を渡すと、その出力 JSON の `pages[].text_with_furniture`
           （AI_PARSE_DOCUMENT LAYOUT の生 Markdown）を S20 のキャッシュとして置き、表と本文も同じ関数で組み直す。
  eval   … 出力 JSON を正解と照合し、採点結果を JSON で書く（評価 DB には登録しない）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .read.regions import Region

ENV_KEYS = ("JPDOCREAD_DOCS", "JPDOCREAD_WORK", "JPDOCREAD_OUT")


class WorkerError(RuntimeError):
    """作業プロセスが失敗した（文書ごとの失敗は結果の errors に入る。これはプロセス自体の失敗）。"""


def run_worker(
    task: str, args: dict, *, docs: Path, work: Path, out: Path, shots: Path | None = None
) -> dict:
    """入出力の場所を環境変数で渡した子プロセスで task を実行し、結果の辞書を返す。"""
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    result_path = work / f"worker-{task}-result.json"
    result_path.unlink(missing_ok=True)
    env = {
        **os.environ,
        "JPDOCREAD_DOCS": str(docs.resolve()),
        "JPDOCREAD_WORK": str(work.resolve()),
        "JPDOCREAD_OUT": str(out.resolve()),
        # 移植元 semantics.term_uses は同じ長さの定義語の順序が集合の反復順（文字列ハッシュの乱数種）で
        # 変わる。判定ロジックは変えず、乱数種を固定して出力の順序を毎回同じにする
        "PYTHONHASHSEED": "0",
        **({"JPDOCREAD_SHOTS": str(shots.resolve())} if shots else {}),
    }
    payload = json.dumps(
        {"task": task, "args": args, "result_path": str(result_path)}, ensure_ascii=False
    )
    proc = subprocess.run([sys.executable, "-m", "jpdocread.worker", payload], env=env, check=False)
    if not result_path.exists():
        raise WorkerError(
            f"作業プロセス（{task}）が結果を書かずに終了した（rc={proc.returncode}）。上に出た例外を確かめる"
        )
    return json.loads(result_path.read_text(encoding="utf-8"))


# --- 子プロセス側 ------------------------------------------------------------


def _seed_layout(doc_id: str, n_pages: int, layout_from: str | None) -> str:
    """S20 のキャッシュを置く。layout_from が無ければ全ページ空文字（AI を使わない読み取り）。"""
    from .read.parse.r12_cortex import write_cache

    if not layout_from:
        write_cache(doc_id, {p: "" for p in range(1, n_pages + 1)}, None, n_pages, "local-no-ai")
        return "none"
    run = json.loads((Path(layout_from) / f"{doc_id}.json").read_text(encoding="utf-8"))
    missing = [p.get("number") for p in run["pages"] if "text_with_furniture" not in p]
    if missing:
        raise ValueError(
            f"{doc_id}: layout_from の出力に text_with_furniture が無いページ: {missing}"
        )
    pages = {int(p["number"]): p["text_with_furniture"] or "" for p in run["pages"]}
    write_cache(doc_id, pages, None, len(pages), "local-from-run")
    return "from_run"


def _task_read(args: dict) -> dict:
    from .common.paths import OUT
    from .read import integrate
    from .read.figures_r4 import figures_for_doc
    from .read.geometry import write_geometry
    from .read.regions import build_regions

    opts = integrate.ReadOptions(**args["options"])
    done, errors = [], {}
    for doc_id in args["doc_ids"]:
        try:
            _, n_pages = write_geometry(doc_id)
            layout = _seed_layout(doc_id, n_pages, args.get("layout_from"))
            build_regions(doc_id)
            figures_for_doc(doc_id)
            out = integrate.build_output(doc_id, opts)
            out["provenance"]["local"] = {"layout": layout, "ai_called": False}
            (OUT / f"{doc_id}.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            done.append(doc_id)
        except Exception as e:  # noqa: BLE001 — 文書ごとの失敗を記録して続ける（黙って捨てない）
            errors[doc_id] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
    return {"done": done, "errors": errors}


def _task_eval(args: dict) -> dict:
    from .eval.evaluate import evaluate

    result = evaluate(
        args["doc_ids"],
        args["eval_excluded"],
        out_dir=Path(args["pred_dir"]),
        subsets=args.get("subsets") or {},
    )
    return {"result": result}


def _containment(gold: list[float], crop: list[float]) -> float:
    """正解の図 bbox のうち、予測のクロップに収まる面積の割合。"""
    ix = max(0.0, min(gold[2], crop[2]) - max(gold[0], crop[0]))
    iy = max(0.0, min(gold[3], crop[3]) - max(gold[1], crop[1]))
    ga = (gold[2] - gold[0]) * (gold[3] - gold[1])
    return (ix * iy / ga) if ga > 0 else 0.0


def _difficulty(fig: dict) -> tuple:
    """難しさの順（グループの有無・辺の数・ノードの数）。few-shot には最も難しい図を選ぶ。"""
    g = fig.get("graph") or {}
    nodes, edges = g.get("nodes") or [], g.get("edges") or []
    return (int(any(n.get("group") for n in nodes)), len(edges), len(nodes))


def _load_gold_figures(doc_id: str) -> tuple[dict, dict]:
    """供出元の正解から、図（figure_id → 図）と要素（element_id → 要素）を読む。"""
    from .common.paths import DOCS

    src = json.loads((DOCS / doc_id / "source.json").read_text(encoding="utf-8"))
    figs = (src.get("derived") or {}).get("figures") or {}
    els = {}
    for line in (DOCS / doc_id / "elements.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            els[e["element_id"]] = e
    return figs, els


def _best_region(element: dict, regions: list[Region]) -> tuple[Region | None, float]:
    """要素の bbox（ページごと）を最もよく包む図領域と、その包含率。"""
    best, best_s = None, 0.0
    for i, gb in enumerate(element["bboxes"]):
        pages = element.get("pages") or [None]
        pg = pages[min(i, len(pages) - 1)]
        for r in regions:
            if pg is not None and r.page != pg:
                continue
            s = _containment(gb, r.bbox_pt)
            if s > best_s:
                best, best_s = r, s
    return best, best_s


def _shot_candidates(figs: dict, els: dict, regions: list[Region]) -> list[tuple]:
    """包含率 ≥ 0.3 の予測領域を持つ図を (figure_id, 図, 領域, 包含率) で並べる。"""
    cands = []
    for fid, fig in figs.items():
        e = els.get(fid)
        if not e or not e.get("bboxes"):
            continue
        best, best_s = _best_region(e, regions)
        if best and best_s >= 0.3:
            cands.append((fid, fig, best, best_s))
    return cands


def _make_shot(doc_id: str) -> dict:
    """供出元 1 件から最も難しい図の期待 JSON を configs/shots/ に書き、作ったものの要約を返す。"""
    from .common.paths import SHOTS
    from .read.geometry import write_geometry
    from .read.regions import build_regions, read_regions

    write_geometry(doc_id)
    build_regions(doc_id)
    regions = [r for r in read_regions(doc_id) if r.kind == "figure"]
    figs, els = _load_gold_figures(doc_id)
    cands = _shot_candidates(figs, els, regions)
    if not cands:
        raise RuntimeError(
            f"{doc_id}: 正解の図を包む予測領域（包含率 ≥ 0.3）が無い"
            "（configs/corpora/ の figure_shots の供出元を見直す）"
        )
    fid, fig, reg, s = max(cands, key=lambda c: _difficulty(c[1]))
    g = fig.get("graph") or {}
    shot = {
        "shot_id": f"{doc_id}#{fid}",
        "doc_id": doc_id,
        "kind": "figure",
        "figure_id": fid,
        "caption_label": fig.get("caption_label"),
        "graph": {"nodes": g.get("nodes") or [], "edges": g.get("edges") or []},
        "n_nodes": len(g.get("nodes") or []),
        "n_edges": len(g.get("edges") or []),
        "crop": reg.rel_path,
        "crop_containment": round(s, 4),
        "_provenance": "generated from gold by jpdocread prompt — DO NOT HAND-EDIT",
    }
    name = f"figure__{doc_id}__{fid}.json"
    (SHOTS / name).write_text(
        json.dumps(shot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"doc_id": doc_id, "figure_id": fid, "crop": reg.rel_path, "containment": round(s, 4),
            "n_nodes": shot["n_nodes"], "n_edges": shot["n_edges"]}  # fmt: skip


def _task_shots(args: dict) -> dict:
    """図 few-shot の期待 JSON を供出元の正解から作り、S40 に渡すプロンプトの仕様を返す（setup の準備作業）。

    正解（source.json・elements.jsonl）を読むのは採点側の準備で、予測経路（read/）には入らない。
    クロップは予測側の regions.py が doc.pdf から作る図領域のうち、正解の図 bbox を最もよく包む（包含率 ≥ 0.3）もの。
    """
    from .common.paths import SHOTS
    from .read.figures import prompt_spec

    SHOTS.mkdir(parents=True, exist_ok=True)
    for p in SHOTS.glob("figure__*.json"):
        p.unlink()
    made = [_make_shot(doc_id) for doc_id in args["donors"]]
    spec = prompt_spec()
    return {"shots": made, "spec": spec}


TASKS = {"read": _task_read, "eval": _task_eval, "shots": _task_shots}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    payload = json.loads(argv[0])
    missing = [k for k in ENV_KEYS if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"作業プロセスの環境変数が無い: {missing}")
    result = TASKS[payload["task"]](payload["args"])
    Path(payload["result_path"]).write_text(
        json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
