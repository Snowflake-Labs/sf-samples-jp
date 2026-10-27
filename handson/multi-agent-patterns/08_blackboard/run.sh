#!/usr/bin/env bash
# 08_blackboard/run.sh - 会議メモを掲示板に投稿し、購読者が PROPOSALS を書くまで待ってタイムラインを表示する。
# Usage: ./run.sh -c <connection>   （MAP_BOARD_NOTE で投稿する会議メモを変更可、既定 N-003）
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
NOTE="${MAP_BOARD_NOTE:-N-003}"
[[ "$NOTE" =~ ^N-[0-9]+$ ]] || die "MAP_BOARD_NOTE は N-001 のような形式にしてください"
CTX="USE ROLE ${ROLE}; USE SECONDARY ROLES NONE; USE WAREHOUSE ${WH}; USE SCHEMA ${DB}.APP;"
q() { snow sql -c "$CONN" --format json -q "$CTX $1" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d[-1] if d and isinstance(d[0], list) else d))"; }
show() { python3 -c "import json,sys; [print('    ', r) for r in json.load(sys.stdin)]"; }

info "(1) POST_MEETING_NOTE('$NOTE')"
POST="$(q "CALL POST_MEETING_NOTE('$NOTE')")" || die "POST_MEETING_NOTE failed"
RUN_ID="$(jfield "$POST" "__import__('json').loads(list(d[0].values())[0]).get('run_id') or ''")"
[[ -n "$RUN_ID" ]] || die "投稿できませんでした: $POST"
echo "    run_id = ${RUN_ID}（以降は購読者のタスクが自律的に動く）"
T0=$(date +%s)
for i in $(seq 1 60); do
  sleep 5
  N="$(q "SELECT COUNT(*) AS N FROM V_BOARD_TIMELINE WHERE RUN_ID = '$RUN_ID' AND KIND = 'PROPOSALS'")" || continue
  [[ "$(jfield "$N" "d[0]['N']")" != "0" ]] && { echo "    PROPOSALS まで $(( $(date +%s) - T0 )) 秒"; break; }
  E="$(q "SELECT COUNT(*) AS N FROM V_BOARD_INBOX WHERE RUN_ID = '$RUN_ID' AND STATUS = 'ERROR'")" || continue
  [[ "$(jfield "$E" "d[0]['N']")" != "0" ]] && { echo "    ERROR があります（下の受信箱を確認）"; break; }
done
info "(2) 掲示板のタイムライン"
q "SELECT TO_CHAR(CREATED_AT, 'HH24:MI:SS') AS T, KIND, PRODUCER, ITEM_ID, PARENT_ITEM_ID, N, CONSUMED_BY FROM V_BOARD_TIMELINE WHERE RUN_ID = '$RUN_ID' ORDER BY CREATED_AT" | show
info "(3) 受信箱"
q "SELECT SUBSCRIBER, ITEM_ID, STATUS, ATTEMPTS, LEFT(LAST_ERROR, 120) AS LAST_ERROR FROM V_BOARD_INBOX WHERE RUN_ID = '$RUN_ID' ORDER BY UPDATED_AT" | show
info "(4) 提案（INTERNAL.PROPOSED_ACTIONS にも PROPOSED で保存。04 の RUN_VERIFICATION で検証できる）"
q "SELECT a.value:action_type::STRING AS ACTION_TYPE, a.value:target_task_id::STRING AS TARGET, a.value:payload:title::STRING AS TITLE, GET(PAYLOAD:action_ids, a.index)::STRING AS ACTION_ID FROM V_BOARD_TIMELINE, LATERAL FLATTEN(PAYLOAD:actions) a WHERE RUN_ID = '$RUN_ID' AND KIND = 'PROPOSALS'" | show
