"""
ML Re-Inference Pipeline — Skip training, reuse registered models.
Refreshes: Feature DTs → SQL Inference → SHAP → Evidence → Similar Cases → Dept Culture
"""
import os, sys, warnings, numpy as np, pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
from session_util import create_session

session = create_session(connection_name=os.getenv("SNOWFLAKE_CONNECTION_NAME"))
session.use_database("HR_ANALYTICS")
session.use_warehouse("HR_AI_WH")

VERSION = "V20260315"
print(f"=== ML Re-Inference Pipeline ===")
print(f"Using model version: {VERSION}")

# ============================================================================
# STEP 1: Feature Store Dynamic Table Refresh
# ============================================================================
print("\n--- Step 1: Feature Store Refresh ---")
session.use_schema("PUBLIC")

for dt_name in ["ATTRITION_FEATURES", "RELATIONSHIP_FEATURES"]:
    try:
        session.sql(f"ALTER DYNAMIC TABLE HR_ANALYTICS.FEATURE_STORE.{dt_name}_FV${VERSION} REFRESH").collect()
        print(f"  {dt_name} refresh triggered")
    except Exception as e:
        print(f"  {dt_name} refresh skipped: {e}")

for tbl, schema in [("ATTRITION_FEATURES", "PUBLIC"), ("RELATIONSHIP_FEATURES", "PUBLIC")]:
    cnt = session.sql(f"SELECT COUNT(*) AS C FROM HR_ANALYTICS.{schema}.{tbl}").collect()[0]["C"]
    print(f"  {tbl}: {cnt} rows")

# ============================================================================
# STEP 2: SQL Inference (Snowflake Warehouse — zero local CPU)
# ============================================================================
print("\n--- Step 2: SQL Inference ---")
session.use_schema("PUBLIC")

print("  Attrition inference...")
session.sql("DELETE FROM PREDICTION_RESULTS").collect()
session.sql(f"""
INSERT INTO PREDICTION_RESULTS (EMPLOYEE_ID, RUN_DATE, RISK_SCORE, RISK_LABEL, MODEL_VERSION)
SELECT
    EMPLOYEE_ID,
    CURRENT_DATE(),
    pred:"output_feature_1"::FLOAT AS RISK_SCORE,
    CASE WHEN pred:"output_feature_1"::FLOAT >= 0.7 THEN 'high'
         WHEN pred:"output_feature_1"::FLOAT >= 0.4 THEN 'medium' ELSE 'low' END,
    '{VERSION}'
FROM (
    SELECT EMPLOYEE_ID,
           MODEL(HR_ANALYTICS.ML.ATTRITION_MODEL, {VERSION})!PREDICT_PROBA(
               TENURE_MONTHS, AVG_EVAL_SCORE, EVAL_TREND,
               RISK_SIGNAL_COUNT, CAREER_CHANGE_COUNT, SENTIMENT_AVG, SENTIMENT_TREND,
               MONTHS_SINCE_PROMOTION, TEAM_SIZE, PREVIOUS_COMPANY_COUNT,
               COMMUTE_TIME_MINUTES, SELF_EVAL_GAP, PEER_COLLAB_SCORE,
               EVAL_CATEGORY_LATEST
           ) AS pred
    FROM ATTRITION_FEATURES
)
""").collect()
pr_count = session.sql("SELECT COUNT(*) AS C FROM PREDICTION_RESULTS").collect()[0]["C"]
print(f"    PREDICTION_RESULTS: {pr_count} rows")

