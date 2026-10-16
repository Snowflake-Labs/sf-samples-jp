"""SPCS ジョブのステップ（S30 幾何・S50 統合）。`python -m jpdocread job s30|s50 --run-id R`。

（処理の順序と台帳の書き方は同じ。名前・パス・コーパスの受け口を本ハンズオンの形にした）

ジョブ仕様（container/job_specs/predict.yaml）が、ステージをマウントして環境変数で場所を渡す：
  JPDOCREAD_STAGE_DOCS     @<DB>.<RAW>.DOCS（/stage/docs）       <corpus>/<doc_id>/doc.pdf
  JPDOCREAD_STAGE_WORK     @<DB>.<RAW>.WORK（/stage/work）       runs/<run_id>/S30/<doc_id>/…・runs/<run_id>/crops/<rel_path>
  JPDOCREAD_STAGE_RESULTS  @<DB>.<OUTPUT>.RESULTS（/stage/results） <run_id>/<corpus>/<doc_id>.json
  JPDOCREAD_DOCS           /stage/docs/<corpus>（移植した read/ が import 時に読む）
  JPDOCREAD_WORK・OUT      コンテナ内のローカル作業域（ステージは追記・書き換えできないので、作ってから 1 回で写す）

対象は RUNS 台帳の run の docs（S30 は図 few-shot の供出元も）。完了済み（STEP_RUNS が SUCCEEDED）の文書は飛ばす。
**1 文書の失敗で他の文書を止めない**が、失敗が 1 件でもあれば終了コード 1（ジョブ→Task が失敗し、--resume で拾える）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection

    from .read.figures import FigureOut
    from .read.regions import Region

REQUIRED_KEYS = (
    "schema_version",
    "doc_id",
    "meta",
    "pages",
    "outline",
    "elements",
    "tables",
    "figures",
    "refs",
    "repair_queue",
    "provenance",
)
CONTRACT_KEYS = ("numbering_scheme", "parties", "defined_terms", "defined_terms_detail")


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


STAGE_DOCS = _env_path("JPDOCREAD_STAGE_DOCS", "/stage/docs")
STAGE_WORK = _env_path("JPDOCREAD_STAGE_WORK", "/stage/work")
STAGE_RESULTS = _env_path("JPDOCREAD_STAGE_RESULTS", "/stage/results")


def copy_file(src: Path, dst: Path) -> None:
    """ステージボリュームは追記・書き換えできないので、ローカルで作ったファイルを丸ごと 1 回で書く。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fi, dst.open("wb") as fo:
        shutil.copyfileobj(fi, fo, length=1 << 20)


def fail_injected(step: str, doc_id: str, spec: str | None = None) -> None:
    """故障注入（再実行の実演用）。JPDOCREAD_FAIL_DOCS=<step>:<doc_id>,… に当たったら例外を出す。"""
    spec = os.environ.get("JPDOCREAD_FAIL_DOCS", "") if spec is None else spec
    if f"{step}:{doc_id}" in {s.strip() for s in spec.split(",") if s.strip()}:
        raise RuntimeError(f"故障注入（JPDOCREAD_FAIL_DOCS）: {step}:{doc_id}")


ELEMENT_KEYS = ("element_id", "node_kind", "citation", "text", "pages")


def validate_output(out: dict) -> None:
    """出力 JSON の最小スキーマ検査。違反は例外（黙って書かない）。"""
    _check_top(out)
    _check_elements(out["elements"])
    _check_pages(out["pages"])
    # 契約書の体裁を判定した出力は、当事者に呼称と名称を必ず持つ（移植元 C-010）
    if out["numbering_scheme"] is not None:
        _check_parties(out["parties"])


def _check_top(out: dict) -> None:
    from .read.integrate import SCHEMA_VERSION

    missing = [k for k in (*REQUIRED_KEYS, *CONTRACT_KEYS) if k not in out]
    if missing:
        raise ValueError(f"出力 JSON に必須キーが無い: {missing}")
    if out["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version が {SCHEMA_VERSION} でない: {out['schema_version']}")


