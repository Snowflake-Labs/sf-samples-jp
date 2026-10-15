-- ============================================================================
-- 人材検索（Cortex Search）と HR AI エージェントの作成
-- ============================================================================
-- 実行タイミング: データ同期（scripts/sync_pg_to_iceberg.py）と
--                 scripts/create_semantic_view.py の後
-- 前提: ACCOUNTADMIN、または SYSADMIN + CREATE AGENT 権限
--
-- setup_analytics.sql の SEARCH_TALENT_SOURCE はデータが入る前に作られて空のため、
-- ここで作り直してから検索サービスを更新する。
-- ============================================================================

USE ROLE SYSADMIN;
USE WAREHOUSE HR_SEARCH_WH;
USE SCHEMA HR_ANALYTICS.PUBLIC;

-- ----------------------------------------------------------------------------
-- 1. 人材検索の元データ（在籍中の社員ごとに、スキル・評価コメント・1on1 メモをまとめる）
-- ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE SEARCH_TALENT_SOURCE AS
SELECT
    e.EMPLOYEE_ID,
    e.FIRST_NAME || ' ' || e.LAST_NAME AS EMPLOYEE_NAME,
    d.DEPT_NAME,
    p.TITLE AS POSITION_TITLE,
    p.GRADE,
    COALESCE(sk.SKILLS_TEXT, '') AS SKILLS_TEXT,
    COALESCE(ev.EVAL_COMMENTS, '') AS EVAL_COMMENTS,
    COALESCE(n.ONEONONE_NOTES, '') AS ONEONONE_NOTES,
    e.BIRTH_DATE
FROM HR_ANALYTICS.STAGING.EMPLOYEES e
LEFT JOIN HR_ANALYTICS.STAGING.DEPARTMENTS d ON e.DEPT_ID = d.DEPT_ID
LEFT JOIN HR_ANALYTICS.STAGING.POSITIONS p ON e.POSITION_ID = p.POSITION_ID
LEFT JOIN (
    SELECT EMPLOYEE_ID, LISTAGG(s.SKILL_NAME, ', ') AS SKILLS_TEXT
    FROM HR_ANALYTICS.STAGING.EMPLOYEE_SKILLS es
    JOIN HR_ANALYTICS.STAGING.SKILLS s ON es.SKILL_ID = s.SKILL_ID
    GROUP BY EMPLOYEE_ID
) sk ON e.EMPLOYEE_ID = sk.EMPLOYEE_ID
LEFT JOIN (
    SELECT EMPLOYEE_ID, LISTAGG(COMMENT, '\n') AS EVAL_COMMENTS
    FROM HR_ANALYTICS.STAGING.EVALUATIONS
    WHERE COMMENT IS NOT NULL
    GROUP BY EMPLOYEE_ID
) ev ON e.EMPLOYEE_ID = ev.EMPLOYEE_ID
LEFT JOIN (
    SELECT EMPLOYEE_ID, LISTAGG(CONTENT, '\n') AS ONEONONE_NOTES
    FROM HR_ANALYTICS.STAGING.ONE_ON_ONE_NOTES
    GROUP BY EMPLOYEE_ID
) n ON e.EMPLOYEE_ID = n.EMPLOYEE_ID
WHERE e.STATUS = 'active';

GRANT SELECT ON TABLE SEARCH_TALENT_SOURCE TO ROLE HR_ADMIN_ROLE;
GRANT SELECT ON TABLE SEARCH_TALENT_SOURCE TO ROLE HR_SERVICE_ROLE;

-- ----------------------------------------------------------------------------
-- 2. 人材検索サービス（元データを作り直したので、検索サービスも作り直す）
-- ----------------------------------------------------------------------------
CREATE OR REPLACE CORTEX SEARCH SERVICE HR_ANALYTICS.PUBLIC.TALENT_SEARCH_SERVICE
    ON EVAL_COMMENTS
    ATTRIBUTES EMPLOYEE_NAME, DEPT_NAME, POSITION_TITLE, GRADE, BIRTH_DATE
    WAREHOUSE = HR_SEARCH_WH
    TARGET_LAG = '1 day'
    EMBEDDING_MODEL = 'snowflake-arctic-embed-l-v2.0'