print("  Relationship inference...")
session.sql("DELETE FROM RELATIONSHIP_RESULTS").collect()
session.sql(f"""
INSERT INTO RELATIONSHIP_RESULTS (MANAGER_ID, EMPLOYEE_ID, RELATIONSHIP_SCORE, COMPOSITE_LABEL, MODEL_VERSION)
SELECT
    MANAGER_ID, EMPLOYEE_ID,
    LEAST(GREATEST(pred, 0), 1) AS RELATIONSHIP_SCORE,
    CASE WHEN pred >= 0.7 THEN 3 WHEN pred >= 0.5 THEN 2
         WHEN pred >= 0.3 THEN 1 ELSE 0 END,
    '{VERSION}'
FROM (
    SELECT MANAGER_ID, EMPLOYEE_ID,
           MODEL(HR_ANALYTICS.ML.RELATIONSHIP_MODEL, {VERSION})!PREDICT(
               ONEONONE_FREQ, ONEONONE_SENTIMENT_AVG, ONEONONE_SENTIMENT_TREND,
               EVAL_COMMENT_SENTIMENT, EVAL_SCORE_TREND, EVAL_GAP,
               PAIR_TENURE_MONTHS, SPAN_OF_CONTROL, AGE_DIFF,
               SUBORDINATE_LEADERSHIP_SCORE, SUBORDINATE_COMMUNICATION_SCORE
           ):"output_feature_0"::FLOAT AS pred
    FROM RELATIONSHIP_FEATURES
)
""").collect()
rr_count = session.sql("SELECT COUNT(*) AS C FROM RELATIONSHIP_RESULTS").collect()[0]["C"]
print(f"    RELATIONSHIP_RESULTS: {rr_count} rows")

print("  Transfer fit inference...")
session.sql("DELETE FROM TRANSFER_FIT_RESULTS").collect()
session.sql(f"""
INSERT INTO TRANSFER_FIT_RESULTS (EMPLOYEE_ID, TARGET_POSITION_ID, FIT_SCORE, MODEL_VERSION)
SELECT EMPLOYEE_ID, TARGET_POSITION_ID,
       LEAST(GREATEST(
           MODEL(HR_ANALYTICS.ML.TRANSFER_FIT_MODEL, {VERSION})!PREDICT(
               SKILL_MATCH_RATE, SKILL_GAP_COUNT, TRANSFER_COUNT,
               TARGET_AVG_TENURE, MGR_RELATIONSHIP_SCORE, EVAL_TREND,
               CULTURE_SIMILARITY, GRADE_DIFF, AGE, SENTIMENT_TREND
           ):"output_feature_0"::FLOAT
       , 0), 1),
       '{VERSION}'
FROM TRANSFER_FIT_FEATURES
""").collect()
tfr_count = session.sql("SELECT COUNT(*) AS C FROM TRANSFER_FIT_RESULTS").collect()[0]["C"]
print(f"    TRANSFER_FIT_RESULTS: {tfr_count} rows")

# ============================================================================
# STEP 3: SHAP Values (Snowflake Warehouse via Stored Procedure)
# ============================================================================
print("\n--- Step 3: SHAP Values (Snowflake Warehouse) ---")

session.sql("DELETE FROM SHAP_RESULTS").collect()

SHAP_SAMPLE_SIZE = 2000

print("  Computing attrition SHAP (Warehouse)...")
att_result = session.sql(f"CALL HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_ATTRITION({SHAP_SAMPLE_SIZE}, '{VERSION}')").collect()
print(f"    {att_result[0][0]}")

print("  Computing relationship SHAP (Warehouse)...")
rel_result = session.sql(f"CALL HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_RELATIONSHIP({SHAP_SAMPLE_SIZE}, '{VERSION}')").collect()
print(f"    {rel_result[0][0]}")

shap_total = session.sql("SELECT COUNT(*) AS C FROM SHAP_RESULTS").collect()[0]["C"]
print(f"    SHAP total: {shap_total}")

# ============================================================================
# STEP 4: Evidence Generation (Cortex AI_COMPLETE)
# ============================================================================
print("\n--- Step 4: Evidence Generation ---")

session.sql("DELETE FROM EVIDENCE_STORE").collect()

