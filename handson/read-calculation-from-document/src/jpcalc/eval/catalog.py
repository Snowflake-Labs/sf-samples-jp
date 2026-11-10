"""公開索引（public_index.jsonl）の作成（評価側）。

完全な索引には正解に由来する列（ルール数・ケース数・パターン・難所など）が入っている。ここでだけ完全な索引を
**メモリ上で**読み、正解に由来しない列（文書 ID・base・層・体裁・ページ数）と、PDF ごとのパスと照合値だけを
書き出す。完全な索引はディスクに保存しない。予測側は書き出した公開索引だけを読む。

照合値：保険約款は索引のファイル一覧（パス → SHA-256）の値、契約書は Hub の LFS の SHA-256。
取得元が照合値を持たない場合（ローカルの写しの契約書など）は null とし、取得時に「未照合」と数える。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..fetch.adapters import PUBLIC_DOC_KEYS, PUBLIC_INDEX, render


class CatalogError(ValueError):
    """完全な索引の形が設定と合わない。"""


def _records(cfg, raw: bytes) -> tuple[list[dict], dict[str, str]]:
    if cfg.index.records is None:  # JSON Lines：1 行 1 文書
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        return rows, {}
    data = json.loads(raw)
    rows = data.get(cfg.index.records)
    if not isinstance(rows, list):
        raise CatalogError(f"{cfg.name}: 索引に {cfg.index.records!r} の一覧が無い")
    files = data.get("files", {}) if cfg.index.sha256_from == "index_files" else {}
    return rows, files


def build_public_index(cfg, source) -> list[dict]:
    rows, files = _records(cfg, source.read_bytes(cfg.index.file))
    col = cfg.index.columns
    out: list[dict] = []
    for r in rows:
        try:
            doc_id = r[col.doc_id]
            styles = r[col.styles]
            row = {
                "corpus": cfg.name,
                "doc_id": doc_id,
                "split_group": r[col.split_group],
                "stratum": r[col.stratum],
                "styles": styles if isinstance(styles, list) else [styles],
                "pages": int(r[col.pages]),
            }
        except KeyError as e:
            raise CatalogError(f"{cfg.name}: 索引の行に列 {e} が無い") from e
        pdfs = []
        for style in row["styles"]:
            path = render(cfg.paths.pdf, doc_id=doc_id, style=style)
            if col.pdf_file is not None and len(row["styles"]) == 1 and r.get(col.pdf_file) != path:
                raise CatalogError(
                    f"{doc_id}: 索引の PDF のパス {r.get(col.pdf_file)!r} がひな型 {path!r} と違う"
                )
            pdfs.append(
                {
                    "style": style,
                    "pdf_id": render(cfg.paths.pdf_id, doc_id=doc_id, style=style),
                    "hub_path": path,
                    "sha256": files.get(path),
                }
            )
        row["pdfs"] = pdfs
        out.append(row)
    if cfg.index.sha256_from == "hub_paths_info":
        lfs = source.lfs_sha256([p["hub_path"] for r in out for p in r["pdfs"]])
        for r in out:
            for p in r["pdfs"]:
                p["sha256"] = lfs.get(p["hub_path"])
    assert all(set(r) <= PUBLIC_DOC_KEYS for r in out)
    return sorted(out, key=lambda r: r["doc_id"])


def write_public_index(rows: list[dict], dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / PUBLIC_INDEX
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    return path
