-- 08_blackboard/sql/30_grants.sql
-- 実行ロールには投稿の入口と確認用ビューだけを許可する（掲示板への直接の書き込み・タスクの操作は不可）。

USE ROLE ACCOUNTADMIN;

GRANT USAGE ON PROCEDURE <% db %>.APP.POST_MEETING_NOTE(STRING) TO ROLE <% role %>;
GRANT SELECT ON VIEW <% db %>.APP.V_BOARD_TIMELINE TO ROLE <% role %>;
GRANT SELECT ON VIEW <% db %>.APP.V_BOARD_INBOX TO ROLE <% role %>;