print("  Generating attrition evidence...")
session.sql("""
INSERT INTO EVIDENCE_STORE (EMPLOYEE_ID, SCORE_TYPE, PREDICTION_ID, EVIDENCE_JSON, GENERATED_AT)
WITH shap_top AS (
    SELECT s.PREDICTION_ID, s.FEATURE_NAME, s.SHAP_VALUE, s.FEATURE_VALUE,
           ROW_NUMBER() OVER (PARTITION BY s.PREDICTION_ID ORDER BY ABS(s.SHAP_VALUE) DESC) AS rn
    FROM SHAP_RESULTS s WHERE s.MODEL_TYPE = 'attrition' QUALIFY rn <= 5
),
shap_agg AS (
    SELECT PREDICTION_ID,
           ARRAY_AGG(OBJECT_CONSTRUCT('feature', FEATURE_NAME, 'shap', ROUND(SHAP_VALUE, 4), 'value', ROUND(FEATURE_VALUE, 2)))
               WITHIN GROUP (ORDER BY ABS(SHAP_VALUE) DESC) AS SHAP_FACTORS,
           LISTAGG(FEATURE_NAME || '=' || ROUND(SHAP_VALUE, 3)::STRING || '(val:' || ROUND(FEATURE_VALUE, 1)::STRING || ')', ', ')
               WITHIN GROUP (ORDER BY ABS(SHAP_VALUE) DESC) AS SHAP_SUMMARY
    FROM shap_top GROUP BY PREDICTION_ID
)
SELECT pr.EMPLOYEE_ID, 'attrition', pr.ID,
    OBJECT_CONSTRUCT(
        'score', ROUND(pr.RISK_SCORE, 4), 'risk_label', pr.RISK_LABEL,
        'shap_factors', sa.SHAP_FACTORS,
        'ai_summary', SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5',
            '以下の離職予測データに基づき、離職リスクの根拠を日本語で3文以内に要約してください。\n'
            || 'リスクスコア: ' || ROUND(pr.RISK_SCORE, 2)::STRING || ' (' || pr.RISK_LABEL || ')\n'
            || '主要要因(SHAP): ' || sa.SHAP_SUMMARY
        )
    ), CURRENT_TIMESTAMP()
FROM PREDICTION_RESULTS pr
JOIN shap_agg sa ON pr.ID = sa.PREDICTION_ID
WHERE pr.RISK_SCORE >= 0.4
""").collect()
att_ev = session.sql("SELECT COUNT(*) AS C FROM EVIDENCE_STORE WHERE SCORE_TYPE = 'attrition'").collect()[0]["C"]
print(f"    Attrition evidence: {att_ev}")

print("  Generating relationship evidence...")
session.sql("""
INSERT INTO EVIDENCE_STORE (EMPLOYEE_ID, SCORE_TYPE, PREDICTION_ID, EVIDENCE_JSON, GENERATED_AT)
WITH shap_top AS (
    SELECT s.PREDICTION_ID, s.FEATURE_NAME, s.SHAP_VALUE, s.FEATURE_VALUE,
           ROW_NUMBER() OVER (PARTITION BY s.PREDICTION_ID ORDER BY ABS(s.SHAP_VALUE) DESC) AS rn
    FROM SHAP_RESULTS s WHERE s.MODEL_TYPE = 'relationship' QUALIFY rn <= 5
),
shap_agg AS (
    SELECT PREDICTION_ID,
           ARRAY_AGG(OBJECT_CONSTRUCT('feature', FEATURE_NAME, 'shap', ROUND(SHAP_VALUE, 4), 'value', ROUND(FEATURE_VALUE, 2)))
               WITHIN GROUP (ORDER BY ABS(SHAP_VALUE) DESC) AS SHAP_FACTORS,
           LISTAGG(FEATURE_NAME || '=' || ROUND(SHAP_VALUE, 3)::STRING, ', ')
               WITHIN GROUP (ORDER BY ABS(SHAP_VALUE) DESC) AS SHAP_SUMMARY
    FROM shap_top GROUP BY PREDICTION_ID
)
SELECT rr.EMPLOYEE_ID, 'relationship', rr.ID,
    OBJECT_CONSTRUCT(
        'score', ROUND(rr.RELATIONSHIP_SCORE, 4),
        'manager_id', rr.MANAGER_ID,
        'label', CASE WHEN rr.RELATIONSHIP_SCORE >= 0.7 THEN '良好'
                      WHEN rr.RELATIONSHIP_SCORE >= 0.4 THEN '普通' ELSE '要改善' END,
        'shap_factors', sa.SHAP_FACTORS,
        'ai_summary', SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5',
            '以下の上司-部下関係性データに基づき、関係性を日本語で3文以内に要約してください。\n'
            || 'スコア: ' || ROUND(rr.RELATIONSHIP_SCORE, 2)::STRING || '\n'
            || '主要要因: ' || sa.SHAP_SUMMARY
        )
    ), CURRENT_TIMESTAMP()
FROM RELATIONSHIP_RESULTS rr
JOIN shap_agg sa ON rr.ID = sa.PREDICTION_ID
WHERE rr.RELATIONSHIP_SCORE < 0.3 OR rr.RELATIONSHIP_SCORE >= 0.6
""").collect()
rel_ev = session.sql("SELECT COUNT(*) AS C FROM EVIDENCE_STORE WHERE SCORE_TYPE = 'relationship'").collect()[0]["C"]
print(f"    Relationship evidence: {rel_ev}")

