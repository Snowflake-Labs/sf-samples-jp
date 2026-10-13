"""コマンドラインの入口（`uv run jpdocread <サブコマンド>` または `python -m jpdocread`）。

サブコマンドの一覧と全オプションは `jpdocread --help`・`jpdocread <サブコマンド> --help`。

fetch         データセットを取得し、manifest と照合する
guard         正解漏れガード（start.sh の前段と pytest で走らせる）
names         Snowflake のオブジェクト名を表示する（シェルスクリプトが使う）
connection    接続名を解決して表示する
local read    AI を使わない層だけをローカルで読み取る。--layout-from で LAYOUT の結果を与えられる
eval          出力 JSON を正解 JSON で採点し、results/ に記録する（評価 DB には登録しない）
deploy        Snowflake への配置（setup・start が使う）
run           Snowflake で読み取り・登録（・評価）を流す（start.sh が呼ぶ）
eval-compare  評価 DB の文書別の指標を移植元の書き出しと比べる
export        評価記録と出力 JSON を results/<run_id>/ に書き出す（teardown の前）
job           SPCS ジョブのステップ（コンテナ内で実行する）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .common import paths
from .common.guard import main as guard_main
from .common.names import load_names
from .config import ConfigError, available_corpora, load_corpus_config, load_pipeline_config
from .fetch.manifest import ManifestError
from .fetch.pipeline import execute_fetch, plan_fetch
from .fetch.select import SelectionError
from .fetch.sources import FetchError, make_source
from .fetch.verify import VerificationError

_NOT_YET: dict[str, str] = {}


def _add_target_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--corpus", required=True, help=f"コーパス（{', '.join(available_corpora())}）")
    target = p.add_argument_group(
        "対象文書（どれか 1 つ。省略時は pipeline.yaml の defaults.slice）"
    )
    target.add_argument("--docs", help="doc_id のカンマ区切り")
    target.add_argument("--docs-file", type=Path, help="1 行 1 doc_id のファイル（# はコメント）")
    target.add_argument("--slice", dest="slice_name", help="スライス名（pilot・all など）")


def _confirm(message: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(f"{message} — 対話できないので中断する（--yes で確認を省略できる）", file=sys.stderr)
        return False
    return input(f"{message} 続けますか？ [y/N] ").strip().lower() in ("y", "yes")


def cmd_fetch(args: argparse.Namespace) -> int:
    corpus = load_corpus_config(args.corpus)
    pipeline = load_pipeline_config()
    source = make_source(corpus)

    plan = plan_fetch(
        source,
        corpus,
        pipeline,
        args.data_dir or paths.DATA_DIR,
        docs=args.docs,
        docs_file=args.docs_file,
        slice_name=args.slice_name,
        with_gold=args.eval,
    )
    sel = plan.selection
    print(
        f"[fetch] {corpus.name}（{source.describe()['kind']}・版 {plan.manifest.version}）: "
        f"{len(sel.doc_ids)} 文書・{sel.pages} ページ・評価除外 {len(sel.eval_excluded)} 件・"
        f"見込み約 {sel.estimated_credits:.1f} クレジット（読み取りを全部流した場合の目安）"
    )
    if args.dry_run:
        plan.discard()
        print(json.dumps(sel.as_dict(), ensure_ascii=False, indent=2))
        return 0
    if sel.needs_confirmation and not _confirm(
        f"[fetch] {sel.how} は {len(sel.doc_ids)} 文書。", args.yes
    ):
        plan.discard()
        return 1

    # 確認した計画（索引と対象文書）をそのまま実行する。索引は取り直さない
    result = execute_fetch(plan)
    s = result.report.summary()
    print(
        f"[fetch] 取得と照合が完了: {result.dataset_dir}（照合 {s['verified']} 件・"
        f"期待値が無く未照合 {s['unverified']} 件・ファイル {', '.join(result.files)}）"
    )
    if result.report.unverified:
        more = " ほか" if s["unverified"] > 5 else ""
        print(
            "[fetch] 未照合のファイル（manifest にも SHA256SUMS にも期待値が無い）: "
            f"{', '.join(result.report.unverified[:5])}{more}"
        )
    return 0


def _select_kwargs(args: argparse.Namespace) -> dict:
    return {"docs": args.docs, "docs_file": args.docs_file, "slice_name": args.slice_name}


def cmd_local_read(args: argparse.Namespace) -> int:
    from .local import local_read, new_run_id

    corpus = load_corpus_config(args.corpus)
    run_id = args.run_id or new_run_id()
    summary = local_read(
        make_source(corpus),
        corpus,
        load_pipeline_config(),
        run_id=run_id,
        data_dir=args.data_dir or paths.DATA_DIR,
        layout_from=args.layout_from,
        compare_with=args.compare_with,
        **_select_kwargs(args),
    )
    n, ok, err = len(summary["doc_ids"]), len(summary["done"]), summary["errors"]
    print(
        f"[local read] {corpus.name} run={run_id}: {ok}/{n} 文書を読み取り"
        f"（AI は呼ばない・LAYOUT={summary['layout']}） → {summary['out_dir']}"
    )
    for d, e in err.items():
        print(f"[local read] 失敗 {d}: {e}", file=sys.stderr)
    rc = 1 if err else 0
    if "compare" in summary:
        mm = summary["compare"]["mismatches"]
        print(
            f"[local read] 照合 {ok - len(mm)}/{ok} 文書が一致（比較先 {summary['compare']['with']}）"
        )
        for d, keys in mm.items():
            print(f"[local read]   不一致 {d}: {', '.join(keys)}", file=sys.stderr)
        rc = rc or (1 if mm else 0)
    return rc


def cmd_eval(args: argparse.Namespace) -> int:
    from .local import local_eval, new_run_id

    corpus = load_corpus_config(args.corpus)
    run_id = args.run_id or new_run_id("eval")
    record = local_eval(
        make_source(corpus),
        corpus,
        load_pipeline_config(),
        run_id=run_id,
        pred_dir=args.pred,
        data_dir=args.data_dir or paths.DATA_DIR,
        **_select_kwargs(args),
    )
    print_eval_summary(record)
    print(f"[eval] 記録: results/{run_id}/{corpus.name}/eval.json")
    missing = record["summary"].get("missing_predictions") or []
    if missing:
        print(
            f"[eval] 予測が無い文書 {len(missing)} 件（採点から外れた）: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1
    return 0


def print_eval_summary(record: dict) -> None:
    s = record["summary"]
    cit, st = s["citation"], s["structure"]
    print(
        f"[eval] {record['corpus']} run={record['run_id']}: 採点 {s['n_docs']} 文書"
        f"（評価除外 {len(record['eval_excluded'])}）"
    )
    print(
        f"[eval] 引用誤り率 {cit['citation_error_rate']:.4f}（{cit['n_wrong']}/{cit['n_elements']}）・"
        f"条 R/P {st['article']['recall']:.3f}/{st['article']['precision']:.3f}"
    )


# deploy.env のうち、名前以外で SQL のテンプレート変数に渡す設定（大きさ・自動停止・イメージ名）
DEPLOY_SETTINGS = (
    "WAREHOUSE_SIZE",
    "WAREHOUSE_AUTO_SUSPEND",
    "COMPUTE_POOL_FAMILY",
    "COMPUTE_POOL_MIN_NODES",
    "COMPUTE_POOL_MAX_NODES",
    "COMPUTE_POOL_AUTO_SUSPEND_SECS",
    "IMAGE_NAME",
)
_SETTING_RE = re.compile(r"^[A-Za-z0-9_]+$")


def deploy_items() -> dict[str, str]:
    """シェルと SQL のテンプレート変数に渡す値（名前は接頭辞から組み立てる）。"""
    from .common.envfile import read_env_file

    names = load_names()
    items = {"NAME_PREFIX": names.prefix}
    items.update({k.upper(): v for k, v in names.account_objects().items()})
    env = read_env_file(paths.DEPLOY_ENV)
    for key in DEPLOY_SETTINGS:
        value = env.get(key)
        if not value:
            raise ConfigError(f"configs/deploy.env に {key} が無い")
        if not _SETTING_RE.match(value):  # シェルと SQL にそのまま埋め込むので形を限る
            raise ConfigError(f"configs/deploy.env の {key} が英数字と _ だけでない: {value!r}")
        items[key] = value
    return items


def cmd_connection(args: argparse.Namespace) -> int:
    from .common.local_settings import LocalSettingError, resolve_connection_name

    try:
        print(resolve_connection_name())
    except LocalSettingError as e:
        print(f"[connection] {e}", file=sys.stderr)
        return 1
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    from . import deploy

    if args.deploy_command == "specs":
        print(f"[deploy specs] {', '.join(deploy.put_specs())}")
        return 0
    corpus = load_corpus_config(args.corpus)
    pipeline = load_pipeline_config()
    data_dir = args.data_dir if getattr(args, "data_dir", None) else paths.DATA_DIR
    try:
        if args.deploy_command == "docs":
            r = deploy.upload_docs(
                make_source(corpus), corpus, pipeline, data_dir=data_dir, **_select_kwargs(args)
            )
            print(
                f"[deploy docs] {r['corpus']}（版 {r['dataset_version']}）: {r['n_docs']} 文書・"
                f"{r['n_pages']} ページを PUT し、ステージの md5 と台帳を照合した"
            )
        elif args.deploy_command == "prompt":
            r = deploy.load_prompt(make_source(corpus), corpus, pipeline, data_dir=data_dir)
            shots = ", ".join(
                f"{s['doc_id']}#{s['figure_id']}（{s['n_nodes']} ノード）" for s in r["shots"]
            )
            print(
                f"[deploy prompt] {r['corpus']}: {r['model']} / {r['prompt_version']} / shot {shots}"
            )
        else:  # register-run
            slice_name = args.slice_name or "pilot"
            ids = (
                [d for d in args.docs.split(",") if d]
                if args.docs
                else list(corpus.slices[slice_name])
            )
            r = deploy.register_run(
                run_id=args.run_id,
                corpus=corpus,
                doc_ids=ids,
                slice_name="custom" if args.docs else slice_name,
                image_tag=args.image_tag,
                dataset_version=args.dataset_version,
            )
            print(
                f"[deploy register-run] {r['run_id']}: {r['corpus']} {r['n_docs']} 文書（image {r['image_tag']}）"
            )
    except deploy.DeployError as e:
        print(f"[deploy] {e}", file=sys.stderr)
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .run import RunArgs, RunError, execute

    try:
        return execute(
            RunArgs(
                corpus=args.corpus, docs=args.docs, docs_file=str(args.docs_file) if args.docs_file else None,
                slice_name=args.slice_name, run_id=args.run_id, resume=args.resume, watch=args.watch,
                from_step=args.from_step, fail=args.fail or "", eval=args.eval, yes=args.yes,
                poll_seconds=args.poll_seconds, timeout_minutes=args.timeout_minutes,
            )
        )  # fmt: skip
    except (
        RunError,
        ConfigError,
        SelectionError,
        FetchError,
        VerificationError,
        ManifestError,
    ) as e:
        print(f"[run] {e}", file=sys.stderr)
        return 1


def cmd_eval_compare(args: argparse.Namespace) -> int:
    """評価 DB の文書別の指標を、別の run の書き出し（DOC_METRICS.json）と比べる（評価ロールで読む）。"""
    from .common import sf
    from .compare import compare_doc_metrics

    def payload(v: str | dict) -> dict:
        return json.loads(v) if isinstance(v, str) else v

    ref = {
        r["doc_id"]: payload(r["payload"])["metrics"]
        for r in json.loads(args.ref.read_text(encoding="utf-8"))
    }
    n = sf.names()
    conn = sf.connect(role=n.role_eval)
    try:
        rows = sf.query(
            conn,
            f"SELECT doc_id, payload FROM {n.fq('schema_results', 'DOC_METRICS')} WHERE pred_run_id = %s",
            (args.run_id,),
        )
    finally:
        conn.close()
    mine = {r["doc_id"]: payload(r["payload"])["metrics"] for r in rows}
    if not mine:
        print(
            f"[eval-compare] 評価 DB に {args.run_id} の文書別の指標が無い（--eval 付きで流した run か、S60 が成功したかを確かめる）",
            file=sys.stderr,
        )
        return 1
    res = compare_doc_metrics(mine, ref)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 1 if res["n_structural_mismatch"] or res["missing_in_ref"] else 0


def cmd_export(args: argparse.Namespace) -> int:
    from .export import export_all

    return export_all(args.run_id or None, args.out_dir)


def cmd_job(args: argparse.Namespace) -> int:
    import os

    # 移植した integrate は provenance.run_id を環境変数から読む。読み取りのモジュールを import する前に決める
    os.environ["JPDOCREAD_RUN_ID"] = args.run_id
    from .jobs import STEPS

    only = [d for d in args.docs.split(",") if d] if args.docs else None
    return STEPS[args.step](args.run_id, only)


def cmd_names(args: argparse.Namespace) -> int:
    items = deploy_items()
    if args.format == "json":
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:  # シェルが eval で読む形（値は英大文字・数字・_ だけなので引用は不要）
        for k, v in items.items():
            print(f"{k}={v}")
    return 0


# ---------------------------------------------------------------- 引数の定義（サブコマンドごと）


def _add_fetch_parser(sub: argparse._SubParsersAction) -> None:
    f = sub.add_parser("fetch", help="データセットを取得して照合する")
    _add_target_args(f)
    f.add_argument("--eval", action="store_true", help="評価用の正解 JSON も取得する")
    f.add_argument(
        "--data-dir",
        type=Path,
        help="取得先（既定は data/。環境変数 JPDOCREAD_DATA_DIR でも変えられる）",
    )
    f.add_argument(
        "--dry-run",
        action="store_true",
        help="索引だけを一時的に取得して対象文書と見込みを表示する（data/ には何も残さない）",
    )
    f.add_argument("--yes", action="store_true", help="確認プロンプトを省略する")
    f.set_defaults(func=cmd_fetch)


def _add_guard_parser(sub: argparse._SubParsersAction) -> None:
    g = sub.add_parser("guard", help="正解漏れガード")
    g.set_defaults(func=lambda a: guard_main())


def _add_local_parser(sub: argparse._SubParsersAction) -> None:
    loc = sub.add_parser("local", help="ローカル実行（AI を使わない層）")
    loc_sub = loc.add_subparsers(dest="local_command", required=True)
    lr = loc_sub.add_parser(
        "read", help="doc.pdf から条項木・参照・当事者・定義語を読み取る（AI を呼ばない）"
    )
    _add_target_args(lr)
    lr.add_argument("--run-id", help="出力先 out/<run_id>/<corpus>/（既定は local-<日時>）")
    lr.add_argument(
        "--layout-from",
        type=Path,
        help="LAYOUT の結果として使う出力 JSON のディレクトリ（<doc_id>.json）",
    )
    lr.add_argument(
        "--compare-with",
        type=Path,
        help="決定的な層を比べる出力 JSON のディレクトリ（移植元の run など）",
    )
    lr.add_argument("--data-dir", type=Path, help="取得先（既定は data/）")
    lr.set_defaults(func=cmd_local_read)


def _add_eval_parser(sub: argparse._SubParsersAction) -> None:
    ev = sub.add_parser("eval", help="出力 JSON を正解 JSON で採点して results/ に記録する")
    _add_target_args(ev)
    ev.add_argument(
        "--pred", type=Path, required=True, help="出力 JSON のディレクトリ（<doc_id>.json）"
    )
    ev.add_argument("--run-id", help="記録先 results/<run_id>/<corpus>/（既定は eval-<日時>）")
    ev.add_argument("--data-dir", type=Path, help="取得先（既定は data/）")
    ev.set_defaults(func=cmd_eval)


def _add_names_parser(sub: argparse._SubParsersAction) -> None:
    n = sub.add_parser("names", help="Snowflake のオブジェクト名を表示する")
    n.add_argument("--format", choices=["env", "json"], default="env")
    n.set_defaults(func=cmd_names)


def _add_connection_parser(sub: argparse._SubParsersAction) -> None:
    c = sub.add_parser(
        "connection", help="接続名を解決して表示する（環境変数 → deploy.local.env。無ければ rc=1）"
    )
    c.set_defaults(func=cmd_connection)


def _add_deploy_parser(sub: argparse._SubParsersAction) -> None:
    dp = sub.add_parser("deploy", help="Snowflake への配置（setup・start が使う）")
    dsub = dp.add_subparsers(dest="deploy_command", required=True)
    d1 = dsub.add_parser(
        "docs", help="取得・照合 → doc.pdf を PUT → ステージの md5 と照合 → RAW.FILES"
    )
    _add_target_args(d1)
    d1.add_argument("--data-dir", type=Path)
    d2 = dsub.add_parser("prompt", help="図 few-shot を作って OPS.FIGURE_PROMPT に書く")
    d2.add_argument("--corpus", required=True, choices=available_corpora())
    d2.add_argument("--data-dir", type=Path)
    dsub.add_parser("specs", help="ジョブ仕様テンプレートを @APP.SPECS へ PUT")
    d4 = dsub.add_parser("register-run", help="RUNS 台帳に run を登録する")
    d4.add_argument("--corpus", required=True, choices=available_corpora())
    d4.add_argument("--run-id", required=True)
    d4.add_argument("--image-tag", required=True)
    d4.add_argument("--docs", help="doc_id のカンマ区切り（無ければ --slice）")
    d4.add_argument("--slice", dest="slice_name")
    d4.add_argument("--dataset-version")
    dp.set_defaults(func=cmd_deploy)


def _add_run_parser(sub: argparse._SubParsersAction) -> None:
    rn = sub.add_parser("run", help="Snowflake で読み取り・登録（・評価）を流す（start.sh が呼ぶ）")
    rn.add_argument("--corpus", choices=available_corpora(), help="コーパス（新しい run では必須）")
    tg = rn.add_argument_group("対象文書（どれか 1 つ。省略時は pipeline.yaml の defaults.slice）")
    tg.add_argument("--docs", help="doc_id のカンマ区切り")
    tg.add_argument("--docs-file", type=Path, help="1 行 1 doc_id のファイル（# はコメント）")
    tg.add_argument("--slice", dest="slice_name", help="スライス名（pilot・all など）")
    rn.add_argument("--run-id", help="新しい run の id（省略時は日時から作る）")
    rn.add_argument("--resume", metavar="RUN_ID", help="失敗・未実行の分だけを再実行する")
    rn.add_argument("--watch", metavar="RUN_ID", help="起動済みの run の完了を待つ")
    rn.add_argument(
        "--from",
        dest="from_step",
        default="S00",
        help="このステップより前を飛ばす（--resume と使う）",
    )
    rn.add_argument("--fail", help="故障注入（S20|S30|S50:<doc_id>,…）。再実行の実演用")
    rn.add_argument("--eval", action="store_true", help="正解で採点して評価 DB に記録する")
    rn.add_argument("--yes", action="store_true", help="確認を出さない（all など）")
    rn.add_argument("--poll-seconds", type=int, default=20)
    rn.add_argument("--timeout-minutes", type=int, default=180)
    rn.set_defaults(func=cmd_run)


def _add_eval_compare_parser(sub: argparse._SubParsersAction) -> None:
    ec = sub.add_parser("eval-compare", help="評価 DB の文書別の指標を移植元の書き出しと比べる")
    ec.add_argument("--run-id", required=True)
    ec.add_argument(
        "--ref",
        type=Path,
        required=True,
        help="比較先の DOC_METRICS.json（results/<run>/ など）",
    )
    ec.set_defaults(func=cmd_eval_compare)


def _add_export_parser(sub: argparse._SubParsersAction) -> None:
    ex = sub.add_parser(
        "export", help="評価記録と出力 JSON を results/<run_id>/ に書き出す（teardown の前）"
    )
    ex.add_argument(
        "--run-id", action="append", help="書き出す run（省略時は評価 DB にある全 run）"
    )
    ex.add_argument("--out-dir", type=Path, help="書き出し先（既定は results/）")
    ex.set_defaults(func=cmd_export)


def _add_job_parser(sub: argparse._SubParsersAction) -> None:
    jb = sub.add_parser("job", help="SPCS ジョブのステップ（コンテナ内で実行する）")
    jb.add_argument("step", choices=["s30", "s50", "s60"])
    jb.add_argument("--run-id", required=True)
    jb.add_argument("--docs", help="対象を限る（既定は RUNS 台帳の run の文書）")
    jb.set_defaults(func=cmd_job)


# `jpdocread --help` に並ぶ順（並べ替えると --help の出力が変わる）
_PARSER_BUILDERS = (
    _add_fetch_parser,
    _add_guard_parser,
    _add_local_parser,
    _add_eval_parser,
    _add_names_parser,
    _add_connection_parser,
    _add_deploy_parser,
    _add_run_parser,
    _add_eval_compare_parser,
    _add_export_parser,
    _add_job_parser,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jpdocread", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for add in _PARSER_BUILDERS:
        add(sub)
    for name, phase in _NOT_YET.items():
        p = sub.add_parser(name, help=f"未実装（{phase}）")
        p.set_defaults(func=lambda a, n=name, ph=phase: _not_yet(n, ph))
    return ap


def _not_yet(name: str, phase: str) -> int:
    print(f"jpdocread {name} は未実装（{phase} で実装する）", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, SelectionError, FetchError, ManifestError, VerificationError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
