"""Offline tests for pattern 07 (parallel fan-out) and 08 (blackboard). Run: python3 -m pytest tests -q"""
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "controller"))
from src import board, contracts, review  # noqa: E402

TASKS = [{"task_id": "T-104", "title": "Audit", "status": "BLOCKED", "priority": "MEDIUM", "assignee": "taylor",
          "due_date": "2026-10-20", "acceptance_criteria": "Report lists violations"},
         {"task_id": "T-105", "title": "Privacy page", "status": "OPEN", "priority": "LOW", "assignee": None,
          "due_date": "2026-11-05", "acceptance_criteria": None}]


# ------------------------------------------------------------------ 07 fan-out / fan-in
def test_perspectives_are_fixed_and_unknown_is_rejected():
    assert set(review.PERSPECTIVES) == {"schedule", "ownership", "quality"}
    with pytest.raises(contracts.ContractError):
        review.agent_for("TMS_ROUTER_AGENT")


@pytest.mark.parametrize("perspective,hidden", [("schedule", "assignee"), ("ownership", "acceptance_criteria"),
                                                ("quality", "due_date")])
def test_each_reviewer_sees_only_its_columns(perspective, hidden):
    prompt = review.build_prompt(perspective, "PRJ-PORTAL", "2026-10-27", TASKS)
    rows = json.loads(prompt.split("<<<\n", 1)[1].split("\n>>>", 1)[0])
    assert all(hidden not in r for r in rows) and "untrusted data" in prompt


def test_findings_on_invented_tasks_are_dropped_and_severity_normalized():
    text = json.dumps({"findings": [{"task_id": "t-104", "severity": "high", "issue": "late"},
                                    {"task_id": "T-999", "severity": "HIGH", "issue": "invented"},
                                    {"task_id": "T-105", "severity": "URGENT", "issue": "x"}]})
    out = review.parse_findings(text, "schedule", {"T-104", "T-105"})
    assert [(f["task_id"], f["severity"]) for f in out] == [("T-104", "HIGH"), ("T-105", "MEDIUM")]


def test_fan_in_merges_by_task_highest_severity_wins_and_reports_missing():
    workers = [{"perspective": "schedule", "status": "OK",
                "findings": [{"task_id": "T-106", "perspective": "schedule", "severity": "HIGH", "issue": "a", "recommendation": ""}]},
               {"perspective": "ownership", "status": "OK",
                "findings": [{"task_id": "T-106", "perspective": "ownership", "severity": "MEDIUM", "issue": "b", "recommendation": ""},
                             {"task_id": "T-105", "perspective": "ownership", "severity": "MEDIUM", "issue": "c", "recommendation": ""}]},
               {"perspective": "quality", "status": "ERROR", "findings": []}]
    rep = review.aggregate("R", "PRJ-PORTAL", "PARALLEL", workers)
    assert rep["partial"] and rep["missing_perspectives"] == ["quality"]
    assert [i["task_id"] for i in rep["items"]] == ["T-106", "T-105"]
    assert rep["items"][0]["severity"] == "HIGH" and rep["items"][0]["perspectives"] == ["schedule", "ownership"]
    assert rep["by_severity"] == {"HIGH": 1, "MEDIUM": 1, "LOW": 0}


def test_fan_in_is_a_finalizer_so_it_runs_even_if_a_worker_fails():
    sql = (ROOT / "07_parallel_fanout" / "sql" / "25_tasks.sql").read_text()
    fanin = sql[sql.index("TASK <% db %>.INTERNAL.REVIEW_FANIN"):]
    assert "FINALIZE = <% db %>.INTERNAL.REVIEW_ROOT" in fanin.split("\nAS\n", 1)[0]
    assert len(re.findall(r"AFTER <% db %>\.INTERNAL\.REVIEW_ROOT", sql)) == 3   # three sibling workers


# ------------------------------------------------------------------ 08 blackboard
def test_no_subscriber_writes_a_kind_it_consumes():
    for name, spec in board.SUBSCRIBERS.items():
        assert not set(spec["consumes"]) & set(spec["writes"]), name


def test_every_written_kind_has_exactly_one_producer():
    produced = [k for kinds in board.WRITERS.values() for k in kinds]
    assert len(produced) == len(set(produced))


@pytest.mark.parametrize("producer,kind", [("dedupe", "PROPOSALS"), ("decompose", "NOTE"), ("human", "CANDIDATES"),
                                           ("intruder", "NOTE")])
def test_write_permission_is_enforced(producer, kind):
    with pytest.raises(contracts.ContractError):
        board.check_write(producer, kind)


def test_unknown_subscriber_is_rejected_without_touching_the_session():
    assert board.react(None, None, "drop_everything")["ok"] is False


def test_each_subscriber_has_a_stream_on_a_view_of_exactly_its_kinds():
    sql = (ROOT / "08_blackboard" / "sql" / "20_objects.sql").read_text()
    for name, spec in board.SUBSCRIBERS.items():
        view = re.search(rf"VIEW <% db %>\.INTERNAL\.BOARD_V_{name.upper()}\n.*?WHERE KIND IN \(([^)]*)\)", sql, re.S)
        assert view, name
        assert {k.strip(" '") for k in view.group(1).split(",")} == set(spec["consumes"])
        assert f"STREAM <% db %>.INTERNAL.BOARD_S_{name.upper()} ON VIEW <% db %>.INTERNAL.BOARD_V_{name.upper()}" in sql


def test_triggered_tasks_have_no_schedule():
    sql = (ROOT / "08_blackboard" / "sql" / "25_tasks.sql").read_text()
    assert "SCHEDULE" not in sql.upper().replace("NO SCHEDULE", "")
    assert sql.count("WHEN SYSTEM$STREAM_HAS_DATA") == len(board.SUBSCRIBERS)


def test_worker_template_does_not_expose_the_note_text():
    assert "{note_text}" not in board.WORKER_TEMPLATE
    contracts.render_worker_request("dedupe", "TMS_DEDUPE_AGENT", board.WORKER_TEMPLATE,
                                    {"project_id": "PRJ-PORTAL", "note_id": "N-003", "candidates_json": "[]"})