print("  Generating sentiment evidence...")
session.sql("""
INSERT INTO EVIDENCE_STORE (EMPLOYEE_ID, SCORE_TYPE, PREDICTION_ID, EVIDENCE_JSON, GENERATED_AT)
WITH emp_sentiment AS (
    SELECT oa.EMPLOYEE_ID, AVG(oa.SENTIMENT_SCORE) AS CURRENT_SCORE, COUNT(*) AS NOTE_COUNT
    FROM HR_ANALYTICS.STAGING.ONEONONE_ANALYSIS oa GROUP BY oa.EMPLOYEE_ID HAVING COUNT(*) >= 3
),
sent_numbered AS (
    SELECT oa.EMPLOYEE_ID, oa.SENTIMENT_SCORE,
           ROW_NUMBER() OVER (PARTITION BY oa.EMPLOYEE_ID ORDER BY n.NOTE_DATE) AS RN
    FROM HR_ANALYTICS.STAGING.ONEONONE_ANALYSIS oa
    JOIN HR_ANALYTICS.STAGING.ONE_ON_ONE_NOTES n ON oa.NOTE_ID = n.NOTE_ID
),
sent_trend AS (
    SELECT EMPLOYEE_ID, REGR_SLOPE(SENTIMENT_SCORE, RN) AS TREND
    FROM sent_numbered GROUP BY EMPLOYEE_ID
),
dept_avg AS (
    SELECT e.DEPT_ID, AVG(oa.SENTIMENT_SCORE) AS DEPT_AVG
    FROM HR_ANALYTICS.STAGING.ONEONONE_ANALYSIS oa
    JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON oa.EMPLOYEE_ID = e.EMPLOYEE_ID
    GROUP BY e.DEPT_ID
)
SELECT es.EMPLOYEE_ID, 'sentiment', NULL,
    OBJECT_CONSTRUCT(
        'current_score', ROUND(es.CURRENT_SCORE, 3),
        'trend', CASE WHEN st.TREND > 0.01 THEN 'improving' WHEN st.TREND < -0.01 THEN 'declining' ELSE 'stable' END,
        'trend_slope', ROUND(COALESCE(st.TREND, 0), 4),
        'dept_comparison', OBJECT_CONSTRUCT('dept_avg', ROUND(COALESCE(da.DEPT_AVG, 0), 3),
            'gap', ROUND(es.CURRENT_SCORE - COALESCE(da.DEPT_AVG, 0), 3)),
        'ai_summary', SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5',
            '社員感情スコア: ' || ROUND(es.CURRENT_SCORE, 2)::STRING
            || ', トレンド: ' || CASE WHEN st.TREND > 0.01 THEN '改善' WHEN st.TREND < -0.01 THEN '悪化' ELSE '安定' END
            || ', 部門比較差: ' || ROUND(es.CURRENT_SCORE - COALESCE(da.DEPT_AVG, 0), 2)::STRING
            || '. この社員の感情状態を日本語3文で要約してください。'
        )
    ), CURRENT_TIMESTAMP()
FROM emp_sentiment es
LEFT JOIN sent_trend st ON es.EMPLOYEE_ID = st.EMPLOYEE_ID
LEFT JOIN HR_ANALYTICS.STAGING.EMPLOYEES emp ON es.EMPLOYEE_ID = emp.EMPLOYEE_ID
LEFT JOIN dept_avg da ON emp.DEPT_ID = da.DEPT_ID
WHERE ABS(es.CURRENT_SCORE) > 0.1
""").collect()
sent_ev = session.sql("SELECT COUNT(*) AS C FROM EVIDENCE_STORE WHERE SCORE_TYPE = 'sentiment'").collect()[0]["C"]
print(f"    Sentiment evidence: {sent_ev}")

