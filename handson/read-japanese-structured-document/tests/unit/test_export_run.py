"""teardown 前の書き出し（export.py）と run の制御（run.py）の、Snowflake を使わない規則。"""

from __future__ import annotations

import decimal
import json

import pytest

from jpdocread import export, run


class TestExport:
    def test_reconcile_ok_only_when_every_count_matches(self):
        assert export.reconcile({"A": {"db": 2, "written": 2}, "B": {"db": 0, "written": 0}})
        assert not export.reconcile({"A": {"db": 2, "written": 2}, "B": {"db": 3, "written": 2}})

    def test_jsonable_parses_variant_and_decimal(self):
        assert export.jsonable('{"a": 1}') == {"a": 1}
        assert export.jsonable("[1]") == [1]
        assert export.jsonable("{not json") == "{not json"
        assert export.jsonable(decimal.Decimal("0.5")) == 0.5


class TestRunArgs:
    @pytest.mark.parametrize(
        "kw, msg",
        [
            ({"resume": "a", "watch": "b"}, "同時"),
            ({}, "--corpus"),
            ({"corpus": "contract", "run_id": "a b"}, "run_id"),
            ({"corpus": "contract", "from_step": "S99"}, "--from"),
            ({"corpus": "contract", "fail": "S40:d"}, "--fail"),
            ({"corpus": "contract", "fail": "S50:d e"}, "--fail"),
        ],
    )
    def test_invalid_args_are_rejected_before_connecting(self, kw, msg):
        with pytest.raises(run.RunError, match=msg):
            run.validate(run.RunArgs(**kw))

    def test_valid_args_pass(self):
        run.validate(
            run.RunArgs(
                corpus="contract", fail="S50:nda-0003--ct-a4-1col-form,S30:x", from_step="S55"
            )
        )
        run.validate(run.RunArgs(resume="m5-contract-fail", from_step="S50"))

    def test_fail_doc_must_be_a_target(self):
        run.check_fail_docs("S50:a", ["a", "b"])
        with pytest.raises(run.RunError, match="c"):
            run.check_fail_docs("S50:a,S30:c", ["a", "b"])

    def test_graph_config_is_json_with_eval_flag(self):
        cfg = json.loads(run.graph_config("r1", "S50", skip_eval=False))
        assert cfg == {"run_id": "r1", "from": "S50", "skip_eval": False}

    def test_step_order_matches_task_graph(self):
        from jpdocread.common.paths import HOME

        dag = (HOME / "sql" / "tasks" / "dag.sql").read_text(encoding="utf-8")
        assert "ARRAY_CONSTRUCT(" + ", ".join(f"'{s}'" for s in run.STEP_ORDER) + ")" in dag

    def test_progress_line_orders_steps_and_marks_failures(self):
        p = run.Progress(
            [
                {"step": "S50", "ok": 1, "ng": 1, "running": 0},
                {"step": "S00", "ok": 1, "ng": 0, "running": 0},
            ]
        )
        assert p.line() == "S00 1✓  S50 1✓ 1✗"

    def test_resume_hint_keeps_eval(self):
        assert run.resume_hint("r1", eval_=True) == "scripts/start.sh --resume r1 --eval"

    def test_new_run_id_is_valid(self):
        rid = run.new_run_id("contract", "slice:pilot")
        assert run.RUN_ID_RE.match(rid) and "contract" in rid


class TestWaitFinished:
    def test_not_finished_while_graph_is_active(self):
        assert not run.finished(1, "RUNNING", True, 999, 180)

    def test_not_finished_before_the_graph_is_seen(self):
        """起動直後（まだ CURRENT_TASK_GRAPHS に出ない）を完了と誤判定しない。"""
        assert not run.finished(0, "RUNNING", False, 10, 180)

    def test_finished_after_seen_or_terminal_or_grace(self):
        assert run.finished(0, "RUNNING", True, 10, 180)
        assert run.finished(0, "SUCCEEDED", False, 10, 180)
        assert run.finished(0, "RUNNING", False, 200, 180)
