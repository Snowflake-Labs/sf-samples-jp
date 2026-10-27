#!/usr/bin/env bash
# 07_parallel_fanout/run.sh - 並列レビュー（タスクグラフ）を起動して完了を待ち、逐次ベースラインと比較する。
# Usage: ./run.sh -c <connection> [-n 1]   （-n はここでは使わない）
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
PROJECT="${MAP_REVIEW_PROJECT:-PRJ-PORTAL}"
[[ "$PROJECT" =~ ^PRJ-[A-Z0-9-]+$ ]] || die "MAP_REVIEW_PROJECT は PRJ-XXX 形式にしてください"
CTX="USE ROLE ${ROLE}; USE SECONDARY ROLES NONE; USE WAREHOUSE ${WH}; USE SCHEMA ${DB}.APP;"
q() { snow sql -c "$CONN" --format json -q "$CTX $1" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d[-1] if d and isinstance(d[0], list) else d))"; }

info "(1) 並列: START_PROJECT_REVIEW('$PROJECT')"
START="$(q "CALL START_PROJECT_REVIEW('$PROJECT')")" || die "START_PROJECT_REVIEW failed"
RUN_ID="$(jfield "$START" "__import__('json').loads(list(d[0].values())[0]).get('run_id') or ''")"
[[ -n "$RUN_ID" ]] || die "開始できませんでした: $START"
echo "    run_id = $RUN_ID"
for i in $(seq 1 36); do
  sleep 5
  ST="$(q "SELECT STATUS FROM V_REVIEW_RUNS WHERE RUN_ID = '$RUN_ID'")" || continue
  [[ "$(jfield "$ST" "d[0]['STATUS'] if d else ''")" != "RUNNING" ]] && break
done
q "SELECT PERSPECTIVE, STATUS, TO_CHAR(STARTED_AT, 'HH24:MI:SS') AS STARTED, TO_CHAR(FINISHED_AT, 'HH24:MI:SS') AS FINISHED, SECONDS, FINDINGS FROM V_REVIEW_WORKERS WHERE RUN_ID = '$RUN_ID' ORDER BY STARTED_AT" \
  | python3 -c "import json,sys; [print('    ', r) for r in json.load(sys.stdin)]"

info "(2) 逐次ベースライン: RUN_PROJECT_REVIEW_SEQUENTIAL('$PROJECT')"
q "CALL RUN_PROJECT_REVIEW_SEQUENTIAL('$PROJECT')" >/dev/null || die "sequential run failed"

info "(3) 比較（最新 2 件）"
q "SELECT RUN_ID, MODE, STATUS, TOTAL_SECONDS, TASKS_FLAGGED, BY_SEVERITY FROM V_REVIEW_RUNS ORDER BY STARTED_AT DESC LIMIT 2" \
  | python3 -c "import json,sys; [print('    ', r) for r in json.load(sys.stdin)]"
info "(4) 統合レポート（並列）"
q "SELECT i.value:task_id::STRING AS TASK_ID, i.value:severity::STRING AS SEVERITY, ARRAY_TO_STRING(i.value:perspectives, ', ') AS PERSPECTIVES, LEFT(i.value:issues[0]:issue::STRING, 90) AS FIRST_ISSUE FROM V_REVIEW_RUNS r, LATERAL FLATTEN(r.REPORT:items) i WHERE r.RUN_ID = '$RUN_ID' ORDER BY i.index" \
  | python3 -c "import json,sys; [print('    ', r) for r in json.load(sys.stdin)]"
