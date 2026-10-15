"""P2 続き — 領域クロップ。

変更点：ページ画像を `pages/*.png`（正解データ一式に同梱の画像）ではなく `doc.pdf` から
150dpi でレンダリングする（入力は doc.pdf だけ）。ステージへの PUT は S30 ジョブ側で行うので削除した。

表 1 つ・図 1 つにつき **PNG 1 枚**を切り出し、ステージへ上げる。

**格子分割はしない（F17）。** ページを格子状に切ると、境界を跨ぐ辺が自己ループの
幻覚になり、図の edge F1 が 0.67 → 0.33 に退行した実測がある。切り出す単位は
「1 つの表」「1 つの図」だけである。

**切り出し矩形は我々自身の幾何から取る。** `layout.json` は正解なので、予測時入力に
使ってはならない。ここが使うのは `geometry.py` が
`PDF_LINES` と描画オブジェクトから推定した `table_boxes` / `figure_boxes` である。

**予測側のモジュールである。** gold を開いてはならない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from ..common.paths import WORK, doc_pdf
from .geometry import read_pages

# PNG は 150dpi で描かれている（pt × 150/72 = px）。
DPI_SCALE = 150.0 / 72.0
# 罫線ぎりぎりで切ると外枠が落ちるので、各辺に余白を付ける（pt）。
# 図では引き出し線やキャプションが枠外にあることがあるため表より広く取る。
PAD_PT = {"table": 6.0, "figure": 12.0}
# これ未満の領域はノイズ（見出しの囲み罫など）として捨てる。
MIN_W_PT, MIN_H_PT = 40.0, 24.0
# **図の領域の絞り込み（本ハンズオンで追加・既定 off）。** 領域の中の曲線（curve）がこの範囲なら図ではない。
# 実測（h13 の 40 文書・220 領域。正解の要素との重なりで種類を決めた）：
#   正解の図 69 領域   曲線 5〜31 本（最小 5）
#   署名欄 35・枠囲み 8 曲線 1〜4 本（押印の丸・角の丸め）
#   表 48・脚注 43 ほか 曲線 0 本
# 手元の PDF の正解の図 111 件では曲線 0 本が 3 件（罫線だけのマトリクス図 `fig_*_matrix`）、1〜4 本は 0 件。
# **0 本は外さない**（表・脚注とマトリクス図を見分けられず、図を落とすと辺がすべて失われる）
FIGURE_FEW_CURVES = (1, 4)


@dataclass
class Region:
    region_id: str
    doc_id: str
    page: int  # 1-based
    kind: str  # 'table' | 'figure'
    bbox_pt: list[float]  # 余白を付けた後の PDF 座標
    rel_path: str  # ステージ上の相対パス
    width_px: int
    height_px: int
    # 表領域のみ。pdfplumber が数えたセル数（P3 の max_tokens 算出用。図は 0）
    n_cells: int = 0


def render_page(pdf: pdfium.PdfDocument, page: int) -> Image.Image:
    """1 始まりのページを 150dpi（pt × 150/72 = px）の RGB 画像にする。"""
    bitmap = pdf[page - 1].render(scale=DPI_SCALE)
    return bitmap.to_pil().convert("RGB")


def _crop_dir(doc_id: str) -> Path:
    return WORK / "regions" / doc_id


def _clip(bbox: list[float], pad: float, page_w: float, page_h: float) -> list[float]:
    x0, y0, x1, y1 = bbox
    return [
        max(0.0, x0 - pad),
        max(0.0, y0 - pad),
        min(page_w, x1 + pad),
        min(page_h, y1 + pad),
    ]


def _curve_centers(doc_id: str) -> dict[int, list[tuple[float, float]]]:
    import pdfplumber

    out: dict[int, list[tuple[float, float]]] = {}
    with pdfplumber.open(doc_pdf(doc_id)) as pdf:
        for i, p in enumerate(pdf.pages, start=1):
            out[i] = [
                ((c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2) for c in p.curves or []
            ]
    return out


def few_curves(box: list[float], centers: list[tuple[float, float]]) -> bool:
    """図の候補の矩形に、中心が入る曲線の数が `FIGURE_FEW_CURVES` の範囲か。"""
    n = sum(1 for x, y in centers if box[0] <= x <= box[2] and box[1] <= y <= box[3])
    return FIGURE_FEW_CURVES[0] <= n <= FIGURE_FEW_CURVES[1]


def build_regions(doc_id: str, filter_figures: bool = False) -> list[Region]:
    """`geometry` の領域 bbox から単一領域 PNG を切り出す。

    `geometry` を先に実行しておく必要がある（`read_pages` が読む）。
    ページ PNG は 150dpi なので pt → px は `DPI_SCALE` 倍。

    **y は反転しない。** `geometry` の bbox は pdfplumber の `top`/`bottom` 系、
    すなわち**上原点**で、画像の座標系と向きが一致している。最初の実装は「PDF は
    下原点」という一般論から y を反転させたが、それは誤りだった。反転しても
    「それらしい表が写った画像」が出てしまうため、**実行では気づけない**種類の
    誤りである（実測で確かめた：gold の表 bbox との IoU が反転で改善しなかった）。

    `filter_figures`（コーパス設定の `figures.filter_regions`）が真なら、曲線の少ない図の候補
    （`FIGURE_FEW_CURVES`）を図の領域にしない。図の領域ごとに S40 が `AI_COMPLETE` を呼ぶので、
    呼び出しの数が減る。外した候補も**番号は消費する**（残る図の領域の id・ファイル名を変えないため。
    S40 のキャッシュはクロップの md5 で引くので、同じ画像なら同じ結果が返る）。
    """
    out: list[Region] = []
    cdir = _crop_dir(doc_id)
    cdir.mkdir(parents=True, exist_ok=True)
    # 古いクロップを消す。領域検出を変えると枚数も名前も変わるので、残しておくと
    # 「どの検出器が作った画像か」が分からなくなる（実測：旧方式の 84 枚が残り、
    # ステージへ 482 枚が上がった。参照されない画像だが、由来の追跡を壊す）。
    for old in cdir.glob("*.png"):
        old.unlink()
    pages = {p.page: p for p in read_pages(doc_id)}
    pdf = pdfium.PdfDocument(str(doc_pdf(doc_id)))
    centers = _curve_centers(doc_id) if filter_figures else {}
    for page in sorted(pages):
        g = pages[page]
        img = render_page(pdf, page)
        for kind, boxes in (("table", g.table_boxes), ("figure", g.figure_boxes)):
            idx = 0
            cells = g.table_cells if kind == "table" else [0] * len(boxes)
            for bi, bb in enumerate(boxes):
                if (bb[2] - bb[0]) < MIN_W_PT or (bb[3] - bb[1]) < MIN_H_PT:
                    continue
                box = _clip(bb, PAD_PT[kind], g.width, g.height)
                left = int(box[0] * DPI_SCALE)
                right = int(box[2] * DPI_SCALE)
                top = int(box[1] * DPI_SCALE)
                bottom = int(box[3] * DPI_SCALE)
                left, top = max(0, left), max(0, top)
                right, bottom = min(img.width, right), min(img.height, bottom)
                if right - left < 8 or bottom - top < 8:
                    continue
                if kind == "figure" and filter_figures and few_curves(box, centers.get(page, [])):
                    idx += 1
                    continue
                rid = f"{doc_id}#p{page:03d}_{kind[:3]}{idx}"
                name = f"page-{page:03d}-{kind[:3]}{idx}.png"
                crop = img.crop((left, top, right, bottom))
                crop.save(cdir / name)
                out.append(
                    Region(
                        region_id=rid,
                        doc_id=doc_id,
                        page=page,
                        kind=kind,
                        bbox_pt=box,
                        rel_path=f"{doc_id}/regions/{name}",
                        width_px=crop.width,
                        height_px=crop.height,
                        n_cells=int(cells[bi]) if bi < len(cells) else 0,
                    )
                )
                idx += 1
    (cdir / "regions.json").write_text(
        json.dumps([r.__dict__ for r in out], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def read_regions(doc_id: str) -> list[Region]:
    p = _crop_dir(doc_id) / "regions.json"
    if not p.exists():
        return []
    return [Region(**d) for d in json.loads(p.read_text(encoding="utf-8"))]
