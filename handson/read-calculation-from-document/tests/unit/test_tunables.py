"""調整できる値の読み出し口（common/tunables.py）。上書きの無い既定の動作が変わらないことを確かめる。"""

import threading

import pytest

from jpcalc.common.tunables import TunableError, active, override, tun


def test_default_outside_context():
    assert not active()
    assert tun("x.a", 3) == 3
    obj = ["a", "b"]
    assert tun("x.list", obj) is obj  # 既定は同じオブジェクトのまま返す


def test_override_inside_only():
    with override({"x.a": 5}) as seen:
        assert active()
        assert tun("x.a", 3) == 5
        assert tun("x.b", 7) == 7  # 上書きに無い名前は既定
    assert seen == {"x.a", "x.b"}
    assert tun("x.a", 3) == 3
    assert not active()


def test_strict_unused_raises():
    with pytest.raises(TunableError, match="x.typo"), override({"x.typo": 1}):
        tun("x.a", 3)


def test_not_strict_allows_unused():
    with override({"x.typo": 1}, strict=False):
        assert tun("x.a", 3) == 3


def test_nested_inner_wins_and_restores():
    with override({"x.a": 5, "x.b": 1}, strict=False):
        with override({"x.a": 9}):
            assert tun("x.a", 0) == 9
            assert tun("x.b", 0) == 1
        assert tun("x.a", 0) == 5


def test_restored_after_exception():
    with pytest.raises(RuntimeError), override({"x.a": 5}, strict=False):
        raise RuntimeError("x")
    assert tun("x.a", 3) == 3 and not active()


def test_other_thread_not_affected():
    got = {}

    def worker():
        got["v"] = tun("x.a", 3)

    with override({"x.a": 5}):
        tun("x.a", 3)
        th = threading.Thread(target=worker)
        th.start()
        th.join()
    assert got["v"] == 3
