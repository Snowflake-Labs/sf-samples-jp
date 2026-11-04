-- 07_parallel_fanout/sql/25_tasks.sql
-- Task graph: REVIEW_ROOT -> three concurrent sibling workers; REVIEW_FANIN is the finalizer.
-- The finalizer runs after the graph regardless of success or failure, so fan-in can record missing perspectives as partial.
-- An AFTER dependency on all workers would prevent fan-in when any worker fails.
-- REVIEW_ROOT has no schedule and remains SUSPENDED; APP.START_PROJECT_REVIEW starts it with EXECUTE TASK ... USING CONFIG.
-- Resume the worker and fan-in child tasks. The unscheduled root cannot be resumed.
-- Tasks run as their owner role, which is the role that executes this file.

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

-- Resume children in fan-in -> worker order; leave the root SUSPENDED.
ALTER TASK <% db %>.INTERNAL.REVIEW_FANIN RESUME;
ALTER TASK <% db %>.INTERNAL.REVIEW_SCHEDULE RESUME;
ALTER TASK <% db %>.INTERNAL.REVIEW_OWNERSHIP RESUME;
ALTER TASK <% db %>.INTERNAL.REVIEW_QUALITY RESUME;
