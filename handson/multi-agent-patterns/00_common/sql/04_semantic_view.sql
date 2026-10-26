-- 00_common/sql/04_semantic_view.sql
-- 共通基盤: Status エージェント（パターン 01）が Cortex Analyst で使うセマンティックビュー。
-- One semantic view over PROJECTS and TASKS for Cortex Analyst (read-only status questions).

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE OR REPLACE SEMANTIC VIEW <% db %>.AGENTS.TMS_SEMANTIC_VIEW
    TABLES (
        projects AS <% db %>.APP.PROJECTS
            PRIMARY KEY (PROJECT_ID)
            COMMENT = 'Projects and their task policies',
        tasks AS <% db %>.APP.TASKS
            PRIMARY KEY (TASK_ID)
            COMMENT = 'Tasks in the task management system'
    )
    RELATIONSHIPS (
        tasks_to_projects AS tasks (PROJECT_ID) REFERENCES projects
    )
    FACTS (
        tasks.overdue_flag AS IFF(DUE_DATE < CURRENT_DATE() AND STATUS <> 'DONE', 1, 0)
            COMMENT = '1 when the task is past due and not DONE',
        tasks.unassigned_flag AS IFF(ASSIGNEE IS NULL, 1, 0)
            COMMENT = '1 when the task has no assignee'
    )
    DIMENSIONS (
        projects.project_id AS PROJECT_ID COMMENT = 'Project identifier, for example PRJ-PORTAL',
        projects.project_name AS PROJECT_NAME
            WITH SYNONYMS = ('project')
            COMMENT = 'Project display name',
        tasks.task_id AS TASK_ID COMMENT = 'Task identifier, for example T-101',
        tasks.title AS TITLE COMMENT = 'Task title',
        tasks.status AS STATUS
            WITH SYNONYMS = ('state', 'progress')
            COMMENT = 'One of OPEN, IN_PROGRESS, BLOCKED, DONE',
        tasks.priority AS PRIORITY COMMENT = 'One of LOW, MEDIUM, HIGH, CRITICAL',
        tasks.assignee AS ASSIGNEE
            WITH SYNONYMS = ('owner', 'assigned to')
            COMMENT = 'Assignee user name; NULL means unassigned',
        tasks.due_date AS DUE_DATE COMMENT = 'Due date',
        tasks.is_overdue AS (DUE_DATE < CURRENT_DATE() AND STATUS <> 'DONE')
            COMMENT = 'TRUE when past due and not DONE'
    )
    METRICS (
        tasks.task_count AS COUNT(tasks.task_id) COMMENT = 'Number of tasks',
        tasks.overdue_task_count AS SUM(tasks.overdue_flag) COMMENT = 'Number of overdue tasks',
        tasks.unassigned_task_count AS SUM(tasks.unassigned_flag) COMMENT = 'Number of unassigned tasks'
    )
    COMMENT = 'Task management semantic view for multi-agent-patterns';
