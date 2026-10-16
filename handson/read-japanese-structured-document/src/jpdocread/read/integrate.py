"""S50 — 統合出力（JSON 契約・schema_version 1.2）。

変更点：図のグラフは S40 の書き出し（`work/figures/s40.json`）から読む。`provenance` を本パイプラインの
実行条件（全文書で P2 を実行・図は検出した全領域に AI_COMPLETE）に合わせ、run_id とイメージタグを足した。

**このファイルは `doc.pdf` のみから生成される**（AI 関数の応答も `doc.pdf` 由来）。

**`provenance` は必須である。** パスごとにモデル・プロンプト版・shot・NULL 件数を
記録しないと「どのパスが劣化したか」を後から切り分けられない。

**未検証のものを検証済みのように並べない。** 表・図・構造には既知の精度上限があるので、
`provenance.known_limits` に**そのステージの実測値と母集団**を書き込む。
統合結果を読む人が、どの層をどこまで信用してよいか分かる状態にする。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..common.paths import OUT
from .cover import meta_for_doc
from .figures_r4 import figures_for_doc
from .geometry import read_pages
from .parse.markdown import strip_markdown
from .parse.r4_local import read_pages_text
from .parse.r12_cortex import parse_doc
from .regions import read_regions
from .spine import reader_for
from .stitch import stitch_tables
from .structure.tree import build_tree_for_doc
from .tables_r2 import cached_layout_pages, tables_for_doc

FIGURE_CACHE_TAG = "s40"

SCHEMA_VERSION = (
    "1.2"  # 1.1 V4：意味層。1.2 W15：tables に R2 格子・figures にノード候補、領域は *_regions へ
)


_TABLE_REF = re.compile(r"[下次]表")  # 親の本文が表を指しているか（F17・D-026）


def _outline(tree, table_rows: set[str] | None = None) -> list[dict]:
    depth_of = {}

    def depth(nid: str) -> int:
        if nid in depth_of:
            return depth_of[nid]
        n = tree.nodes[nid]
        d = 0 if n.parent_id is None else depth(n.parent_id) + 1
        depth_of[nid] = d
        return d

    out = []
    for nid, n in tree.nodes.items():
        # **列挙表の行の号は outline にも出さない（F17・D-026）。** elements からは D-023 で外していたが outline には残り、
        # 号の適合率を下げていた（章が正しく付くと表の ①〜⑤ が号として生える）。子を持つ号は木を壊さないよう残す
        # ラウンド 2：親の本文が表を指すとき（`下表に掲げる…`）だけ外す。`次に掲げる…` の下の本物の号は
        # 表として二重に取り出されていても残す（ラウンド 1 は dev の号の再現率を 0.5294 → 0.3725 に落とした）
        parent = tree.nodes.get(n.parent_id) if n.parent_id else None
        if (
            not n.children
            and parent is not None
            and _TABLE_REF.search(parent.text or "")
            and _is_table_row_item(n, table_rows)
        ):
            continue
        out.append(
            {
                "id": nid,
                "depth": depth(nid),
                "node_kind": n.kind,
                "label": n.label,
                "title": n.heading,
                "parent_id": n.parent_id,
                "citation": n.citation,
                "page": (n.pages or [None])[0],
                # 採用集合は greedy デコード（tree.py の decode 既定）で決まり、ノードごとの確信度を出さない。
                # 大域デコード（decode.py の decode_global）は実装済みだが引用木では greedy に勝たないので使わない
                "confidence": None,
                "flags": [],
            }
        )
    return out


# 本文を運ぶノード種別。**引用付きパッセージの実体**であり、本プロジェクトの成果物
# （「すべてのパッセージが検証可能な引用パスを持つコーパス」）。
BODY_KINDS = ("paragraph", "item")


def _regions_built(doc_id: str) -> bool:
    """P2 を回したかどうか。**領域 0 件と未実行を区別するため。**"""
    from .regions import _crop_dir

    return (_crop_dir(doc_id) / "regions.json").exists()


def _table_row_texts(tables: list[dict]) -> set[str]:
    """列挙表の各行（記号＋本文）を、本文要素と照合できる形にする。"""
    out = set()
    for t in tables:
        if t.get("source") != "R2_enumerated":
            continue
        rows: dict[int, list[str]] = {}
        for c in t["grid"]:
            rows.setdefault(c["row"], []).append(c["text"])
        for cells in rows.values():
            body = _norm_row(cells[-1])
            if len(body) >= 4:
                out.add(body)
    return out


_CIRCLED = re.compile(r"^[①-⑳❶-❿]$")


def _norm_row(s: str) -> str:
    return "".join(unicodedata.normalize("NFKC", s or "").split()).rstrip("。")


def _ov(a: list[float], b: list[float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def figures_with_graph(doc_id: str, fig_regions: list) -> list[dict]:
    """W15 のノード候補に、`AI_COMPLETE` 経路のグラフ（キャッシュ）を重ねる（W17-E・W17-F）。

    対応は、同じページの図領域クロップ（`rel_path`）のうち bbox が最も重なるもの。
    キャッシュは S50 が S40 の結果テーブルから書き出した `work/figures/s40.json`。
    """
    from .figures import graph_for_out, read_figures

    cache = read_figures(FIGURE_CACHE_TAG)
    out = []
    for f in figures_for_doc(doc_id):
        rec = {**f, "edges": None, "paths": None}
        best, best_ov = None, 0.0
        for r in fig_regions:
            if r.page == f["pages"][0]:
                ov = _ov(r.bbox_pt, f["bbox"])
                if ov > best_ov:
                    best, best_ov = r, ov
        hit = cache.get(best.rel_path) if best is not None else None
        if hit and hit.get("nodes") and not hit.get("err"):
            g = graph_for_out(hit["nodes"], hit.get("edges") or [])
            rec.update(
                source="AI_COMPLETE_opus5",
                nodes=g["nodes"],
                edges=g["edges"],
                paths=g["paths"],
                crop=best.rel_path,
                query_id=hit.get("query_id"),
            )
        out.append(rec)
    return out


def citation_use_for(doc_id: str) -> dict:
    """文書系統ごとの引用の使い方（`configs/citation_use.yaml`・W17-A）。

    区分は評価で測った系統別の引用誤り率から決めて設定に固定したもので、ここでは読むだけ。
    系統は `doc_id` の先頭で決まる。未知の系統は `default`（candidate）。
    """
    import yaml

    from ..common.paths import CONFIGS

    cfg = yaml.safe_load((CONFIGS / "citation_use.yaml").read_text(encoding="utf-8"))
    genre = doc_id.split("-", 1)[0]
    g = (cfg.get("genres") or {}).get(genre) or {}
    return {
        "citation_use": g.get("use", cfg.get("default", "candidate")),
        "citation_error_rate_genre": g.get("error_rate"),
        "citation_use_source_run": cfg.get("source_run"),
    }


def _is_table_row_item(n, table_rows: set[str] | None) -> bool:
    """列挙表の行と同じ文字の号か（W15 V6・D-023）。elements と outline の両方がこの 1 つの判定を使う（F17・D-026）。"""
    segs = (n.citation or "").split()
    nested = len(segs) >= 2 and all(_CIRCLED.match(x) for x in segs[-2:])
    return bool(table_rows) and n.kind == "item" and not nested and _norm_row(n.text) in table_rows


def _elements(tree, table_rows: set[str] | None = None) -> list[dict]:
    """本文を持つノードを引用付きで書き出す。

    **`outline` と重複しない。** `outline` は木の骨格（全ノードの親子関係）で、
    こちらは**検索・引用の単位**である。本文が空のノードは出さない
    （空を出すと「抽出したが空だった」と読める。§1.6）。
    """
    out = []
    for nid, n in tree.nodes.items():
        if n.kind not in BODY_KINDS or not n.text.strip():
            continue
        # **列挙表の行は本文要素ではない**（W15 V6 試行 1）。gold は罫線の無い列挙表を表として
        # 持ち、その行を号（item）として持たない。成果物の引用誤りのうち item の 55/58 件がこれだった。
        # 文字は `tables[].grid` に残るので失われない。
        # 試行 2：親が号（item）の入れ子の列挙（`② 次のいずれか` の下の ①②）は本文として残す。
        # 判定は引用の形で行う：最後の 2 段がともに丸数字なら入れ子（木の上では親は article 種になる）。
        if _is_table_row_item(n, table_rows):
            continue
        out.append(
            {
                "element_id": nid,
                "kind": n.kind,
                "node_kind": n.kind,
                "label": n.label,
                "citation": n.citation,
                "text": n.text,
                "pages": n.pages,
                "parent_id": n.parent_id,
                "refs_to": [],  # 下の build_output で refs から埋める
            }
        )
    return out


def _with_refs(elements: list[dict], refs: list[dict]) -> list[dict]:
    by: dict[str, list[str]] = {}
    for r in refs:
        by.setdefault(r["from_citation"], []).append(r["to_citation"])
    from .structure.tree import canonical_citation

    for e in elements:
        e["refs_to"] = sorted(by.get(canonical_citation(e["citation"]), []))
    return elements


def semantics_for(doc_id: str, tree) -> dict:
    """意味層（V4）。参照・脚注・列挙は予測木から、定義語は R2 の定義表の行から導く。"""
    from .parse.r12_cortex import parse_doc
    from .structure import semantics as S

    parsed = parse_doc(doc_id, reader="R2", cache_only=True)
    terms = S.defined_terms(parsed.pages) if not parsed.err else []
    refs = sorted(S.resolve_refs(tree))
    out = {
        "refs": [{"from_citation": a, "to_citation": b} for a, b in refs],
        "footnotes": S.footnotes(tree),
        "enumerations": S.enumerations(tree),
        "defined_terms": terms,
        "term_uses": S.term_uses(tree, terms),
    }
    scheme = next(
        (r.split("=", 1)[1] for r in tree.rejected if r.startswith("contract_scheme=")), None
    )
    if scheme is None:
        return out  # 約款：従来どおり
    # 契約書（C-007）：当事者と、本文の定義条から拾った定義語を足す。defined_terms は語の配列のまま和集合にする
    from .parse.r4_local import read_pages_text
    from .parties import defined_terms as contract_terms
    from .parties import item_lead_words, parties

    # 当事者欄は前文の直前にある。目次の後に前文が来る文書（sys-0001）があるので、前文のページの行を使う（C-010）
    pre_pages = [n.pages[0] for n in tree.nodes.values() if n.kind == "preamble" and n.pages]
    pts = {pt.page: pt.text for pt in read_pages_text(doc_id)}
    header = pts.get(pre_pages[0] if pre_pages else 1, "").split("\n")
    detail = contract_terms(tree, terms, item_lead_words(doc_id))
    all_terms = [d["term"] for d in detail]
    out.update(
        {
            "numbering_scheme": scheme,
            "parties": parties(tree, header),
            "defined_terms": all_terms,
            "defined_terms_detail": detail,
            "term_uses": S.term_uses(tree, all_terms),
        }
    )
    return out


def _fig_model(figures: list[dict]) -> str | None:
    """グラフ付きの図があれば、そのモデル名。S40 は FIGURE_PROMPT のモデルで呼び、そのモデルは
    pipeline.yaml の `figure.model`（＝ figures.MODEL_DEFAULT）と同じ値であることをテストで確かめている。"""
    from .figures import MODEL_DEFAULT

    return MODEL_DEFAULT if any(f.get("source") == "AI_COMPLETE_opus5" for f in figures) else None


def _meta(doc_id: str, sem: dict) -> dict:
    """書誌。契約書は題名・番号方式・当事者の数（C-010）。約款の項目（商品名・引用の使い方の区分）は約款だけに付ける。"""
    m = meta_for_doc(doc_id)
    if not sem.get("numbering_scheme"):
        return {**m, **citation_use_for(doc_id)}
    return {
        "title": m.get("title", ""),
        "numbering_scheme": sem["numbering_scheme"],
        "n_parties": len(sem.get("parties") or []),
    }


@dataclass(frozen=True)
class ReadOptions:
    """コーパス設定のうち読み取りが使うもの（本ハンズオンで追加。移植元は pipeline.yaml を直接読んでいた）。

    既定値は移植元の振る舞い（体裁の自動判定・契約書なら当事者と定義語を出す）。known_limits は必ずコーパス設定から渡す
    （空なら build_output が止まる。移植元は pipeline.yaml を必ず読んでいた）。
    """

    structure_builder: str = "auto"
    parties: bool = True
    defined_terms: bool = True
    known_limits: dict = field(default_factory=dict)
    # ここから下は本ハンズオンで足したキー。位置引数で作る呼び出し（tests/unit/test_read_options.py）を壊さないよう、
    # 足すときは末尾に置く。対応するコーパス設定は from_corpus の 1 か所だけに書く（local.read_options もここから作る）
    # ページ・段をまたぐ表を 1 つにつなぐ（read/stitch.py）。既定は従来どおりつながない
    stitch_tables: bool = False
    # 目次の続きで先に開いた空の特約・別表を本物の見出しで置き換える（tree.Builder._supersede）。既定 off
    supersede_empty_upper: bool = False
    # 曲線の少ない図の候補を図の領域にしない（regions.build_regions に渡す：Snowflake では S30 の jobs.cmd_s30、
    # ローカルでは worker._task_read。S50 の build_output は provenance.read_options に記録するだけ）
    filter_figure_regions: bool = False
    # repair_queue の定型の棄却を resolution "routine" にする（ROUTINE_REJECTIONS）。既定 off
    label_routine_repairs: bool = False

    @classmethod
    def from_corpus(cls, corpus) -> ReadOptions:
        return cls(
            structure_builder=corpus.structure_builder,
            parties=corpus.features.parties,
            defined_terms=corpus.features.defined_terms,
            known_limits=dict(corpus.known_limits),
            stitch_tables=corpus.tables.stitch,
            supersede_empty_upper=corpus.structure.supersede_empty_upper,
            filter_figure_regions=corpus.figures.filter_regions,
            label_routine_repairs=corpus.structure.label_routine_repairs,
        )


# 契約書の追加キー。約款でも空の値で出す（キーの有無をコーパスで変えない）
CONTRACT_KEYS_EMPTY = {"numbering_scheme": None, "parties": [], "defined_terms_detail": []}


def build_output(doc_id: str, opts: ReadOptions) -> dict:
    """1 文書ぶんの統合 JSON を組む。

    表・図の中身（格子・グラフ）は E3/E4 の実験出力とは別系統であり、本関数は
    **領域の所在だけ**を書く。理由：E3/E4 は「gold 表と対応づいた領域」に限って
    呼び出しており、全領域に対する抽出結果は持っていない。持っていないものを
    空配列で埋めると「抽出したが空だった」と読めてしまう（§1.6 の暗黙フォールバック禁止）。
    """
    if not opts.known_limits:
        raise ValueError("known_limits が空（コーパス設定の known_limits を ReadOptions に渡す）")
    tree = build_tree_for_doc(
        doc_id, builder=opts.structure_builder, supersede_empty_upper=opts.supersede_empty_upper
    )
    reader = reader_for(doc_id)
    local_pages = {pt.page: pt for pt in read_pages_text(doc_id)}
    if reader == "R2":
        parsed = parse_doc(doc_id, reader="R2", cache_only=True)
        pages_text = {
            page: {
                "text": strip_markdown(text),
                "raw": text,
            }
            for page, text in parsed.pages.items()
        }
        p1_error = parsed.err
        p1_query_id = parsed.query_id
        p1_cache = parsed.from_cache
    else:
        pages_text = {page: {"text": pt.text, "raw": pt.text} for page, pt in local_pages.items()}
        p1_error = None
        p1_query_id = None
        p1_cache = False
    sem = semantics_for(doc_id, tree)
    geoms = {g.page: g for g in read_pages(doc_id)}
    regions = read_regions(doc_id)
    pages = []
    for p in sorted(pages_text):
        pt = pages_text[p]
        g = geoms.get(p)
        cls = []
        if g:
            if g.n_line_objs > 800:
                cls.append("toc")
            if g.table_boxes:
                cls.append("table_heavy")
            if g.figure_boxes:
                cls.append("figure")
            if not cls:
                cls.append("prose")
        pages.append(
            {
                "number": p,
                "class": cls,
                "text": pt["text"],
                "text_with_furniture": pt["raw"],
            }
        )
    tabs = [r for r in regions if r.kind == "table"]
    figs = [r for r in regions if r.kind == "figure"]
    # 領域ファイルが存在するか（0 件と未実行の区別に使う。下記 P2）
    has_regions = bool(regions) or _regions_built(doc_id)
    layout_pages = cached_layout_pages(doc_id)
    tables = tables_for_doc(doc_id) if layout_pages else []
    if opts.stitch_tables and tables:
        tables = stitch_tables(
            tables, layout_pages, {p: pt.furniture for p, pt in local_pages.items()}
        )
    figures = figures_with_graph(doc_id, figs)
    # **契約書では列挙表の行と同じ文字の号を外さない（C-009）。** 約款の規則（D-023）は gold が罫線の無い列挙表を
    # 号として持たない前提だったが、契約書では LAYOUT が本物の号の並び（`(1)…(4)`）を表と見なし、pilot で本物の号
    # 45 件を消した（網羅 1.000 → 0.956）。契約書の gold の列挙表は全 100 文書で 4 個（nda-0001 の 2 版面）だけである
    table_rows = set() if sem.get("numbering_scheme") else _table_row_texts(tables)
    return {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        # 表紙の行の性質から（read/cover.py・S7）＋ 引用の使い方の区分（W17-A・D-1⁵）
        "meta": _meta(doc_id, sem),
        "pages": pages,
        "outline": _outline(tree, table_rows),
        "elements": _with_refs(_elements(tree, table_rows), sem["refs"]),
        # 表の格子は R2 のパイプ表・列挙表から全ページについて出す（read/tables_r2.py・W15 R1）。
        # 展開後の格子なので rowspan/colspan は常に 1。検出領域（クロップ）は別キーに残す。
        "tables": tables,
        "table_regions": [
            {
                "id": r.region_id,
                "pages": [r.page],
                "bbox": r.bbox_pt,
                "crop": r.rel_path,
                "n_cells_est": r.n_cells,
            }
            for r in tabs
        ],
        # 図：`AI_COMPLETE`（opus-5）の抽出があればノード・辺・経路（W17-E。role は 2 値・D-10）、
        # 無ければ領域内の語の塊をノード候補として出す（W15 R3。辺は無い）。
        "figures": figures,
        "figure_regions": [
            {"id": r.region_id, "pages": [r.page], "bbox": r.bbox_pt, "crop": r.rel_path}
            for r in figs
        ],
        "enumerations": sem["enumerations"],
        "footnotes": sem["footnotes"],
        "refs": sem["refs"],
        "term_uses": sem["term_uses"],
        "defined_terms": sem["defined_terms"],
        **CONTRACT_KEYS_EMPTY,
        **(
            {k: sem[k] for k in ("numbering_scheme", "parties", "defined_terms_detail") if k in sem}
        ),
        **({} if opts.parties else {"parties": []}),
        **({} if opts.defined_terms else {"defined_terms_detail": []}),
        "repair_queue": [
            {
                "kind": "rejected_heading",
                "locus": r,
                "evidence": "",
                "resolution": _resolution(r, opts.label_routine_repairs),
            }
            for r in tree.rejected[:200]
        ]
        + [
            {"kind": "number_resync", "locus": r, "evidence": "", "resolution": "open"}
            for r in tree.resyncs
        ],
        "provenance": {
            "passes": {
                "P1": {
                    "reader": reader,
                    "model": None,
                    "raw_markdown_preserved": reader == "R2",
                    "from_cache": p1_cache,
                    "query_id": p1_query_id,
                    "error": p1_error,
                },
                # 「0 件」と「未実行」を区別する（P2 を回していない文書で 0 件と書かない）。
                "P2": {
                    "status": "実行済み" if has_regions else "未実行",
                    "n_table_regions": len(tabs),
                    "n_figure_regions": len(figs),
                    "render": "pypdfium2 150dpi（doc.pdf から）",
                },
                "P3": {
                    "method": "R2（LAYOUT）のパイプ表と罫線なし列挙表から格子を復元（AI 追加呼び出しなし）",
                    "n_tables": len(tables),
                    # ページ・段をまたぐ表をつないだとき（read/stitch.py）だけ出す。つながないときは従来と同じ
                    **(
                        {"n_stitched": sum(1 for t in tables if t.get("fragments"))}
                        if opts.stitch_tables
                        else {}
                    ),
                },
                "P4": {
                    "method": "検出した図領域ごとに AI_COMPLETE few-shot（2 例）でノード・辺を抽出",
                    "model": _fig_model(figures),
                    "n_with_graph": sum(
                        1 for f in figures if f.get("source") == "AI_COMPLETE_opus5"
                    ),
                    "n_regions": len(figs),
                },
                "P5": {
                    "decoder": "greedy",
                    "grammar": "印字形から推定（yakkan / jyusetsu）",
                    "input": "PDF テキスト層の行（R4）",
                },
            },
            "run_id": os.environ.get("JPDOCREAD_RUN_ID"),
            "image_tag": os.environ.get("JPDOCREAD_IMAGE_TAG"),
            "parsed_at": datetime.now(UTC).isoformat(),
            "n_null_outputs": sum(1 for page in pages if not page["text"]),
            "n_errors": int(bool(p1_error)),
            # 既知の限界（実測値と出典）。値はコーパス設定の known_limits に置く（移植元 T16.8）
            "known_limits": dict(opts.known_limits),
            # 空の parties・defined_terms_detail が「抽出して 0 件」か「対象外・無効」かを区別する記録
            "read_options": {
                "structure_builder": opts.structure_builder,
                "parties": opts.parties,
                "defined_terms": opts.defined_terms,
                "contract_scheme_detected": bool(sem.get("numbering_scheme")),
                # つながないときはキーを出さない（従来の出力とバイト単位で同じにする）
                **({"stitch_tables": True} if opts.stitch_tables else {}),
                **({"supersede_empty_upper": True} if opts.supersede_empty_upper else {}),
                **({"filter_figure_regions": True} if opts.filter_figure_regions else {}),
                **({"label_routine_repairs": True} if opts.label_routine_repairs else {}),
            },
        },
    }


# 定型の規則で捨てた見出しの記録（tree.Builder が `p<頁> <理由>: <行>` の形で書く）。目次・柱は版面の作りで毎ページ出るので、
# 1 文書で数百件になり（h13 の約款 20 文書で 551 件）、確かめるべき項目（番号の再同期・降格など）が埋もれる。
# "routine" は「規則どおりに捨てた」という意味で、捨てたのが正しいと確かめた印ではない
ROUTINE_REJECTIONS = ("目次行", "目次ブロックの上位見出し", "柱の上位見出し")


def _resolution(locus: str, label_routine: bool) -> str:
    if label_routine:
        reason = locus.split(" ", 1)[1].split(":", 1)[0] if " " in locus else ""
        if reason in ROUTINE_REJECTIONS:
            return "routine"
    return "open"


def write_output(doc_id: str, opts: ReadOptions) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{doc_id}.json"
    p.write_text(
        json.dumps(build_output(doc_id, opts), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return str(p)