def _check_elements(elements: list[dict]) -> None:
    for e in elements:
        for k in ELEMENT_KEYS:
            if k not in e:
                raise ValueError(f"elements[] に {k} が無い: {e.get('element_id')}")


def _check_pages(pages: list[dict]) -> None:
    for p in pages:
        if "number" not in p or "text" not in p:
            raise ValueError("pages[] に number / text が無い")


def _check_parties(parties: list[dict]) -> None:
    for pt in parties:
        if not pt.get("alias") or not pt.get("name"):
            raise ValueError(f"parties[] に alias / name が無い: {pt}")


def run_info(conn: SnowflakeConnection, run_id: str) -> dict:
    from .common import sf

    rows = sf.query(
        conn,
        f"SELECT corpus, docs, donors, config FROM {sf.ops()}.RUNS WHERE run_id = %s",
        (run_id,),
    )
    if not rows:
        raise SystemExit(
            f"run が RUNS 台帳に無い: {run_id}（Task の CONFIG の run_id を確かめる。登録は scripts/start.sh が行う）"
        )
    r = rows[0]
    config = json.loads(r["config"]) if isinstance(r["config"], str) else (r["config"] or {})
    return {
        "corpus": r["corpus"],
        "docs": sf.as_list(r["docs"]),
        "donors": sf.as_list(r["donors"]),
        "config": config,
    }


def _check_docs_root(corpus: str) -> None:
    """ジョブ仕様が渡した入力の場所が、run のコーパスと合っていること（取り違えを止める）。"""
    expected = STAGE_DOCS / corpus
    got = Path(os.environ.get("JPDOCREAD_DOCS", ""))
    if got != expected:
        raise SystemExit(f"JPDOCREAD_DOCS が run のコーパスと合わない: {got}（期待 {expected}）")


# ---------------------------------------------------------------- S30


def _figure_candidates(figures: list[dict]) -> list[tuple[int, list[float], int]]:
    """図のノード候補数（`figures_r4.figures_for_doc` が領域内の語を塊にしたノード）を (ページ, bbox, ノード数) で並べる。

    max_tokens の見積もりに使う。正解の要素数は使わない（予測経路に正解を入れない。移植元 D-006）。
    """
    return [(f["pages"][0], f["bbox"], len(f["nodes"])) for f in figures]


def _node_count(region: Region, cand: list[tuple[int, list[float], int]]) -> int:
    """図の領域に収まる最初の候補のノード数（0.5pt の余裕を見る）。図以外・該当なしは 0。"""
    from .common.bbox import contains

    if region.kind != "figure":
        return 0
    return next(
        (n for pg, bb, n in cand if pg == region.page and contains(region.bbox_pt, bb, tol=0.5)), 0
    )


def _publish_s30(
    run_id: str,
    corpus: str,
    doc_id: str,
    regions: list[Region],
    cand: list[tuple[int, list[float], int]],
) -> list[tuple]:
    """幾何・領域・クロップを WORK ステージへ写し、REGIONS 表に入れる行を返す。"""
    from .read.geometry import geom_paths
    from .read.regions import _crop_dir

    base = STAGE_WORK / "runs" / run_id / "S30" / doc_id
    lp, pp = geom_paths(doc_id)
    for p in (lp, pp, _crop_dir(doc_id) / "regions.json"):
        copy_file(p, base / p.name)
    rows = []
    for r in regions:
        crop = _crop_dir(doc_id) / Path(r.rel_path).name
        copy_file(crop, STAGE_WORK / "runs" / run_id / "crops" / r.rel_path)
        md5 = hashlib.md5(crop.read_bytes()).hexdigest()
        n_nodes = _node_count(r, cand)
        rows.append(
            (run_id, corpus, doc_id, r.region_id, r.kind, r.page, r.rel_path,
             f"runs/{run_id}/crops/{r.rel_path}", json.dumps(r.bbox_pt), r.width_px,
             r.height_px, int(r.n_cells), int(n_nodes), md5)
        )  # fmt: skip
    return rows


