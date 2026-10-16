"""関数の分割で切り出した規則の単体テスト。Snowflake には接続しない（偽の接続で SQL と引数を見る）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jpdocread import cli, jobs, run, worker
from jpdocread.common.names import NamingError, check_names


def _region(**kw: object) -> SimpleNamespace:
    base = {"kind": "figure", "page": 1, "bbox_pt": [0.0, 0.0, 100.0, 100.0], "rel_path": "d/r.png"}
    return SimpleNamespace(**{**base, **kw})


class _Cursor:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn
        self.description = None
        self._rows: list[tuple] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.sql.append((sql, params))
        self.description, self._rows = self.conn.answer(sql)

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:
        pass


class _Conn:
    """sf.query が使う cursor() だけを持つ偽の接続。SELECT COUNT(*) には count を返す。"""

    def __init__(self, count: int = 0) -> None:
        self.sql: list[tuple[str, object]] = []
        self.count = count

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def answer(self, sql: str) -> tuple[list | None, list[tuple]]:
        if sql.startswith("SELECT COUNT(*)"):
            return [("COUNT(*)",)], [(self.count,)]
        return None, []


class TestS30NodeCount:
    def test_figure_inside_region_with_margin(self):
        cand = jobs._figure_candidates(
            [{"pages": [1], "bbox": [10.0, 10.0, 100.4, 50.0], "nodes": [1, 2, 3]}]
        )
        assert cand == [(1, [10.0, 10.0, 100.4, 50.0], 3)]
        assert jobs._node_count(_region(), cand) == 3

    def test_outside_other_page_or_table_is_zero(self):
        cand = [(1, [10.0, 10.0, 101.0, 50.0], 3), (2, [10.0, 10.0, 20.0, 20.0], 4)]
        assert jobs._node_count(_region(), cand) == 0  # 0.5pt を超えてはみ出す
        assert jobs._node_count(_region(page=3), cand) == 0
        assert jobs._node_count(_region(kind="table", page=2), cand) == 0

    def test_first_matching_candidate_wins(self):
        cand = [(1, [1.0, 1.0, 2.0, 2.0], 5), (1, [3.0, 3.0, 4.0, 4.0], 7)]
        assert jobs._node_count(_region(), cand) == 5


class TestShotSelection:
    def test_containment(self):
        assert worker._containment([0, 0, 10, 10], [0, 0, 5, 10]) == pytest.approx(0.5)
        assert worker._containment([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
        assert worker._containment([0, 0, 0, 10], [0, 0, 10, 10]) == 0.0  # 面積 0 の正解

    def test_difficulty_orders_group_then_edges_then_nodes(self):
        grouped = {"graph": {"nodes": [{"group": "g"}], "edges": []}}
        many_edges = {"graph": {"nodes": [{}, {}], "edges": [{}, {}, {}]}}
        assert worker._difficulty(grouped) > worker._difficulty(many_edges)
        assert worker._difficulty({}) == (0, 0, 0)

    def test_best_region_respects_page(self):
        r1 = _region(page=1, bbox_pt=[0, 0, 10, 10])
        r2 = _region(page=2, bbox_pt=[0, 0, 100, 100])
        best, s = worker._best_region({"bboxes": [[0, 0, 10, 10]], "pages": [1]}, [r1, r2])
        assert best is r1 and s == pytest.approx(1.0)

    def test_candidates_need_bbox_and_threshold(self):
        r = _region(bbox_pt=[0, 0, 10, 10])
        figs = {"f1": {}, "f2": {}, "f3": {}}
        els = {
            "f1": {"bboxes": [[0, 0, 10, 10]], "pages": [1]},  # 包含率 1.0
            "f2": {"bboxes": [[0, 0, 100, 10]], "pages": [1]},  # 包含率 0.1（閾値 0.3 未満）
        }  # f3 は要素が無い
        assert [c[0] for c in worker._shot_candidates(figs, els, [r])] == ["f1"]


class TestRegisterNewRun:
    def _corpus(self) -> SimpleNamespace:
        return SimpleNamespace(name="contract", figure_shots=("s1", "s2"), eval_excluded=("s1",))

    def _fetched(self) -> SimpleNamespace:
        sel = SimpleNamespace(doc_ids=("d1", "d2"), how="slice:pilot")
        return SimpleNamespace(selection=sel, manifest=SimpleNamespace(version="v1"))

    def test_inserts_running_row(self):
        conn = _Conn(count=0)
        a = run.RunArgs(corpus="contract", run_id="r1", fail="S50:d1")
        assert run._register_new_run(conn, a, self._corpus(), self._fetched(), "t1") == "r1"
        sql, params = conn.sql[-1]
        assert sql.startswith("INSERT INTO") and "'RUNNING'" in sql
        assert params[:3] == ("r1", "contract", "slice:pilot")
        assert params[-4:] == ("S50:d1", True, "t1", "v1")

    def test_existing_run_id_is_rejected(self):
        with pytest.raises(run.RunError, match="--resume"):
            run._register_new_run(
                _Conn(count=1), run.RunArgs(run_id="r1"), self._corpus(), self._fetched(), "t1"
            )


def test_run_log_splits_progress_and_failure(capsys):
    run._log("進捗")
    run._log("失敗", error=True)
    got = capsys.readouterr()
    assert got.out == "[run] 進捗\n" and got.err == "[run] 失敗\n"


def test_parser_keeps_subcommand_order():
    sub = next(a for a in cli.build_parser()._actions if a.dest == "command")
    assert list(sub.choices) == [
        "fetch", "guard", "local", "eval", "names", "connection",
        "deploy", "run", "eval-compare", "export", "job",
    ]  # fmt: skip


def test_duplicate_names_are_listed():
    names = SimpleNamespace(
        prefix="P_", account_objects=lambda: {"a": "P_X", "b": "P_X", "c": "P_Y"}
    )
    with pytest.raises(NamingError, match=r"\['P_X'\]"):
        check_names(names)


class TestResumeEval:
    """再開で --eval を付けたときだけ、登録済みの対象文書の正解を置き直す（置かないと前の run の残りで結果が変わる）。"""

    def _resume(self, monkeypatch: pytest.MonkeyPatch, eval_: bool) -> list:
        calls: list = []
        row = {
            "corpus": "contract",
            "docs": '["d1", "d2"]',
            "config": {"skip_eval": True},
            "status": "FAILED",
        }

        def fake_query(conn: object, sql: str, params: object = None) -> list:
            return [row] if sql.startswith("SELECT corpus") else []

        monkeypatch.setattr(run, "_use_predict_role", lambda conn: None)
        monkeypatch.setattr(run.sf, "query", fake_query)
        monkeypatch.setattr(run, "_put_gold_for_resume", lambda c, d: calls.append((c, d)))
        monkeypatch.setattr("jpdocread.common.local_settings.lookup_local", lambda k: "t1")
        out = run.prepare_resume(run.RunArgs(resume="r1", eval=eval_), conn=None)
        assert out["eval"] is eval_
        return calls

    def test_eval_on_resume_puts_gold_for_registered_docs(self, monkeypatch: pytest.MonkeyPatch):
        assert self._resume(monkeypatch, True) == [("contract", ["d1", "d2"])]

    def test_no_eval_on_resume_puts_nothing(self, monkeypatch: pytest.MonkeyPatch):
        assert self._resume(monkeypatch, False) == []
