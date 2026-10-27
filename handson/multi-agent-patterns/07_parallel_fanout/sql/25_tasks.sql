-- 07_parallel_fanout/sql/25_tasks.sql
-- タスクグラフ: REVIEW_ROOT → 3 ワーカー（兄弟タスク = 並列実行）、REVIEW_FANIN は finalizer。
-- finalizer はグラフの全タスクが終わった後に、成否にかかわらず必ず実行される。ワーカーが失敗しても
-- fan-in が走り、欠けた観点を partial として記録する（AFTER で 3 ワーカーを待つと、1 つの失敗で fan-in が止まる）。
-- root はスケジュールを持たず SUSPEND のまま。APP.START_PROJECT_REVIEW が EXECUTE TASK ... USING CONFIG で起動する。
-- 子タスク（ワーカーと fan-in）は RESUME しておく必要がある（root はスケジュールが無いため RESUME できない）。
-- タスクは所有者ロール（このファイルを実行したロール）で動く。

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE OR REPLACE TASK <% db %>.INTERNAL.REVIEW_ROOT
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 07 root: started by APP.START_PROJECT_REVIEW with CONFIG {run_id, project_id}'
AS
    SELECT SYSTEM$GET_TASK_GRAPH_CONFIG('run_id');

CREATE OR REPLACE TASK <% db %>.INTERNAL.REVIEW_SCHEDULE
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 07 fan-out worker: schedule perspective'
    AFTER <% db %>.INTERNAL.REVIEW_ROOT
AS
    CALL <% db %>.INTERNAL.RUN_REVIEW_WORKER('schedule', SYSTEM$GET_TASK_GRAPH_CONFIG('run_id')::STRING,
                                             SYSTEM$GET_TASK_GRAPH_CONFIG('project_id')::STRING);

CREATE OR REPLACE TASK <% db %>.INTERNAL.REVIEW_OWNERSHIP
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 07 fan-out worker: ownership perspective'
    AFTER <% db %>.INTERNAL.REVIEW_ROOT
AS
    CALL <% db %>.INTERNAL.RUN_REVIEW_WORKER('ownership', SYSTEM$GET_TASK_GRAPH_CONFIG('run_id')::STRING,
                                             SYSTEM$GET_TASK_GRAPH_CONFIG('project_id')::STRING);

CREATE OR REPLACE TASK <% db %>.INTERNAL.REVIEW_QUALITY
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 07 fan-out worker: quality perspective'
    AFTER <% db %>.INTERNAL.REVIEW_ROOT
AS
    CALL <% db %>.INTERNAL.RUN_REVIEW_WORKER('quality', SYSTEM$GET_TASK_GRAPH_CONFIG('run_id')::STRING,
                                             SYSTEM$GET_TASK_GRAPH_CONFIG('project_id')::STRING);

CREATE OR REPLACE TASK <% db %>.INTERNAL.REVIEW_FANIN
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 07 fan-in (finalizer): always runs after the graph, even if a worker failed'
    FINALIZE = <% db %>.INTERNAL.REVIEW_ROOT
AS
    CALL <% db %>.INTERNAL.AGGREGATE_REVIEW(SYSTEM$GET_TASK_GRAPH_CONFIG('run_id')::STRING);

-- 子を RESUME（fan-in → ワーカーの順）。root は SUSPEND のまま。
ALTER TASK <% db %>.INTERNAL.REVIEW_FANIN RESUME;
ALTER TASK <% db %>.INTERNAL.REVIEW_SCHEDULE RESUME;
ALTER TASK <% db %>.INTERNAL.REVIEW_OWNERSHIP RESUME;
ALTER TASK <% db %>.INTERNAL.REVIEW_QUALITY RESUME;