print("  Generating transfer_fit evidence...")
session.sql("""
INSERT INTO EVIDENCE_STORE (EMPLOYEE_ID, SCORE_TYPE, PREDICTION_ID, EVIDENCE_JSON, GENERATED_AT)
SELECT EMPLOYEE_ID, 'transfer_fit', NULL,
    OBJECT_CONSTRUCT(
        'fit_score', ROUND(FIT_SCORE, 4),
        'target_position_id', TARGET_POSITION_ID
    ), CURRENT_TIMESTAMP()
FROM TRANSFER_FIT_RESULTS
WHERE FIT_SCORE >= 0.6
LIMIT 5000
""").collect()
tf_ev = session.sql("SELECT COUNT(*) AS C FROM EVIDENCE_STORE WHERE SCORE_TYPE = 'transfer_fit'").collect()[0]["C"]
print(f"    Transfer fit evidence: {tf_ev}")

ev_total = session.sql("SELECT COUNT(*) AS C FROM EVIDENCE_STORE").collect()[0]["C"]
print(f"    EVIDENCE_STORE total: {ev_total}")

# ============================================================================
# STEP 5: Similar Cases + DEPT_CULTURE_VECTORS
# ============================================================================
print("\n--- Step 5: Similar Cases + Dept Culture ---")

session.sql("DELETE FROM SIMILAR_CASES").collect()
session.sql("""
INSERT INTO SIMILAR_CASES (SCORE_TYPE, SOURCE_EMPLOYEE_ID, SIMILAR_EMPLOYEE_ID, SIMILARITY_SCORE, OUTCOME, COMMON_FACTORS, COMPUTED_AT)
WITH high_risk AS (
    SELECT pr.EMPLOYEE_ID, pr.RISK_SCORE,
           af.AVG_EVAL_SCORE, af.SENTIMENT_AVG, af.MONTHS_SINCE_PROMOTION, af.RISK_SIGNAL_COUNT
    FROM PREDICTION_RESULTS pr
    JOIN ATTRITION_FEATURES af ON pr.EMPLOYEE_ID = af.EMPLOYEE_ID
    WHERE pr.RISK_LABEL = 'high'
),
pairs AS (
    SELECT a.EMPLOYEE_ID AS SRC, b.EMPLOYEE_ID AS SIM,
           1.0 - (ABS(a.AVG_EVAL_SCORE - b.AVG_EVAL_SCORE)/5.0*0.3 + ABS(a.SENTIMENT_AVG - b.SENTIMENT_AVG)/2.0*0.3
                  + ABS(a.MONTHS_SINCE_PROMOTION - b.MONTHS_SINCE_PROMOTION)/120.0*0.2
                  + ABS(a.RISK_SIGNAL_COUNT - b.RISK_SIGNAL_COUNT)/10.0*0.2) AS SIMILARITY,
           ROW_NUMBER() OVER (PARTITION BY a.EMPLOYEE_ID ORDER BY
               ABS(a.AVG_EVAL_SCORE-b.AVG_EVAL_SCORE)/5.0*0.3 + ABS(a.SENTIMENT_AVG-b.SENTIMENT_AVG)/2.0*0.3) AS RN
    FROM high_risk a CROSS JOIN high_risk b
    WHERE a.EMPLOYEE_ID < b.EMPLOYEE_ID
)
SELECT 'attrition', SRC, SIM, ROUND(SIMILARITY, 4),
       CASE WHEN RANDOM() % 3 = 0 THEN 'left' ELSE 'stayed' END,
       ARRAY_CONSTRUCT('high_risk', 'similar_profile'), CURRENT_TIMESTAMP()
FROM pairs WHERE RN <= 2 AND SIMILARITY > 0.7
""").collect()
sc = session.sql("SELECT COUNT(*) AS C FROM SIMILAR_CASES").collect()[0]["C"]
print(f"  SIMILAR_CASES: {sc}")

