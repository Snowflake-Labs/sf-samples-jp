"""コマンドラインの入口（`python -m jpcalc` / `jpcalc`）。

予測側のコマンドは公開索引と PDF だけを扱う。完全な索引や正解に触れるコマンド（index・fetch-gold）は、
その関数の中でだけ jpcalc.eval を import する（common/guard.py の EVAL_LAUNCHERS）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__

_CORPORA = ("yakkan", "contract")


def _corpus_args(p: argparse.ArgumentParser, *, allow_all: bool = True) -> None:
    choices = (*_CORPORA, "all") if allow_all else _CORPORA
    p.add_argument("--corpus", required=True, choices=choices)


def _corpora(name: str) -> list[str]:
    return list(_CORPORA) if name == "all" else [name]


def _load(name: str):
    from .common.paths import corpus_dir
    from .config import load_corpus_config

    cfg = load_corpus_config(name)
    return cfg, corpus_dir(name, cfg.source.huggingface.revision)


def _refs(cfg, root: Path):
    from .fetch.adapters import PUBLIC_INDEX, pdf_refs, read_public_index

    rows = read_public_index(root / PUBLIC_INDEX)
    return rows, pdf_refs(rows, cfg)


def _fail(e: Exception) -> int:
    print(f"エラー: {e}", file=sys.stderr)
    return 1


# ---- 設定・ガード ------------------------------------------------------------------------------


def _cmd_check_config(args: argparse.Namespace) -> int:
    from .common.names import load_names
    from .config import (
        CORPUS_NAMES,
        ConfigError,
        load_conventions,
        load_corpus_config,
        load_guard_config,
        load_pipeline_config,
    )

    try:
        load_pipeline_config()
        load_conventions()
        load_guard_config()
        corpora = [load_corpus_config(n) for n in CORPUS_NAMES]
        names = load_names()
    except (ConfigError, ValueError) as e:
        print(f"config: FAIL — {e}", file=sys.stderr)
        return 1
    for c in corpora:
        hf = c.source.huggingface
        print(f"config: {c.name}: {hf.repo_id}@{hf.revision}")
    print(f"config: names: {names.db} / {names.eval_db} / {names.warehouse} / {names.compute_pool}")
    print("config: OK")
    return 0


def _cmd_guard(args: argparse.Namespace) -> int:
    from .common.guard import main as guard_main

    return guard_main([])


# ---- 公開索引（評価側の入口） ------------------------------------------------------------------


def _cmd_index(args: argparse.Namespace) -> int:
    """完全な索引をメモリ上で読み、公開索引だけを書き出す。"""
    from .eval.catalog import build_public_index, write_public_index
    from .fetch.sources import source_from_config

    try:
        for name in _corpora(args.corpus):
            cfg, root = _load(name)
            rows = build_public_index(cfg, source_from_config(cfg))
            path = write_public_index(rows, root)
            n_pdf = sum(len(r["pdfs"]) for r in rows)
            n_sha = sum(1 for r in rows for p in r["pdfs"] if p["sha256"])
            print(f"index: {name}: 文書 {len(rows)}・PDF {n_pdf}（照合値あり {n_sha}）→ {path}")
    except Exception as e:  # noqa: BLE001 — 取得・設定の失敗をそのまま表示して止める
        return _fail(e)
    return 0


# ---- 分割 -------------------------------------------------------------------------------------


def _cmd_split(args: argparse.Namespace) -> int:
    from .fetch.split import (
        SPLIT_YAML,
        check_split,
        compute_split,
        load_split,
        summarize,
        write_split,
    )

    try:
        recorded = load_split() if SPLIT_YAML.is_file() else {}
        entries = dict(recorded)
        for name in _corpora(args.corpus):
            cfg, root = _load(name)
            rows, _ = _refs(cfg, root)
            sp = compute_split(rows, salt=cfg.split.salt, dev_fraction=cfg.split.dev_fraction)
            entry = summarize(
                rows,
                sp,
                revision=cfg.source.huggingface.revision,
                salt=cfg.split.salt,
                dev_fraction=cfg.split.dev_fraction,
            )
            if args.check_only:
                check_split(name, entry, recorded)
                print(f"split: {name}: 記録と再計算が一致（交差 0）")
            else:
                entries[name] = entry
            d, h = entry["dev"], entry["holdout"]
            print(
                f"split: {name}: DEV base {d['n_bases']}・文書 {d['n_docs']}・PDF {d['n_pdfs']} ／ "
                f"HOLDOUT base {h['n_bases']}・文書 {h['n_docs']}・PDF {h['n_pdfs']}"
            )
        if not args.check_only:
            write_split({k: entries[k] for k in _CORPORA if k in entries})
            print(f"split: 書き出し → {SPLIT_YAML}")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


# ---- pilot の選定 ------------------------------------------------------------------------------


def _write_slices(slices: dict[str, dict[str, list[str]]], path: Path) -> None:
    """pipeline.yaml の末尾の slices: 節だけを書き換える（他の行とコメントは残す）。"""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^slices:\n(?:[ #].*\n?|\n)*\Z", text, flags=re.M)
    if not m:
        raise ValueError(f"{path} の末尾に slices: 節が無い")
    lines = ["slices:"]
    for corpus in _CORPORA:
        lines.append(f"  {corpus}:")
        for key in ("pilot", "shots"):
            ids = slices[corpus][key]
            lines.append(f"    {key}:" + ("" if ids else " []"))
            lines += [f"      - {i}" for i in ids]
    path.write_text(text[: m.start()] + "\n".join(lines) + "\n", encoding="utf-8")


def _cmd_pick_pilot(args: argparse.Namespace) -> int:
    from .common.paths import PIPELINE_YAML
    from .config import load_pipeline_config
    from .fetch.pilot import pick
    from .fetch.split import load_split

    try:
        split = load_split()
        cur = load_pipeline_config().slices
        slices = {c: {"pilot": list(cur[c].pilot), "shots": list(cur[c].shots)} for c in _CORPORA}
        for name in _corpora(args.corpus):
            cfg, root = _load(name)
            _, refs = _refs(cfg, root)
            dev = set(split[name]["dev"]["bases"])
            pilot, shots = pick(
                [r for r in refs if r.split_group in dev],
                n_pilot=args.n_pilot,
                n_shots=args.n_shots,
            )
            slices[name] = {"pilot": pilot, "shots": shots}
            print(f"pick-pilot: {name}: pilot {pilot}")
            print(f"pick-pilot: {name}: shots {shots}")
        if args.write:
            _write_slices(slices, PIPELINE_YAML)
            load_pipeline_config()  # 書いた結果が検証を通ること
            print(f"pick-pilot: 書き出し → {PIPELINE_YAML}")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


# ---- 取得（予測用：PDF だけ） -------------------------------------------------------------------


def _cmd_fetch(args: argparse.Namespace) -> int:
    from .config import load_guard_config, load_pipeline_config
    from .fetch.run import fetch_predict
    from .fetch.select import select
    from .fetch.sources import source_from_config
    from .fetch.split import check_split, compute_split, load_split, summarize

    try:
        cfg, root = _load(args.corpus)
        rows, refs = _refs(cfg, root)
        recorded = load_split()
        entry = summarize(
            rows,
            compute_split(rows, salt=cfg.split.salt, dev_fraction=cfg.split.dev_fraction),
            revision=cfg.source.huggingface.revision,
            salt=cfg.split.salt,
            dev_fraction=cfg.split.dev_fraction,
        )
        check_split(args.corpus, entry, recorded)
        sl = load_pipeline_config().slices[args.corpus]
        picked = select(
            refs,
            recorded[args.corpus],
            docs=args.docs,
            docs_file=Path(args.docs_file) if args.docs_file else None,
            slice_name=args.slice,
            slice_lists={"pilot": sl.pilot, "shots": sl.shots},
            allow_holdout=args.allow_holdout,
        )
        allow = load_guard_config().predict_allow[args.corpus]
        print(
            f"fetch: {args.corpus}: 対象 PDF {len(picked)} 件（{cfg.source.huggingface.revision}）"
        )
        rep, record = fetch_predict(picked, source_from_config(cfg), root, allow)
        pages = sum(p["page_count"] for p in record["pdfs"])
        print(
            f"fetch: 取得 {record['n_downloaded']}・照合済み {len(rep.verified)}・"
            f"未照合 {len(rep.unverified)}・ページ {pages}"
        )
        for pid in rep.unverified:
            print(f"fetch: 未照合（照合値が無い）: {pid}")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


# ---- 読み取り（段 R/A） -------------------------------------------------------------------------


def _cmd_pdoc(args: argparse.Namespace) -> int:
    from .common.paths import OUT
    from .config import load_pipeline_config
    from .pdfread.run import load_record, make_pdocs

    try:
        cfg, root = _load(args.corpus)
        rev = cfg.source.huggingface.revision
        if args.docs:
            want = [x.strip() for x in args.docs.split(",") if x.strip()]
        else:
            sl = load_pipeline_config().slices[args.corpus]
            want = list(sl.pilot if args.slice == "pilot" else sl.shots)
        # 文書 ID が与えられたら、その文書の取得済みの PDF（全体裁）に広げる
        record = load_record(root)
        pdf_ids = []
        for w in want:
            hits = [p for p in record if p == w or record[p].get("doc_id") == w]
            pdf_ids += hits or [w]
        out_dir = Path(args.out) if args.out else OUT / args.corpus / rev / "pdoc"
        res = make_pdocs(root, list(dict.fromkeys(pdf_ids)), out_dir)
        for r in res:
            print(
                f"pdoc: {r.pdf_id}: 条 {r.n_articles}・read_errors {r.n_read_errors}・"
                f"value_span_errors {r.n_value_span_errors}"
            )
        n_err = sum(r.n_read_errors + r.n_value_span_errors for r in res)
        print(f"pdoc: {len(res)} 件を {out_dir} に書いた（読み取りの誤り {n_err} 件）")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


# ---- 正解の取得（評価側の入口） ----------------------------------------------------------------


def _cmd_fetch_gold(args: argparse.Namespace) -> int:
    from .common.paths import eval_corpus_dir
    from .config import load_guard_config
    from .eval.gold_fetch import fetch_gold
    from .fetch.sources import source_from_config

    try:
        cfg, root = _load(args.corpus)
        _, refs = _refs(cfg, root)
        known = {r.doc_id for r in refs}
        ids = [d.strip() for d in args.docs.split(",") if d.strip()]
        unknown = sorted(set(ids) - known)
        if unknown:
            raise ValueError(f"未知の文書 ID: {unknown}")
        dest = eval_corpus_dir(args.corpus, cfg.source.huggingface.revision)
        got = fetch_gold(
            cfg, source_from_config(cfg), ids, dest, load_guard_config().predict_allow[args.corpus]
        )
        print(f"fetch-gold: {args.corpus}: {len(got)} ファイル → {dest}（評価側の置き場所）")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    """採点（評価側の入口）。生成物を対応付け M のアダプタ越しに正解テストで採点する（課金なし）。

    --control：逆対照。正解プログラム自身と、正解カードを合成カードとして与えた恒等の対応で全件合格を確かめる。
    """
    from .common.paths import OUT, WORK, eval_corpus_dir
    from .eval import controls, evaluate
    from .eval.gold import Gold

    try:
        cfg, root = _load(args.corpus)
        rev = cfg.source.huggingface.revision
        gold_root = eval_corpus_dir(args.corpus, rev)
        _, refs = _refs(cfg, root)
        meta = {r.pdf_id: {"stratum": r.stratum, "style": r.style} for r in refs}
        if args.report:
            return _eval_report(args.run_id)
        if args.control:
            docs = sorted(
                {
                    r.doc_id
                    for r in refs
                    if Gold(args.corpus, gold_root, r.doc_id).path("tasks").exists()
                }
            )
            bad = 0
            for d in docs:
                c = controls.run_controls(Gold(args.corpus, gold_root, d))
                bad += not c["ok"]
                print(
                    f"{'OK' if c['ok'] else 'NG'} {d}: 正解プログラム {c['reference']}・"
                    f"恒等の対応 {c['identity_map']}・アダプタ越し {c['identity_adapter']}"
                )
            print(f"逆対照: {len(docs) - bad}/{len(docs)} 文書が全件合格")
            return 0 if docs and not bad else 1
        run_dir = (
            Path(args.run_dir) if args.run_dir else OUT / args.corpus / rev / "runs" / args.run_id
        )
        if not run_dir.is_dir():
            raise ValueError(f"生成物の置き場所が無い: {run_dir}")
        pdfs = sorted(p.name for p in run_dir.iterdir() if p.is_dir())
        unknown = sorted(set(pdfs) - set(meta))
        if unknown:
            raise ValueError(f"公開索引に無い PDF: {unknown}")
        work = WORK / "eval" / args.corpus / args.run_id
        res = evaluate.evaluate_run(args.corpus, gold_root, run_dir, pdfs, work, meta)
        res.update(run_id=args.run_id, dataset_revision=rev)
        out = work / "eval.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        d = res["discovery"]
        print(
            f"evaluate: {args.corpus} run {args.run_id}: PDF {res['n_pdfs']}・"
            f"ルールの合格 {res['n_rules_pass']}/{res['n_rules']}・"
            f"ケース {res['n_cases_pass']}/{res['n_cases']}・"
            f"対応 {d['n_matched']}/{d['n_gold_rules']}（生成 {d['n_gen_functions']}）・"
            f"損失 {d['lost_by_stage']} → {out}"
        )
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_read_score(args: argparse.Namespace) -> int:
    """読み取りの採点（評価側の入口）。正解の layout.json と pdoc を照らし合わせる。"""
    from .common.paths import OUT, eval_corpus_dir
    from .eval.read_score import score_files, total

    try:
        cfg, _ = _load(args.corpus)
        rev = cfg.source.huggingface.revision
        pdoc_dir = Path(args.pdoc_dir) if args.pdoc_dir else OUT / args.corpus / rev / "pdoc"
        ids = (
            [x.strip() for x in args.pdfs.split(",") if x.strip()]
            if args.pdfs
            else sorted(p.stem for p in pdoc_dir.glob("*.json"))
        )
        if not ids:
            raise ValueError(f"採点する pdoc がありません: {pdoc_dir}")
        scores = score_files(cfg, eval_corpus_dir(args.corpus, rev), pdoc_dir, ids)
        print(f"read-score: {args.corpus}: {len(scores)} PDF（{rev}）")
        for k, v in total(scores).items():
            r = "-" if v.recall is None else f"{v.recall:.3f}"
            pr = "-" if v.precision is None else f"{v.precision:.3f}"
            print(
                f"  {k:10} 正解 {v.n_gold:4}・読み取り {v.n_pred:4}・対応 {v.n_match:4}・"
                f"再現率 {r}・適合率 {pr}"
            )
        if args.json:
            Path(args.json).write_text(
                json.dumps([s.to_dict() for s in scores], ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8",
            )
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_make_shots(args: argparse.Namespace) -> int:
    """few-shot の手本を作る（評価側の入口。shots の PDF の正解から機械的に作り、work/shots/ に書く）。"""
    from .common.paths import OUT, WORK, eval_corpus_dir
    from .config import load_pipeline_config
    from .eval.shots import make_shots, write_shots
    from .fetch.select import select
    from .fetch.split import load_split

    try:
        cfg, root = _load(args.corpus)
        rev = cfg.source.huggingface.revision
        _, refs = _refs(cfg, root)
        sl = load_pipeline_config().slices[args.corpus]
        lists = {"pilot": sl.pilot, "shots": sl.shots}
        # 選定が DEV に属することと、pilot と base を共有しないことを公開索引で確かめる
        picked = select(refs, load_split()[args.corpus], slice_name="shots", slice_lists=lists)
        shots = make_shots(
            cfg,
            eval_corpus_dir(args.corpus, rev),
            OUT / args.corpus / rev / "pdoc",
            [r.pdf_id for r in picked],
            list(sl.pilot),
        )
        rep = write_shots(args.corpus, shots, Path(args.out) if args.out else WORK / "shots")
        n_kept = sum(len(d["kept"]) for d in rep["docs"])
        n_drop = sum(len(d["dropped"]) for d in rep["docs"])
        print(
            f"make-shots: {args.corpus}: {len(shots)} PDF・ルール {n_kept} 件を手本にした（外した {n_drop} 件）→ {rep['dir']}"
        )
        for d in rep["docs"]:
            for old, new in d["renamed"].items():
                print(f"  名前を置き換えた（pilot の正解と重なる）: {d['pdf_id']}: {old} → {new}")
            for fn, why in d["dropped"].items():
                print(f"  外した: {d['pdf_id']}: {fn}: {why[:160]}")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


# 見込みの目安（内部の実測。保険約款・claude-sonnet-5・キャッシュ無し）：1 PDF あたり約 10 要求・1 要求 約 0.1 クレジット
_REQ_PER_PDF = 10
_CREDIT_PER_REQ = 0.1
# 予測ジョブの所要の目安（初回・キャッシュが空のとき）：1 PDF で約 13〜15 分、保険約款の 4 PDF で約 45 分の実測から
_MIN_BASE, _MIN_PER_PDF = 4, 10.5
_TASK_LIMIT_MIN = 240  # T_S10 の USER_TASK_TIMEOUT_MS（sql/tasks/dag.sql）
_BATCH_PDFS = 10  # 分けて流すときの目安（約 110 分。予測ジョブの時間制限に余裕をもって収まる）


def _duration_note(n_pdfs: int) -> str:
    m = round(_MIN_BASE + _MIN_PER_PDF * n_pdfs)
    note = f"予測ジョブの所要の見込み 約 {m} 分（初回の目安。キャッシュに当たる分は短い）"
    if m > _TASK_LIMIT_MIN:
        note += (
            f"。Task の時間制限（{_TASK_LIMIT_MIN // 60} 時間）を超える見込み：--docs-file で {_BATCH_PDFS} PDF ほどずつに"
            "分けて流すか、時間切れの後に --resume で続きを流す（4 PDF ずつ記録するので、終わった分は飛ばす。"
            "前のジョブが動いている間は再開を止める）"
        )
    return note


def _refuse_shot_documents(refs, ids: list[str], args: argparse.Namespace) -> None:
    """手本を使う run の対象に、手本（shots）と base を共有する PDF があれば止める（自分の正解の手本で採点しない）。"""
    from .config import load_pipeline_config
    from .fetch.select import shot_overlap

    if getattr(args, "no_shots", False):
        return
    bad = shot_overlap(refs, ids, load_pipeline_config().slices[args.corpus].shots)
    if bad:
        raise ValueError(
            f"手本（shots）と同じ base の PDF が対象にある: {bad[:3]}。手本はその正解から作るので、"
            "手本を使う run では対象にしない（対象から外す）"
        )


def _cmd_predict(args: argparse.Namespace) -> int:
    """予測（段 K〜R）をローカルで回す。AI を呼ぶので課金がある。--yes が無ければ見込みを表示して止まる。"""
    import uuid

    from .common import sf
    from .config import load_pipeline_config
    from .predict import pipeline
    from .predict import shots as PS

    try:
        cfg, root = _load(args.corpus)
        rev = cfg.source.huggingface.revision
        sl = load_pipeline_config().slices[args.corpus]
        ids = (
            [x.strip() for x in args.pdfs.split(",") if x.strip()]
            if args.pdfs
            else list(sl.pilot if args.slice == "pilot" else sl.shots)
        )
        if args.limit:
            ids = ids[: args.limit]
        if not ids:
            raise ValueError("対象の PDF がありません")
        missing = [
            i for i in ids if not (pipeline.pdoc_dir(args.corpus, rev) / f"{i}.json").is_file()
        ]
        if missing:
            raise ValueError(
                f"pdoc がありません: {missing}（jpcalc pdoc --corpus {args.corpus} で作る）"
            )
        _refuse_shot_documents(_refs(cfg, root)[1], ids, args)
        if args.no_shots:
            k_text = d_text = ""
        else:
            from .predict import d_spec, k_cards

            k_text = k_cards.render_shots(PS.load(args.corpus, "k_cards"))
            d_text = d_spec.render_shots(PS.load(args.corpus, "d_spec"))
        n_req = _REQ_PER_PDF * len(ids)
        print(
            f"predict: {args.corpus}: {len(ids)} PDF（{rev}）。見込み 約 {n_req} 要求・"
            f"約 {n_req * _CREDIT_PER_REQ:.1f} AI クレジット（キャッシュに当たる分は課金しない）"
        )
        if not args.yes:
            print(
                "predict: AI を呼ぶので課金があります。見込みを確かめてから --yes を付けて実行する"
            )
            return 2
        run_id = args.run_id or f"{args.corpus}-{uuid.uuid4().hex[:8]}"
        from .config import load_corpus_config

        conn = sf.connect()
        try:
            out = pipeline.run_pdfs(
                conn,
                run_id,
                args.corpus,
                rev,
                ids,
                k_shots_text=k_text,
                d_shots_text=d_text,
                max_iter=args.max_iter,
                tuning=load_corpus_config(args.corpus).tuning,
            )
        finally:
            conn.close()
        st = out.pop("_llm_stats", {})
        for d, s in out.items():
            ok = sum(1 for v in s["selftest_by_function"].values() if v)
            n = len(s["selftest_by_function"])
            print(
                f"  {d}: カード {n}・自己テスト合格 {ok}/{n}・最終の周回 {s['final_iteration']}・"
                f"モジュール {s['module'] or 'なし'}{'・誤り ' + s['error'] if s['error'] else ''}"
            )
        print(f"predict: run_id {run_id}・AI {st}")
        print(f"predict: 出力 → {pipeline.OUT / args.corpus / rev / 'runs' / run_id}")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_setup(args: argparse.Namespace) -> int:
    """Snowflake のオブジェクトを作る（冪等）。--apply が無ければ SQL を表示するだけ。"""
    from .common import sf, sqltpl
    from .ops import deploy_values, setup

    try:
        if not args.apply:
            v = deploy_values("<current_user>")
            for f in sqltpl.SETUP_FILES:
                print(f"-- {f}\n{sqltpl.render_file(f, v)}")
            print("setup: --apply を付けると実行する（ACCOUNTADMIN が要る）")
            return 2
        conn = sf.connect(role="ACCOUNTADMIN", use_warehouse=False)
        try:
            n = setup(conn)
        finally:
            conn.close()
        print(f"setup: {n} 文を実行し、ジョブ仕様を置いた")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_verify_roles(args: argparse.Namespace) -> int:
    """ロール分離の検証（USE SECONDARY ROLES NONE つき）。1 件でも期待と違えば非 0。"""
    from .common import sf
    from .ops import verify_roles

    try:
        conn = sf.connect(role="ACCOUNTADMIN", use_warehouse=False)
        try:
            res = verify_roles(conn)
        finally:
            conn.close()
        bad = [r for r in res if r["expect"] != r["got"]]
        for r in res:
            mark = "OK" if r["expect"] == r["got"] else "NG"
            print(f"  {mark} expect={r['expect']} got={r['got']}  {r['sql'][:150]}")
            if mark == "NG" and r["error"]:
                print(f"     {r['error']}")
        if bad:
            print(f"verify-roles: {len(bad)}/{len(res)} 件が期待と違う", file=sys.stderr)
            return 1
        print(f"verify-roles: {len(res)} 件すべて期待どおり")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_check_model(args: argparse.Namespace) -> int:
    """設定のモデルが使えるかを、予測ロールで AI_COMPLETE を 1 回呼んで確かめる（数トークンの課金）。"""
    from .common import sf
    from .config import load_pipeline_config
    from .ops import check_model

    try:
        model = load_pipeline_config().llm.model
        conn = sf.connect()
        try:
            r = check_model(conn, model)
        finally:
            conn.close()
        if r["ok"]:
            print(f"check-model: {model} を使える")
            return 0
        print(f"check-model: {model} を使えない: {r['error']}", file=sys.stderr)
        if r["cross_region"] is not None:
            print(
                f"check-model: CORTEX_ENABLED_CROSS_REGION の今の値は {r['cross_region']!r}",
                file=sys.stderr,
            )
        print(
            "check-model: 既定のモデルはクロスリージョン推論を要る。README の「3.1 Snowflake アカウントの要件」と"
            "「15. 既知の限界と注意事項」を見て、管理者に設定を確かめるか、configs/pipeline.yaml の llm.model を変える",
            file=sys.stderr,
        )
        return 1
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _pick_pdfs(args, sl) -> list[str]:
    ids = (
        [x.strip() for x in args.pdfs.split(",") if x.strip()]
        if args.pdfs
        else list(sl.pilot if args.slice == "pilot" else sl.shots)
    )
    if args.limit:
        ids = ids[: args.limit]
    if not ids:
        raise ValueError("対象の PDF がありません")
    return ids


def _cmd_teardown(args: argparse.Namespace) -> int:
    """専用オブジェクトを名前指定で消す（ACCOUNTADMIN）。--yes が無ければ消す文を表示するだけ。"""
    from .common import sf
    from .ops import applicable, db_exists, deploy_values, eval_job_services, residue, teardown_plan

    try:
        v = deploy_values()
        plan = teardown_plan(v, keep_eval=args.keep_eval)
        if not args.yes:
            print("teardown: 次の文を実行する（--yes で実行）")
            for x in plan:
                print(f"  {x};")
            return 2
        conn = sf.connect(role="ACCOUNTADMIN", use_warehouse=False)
        try:
            if args.keep_eval:
                for job in eval_job_services(conn, v):
                    sf.query(conn, f"DROP SERVICE IF EXISTS {job}")
            for x in applicable(plan, v, db_exists(conn, v["db"])):
                sf.query(conn, x)
            left = residue(conn, v, keep_eval=args.keep_eval)
        finally:
            conn.close()
        if left:
            raise RuntimeError(f"残っている専用オブジェクトがある: {left}")
        kept = (
            f"（残した：{v['eval_db']}・{v['role_eval']}・{v['role_admin']}・{v['warehouse']}）"
            if args.keep_eval
            else ""
        )
        print(f"teardown: 専用オブジェクトを消した。残存 0{kept}")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_targets(args: argparse.Namespace) -> int:
    """対象の PDF ID を 1 行に出す（--docs・--docs-file・--slice の排他・未知 ID・HOLDOUT の検査つき）。"""
    from .config import load_pipeline_config
    from .fetch.select import select
    from .fetch.split import load_split

    try:
        cfg, root = _load(args.corpus)
        _, refs = _refs(cfg, root)
        sl = load_pipeline_config().slices[args.corpus]
        picked = select(
            refs,
            load_split()[args.corpus],
            docs=args.docs,
            docs_file=Path(args.docs_file) if args.docs_file else None,
            slice_name=args.slice,
            slice_lists={"pilot": sl.pilot, "shots": sl.shots},
            allow_holdout=args.allow_holdout,
        )
        print(",".join(r.pdf_id for r in picked))
        print(
            f"targets: {len(picked)} PDF・ページ {sum(r.pages_index for r in picked)}（索引の値）",
            file=sys.stderr,
        )
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_upload(args: argparse.Namespace) -> int:
    """予測の入力ステージに、照合済みの PDF・照合値・手本を置く（正解は置かない）。"""
    from .common import sf
    from .config import load_pipeline_config
    from .ops import upload_predict

    try:
        cfg, root = _load(args.corpus)
        ids = _pick_pdfs(args, load_pipeline_config().slices[args.corpus])
        conn = sf.connect(role=sf.names().role_admin)
        try:
            r = upload_predict(
                conn,
                args.corpus,
                cfg.source.huggingface.revision,
                ids,
                root,
                shots=not args.no_shots,
            )
        finally:
            conn.close()
        print(f"upload: {r['stage']} に PDF {r['n_pdfs']} 件・手本 {r['n_shots']} 件を置いた")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Task グラフで予測を回す（SPCS。AI と SPCS の課金がある。--yes が無ければ見込みを表示して止まる）。"""
    import uuid

    from .common import sf
    from .config import load_pipeline_config
    from .fetch.split import load_split
    from .ops import (
        active_jobs,
        ai_signature,
        ai_summary,
        needs_declaration,
        run_exists,
        signature_seen,
        start_run,
        wait_run,
    )

    try:
        cfg, root = _load(args.corpus)
        rev = cfg.source.huggingface.revision
        ids = _pick_pdfs(args, load_pipeline_config().slices[args.corpus])
        n_req = _REQ_PER_PDF * len(ids)
        print(
            f"run: {args.corpus}: {len(ids)} PDF（{rev}）。AI の見込み 約 {n_req} 要求・"
            f"約 {n_req * _CREDIT_PER_REQ:.1f} クレジット（キャッシュに当たる分は課金しない）＋ SPCS のプールの稼働"
        )
        print(f"run: {_duration_note(len(ids))}")
        if not args.yes:
            print("run: 課金があります。見込みを確かめてから --yes を付けて実行する")
            return 2
        run_id = args.resume or args.run_id or f"{args.corpus}-{uuid.uuid4().hex[:8]}"
        fail = None
        if args.fail:
            step, _, pdf = args.fail.partition(":")
            if step not in ("A", "P") or pdf not in ids:
                raise ValueError(f"--fail は A:<PDF ID> か P:<PDF ID>（対象の PDF）: {args.fail!r}")
            fail = {"step": step, "pdf": pdf}
        _, refs = _refs(cfg, root)
        held_bases = set(load_split()[args.corpus]["holdout"]["bases"])
        holdout = any(r.split_group in held_bases for r in refs if r.pdf_id in ids)
        if holdout and not args.allow_holdout:
            raise ValueError("HOLDOUT の PDF が含まれる（--allow-holdout と宣言が要る）")
        _refuse_shot_documents(refs, ids, args)
        conn = sf.connect()
        try:
            exists = run_exists(conn, run_id)
            if args.resume and not exists:
                raise ValueError(
                    f"再開する run が無い: {run_id}（新しい run は --run-id で始める）"
                )
            if args.resume and (busy := active_jobs(conn, run_id)):
                raise ValueError(
                    f"前の予測ジョブがまだ動いている: {busy}。終わってから再開する（状態は "
                    "SHOW JOB SERVICES で確かめる。同じ run のジョブを 2 つ動かさないため）"
                )
            if args.run_id and exists and not args.resume:
                raise ValueError(f"run_id が既にある: {run_id}（再開なら --resume を使う）")
            why = needs_declaration(
                n_pdfs=len(ids),
                n_pilot=len(load_pipeline_config().slices[args.corpus].pilot),
                no_cache=args.no_cache,
                n_cache=ai_summary(conn, run_id)["n_cache"],
                holdout=holdout,
                new_signature=not signature_seen(conn, ai_signature()),
            )
            if why and not args.declare and not exists:
                print(
                    f"run: 課金の宣言が要る（{'・'.join(why)}）。--declare に要求数と見込みを書いて実行する"
                )
                return 2
            if args.check_only:
                print(f"run: 起動の前の検査が通った（宣言の理由：{'・'.join(why) or 'なし'}）")
                return 0
            start_run(
                conn,
                run_id,
                args.corpus,
                rev,
                ids,
                shots=not args.no_shots,
                declaration=args.declare,
                max_iter=args.max_iter,
                evaluate=args.eval,
                no_cache=args.no_cache,
                fail=fail,
                from_step=args.from_step,
            )
            print(f"run: run_id {run_id} を起動した")
            if args.no_wait:
                return 0
            st = wait_run(conn, run_id)
            ai = ai_summary(conn, run_id)
        finally:
            conn.close()
        print(f"run: {st['run']['status']}・{st['run']['message']}")
        for r in st["steps"]:
            print(f"  {r['step']:4} {r['doc_id']:45} {r['status']:9} 誤り {r['n_errors']}")
            if r["status"] == "FAILED" and r.get("error_text"):
                print(f"       {str(r['error_text'])[:200]}")
        print(
            f"run: AI 要求 {ai['n_requests']}・この run_id で呼んだ累計 {ai['n_called']}"
            f"（残りはキャッシュ）。再開：--resume {run_id}"
        )
        return 0 if st["run"]["status"] == "SUCCEEDED" else 1
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _cmd_image_repo(args: argparse.Namespace) -> int:
    """イメージリポジトリの URL を表示する。--record-tag は push したタグを確かめて deploy.local.env に書く。"""
    from .common import sf
    from .ops import image_repo_url, record_tag

    try:
        conn = sf.connect(role=sf.names().role_admin)
        try:
            if args.record_tag:
                record_tag(conn, args.record_tag)
            else:
                print(image_repo_url(conn))
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_job(args: argparse.Namespace) -> int:
    """SPCS のジョブの中で動く入口。"""
    if args.kind == "evaluate":
        return _cmd_eval_job(args)
    from .jobs import run_predict

    try:
        print(json.dumps(run_predict(args.run_id), ensure_ascii=False, default=str))
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _eval_report(run_id: str) -> int:
    """評価 DB の最新の評価結果を表示する（評価ロール）。予測ロールでは読めない。"""
    from .common import sf

    n = sf.names()
    conn = sf.connect(role=n.role_eval)
    try:
        rows = sf.query(
            conn,
            f"SELECT eval_run_id, n_rules_pass, n_rules, n_cases_pass, n_cases, n_errors, "
            f"summary:discovery:lost_by_stage::STRING AS lost, image_tag FROM {n.fq('schema_results', 'EVAL_RUNS')} "
            "WHERE run_id = %s ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
    finally:
        conn.close()
    if not rows:
        print(f"evaluate: 評価記録が無い: {run_id}")
        return 1
    r = rows[0]
    print(
        f"evaluate: run {run_id}（eval {r['eval_run_id']}・image {r['image_tag']}）："
        f"ルールの合格 {r['n_rules_pass']}/{r['n_rules']}・ケース {r['n_cases_pass']}/{r['n_cases']}・"
        f"誤り {r['n_errors']}・損失 {r['lost']}"
    )
    return 0


def _cmd_eval_job(args: argparse.Namespace) -> int:
    """評価ジョブの入口（評価側。評価ロールで動く）。"""
    from .eval.job import run_evaluate

    try:
        if not args.eval_run_id:
            raise ValueError("--eval-run-id が無い")
        print(
            json.dumps(run_evaluate(args.run_id, args.eval_run_id), ensure_ascii=False, default=str)
        )
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _cmd_upload_gold(args: argparse.Namespace) -> int:
    """評価用の正解を正解のステージに置く（評価側。評価ロールで PUT する。--eval の run の前に実行する）。"""
    from .common import sf
    from .common.paths import eval_corpus_dir
    from .config import load_pipeline_config
    from .eval.store import upload_gold

    try:
        cfg, _ = _load(args.corpus)
        rev = cfg.source.huggingface.revision
        ids = _pick_pdfs(args, load_pipeline_config().slices[args.corpus])
        conn = sf.connect(role=sf.names().role_eval)
        try:
            r = upload_gold(conn, args.corpus, rev, ids, eval_corpus_dir(args.corpus, rev))
        finally:
            conn.close()
        print(
            f"upload-gold: {r['stage']} に {r['n_docs']} 文書・{r['n_files']} ファイルを置いた（照合済み）"
        )
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def _eval_db_exists() -> bool:
    """評価 DB があるか（ACCOUNTADMIN で名前を完全一致で確かめる。確かめられなければ例外のまま止める）。"""
    from .common import sf
    from .ops import db_exists

    conn = sf.connect(role="ACCOUNTADMIN", use_warehouse=False)
    try:
        return db_exists(conn, sf.names().eval_db)
    finally:
        conn.close()


def _cmd_export_results(args: argparse.Namespace) -> int:
    """評価記録を results/<run_id>__<eval_run_id>/ に退避し、行数を照合する（評価側。teardown の前に実行する）。"""
    from .common import sf
    from .common.paths import HOME
    from .eval.store import export

    try:
        try:
            conn = sf.connect(role=sf.names().role_eval)
        except Exception as e:  # noqa: BLE001
            if not args.all:
                raise
            # 評価 DB がもう無い（消した後の再実行）ときだけ、退避するものは無いとみなす。評価 DB があるのに
            # 評価ロールで入れない（setup とは別の利用者・認証の期限切れなど）ときは、退避できないので止める
            # （teardown はこの失敗で評価 DB を消さずに止まる）
            if _eval_db_exists():
                raise RuntimeError(
                    f"評価 DB {sf.names().eval_db} はあるが、評価ロールで接続できない（{type(e).__name__}: "
                    f"{str(e).splitlines()[0][:200]}）。評価記録を退避できないので消さない。setup を実行した"
                    "利用者で流すか、退避が要らなければ teardown に --no-export を付ける"
                ) from e
            print("export-results: 評価 DB が無いので、退避する評価記録は無い")
            return 0
        try:
            out = export(conn, args.run_id, Path(args.dest) if args.dest else HOME / "results")
        finally:
            conn.close()
        if not out and args.run_id:
            raise ValueError(f"評価記録が無い: {args.run_id}")
        if not out:
            print("export-results: 退避する評価記録は無い")
        for o in out:
            print(
                f"export-results: {o['eval_run_id']} → {o['dir']}（行数の照合 OK: {o['counts']}）"
            )
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jpcalc",
        description="日本語の文書の PDF から計算・判定のプログラムを作るパイプライン",
    )
    p.add_argument("--version", action="version", version=f"jpcalc {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check-config", help="設定ファイル一式を検査する").set_defaults(
        func=_cmd_check_config
    )
    sub.add_parser("guard", help="正解漏れガード（AST 検査）を実行する").set_defaults(
        func=_cmd_guard
    )

    s = sub.add_parser("index", help="公開索引を作る（正解由来の列を写さない）")
    _corpus_args(s)
    s.set_defaults(func=_cmd_index)

    s = sub.add_parser("split", help="DEV/HOLDOUT の分割を記録する（--check-only で照合だけ）")
    _corpus_args(s)
    s.add_argument("--check-only", action="store_true", help="記録と再計算を照合し、書き換えない")
    s.set_defaults(func=_cmd_split)

    s = sub.add_parser("pick-pilot", help="DEV から pilot と shots の PDF を選ぶ")
    _corpus_args(s)
    s.add_argument("--n-pilot", type=int, default=4)
    s.add_argument("--n-shots", type=int, default=2)
    s.add_argument("--write", action="store_true", help="configs/pipeline.yaml の slices に書く")
    s.set_defaults(func=_cmd_pick_pilot)

    s = sub.add_parser("fetch", help="予測用の PDF だけを取得して照合する")
    _corpus_args(s, allow_all=False)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--docs", help="文書 ID か PDF ID（カンマ区切り）")
    g.add_argument("--docs-file", help="ID を 1 行 1 件で書いたファイル")
    g.add_argument("--slice", choices=("pilot", "shots", "dev", "holdout"))
    s.add_argument(
        "--allow-holdout", action="store_true", help="HOLDOUT を含めてよい（承認後だけ）"
    )
    s.set_defaults(func=_cmd_fetch)

    s = sub.add_parser("pdoc", help="取得済みで照合済みの PDF から pdoc を作る（AI を使わない）")
    _corpus_args(s, allow_all=False)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--docs", help="文書 ID か PDF ID（カンマ区切り）。取得済みのものに限る")
    g.add_argument("--slice", choices=("pilot", "shots"))
    s.add_argument("--out", help="書き出し先（既定は out/<corpus>/<revision>/pdoc）")
    s.set_defaults(func=_cmd_pdoc)

    s = sub.add_parser(
        "teardown", help="専用オブジェクトを名前指定で消す（--yes が無ければ表示だけ）"
    )
    s.add_argument("--yes", action="store_true")
    s.add_argument(
        "--keep-eval",
        action="store_true",
        help="評価 DB・評価ロール・管理ロール・ウェアハウスを残す",
    )
    s.set_defaults(func=_cmd_teardown)

    s = sub.add_parser("targets", help="対象の PDF ID を出す（排他・未知 ID・HOLDOUT の検査）")
    _corpus_args(s, allow_all=False)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--docs", help="文書 ID か PDF ID（カンマ区切り）")
    g.add_argument("--docs-file", help="ID を 1 行 1 件で書いたファイル")
    g.add_argument("--slice", choices=("pilot", "shots", "dev", "holdout"))
    s.add_argument("--allow-holdout", action="store_true")
    s.set_defaults(func=_cmd_targets)

    s = sub.add_parser("fetch-gold", help="評価用の正解を取得する（評価側の置き場所）")
    _corpus_args(s, allow_all=False)
    s.add_argument("--docs", required=True, help="文書 ID（カンマ区切り）")
    s.set_defaults(func=_cmd_fetch_gold)

    s = sub.add_parser("evaluate", help="生成物を正解テストで採点する（評価側。課金なし）")
    _corpus_args(s, allow_all=False)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-id", help="採点する run（<出力>/runs/<run_id>）")
    g.add_argument("--control", action="store_true", help="逆対照（正解プログラム・恒等の対応）")
    s.add_argument(
        "--report",
        action="store_true",
        help="評価 DB の結果を表示する（--run-id と一緒に指定。評価ロール）",
    )
    s.add_argument(
        "--run-dir", help="生成物の置き場所（既定は <出力>/<corpus>/<revision>/runs/<run_id>）"
    )
    s.set_defaults(func=_cmd_eval)

    s = sub.add_parser(
        "read-score",
        help="読み取りを採点する（評価側。正解の layout.json と pdoc を照らし合わせる）",
    )
    _corpus_args(s, allow_all=False)
    s.add_argument("--pdfs", help="PDF ID（カンマ区切り）。既定は pdoc の置き場所にあるすべて")
    s.add_argument("--pdoc-dir", help="pdoc の置き場所（既定は out/<corpus>/<revision>/pdoc）")
    s.add_argument("--json", help="PDF ごとの採点を書き出すファイル")
    s.set_defaults(func=_cmd_read_score)

    s = sub.add_parser(
        "make-shots",
        help="few-shot の手本を作る（評価側。shots の PDF の正解から作り、work/shots/ に書く）",
    )
    _corpus_args(s, allow_all=False)
    s.add_argument("--out", help="書き出し先（既定は work/shots）")
    s.set_defaults(func=_cmd_make_shots)

    s = sub.add_parser(
        "predict",
        help="予測（段 K〜R）をローカルで回す（AI を呼ぶ。--yes が無ければ見込みを表示して止まる）",
    )
    _corpus_args(s, allow_all=False)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--pdfs", help="PDF ID（カンマ区切り）")
    g.add_argument("--slice", choices=("pilot", "shots"))
    s.add_argument("--limit", type=int, help="先頭から N 件だけ")
    s.add_argument("--run-id", help="既定は <corpus>-<乱数 8 桁>")
    s.add_argument("--max-iter", type=int, help="改修（R）の周回の上限（既定は pipeline.yaml）")
    s.add_argument(
        "--no-shots", action="store_true", help="手本なしで回す（手本の効果を比べるとき）"
    )
    s.add_argument("--yes", action="store_true", help="課金を承知して実行する")
    s.set_defaults(func=_cmd_predict)

    s = sub.add_parser(
        "setup",
        help="Snowflake のオブジェクトを作る（冪等。--apply が無ければ SQL を表示するだけ）",
    )
    s.add_argument("--apply", action="store_true", help="実行する")
    s.set_defaults(func=_cmd_setup)

    s = sub.add_parser("verify-roles", help="ロール分離を検証する（USE SECONDARY ROLES NONE つき）")
    s.set_defaults(func=_cmd_verify_roles)

    s = sub.add_parser(
        "check-model", help="設定のモデルを使えるかを確かめる（AI_COMPLETE を 1 回。数トークン）"
    )
    s.set_defaults(func=_cmd_check_model)

    for name, fn, hlp in (
        (
            "upload",
            _cmd_upload,
            "予測の入力ステージに照合済みの PDF・照合値・手本を置く（正解は置かない）",
        ),
        (
            "upload-gold",
            _cmd_upload_gold,
            "評価用の正解を正解のステージに置く（評価ロール。--eval の run の前に実行する）",
        ),
        (
            "run",
            _cmd_run,
            "Task グラフで予測を回す（SPCS。--yes が無ければ見込みを表示して止まる）",
        ),
    ):
        s = sub.add_parser(name, help=hlp)
        _corpus_args(s, allow_all=False)
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--pdfs", help="PDF ID（カンマ区切り）")
        g.add_argument("--slice", choices=("pilot", "shots"))
        s.add_argument("--limit", type=int, help="先頭から N 件だけ")
        s.add_argument("--no-shots", action="store_true", help="手本なし")
        if name == "run":
            s.add_argument("--run-id", help="既定は <corpus>-<乱数 8 桁>")
            s.add_argument("--resume", help="この run_id を再開する（成功済みの PDF は飛ばす）")
            s.add_argument("--max-iter", type=int)
            s.add_argument("--declare", help="課金の宣言（要求数・見込み）。台帳に残す")
            s.add_argument("--no-wait", action="store_true")
            s.add_argument("--yes", action="store_true", help="課金を承知して実行する")
            s.add_argument(
                "--eval",
                action="store_true",
                help="予測の後に評価ジョブを回す（upload-gold を先に）",
            )
            s.add_argument(
                "--no-cache", action="store_true", help="AI のキャッシュを使わない（宣言が要る）"
            )
            s.add_argument(
                "--from",
                dest="from_step",
                choices=("A", "P", "E"),
                help="この段からやり直す（--resume と一緒に指定。A: 読み取り、P: K〜R、E: 評価のみ）",
            )
            s.add_argument("--fail", help="故障注入（運用の試験用）：A:<PDF ID> か P:<PDF ID>")
            s.add_argument(
                "--allow-holdout", action="store_true", help="HOLDOUT を含む（宣言が要る）"
            )
            s.add_argument(
                "--check-only", action="store_true", help="起動の前の検査（再開・宣言）だけ"
            )
        s.set_defaults(func=fn)

    s = sub.add_parser(
        "export-results", help="評価記録を results/ に退避して行数を照合する（評価ロール）"
    )
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-id")
    g.add_argument("--all", action="store_true", help="すべての評価記録（teardown の前）")
    s.add_argument("--dest", help="退避先（既定は results/）")
    s.set_defaults(func=_cmd_export_results)

    s = sub.add_parser(
        "image-repo", help="イメージリポジトリの URL（--record-tag で push したタグを記録する）"
    )
    s.add_argument("--record-tag")
    s.set_defaults(func=_cmd_image_repo)

    s = sub.add_parser("job", help="SPCS のジョブの中で動く入口")
    s.add_argument("kind", choices=("predict", "evaluate"))
    s.add_argument("--run-id", required=True)
    s.add_argument("--eval-run-id")
    s.set_defaults(func=_cmd_job)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
