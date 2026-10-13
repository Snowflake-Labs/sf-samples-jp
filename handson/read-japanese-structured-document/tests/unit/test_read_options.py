"""コーパス設定の受け口：条項木の組み立て器・出力キーの同一性・features の切り替え。

実文書を使う試験は tests/ported の実データの置き場所（deploy.local.env の DATA_ROOT_*）があるときだけ走る。
"""

from __future__ import annotations

import pytest
from fixtures.data_roots import CDOCS, SKIP_REASON, YDOCS

from jpdocread.config import load_corpus_config
from jpdocread.read.integrate import CONTRACT_KEYS_EMPTY, ReadOptions
from jpdocread.read.structure.contract import detect_contract_scheme
from jpdocread.read.structure.tree import build_tree_for_doc

YDOC = "auto-0001--nl-a4-2col-mincho"
CDOC = "sys-0004--ct-a4-1col-mincho"
needs_data = pytest.mark.skipif(
    not (YDOCS and (YDOCS / YDOC).exists() and CDOCS and (CDOCS / CDOC).exists()),
    reason=SKIP_REASON,
)


@pytest.mark.parametrize("corpus", ["yakkan", "contract"])
def test_read_options_come_from_corpus_config(corpus):
    c = load_corpus_config(corpus)
    o = ReadOptions.from_corpus(c)
    assert o.structure_builder == c.structure_builder
    assert (o.parties, o.defined_terms) == (c.features.parties, c.features.defined_terms)
    assert o.known_limits == c.known_limits


def test_default_options_keep_the_source_behaviour():
    """既定値は移植元の振る舞い（体裁の自動判定・当事者と定義語を出す・known_limits は空）。"""
    assert ReadOptions() == ReadOptions("auto", True, True, {})


def test_unknown_builder_is_rejected():
    with pytest.raises(ValueError, match="structure_builder"):
        build_tree_for_doc("x", builder="other")


def test_detect_scheme_is_none_for_yakkan_style_lines():
    """約款の印字形は契約書と判定されない（auto で約款の経路に入る根拠。肯定例は ported の test_c_contract）。"""
    lines = [
        "第１章　総則",
        "第１条（用語の定義）",
        "この約款において、次の用語の意味は、次のとおりとします。",
    ]
    assert detect_contract_scheme(lines) is None


@needs_data
def test_contract_builder_on_yakkan_document_is_an_error():
    """builder=contract で契約書の体裁を判定できなければ止まる（黙って約款の経路に回さない）。"""
    with pytest.raises(ValueError, match="契約書の体裁"):
        build_tree_for_doc(YDOC, builder="contract")


@needs_data
def test_yakkan_builder_skips_contract_detection():
    """builder=yakkan は契約書でも判定せずに約款の組み立て器で組む（契約書の体裁の印が付かない）。"""
    t_auto = build_tree_for_doc(CDOC, builder="auto")
    t_yak = build_tree_for_doc(CDOC, builder="yakkan")
    assert any(r.startswith("contract_scheme=") for r in t_auto.rejected)
    assert not any(r.startswith("contract_scheme=") for r in t_yak.rejected)


@needs_data
def test_auto_and_explicit_builder_agree_on_their_own_corpus():
    """各コーパスの既定（設定）の組み立て器は、auto と同じ木を作る。"""
    for doc, builder in ((YDOC, "yakkan"), (CDOC, "contract")):
        a, b = build_tree_for_doc(doc, builder="auto"), build_tree_for_doc(doc, builder=builder)
        assert [(n.kind, n.citation) for n in a.nodes.values()] == [
            (n.kind, n.citation) for n in b.nodes.values()
        ]


def test_contract_keys_are_always_present_with_empty_values():
    """約款でも契約書の追加キーを空の値で出す（キーの有無をコーパスで変えない）。"""
    assert CONTRACT_KEYS_EMPTY == {
        "numbering_scheme": None,
        "parties": [],
        "defined_terms_detail": [],
    }