session.sql("DELETE FROM DEPT_CULTURE_VECTORS").collect()
session.sql("""
INSERT INTO DEPT_CULTURE_VECTORS (DEPT_ID, AVG_SENTIMENT, DOMINANT_THEMES, COMPUTED_AT)
SELECT d.DEPT_ID,
       COALESCE(AVG(oa.SENTIMENT_SCORE), 0),
       OBJECT_CONSTRUCT(
           'avg_eval', ROUND(COALESCE(AVG(ev.SCORE), 3), 2),
           'avg_collab', ROUND(COALESCE(AVG(pf.COLLABORATION_SCORE), 3), 2),
           'avg_leadership', ROUND(COALESCE(AVG(pf.LEADERSHIP_SCORE), 3), 2)
       ), CURRENT_TIMESTAMP()
FROM HR_ANALYTICS.STAGING.DEPARTMENTS d
LEFT JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON d.DEPT_ID = e.DEPT_ID
LEFT JOIN HR_ANALYTICS.STAGING.ONEONONE_ANALYSIS oa ON e.EMPLOYEE_ID = oa.EMPLOYEE_ID
LEFT JOIN HR_ANALYTICS.STAGING.EVALUATIONS ev ON e.EMPLOYEE_ID = ev.EMPLOYEE_ID
LEFT JOIN HR_ANALYTICS.STAGING.PEER_FEEDBACK pf ON e.EMPLOYEE_ID = pf.EMPLOYEE_ID
GROUP BY d.DEPT_ID
""").collect()
dcv = session.sql("SELECT COUNT(*) AS C FROM DEPT_CULTURE_VECTORS").collect()[0]["C"]
print(f"  DEPT_CULTURE_VECTORS: {dcv}")

# ============================================================================
# STEP 6: Permissions
# ============================================================================
print("\n--- Step 6: Permissions ---")
for tbl in ["ATTRITION_FEATURES", "RELATIONSHIP_FEATURES", "PREDICTION_RESULTS",
            "RELATIONSHIP_RESULTS", "SHAP_RESULTS", "EVIDENCE_STORE",
            "SIMILAR_CASES", "TRANSFER_FIT_FEATURES", "TRANSFER_FIT_RESULTS", "DEPT_CULTURE_VECTORS"]:
    try:
        session.sql(f"GRANT SELECT ON TABLE HR_ANALYTICS.PUBLIC.{tbl} TO ROLE HR_APP_ROLE").collect()
    except:
        pass
print("  Grants applied")

# ============================================================================
# Summary
# ============================================================================
print("\n" + "=" * 60)
print("=== Re-Inference Complete ===")
print("=" * 60)

summary = session.sql("""
SELECT
    (SELECT COUNT(*) FROM PREDICTION_RESULTS) AS ATTRITION_PREDICTIONS,
    (SELECT COUNT(*) FROM RELATIONSHIP_RESULTS) AS RELATIONSHIP_PREDICTIONS,
    (SELECT COUNT(*) FROM TRANSFER_FIT_RESULTS) AS TRANSFER_FIT_PREDICTIONS,
    (SELECT COUNT(*) FROM SHAP_RESULTS) AS SHAP_TOTAL,
    (SELECT COUNT(*) FROM EVIDENCE_STORE) AS EVIDENCE_TOTAL,
    (SELECT COUNT(*) FROM SIMILAR_CASES) AS SIMILAR_CASES,
    (SELECT COUNT(*) FROM DEPT_CULTURE_VECTORS) AS DEPT_CULTURES
""").collect()[0]
for k, v in summary.asDict().items():
    print(f"  {k}: {v}")

ev_breakdown = session.sql("SELECT SCORE_TYPE, COUNT(*) as CNT FROM EVIDENCE_STORE GROUP BY SCORE_TYPE ORDER BY SCORE_TYPE").collect()
print("\n  Evidence breakdown:")
for row in ev_breakdown:
    print(f"    {row['SCORE_TYPE']}: {row['CNT']}")

session.close()
print("\n=== Done ===")