def _replace_regions(
    conn: SnowflakeConnection, run_id: str, doc_id: str, rows: list[tuple]
) -> None:
    """(run_id, doc_id) の REGIONS を消してから入れ直す（再実行で重ならない）。"""
    from .common import sf

    sf.query(
        conn,
        f"DELETE FROM {sf.ops()}.REGIONS WHERE run_id = %s AND doc_id = %s",
        (run_id, doc_id),
    )
    if rows:
        cur = conn.cursor()
        cur.executemany(
            f"INSERT INTO {sf.ops()}.REGIONS (run_id, corpus, doc_id, region_id, kind, page,"
            " rel_path, stage_path, bbox_pt, width_px, height_px, n_cells_est,"
            " n_node_candidates, image_md5) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
        cur.close()


def cmd_s30(run_id: str, only: list[str] | None = None) -> int:
    from .common import sf
    from .config import load_corpus_config
    from .read.figures_r4 import figures_for_doc
    from .read.geometry import write_geometry
    from .read.regions import build_regions

    conn = sf.connect()
    info = run_info(conn, run_id)
    _check_docs_root(info["corpus"])
    # 図の領域の絞り込み（figures.filter_regions）。供出元には掛けない：few-shot の例画像は供出元の図の
    # クロップの名前で引くので、供出元の領域は従来と同じにしておく
    filter_figs = load_corpus_config(info["corpus"]).figures.filter_regions
    donors = set(info["donors"])
    # few-shot の例画像は供出元のクロップ（S40 が同じ run の WORK から読む。移植元 T4.3）
    docs = only or sorted(set(info["docs"]) | set(info["donors"]))
    done = sf.done_docs(conn, run_id, "S30")
    n_fail = 0
    for doc_id in docs:
        if doc_id in done:
            print(f"S30 skip {doc_id}", flush=True)
            continue
        t0 = time.time()
        try:
            with sf.step_doc(conn, run_id, "S30", doc_id) as box:
                fail_injected("S30", doc_id)
                n_lines, n_pages = write_geometry(doc_id)
                regions = build_regions(doc_id, filter_figures=filter_figs and doc_id not in donors)
                cand = _figure_candidates(figures_for_doc(doc_id))
                rows = _publish_s30(run_id, info["corpus"], doc_id, regions, cand)
                _replace_regions(conn, run_id, doc_id, rows)
                box["output_uri"] = (
                    f"@{sf.names().fq('schema_raw', 'WORK')}/runs/{run_id}/S30/{doc_id}/"
                )
                box["detail"] = {
                    "n_lines": n_lines,
                    "n_pages": n_pages,
                    "n_regions": len(regions),
                    "n_figure_regions": sum(r.kind == "figure" for r in regions),
                    "wall_clock_s": round(time.time() - t0, 1),
                }
            print(
                f"S30 ok   {doc_id} lines={n_lines} pages={n_pages} regions={len(regions)}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001 — 1 文書の失敗で他を止めない（台帳には記録済み）
            n_fail += 1
            print(f"S30 FAIL {doc_id}: {e}", file=sys.stderr, flush=True)
    return 1 if n_fail else 0


# ---------------------------------------------------------------- S50


def _copy_s30_inputs(run_id: str, doc_id: str) -> None:
    """S30 が WORK ステージに置いた幾何と領域を、移植した read/ が読むローカルの場所に戻す。"""
    from .read.geometry import geom_paths
    from .read.regions import _crop_dir

    base = STAGE_WORK / "runs" / run_id / "S30" / doc_id
    lp, pp = geom_paths(doc_id)
    for p in (lp, pp):
        copy_file(base / p.name, p)
    cdir = _crop_dir(doc_id)
    cdir.mkdir(parents=True, exist_ok=True)
    copy_file(base / "regions.json", cdir / "regions.json")


def _s20_cache_key(conn: SnowflakeConnection, run_id: str, doc_id: str) -> str:
    """この run の S20 の台帳が記録した cache_key。無ければ推測で補わずに失敗させる。"""
    from .common import sf

    key = sf.query(
        conn,
        f"SELECT detail:cache_key::STRING AS cache_key FROM {sf.ops()}.STEP_RUNS"
        " WHERE run_id = %s AND step = 'S20' AND doc_id = %s AND status = 'SUCCEEDED'",
        (run_id, doc_id),
    )
    cache_key = key[0]["cache_key"] if key else None
    if not cache_key:
        raise RuntimeError(
            f"S20 の台帳に成功した cache_key が無い: run_id={run_id} doc_id={doc_id}"
            "（S20 が失敗か未実行。scripts/start.sh --resume <run_id> で失敗分から流し直す）"
        )
    return cache_key


def _write_s20_cache(conn: SnowflakeConnection, doc_id: str, cache_key: str) -> int:
    """S20 の結果（ページごとの LAYOUT）を移植元と同じキャッシュ形式で書く。ページ数を返す。"""
    from .common import sf
    from .read.parse.r12_cortex import write_cache

    parsed = sf.names().fq("schema_parsed")
    rows = sf.query(
        conn,
        f"""SELECT p.page, p.content, p.err, r.page_count, r.query_id
        FROM {parsed}.PARSE_PAGES p
        JOIN {parsed}.PARSE_RAW r ON r.cache_key = p.cache_key AND r.query_id = p.query_id AND r.err IS NULL
        WHERE p.cache_key = %s ORDER BY p.page""",
        (cache_key,),
    )
    if not rows:
        raise RuntimeError(
            f"S20 の結果が無い: {doc_id} cache_key={cache_key}（PARSED.PARSE_PAGES・PARSE_RAW に成功した行が無い）"
        )
    if len({r["page"] for r in rows}) != len(rows):
        raise RuntimeError(f"S20 のページが重複している: {doc_id} cache_key={cache_key}")
    pages = {int(r["page"]): r["content"] or "" for r in rows}
    write_cache(doc_id, pages, rows[0]["err"], rows[0]["page_count"], rows[0]["query_id"])
    return len(pages)


def _write_s40_outputs(conn: SnowflakeConnection, run_id: str, doc_id: str) -> list[FigureOut]:
    """S40 の図の応答を領域ごとに 1 件（成功を優先し、新しいもの）選び、figures/s40.json に書く。"""
    from .common import sf
    from .read.figures import parse_raw

    parsed = sf.names().fq("schema_parsed")
    figs = sf.query(
        conn,
        f"""SELECT r.rel_path, f.raw_out, f.max_tokens, f.query_id, f.err, f.model
        FROM {sf.ops()}.REGIONS r
        JOIN {parsed}.FIGURE_RAW f ON f.image_md5 = r.image_md5 AND f.prompt_key = r.prompt_key
        WHERE r.run_id = %s AND r.doc_id = %s AND r.kind = 'figure'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY r.rel_path ORDER BY (f.err IS NULL) DESC, f.created_at DESC) = 1""",
        (run_id, doc_id),
    )
    outs = [
        parse_raw(f["rel_path"], f["raw_out"], int(f["max_tokens"] or 0), f["query_id"], f["err"])
        for f in figs
    ]
    models = {f["rel_path"]: f["model"] for f in figs}
    fdir = Path(os.environ["JPDOCREAD_WORK"]) / "figures"
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "s40.json").write_text(
        json.dumps(
            [
                {"rel_path": p.rel_path, "doc_id": p.doc_id, "nodes": p.nodes, "edges": p.edges,
                 "query_id": p.query_id, "err": p.err, "model": models[p.rel_path]}
                for p in outs
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )  # fmt: skip
    return outs


def _count_figure_regions(conn: SnowflakeConnection, run_id: str, doc_id: str) -> int:
    from .common import sf

    return int(
        sf.query(
            conn,
            f"SELECT COUNT(*) AS n FROM {sf.ops()}.REGIONS WHERE run_id = %s AND doc_id = %s AND kind = 'figure'",
            (run_id, doc_id),
        )[0]["n"]
    )


def materialize_inputs(conn: SnowflakeConnection, run_id: str, doc_id: str) -> dict:
    """S30 の幾何・領域と、S20・S40 の AI 応答をローカルの作業域に移植元と同じ形式で書き出す。"""
    _copy_s30_inputs(run_id, doc_id)
    n_pages = _write_s20_cache(conn, doc_id, _s20_cache_key(conn, run_id, doc_id))
    outs = _write_s40_outputs(conn, run_id, doc_id)
    n_fig = _count_figure_regions(conn, run_id, doc_id)
    return {
        "n_pages": n_pages,
        "n_figure_regions": n_fig,
        "n_figure_outputs": len(outs),
        "n_figure_errors": sum(1 for p in outs if p.err),
        "figure_errors": sorted({p.err.split(":")[0] for p in outs if p.err}),
    }


def cmd_s50(run_id: str, only: list[str] | None = None) -> int:
    from .common import sf
    from .config import load_corpus_config
    from .read.integrate import ReadOptions, build_output

    conn = sf.connect()
    info = run_info(conn, run_id)
    _check_docs_root(info["corpus"])
    opts = ReadOptions.from_corpus(load_corpus_config(info["corpus"]))
    docs = only or info["docs"]
    done = sf.done_docs(conn, run_id, "S50")
    out_dir = Path(os.environ["JPDOCREAD_OUT"])
    n_fail = 0
    for doc_id in docs:
        if doc_id in done:
            print(f"S50 skip {doc_id}", flush=True)
            continue
        try:
            with sf.step_doc(conn, run_id, "S50", doc_id) as box:
                fail_injected("S50", doc_id)
                mat = materialize_inputs(conn, run_id, doc_id)
                out = build_output(doc_id, opts)
                validate_output(out)
                tmp = out_dir / f"{doc_id}.json"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
                rel = f"{run_id}/{info['corpus']}/{doc_id}.json"
                copy_file(tmp, STAGE_RESULTS / rel)
                box["n_errors"] = int(out["provenance"]["n_errors"]) + mat["n_figure_errors"]
                box["output_uri"] = f"@{sf.names().fq('schema_output', 'RESULTS')}/{rel}"
                box["detail"] = {
                    **mat,
                    "n_elements": len(out["elements"]),
                    "n_outline": len(out["outline"]),
                    "n_tables": len(out["tables"]),
                    "n_figures": len(out["figures"]),
                }
            print(f"S50 ok   {doc_id} elements={len(out['elements'])}", flush=True)
        except Exception as e:  # noqa: BLE001 — 1 文書の失敗で他を止めない（台帳には記録済み）
            n_fail += 1
            print(f"S50 FAIL {doc_id}: {e}", file=sys.stderr, flush=True)
    return 1 if n_fail else 0


# ---------------------------------------------------------------- S60


def insert_json(
    conn: SnowflakeConnection, table: str, rows: list[dict], key_cols: tuple[str, ...]
) -> None:
    """キー列＋行全体を VARIANT 列 `payload` に入れる（移植元 cli._insert_json。列の追加でスキーマを壊さない）。

    VALUES 句には PARSE_JSON を書けないので、JSON を文字列として一時表にバインドで入れてから INSERT … SELECT する。
    """
    if not rows:
        return
    cols = ", ".join(key_cols) + ", payload"
    sel = ", ".join(f"v:{k}::INT" if k == "page" else f"v:{k}::STRING" for k in key_cols)
    cur = conn.cursor()
    try:
        cur.execute("CREATE OR REPLACE TEMPORARY TABLE S60_JSON_BUF (j STRING)")
        cur.executemany(
            "INSERT INTO S60_JSON_BUF (j) VALUES (%s)",
            [(json.dumps(r, ensure_ascii=False, default=str),) for r in rows],
        )
        cur.execute(
            f"INSERT INTO {table} ({cols}) SELECT {sel}, v FROM (SELECT PARSE_JSON(j) AS v FROM S60_JSON_BUF)"
        )
    finally:
        cur.close()


def cmd_s60(run_id: str, only: list[str] | None = None) -> int:
    """評価ジョブ（オーナーは評価ロール）。正解は JPDOCREAD_DOCS（@GOLD.FILES/<corpus>）、予測は JPDOCREAD_OUT。

    評価対象は S60 のプロシージャが EVAL_REQUESTS に書いた文書（予測側の RUNS を写したもの）。供出元・評価除外は
    採点から外し、外したことを summary.excluded_shot_donors に残す（eval/evaluate.py）。
    """
    from .common import sf
    from .config import load_corpus_config
    from .eval.evaluate import as_rows, evaluate

    n = sf.names()
    res = n.fq("schema_results")
    conn = sf.connect()
    rows = sf.query(
        conn,
        f"SELECT corpus, docs, eval_excluded, image_tag FROM {res}.EVAL_REQUESTS WHERE run_id = %s",
        (run_id,),
    )
    if not rows:
        raise SystemExit(f"評価の依頼が無い: {run_id}（S60_EVALUATE が書く）")
    req = rows[0]
    corpus = req["corpus"]
    gold_root = Path(os.environ.get("JPDOCREAD_DOCS", ""))
    if gold_root.name != corpus:
        raise SystemExit(
            f"JPDOCREAD_DOCS が依頼のコーパスと合わない: {gold_root}（期待 …/{corpus}）"
        )
    docs = only or sf.as_list(req["docs"])
    excluded = sf.as_list(req["eval_excluded"])
    cfg = load_corpus_config(corpus)
    eval_run_id = f"{run_id}__eval"
    sf.query(conn, f"USE SCHEMA {res}")  # 一時表を作るスキーマ
    t0 = time.time()
    result = evaluate(
        docs, excluded, out_dir=Path(os.environ["JPDOCREAD_OUT"]), subsets=dict(cfg.slices)
    )
    tables = as_rows(result, eval_run_id, run_id)
    for name in ("DOC_METRICS", "PAGE_METRICS", "ELEMENT_ERRORS", "EVAL_RUNS"):
        sf.query(conn, f"DELETE FROM {res}.{name} WHERE eval_run_id = %s", (eval_run_id,))
    for t in ("doc_metrics", "page_metrics", "element_errors"):
        for r in tables[t]:
            r["corpus"] = corpus
    insert_json(conn, f"{res}.DOC_METRICS", tables["doc_metrics"],
                ("eval_run_id", "pred_run_id", "corpus", "doc_id", "style_id", "genre"))  # fmt: skip
    insert_json(conn, f"{res}.PAGE_METRICS", tables["page_metrics"],
                ("eval_run_id", "pred_run_id", "corpus", "doc_id", "page"))  # fmt: skip
    insert_json(conn, f"{res}.ELEMENT_ERRORS", tables["element_errors"],
                ("eval_run_id", "pred_run_id", "corpus", "doc_id"))  # fmt: skip
    summary = {**tables["summary"][0], "wall_clock_s": round(time.time() - t0, 1)}
    insert_json(
        conn,
        f"{res}.EVAL_RUNS",
        [{"eval_run_id": eval_run_id, "pred_run_id": run_id, "corpus": corpus,
          "image_tag": os.environ.get("JPDOCREAD_IMAGE_TAG"), **summary}],
        ("eval_run_id", "pred_run_id", "corpus", "image_tag"),
    )  # fmt: skip
    s = result["summary"]
    print(json.dumps({"eval_run_id": eval_run_id, "n_docs": s["n_docs"],
                      "excluded": s["excluded_shot_donors"],
                      "citation_error_rate": s["citation"]["citation_error_rate"]}, ensure_ascii=False))  # fmt: skip
    return 0


STEPS = {"s30": cmd_s30, "s50": cmd_s50, "s60": cmd_s60}
