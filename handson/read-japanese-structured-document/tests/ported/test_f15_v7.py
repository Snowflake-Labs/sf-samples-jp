"""採点の部分集合別の集計（移植元 T15.8）。

ready 以外の文書の拒否・PDF の照合・未知 ID の拒否は、取得（fetch/）の単体テスト（tests/unit/test_select.py・test_verify.py）が検査している。
スライスはコーパス設定に移植元の値を置いた。
"""


def _fake_doc(doc_id, n_el, n_wrong, cers, tp, gold, pred, refs):
    from jpdocread.eval import evaluate as ev  # noqa: F401

    st = {k: {"tp": tp, "gold": gold, "pred": pred} for k in ("article", "paragraph", "item")}
    st |= {
        "nted": {"nted": 0.1},
        "nted_doc": {"nted_doc": 0.0, "ted_doc": 0, "n_unordered": 0},
        "number_violations_intrinsic": 1,
        "number_violations_gold_origin": 0,
    }
    return {
        "doc_id": doc_id,
        "content_id": doc_id.split("--")[0],
        "style_id": doc_id.split("--")[1],
        "pages": [{"cer": c, "cer_normalized": c, "char_f1": 1 - c} for c in cers],
        "text": {"n_missing_pages": 0},
        "citation": {
            "n_elements": n_el,
            "n_wrong": n_wrong,
            "citation_error_rate": n_wrong / n_el,
            "per_kind": {"paragraph": {"n": n_el, "ok": n_el - n_wrong, "bad": n_wrong}},
        },
        "structure": st,
        "tables": [],
        "figures": [],
        "refs": refs,
        "pred_text": "x",
    }


def test_subset_summaries_recombine_to_overall(monkeypatch):
    """部分集合別の値は、要素数・ページ数で重みを付けて足すと全体の値に戻る（T15.8）。"""
    from jpdocread.eval import evaluate as ev

    def refs(tp, pr, gr, gu):
        return {
            "tp": tp,
            "pred": pr,
            "gold_reachable": gr,
            "gold_unreachable": gu,
            "gold_unreachable_by_kind": {},
        }

    docs = {
        "a-1--s1": _fake_doc("a-1--s1", 100, 2, [0.1, 0.2], 9, 10, 10, refs(8, 10, 9, 1)),
        "b-1--s1": _fake_doc("b-1--s1", 50, 10, [0.3], 4, 5, 6, refs(2, 4, 3, 2)),
        "c-1--s1": _fake_doc("c-1--s1", 50, 5, [0.0, 0.4, 0.5], 7, 8, 9, refs(5, 5, 6, 0)),
    }
    monkeypatch.setattr(ev, "assert_checksums", lambda ids: {"ok": True})
    monkeypatch.setattr(ev, "score_document", lambda d, out_dir=None: docs[d])
    res = ev.evaluate(
        list(docs) + ["donor--x"],
        ["donor--x"],
        subsets={"dev": ["a-1--s1"], "test": ["b-1--s1", "c-1--s1"], "none": ["zz"]},
    )
    s, sub = res["summary"], res["summary"]["subsets"]
    assert set(sub) == {"dev", "test"}  # 0 文書の部分集合は出さない
    assert sub["dev"]["n_docs"] + sub["test"]["n_docs"] == s["n_docs"] == 3
    c = [sub[k]["citation"] for k in ("dev", "test")]
    assert sum(x["n_elements"] for x in c) == s["citation"]["n_elements"]
    assert sum(x["n_wrong"] for x in c) == s["citation"]["n_wrong"]
    pages = [sub[k]["text"]["n_pages"] for k in ("dev", "test")]
    recomb = sum(
        sub[k]["text"]["cer"] * n for k, n in zip(("dev", "test"), pages, strict=True)
    ) / sum(pages)
    assert abs(recomb - s["text"]["cer"]) < 1e-3
    for k in ("article", "paragraph", "item"):
        assert sum(sub[x]["structure"][k]["tp"] for x in sub) == s["structure"][k]["tp"]
    for f in ("tp", "pred", "gold_reachable", "gold_unreachable"):
        assert sum(sub[x]["refs"][f] for x in sub) == s["refs"][f]
