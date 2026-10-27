-- 08_blackboard/sql/90_try.sql
-- Try the blackboard. Posting is asynchronous; subscribers react in sequence and write PROPOSALS in 1-2 minutes.

-- Run with the least-privilege execution role; only owner-rights procedures can write.
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- (1) Post meeting note N-003 to the board and return RUN_ID.
CALL POST_MEETING_NOTE('N-003');
SET board_run = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));

-- (2) Re-run the board timeline every few dozen seconds to see NOTE -> CANDIDATES -> DEDUPE / CRITERIA -> PROPOSALS.
SELECT CREATED_AT, KIND, PRODUCER, ITEM_ID, PARENT_ITEM_ID, N, CONSUMED_BY
FROM V_BOARD_TIMELINE WHERE RUN_ID = $board_run ORDER BY CREATED_AT;

-- (3) Inbox: WAITING means the paired result is pending; ERROR records the reason in LAST_ERROR.
SELECT SUBSCRIBER, ITEM_ID, STATUS, ATTEMPTS, LAST_ERROR FROM V_BOARD_INBOX WHERE RUN_ID = $board_run ORDER BY UPDATED_AT;

-- (4) Expected proposals match pattern 02: CREATE_TASK and LINK_DUPLICATE to T-108.
--     Proposals are also saved as PROPOSED in INTERNAL.PROPOSED_ACTIONS for pattern 04 RUN_VERIFICATION.
SELECT a.value:action_type::STRING AS ACTION_TYPE, a.value:target_task_id::STRING AS TARGET,
       a.value:payload:title::STRING AS TITLE, GET(PAYLOAD:action_ids, a.index)::STRING AS ACTION_ID
FROM V_BOARD_TIMELINE, LATERAL FLATTEN(PAYLOAD:actions) a
WHERE RUN_ID = $board_run AND KIND = 'PROPOSALS';