AS (
    SELECT * FROM HR_ANALYTICS.PUBLIC.SEARCH_TALENT_SOURCE
);

GRANT USAGE ON CORTEX SEARCH SERVICE HR_ANALYTICS.PUBLIC.TALENT_SEARCH_SERVICE TO ROLE HR_ADMIN_ROLE;
GRANT USAGE ON CORTEX SEARCH SERVICE HR_ANALYTICS.PUBLIC.TALENT_SEARCH_SERVICE TO ROLE HR_MANAGER_ROLE;
GRANT USAGE ON CORTEX SEARCH SERVICE HR_ANALYTICS.PUBLIC.TALENT_SEARCH_SERVICE TO ROLE HR_SERVICE_ROLE;

-- ----------------------------------------------------------------------------
-- 3. HR AI エージェント（構造化データは Semantic View、テキストは人材検索で答える）
-- ----------------------------------------------------------------------------
CREATE OR REPLACE AGENT HR_ANALYTICS.PUBLIC.HR_AGENT
    COMMENT = 'HR Intelligence AIエージェント - 人事データの横断分析・人材検索'
    PROFILE = '{"display_name": "HR Intelligence Agent"}'
    FROM SPECIFICATION $$
{
  "models": {"orchestration": "claude-haiku-4-5"},
  "instructions": {
    "response": "回答は必ず日本語で行ってください。データに基づいた具体的な数値を含め、簡潔かつ分かりやすく回答してください。社員名は「姓 名」の順で表示してください。テーブルやリスト形式で見やすく整理してください。",
    "orchestration": "あなたはHR Intelligence AIエージェントです。人事に関するあらゆる質問に回答します。\n\nツール選択ガイド:\n- 構造化データの集計・分析（社員数、平均評価、離職リスク分布、年収分析など）→ hr_analyst を使用\n- 評価コメント・1on1メモ・スキル情報の検索（人材検索、コメント傾向、特定社員の定性情報など）→ talent_search を使用\n\n複数ツールの組合せ:\n- 「この空きポストにふさわしい人材は？」→ hr_analyst で等級フィルタ + talent_search でスキル検索\n- 「離職リスクが高い人の評価傾向は？」→ hr_analyst でリスク高を特定 + talent_search でコメント検索"
  },
  "tools": [
    {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": "hr_analyst",
      "description": "社員マスタ・部署・ポジション・評価・離職予測・関係性スコア・配置適合予測の構造化データを自然言語で検索・集計・分析する"}},
    {"tool_spec": {"type": "cortex_search", "name": "talent_search",
      "description": "評価コメント・1on1メモ・スキル情報を横断的にセマンティック検索する。人材検索、コメント傾向分析、特定社員の定性情報取得に使用"}}
  ],
  "tool_resources": {
    "hr_analyst": {
      "semantic_view": "HR_ANALYTICS.PUBLIC.HR_SEMANTIC_VIEW",
      "execution_environment": {"type": "warehouse", "warehouse": "HR_AI_WH"},
      "query_timeout": 60
    },
    "talent_search": {
      "search_service": "HR_ANALYTICS.PUBLIC.TALENT_SEARCH_SERVICE",
      "max_results": 10,
      "columns": ["EMPLOYEE_ID", "EMPLOYEE_NAME", "DEPT_NAME", "POSITION_TITLE", "GRADE",
                  "SKILLS_TEXT", "EVAL_COMMENTS", "ONEONONE_NOTES"]
    }
  }
}
$$;

GRANT USAGE ON AGENT HR_ANALYTICS.PUBLIC.HR_AGENT TO ROLE HR_ADMIN_ROLE;
GRANT USAGE ON AGENT HR_ANALYTICS.PUBLIC.HR_AGENT TO ROLE HR_MANAGER_ROLE;
GRANT USAGE ON AGENT HR_ANALYTICS.PUBLIC.HR_AGENT TO ROLE HR_SERVICE_ROLE;
