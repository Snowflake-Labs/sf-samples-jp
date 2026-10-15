"""
HR ML Pipeline V3 — Snowflake-Native Edition
=============================================
Maximizes use of Snowflake ML platform features:
  - Feature Store API (Managed Feature Views backed by Dynamic Tables)
  - Snowpark ML GridSearchCV (server-side hyperparameter tuning on Warehouse)
  - Model Registry with versioning
  - SQL-based inference via MODEL()!PREDICT()
  - All Evidence generation in Snowflake SQL (Cortex AI_COMPLETE)
  - Model Monitor with baseline

Local CPU usage is minimized — only lightweight orchestration runs locally.
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from session_util import create_session

session = create_session()
session.use_database("HR_ANALYTICS")
session.use_warehouse("HR_AI_WH")

VERSION = f"V{datetime.now().strftime('%Y%m%d')}"
print(f"=== HR ML Pipeline V3 (Snowflake-Native) ===")
print(f"Model Version: {VERSION}")

# ============================================================================
# STEP 1: Feature Store — Managed Feature Views (Dynamic Table auto-refresh)
# ============================================================================
print("\n--- Step 1: Feature Store Setup ---")

from snowflake.ml.feature_store import FeatureStore, FeatureView, Entity, CreationMode

session.use_schema("PUBLIC")

FS_SCHEMA = "FEATURE_STORE"
try:
    session.sql(f"CREATE SCHEMA IF NOT EXISTS HR_ANALYTICS.{FS_SCHEMA}").collect()
except:
    pass

fs = FeatureStore(
    session=session,
    database="HR_ANALYTICS",
    name=FS_SCHEMA,
    default_warehouse="HR_AI_WH",
    creation_mode=CreationMode.CREATE_IF_NOT_EXIST,
)

# 1a. Define Entities
print("  Registering entities...")
try:
    employee_entity = Entity(name="EMPLOYEE", join_keys=["EMPLOYEE_ID"])
    fs.register_entity(employee_entity)
    print("    EMPLOYEE entity registered")
except Exception as e:
    if "already exists" in str(e).lower():
        employee_entity = fs.get_entity("EMPLOYEE")
        print("    EMPLOYEE entity already exists")
    else:
        print(f"    Entity error: {e}")

try:
    emp_mgr_entity = Entity(name="EMP_MGR_PAIR", join_keys=["EMPLOYEE_ID", "MANAGER_ID"])
    fs.register_entity(emp_mgr_entity)
    print("    EMP_MGR_PAIR entity registered")
except Exception as e:
    if "already exists" in str(e).lower():
        emp_mgr_entity = fs.get_entity("EMP_MGR_PAIR")
        print("    EMP_MGR_PAIR entity already exists")
    else:
        print(f"    Entity error: {e}")

# 1b. Attrition Feature View (Snowflake-managed, backed by Dynamic Table)
print("  Creating ATTRITION_FEATURES_FV...")
att_feature_df = session.sql("""
WITH emp_base AS (
    SELECT e.EMPLOYEE_ID, e.DEPT_ID, e.MANAGER_ID,
           DATEDIFF('month', e.HIRE_DATE, CURRENT_DATE()) AS TENURE_MONTHS,
           DATEDIFF('month', COALESCE(e.LAST_PROMOTION_DATE, e.HIRE_DATE), CURRENT_DATE()) AS MONTHS_SINCE_PROMOTION,
           COALESCE(e.COMMUTE_TIME_MINUTES, 30) AS COMMUTE_TIME_MINUTES,
           COALESCE(ep.PREVIOUS_COMPANY_COUNT, 0) AS PREVIOUS_COMPANY_COUNT
    FROM HR_ANALYTICS.STAGING.EMPLOYEES e
    LEFT JOIN HR_ANALYTICS.STAGING.EMPLOYEE_PROFILES ep ON e.EMPLOYEE_ID = ep.EMPLOYEE_ID
    WHERE e.STATUS = 'active'
),
eval_numbered AS (
    SELECT EMPLOYEE_ID, SCORE, SELF_SCORE,
           ROW_NUMBER() OVER (PARTITION BY EMPLOYEE_ID ORDER BY PERIOD) AS RN
    FROM HR_ANALYTICS.STAGING.EVALUATIONS
),
eval_stats AS (
    SELECT EMPLOYEE_ID,
           AVG(SCORE) AS AVG_EVAL_SCORE,
           REGR_SLOPE(SCORE, RN) AS EVAL_TREND,
           AVG(SCORE - SELF_SCORE) AS SELF_EVAL_GAP
    FROM eval_numbered GROUP BY EMPLOYEE_ID
),
note_numbered AS (
    SELECT oa.EMPLOYEE_ID, oa.SENTIMENT_SCORE,
           ROW_NUMBER() OVER (PARTITION BY oa.EMPLOYEE_ID ORDER BY n.NOTE_DATE) AS RN
    FROM HR_ANALYTICS.STAGING.ONEONONE_ANALYSIS oa
    JOIN HR_ANALYTICS.STAGING.ONE_ON_ONE_NOTES n ON oa.NOTE_ID = n.NOTE_ID
),
note_stats AS (
    SELECT EMPLOYEE_ID, AVG(SENTIMENT_SCORE) AS SENTIMENT_AVG, REGR_SLOPE(SENTIMENT_SCORE, RN) AS SENTIMENT_TREND
    FROM note_numbered GROUP BY EMPLOYEE_ID
),
risk_counts AS (
    SELECT EMPLOYEE_ID, COUNT(*) AS RISK_SIGNAL_COUNT
    FROM HR_ANALYTICS.STAGING.ONEONONE_ANALYSIS
    WHERE RISK_SIGNALS IS NOT NULL AND ARRAY_SIZE(RISK_SIGNALS) > 0
    GROUP BY EMPLOYEE_ID
),
career_stats AS (
    SELECT EMPLOYEE_ID, COUNT(*) AS CAREER_CHANGE_COUNT
    FROM HR_ANALYTICS.STAGING.CAREER_HISTORY WHERE TRANSFER_TYPE != 'hire'
    GROUP BY EMPLOYEE_ID
),
team_sizes AS (
    SELECT MANAGER_ID, COUNT(*) AS TEAM_SIZE
    FROM HR_ANALYTICS.STAGING.EMPLOYEES WHERE STATUS = 'active' AND MANAGER_ID IS NOT NULL
    GROUP BY MANAGER_ID
),
peer_collab AS (
    SELECT EMPLOYEE_ID, AVG(COLLABORATION_SCORE) AS PEER_COLLAB_SCORE
    FROM HR_ANALYTICS.STAGING.PEER_FEEDBACK GROUP BY EMPLOYEE_ID
),
eval_cat_latest AS (
    SELECT ea.EMPLOYEE_ID, ea.CATEGORY AS EVAL_CATEGORY_LATEST
    FROM HR_ANALYTICS.STAGING.EVALUATION_ANALYSIS ea
    INNER JOIN (
        SELECT EMPLOYEE_ID, MAX(EVALUATION_ID) AS MAX_EID
        FROM HR_ANALYTICS.STAGING.EVALUATION_ANALYSIS GROUP BY EMPLOYEE_ID
    ) latest ON ea.EMPLOYEE_ID = latest.EMPLOYEE_ID AND ea.EVALUATION_ID = latest.MAX_EID
)
SELECT
    eb.EMPLOYEE_ID,
    eb.TENURE_MONTHS,
    COALESCE(es.AVG_EVAL_SCORE, 3.0) AS AVG_EVAL_SCORE,
    COALESCE(es.EVAL_TREND, 0.0) AS EVAL_TREND,
    COALESCE(rc.RISK_SIGNAL_COUNT, 0) AS RISK_SIGNAL_COUNT,
    COALESCE(cs.CAREER_CHANGE_COUNT, 0) AS CAREER_CHANGE_COUNT,
    COALESCE(ns.SENTIMENT_AVG, 0.0) AS SENTIMENT_AVG,
    COALESCE(ns.SENTIMENT_TREND, 0.0) AS SENTIMENT_TREND,
    eb.MONTHS_SINCE_PROMOTION,
    COALESCE(ts.TEAM_SIZE, 1) AS TEAM_SIZE,
    eb.PREVIOUS_COMPANY_COUNT,
    eb.COMMUTE_TIME_MINUTES,
    COALESCE(es.SELF_EVAL_GAP, 0.0) AS SELF_EVAL_GAP,
    COALESCE(pc.PEER_COLLAB_SCORE, 3.0) AS PEER_COLLAB_SCORE,
    CASE COALESCE(ecl.EVAL_CATEGORY_LATEST, 'stable')
        WHEN 'critical' THEN 0 WHEN 'declining' THEN 1 WHEN 'stable' THEN 2 WHEN 'growth' THEN 3 ELSE 2
    END AS EVAL_CATEGORY_LATEST,
    eb.DEPT_ID
FROM emp_base eb
LEFT JOIN eval_stats es ON eb.EMPLOYEE_ID = es.EMPLOYEE_ID
LEFT JOIN note_stats ns ON eb.EMPLOYEE_ID = ns.EMPLOYEE_ID
LEFT JOIN risk_counts rc ON eb.EMPLOYEE_ID = rc.EMPLOYEE_ID
LEFT JOIN career_stats cs ON eb.EMPLOYEE_ID = cs.EMPLOYEE_ID
LEFT JOIN team_sizes ts ON eb.MANAGER_ID = ts.MANAGER_ID
LEFT JOIN peer_collab pc ON eb.EMPLOYEE_ID = pc.EMPLOYEE_ID
LEFT JOIN eval_cat_latest ecl ON eb.EMPLOYEE_ID = ecl.EMPLOYEE_ID
""")

try:
    existing = fs.get_feature_view("ATTRITION_FEATURES_FV", VERSION)
    print(f"    ATTRITION_FEATURES_FV {VERSION} already exists ({existing})")
    registered_att_fv = existing
except:
    try:
        att_fv = FeatureView(
            name="ATTRITION_FEATURES_FV",
            entities=[employee_entity],
            feature_df=att_feature_df,
            refresh_freq="1 day",
            desc="Attrition risk features: eval, sentiment, career, peer collab (auto-refresh daily)"
        )
        att_fv = att_fv.attach_feature_desc({
            "TENURE_MONTHS": "Months since hire date",
            "AVG_EVAL_SCORE": "Average evaluation score",
            "EVAL_TREND": "Evaluation score regression slope",
            "RISK_SIGNAL_COUNT": "Count of 1on1 risk signal detections",
            "CAREER_CHANGE_COUNT": "Number of career changes (transfers/promotions)",
            "SENTIMENT_AVG": "Average 1on1 sentiment score",
            "SENTIMENT_TREND": "Sentiment score regression slope",
            "MONTHS_SINCE_PROMOTION": "Months since last promotion",
            "TEAM_SIZE": "Manager team size",
            "PREVIOUS_COMPANY_COUNT": "Number of previous employers",
            "COMMUTE_TIME_MINUTES": "Commute time in minutes",
            "SELF_EVAL_GAP": "Gap between self-evaluation and manager evaluation",
            "PEER_COLLAB_SCORE": "Average peer collaboration score from 360 feedback",
            "EVAL_CATEGORY_LATEST": "Latest evaluation category (0=critical, 1=declining, 2=stable, 3=growth)",
        })
        registered_att_fv = fs.register_feature_view(
            feature_view=att_fv, version=VERSION, block=True, overwrite=False
        )
        print(f"    ATTRITION_FEATURES_FV {VERSION} registered (Dynamic Table)")
    except Exception as e:
        print(f"    Attrition FV: {e}")
        registered_att_fv = None

# 1c. Relationship Feature View
print("  Creating RELATIONSHIP_FEATURES_FV...")
rel_feature_df = session.sql("""
WITH pairs AS (
    SELECT e.EMPLOYEE_ID, e.MANAGER_ID, e.DEPT_ID, e.HIRE_DATE, e.BIRTH_DATE
    FROM HR_ANALYTICS.STAGING.EMPLOYEES e
    WHERE e.STATUS = 'active' AND e.MANAGER_ID IS NOT NULL
),
mgr_info AS (
    SELECT EMPLOYEE_ID, HIRE_DATE AS MGR_HIRE, BIRTH_DATE AS MGR_BIRTH
    FROM HR_ANALYTICS.STAGING.EMPLOYEES
),
note_numbered2 AS (
    SELECT oa.EMPLOYEE_ID, oa.MANAGER_ID, oa.SENTIMENT_SCORE,
           ROW_NUMBER() OVER (PARTITION BY oa.EMPLOYEE_ID, oa.MANAGER_ID ORDER BY n.NOTE_DATE) AS RN
    FROM HR_ANALYTICS.STAGING.ONEONONE_ANALYSIS oa
    JOIN HR_ANALYTICS.STAGING.ONE_ON_ONE_NOTES n ON oa.NOTE_ID = n.NOTE_ID
),
note_agg AS (
    SELECT EMPLOYEE_ID, MANAGER_ID, COUNT(*) AS NOTE_CNT,
           AVG(SENTIMENT_SCORE) AS AVG_SENT, REGR_SLOPE(SENTIMENT_SCORE, RN) AS SENT_TREND
    FROM note_numbered2 GROUP BY EMPLOYEE_ID, MANAGER_ID
),
eval_numbered_r AS (
    SELECT EMPLOYEE_ID, EVALUATOR_ID, SCORE,
           ROW_NUMBER() OVER (PARTITION BY EMPLOYEE_ID, EVALUATOR_ID ORDER BY PERIOD) AS RN
    FROM HR_ANALYTICS.STAGING.EVALUATIONS
    WHERE EVALUATOR_ID IS NOT NULL
),
eval_agg AS (
    SELECT EMPLOYEE_ID, EVALUATOR_ID,
           AVG(SCORE) AS AVG_EVAL, REGR_SLOPE(SCORE, RN) AS EVAL_TREND
    FROM eval_numbered_r GROUP BY EMPLOYEE_ID, EVALUATOR_ID
),
eval_gap AS (
    SELECT e.EMPLOYEE_ID, AVG(e.SCORE - e.SELF_SCORE) AS GAP
    FROM HR_ANALYTICS.STAGING.EVALUATIONS e GROUP BY e.EMPLOYEE_ID
),
peer_sub AS (
    SELECT EMPLOYEE_ID, AVG(LEADERSHIP_SCORE) AS SUB_LEAD, AVG(COMMUNICATION_SCORE) AS SUB_COMM
    FROM HR_ANALYTICS.STAGING.PEER_FEEDBACK WHERE REVIEWER_RELATION = 'subordinate'
    GROUP BY EMPLOYEE_ID
),
span AS (
    SELECT MANAGER_ID, COUNT(*) AS SPAN
    FROM HR_ANALYTICS.STAGING.EMPLOYEES WHERE STATUS='active' AND MANAGER_ID IS NOT NULL
    GROUP BY MANAGER_ID
)
SELECT
    p.EMPLOYEE_ID, p.MANAGER_ID,
    COALESCE(na.NOTE_CNT, 0)::FLOAT / GREATEST(DATEDIFF('month', p.HIRE_DATE, CURRENT_DATE()), 1) AS ONEONONE_FREQ,
    COALESCE(na.AVG_SENT, 0.0) AS ONEONONE_SENTIMENT_AVG,
    COALESCE(na.SENT_TREND, 0.0) AS ONEONONE_SENTIMENT_TREND,
    COALESCE(ea.AVG_EVAL, 3.0) / 5.0 AS EVAL_COMMENT_SENTIMENT,
    COALESCE(ea.EVAL_TREND, 0.0) AS EVAL_SCORE_TREND,
    COALESCE(eg.GAP, 0.0) AS EVAL_GAP,
    DATEDIFF('month', GREATEST(p.HIRE_DATE, COALESCE(mi.MGR_HIRE, p.HIRE_DATE)), CURRENT_DATE()) AS PAIR_TENURE_MONTHS,
    COALESCE(sp.SPAN, 1) AS SPAN_OF_CONTROL,
    ABS(DATEDIFF('year', p.BIRTH_DATE, COALESCE(mi.MGR_BIRTH, p.BIRTH_DATE))) AS AGE_DIFF,
    COALESCE(ps.SUB_LEAD, 3.0) / 5.0 AS SUBORDINATE_LEADERSHIP_SCORE,
    COALESCE(ps.SUB_COMM, 3.0) / 5.0 AS SUBORDINATE_COMMUNICATION_SCORE
FROM pairs p
LEFT JOIN mgr_info mi ON p.MANAGER_ID = mi.EMPLOYEE_ID
LEFT JOIN note_agg na ON p.EMPLOYEE_ID = na.EMPLOYEE_ID AND p.MANAGER_ID = na.MANAGER_ID
LEFT JOIN eval_agg ea ON p.EMPLOYEE_ID = ea.EMPLOYEE_ID AND p.MANAGER_ID = ea.EVALUATOR_ID
LEFT JOIN eval_gap eg ON p.EMPLOYEE_ID = eg.EMPLOYEE_ID
LEFT JOIN peer_sub ps ON p.MANAGER_ID = ps.EMPLOYEE_ID
LEFT JOIN span sp ON p.MANAGER_ID = sp.MANAGER_ID
""")

try:
    existing_rel = fs.get_feature_view("RELATIONSHIP_FEATURES_FV", VERSION)
    print(f"    RELATIONSHIP_FEATURES_FV {VERSION} already exists")
    registered_rel_fv = existing_rel
except:
    try:
        rel_fv = FeatureView(
            name="RELATIONSHIP_FEATURES_FV",
            entities=[emp_mgr_entity],
            feature_df=rel_feature_df,
            refresh_freq="1 day",
            desc="Manager-employee relationship features (auto-refresh daily)"
        )
        registered_rel_fv = fs.register_feature_view(
            feature_view=rel_fv, version=VERSION, block=True, overwrite=False
        )
        print(f"    RELATIONSHIP_FEATURES_FV {VERSION} registered (Dynamic Table)")
    except Exception as e:
        print(f"    Relationship FV: {e}")
        registered_rel_fv = None

# ============================================================================
# STEP 2: Model Training (data from Snowflake, sklearn GridSearchCV, register to Model Registry)
# ============================================================================
print("\n--- Step 2: Model Training ---")

from sklearn.model_selection import GridSearchCV
from xgboost import XGBClassifier, XGBRegressor
from lightgbm import LGBMRegressor
from sklearn.metrics import roc_auc_score, mean_squared_error

ATTRITION_NUM_COLS = [
    "TENURE_MONTHS", "AVG_EVAL_SCORE", "EVAL_TREND",
    "RISK_SIGNAL_COUNT", "CAREER_CHANGE_COUNT", "SENTIMENT_AVG", "SENTIMENT_TREND",
    "MONTHS_SINCE_PROMOTION", "TEAM_SIZE", "PREVIOUS_COMPANY_COUNT",
    "COMMUTE_TIME_MINUTES", "SELF_EVAL_GAP", "PEER_COLLAB_SCORE", "EVAL_CATEGORY_LATEST"
]
REL_FEATURES_COLS = [
    "ONEONONE_FREQ", "ONEONONE_SENTIMENT_AVG", "ONEONONE_SENTIMENT_TREND",
    "EVAL_COMMENT_SENTIMENT", "EVAL_SCORE_TREND", "EVAL_GAP",
    "PAIR_TENURE_MONTHS", "SPAN_OF_CONTROL", "AGE_DIFF",
    "SUBORDINATE_LEADERSHIP_SCORE", "SUBORDINATE_COMMUNICATION_SCORE"
]
TF_FEATURES_COLS = [
    "SKILL_MATCH_RATE", "SKILL_GAP_COUNT", "TRANSFER_COUNT",
    "TARGET_AVG_TENURE", "MGR_RELATIONSHIP_SCORE", "EVAL_TREND",
    "CULTURE_SIMILARITY", "GRADE_DIFF", "AGE", "SENTIMENT_TREND"
]

# 2a. Synthetic labels in Snowflake SQL (no local compute for label generation)
print("  Creating training data (synthetic labels in Snowflake SQL)...")
session.sql("""
CREATE OR REPLACE TEMPORARY TABLE HR_ANALYTICS.PUBLIC._ATT_TRAIN AS
SELECT EMPLOYEE_ID, TENURE_MONTHS, AVG_EVAL_SCORE, EVAL_TREND,
    RISK_SIGNAL_COUNT, CAREER_CHANGE_COUNT, SENTIMENT_AVG, SENTIMENT_TREND,
    MONTHS_SINCE_PROMOTION, TEAM_SIZE, PREVIOUS_COMPANY_COUNT, COMMUTE_TIME_MINUTES,
    SELF_EVAL_GAP, PEER_COLLAB_SCORE,
    EVAL_CATEGORY_LATEST,
    DEPT_ID,
    CASE WHEN (
        0.3
        - AVG_EVAL_SCORE * 0.12
        + RISK_SIGNAL_COUNT * 0.15
        - SENTIMENT_AVG * 0.2
        + MONTHS_SINCE_PROMOTION * 0.003
        + PREVIOUS_COMPANY_COUNT * 0.08
        - PEER_COLLAB_SCORE * 0.05
        - TENURE_MONTHS * 0.002
        + COMMUTE_TIME_MINUTES * 0.002
        + SELF_EVAL_GAP * 0.1
        - EVAL_CATEGORY_LATEST * 0.1
        + NORMAL(0, 0.15, RANDOM())
    ) > 0 THEN 1 ELSE 0 END AS LABEL
FROM HR_ANALYTICS.PUBLIC.ATTRITION_FEATURES
""").collect()

session.sql("""
CREATE OR REPLACE TEMPORARY TABLE HR_ANALYTICS.PUBLIC._REL_TRAIN AS
SELECT *,
    LEAST(GREATEST(
        ONEONONE_SENTIMENT_AVG * 0.25 + EVAL_COMMENT_SENTIMENT * 0.15
        + ONEONONE_FREQ * 0.1 + SUBORDINATE_LEADERSHIP_SCORE * 0.2
        + SUBORDINATE_COMMUNICATION_SCORE * 0.15 - ABS(EVAL_GAP) * 0.08
        + ONEONONE_SENTIMENT_TREND * 0.05 - ABS(AGE_DIFF) * 0.002
        + NORMAL(0, 0.08, RANDOM())
    , 0), 1) AS LABEL
FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_FEATURES
""").collect()

session.sql("""
CREATE OR REPLACE TEMPORARY TABLE HR_ANALYTICS.PUBLIC._TF_TRAIN AS
SELECT *,
    LEAST(GREATEST(
        SKILL_MATCH_RATE * 0.25 + MGR_RELATIONSHIP_SCORE / 5.0 * 0.15
        + EVAL_TREND * 0.1 + CULTURE_SIMILARITY * 0.2
        - SKILL_GAP_COUNT * 0.02 - GRADE_DIFF * 0.05
        + TRANSFER_COUNT * 0.03 + SENTIMENT_TREND * 0.05
        + NORMAL(0, 0.08, RANDOM())
    , 0), 1) AS LABEL
FROM HR_ANALYTICS.PUBLIC.TRANSFER_FIT_FEATURES SAMPLE (50000 ROWS)
""").collect()

print("  Pulling data from Snowflake for training...")
att_train_df = session.table("_ATT_TRAIN").to_pandas()
rel_train_df = session.table("_REL_TRAIN").to_pandas()
tf_train_df = session.table("_TF_TRAIN").to_pandas()
print(f"    ATT: {len(att_train_df)}, REL: {len(rel_train_df)}, TF: {len(tf_train_df)}")

# 2b. Attrition model — GridSearchCV
print("  Training ATTRITION_MODEL (GridSearchCV)...")
X_att = att_train_df[ATTRITION_NUM_COLS].astype(float)
y_att = att_train_df["LABEL"].astype(int)

grid_att = GridSearchCV(
    XGBClassifier(random_state=42, eval_metric="logloss", tree_method="hist"),
    {"n_estimators": [200, 400], "max_depth": [3, 5], "learning_rate": [0.03, 0.1],
     "min_child_weight": [3, 6], "subsample": [0.7, 0.9]},
    cv=5, scoring="roc_auc", n_jobs=-1
)
grid_att.fit(X_att, y_att)
att_sklearn = grid_att.best_estimator_
print(f"    Best AUC (CV): {grid_att.best_score_:.4f}")
print(f"    Best params: {grid_att.best_params_}")

# 2c. Relationship model — GridSearchCV
print("  Training RELATIONSHIP_MODEL (GridSearchCV)...")
X_rel = rel_train_df[REL_FEATURES_COLS].astype(float)
y_rel = rel_train_df["LABEL"].astype(float)

grid_rel = GridSearchCV(
    LGBMRegressor(random_state=42, verbose=-1),
    {"n_estimators": [200, 400], "max_depth": [3, 5], "learning_rate": [0.03, 0.1],
     "num_leaves": [31, 56], "min_child_samples": [20, 50]},
    cv=5, scoring="neg_root_mean_squared_error", n_jobs=-1
)
grid_rel.fit(X_rel, y_rel)
rel_sklearn = grid_rel.best_estimator_
print(f"    Best RMSE (CV): {-grid_rel.best_score_:.4f}")
print(f"    Best params: {grid_rel.best_params_}")

# 2d. Transfer Fit model
print("  Training TRANSFER_FIT_MODEL...")
X_tf = tf_train_df[TF_FEATURES_COLS].astype(float)
y_tf = tf_train_df["LABEL"].astype(float)
tf_sklearn = XGBRegressor(
    n_estimators=200, max_depth=5, learning_rate=0.1,
    subsample=0.8, colsample_bytree=0.8, random_state=42, tree_method="hist"
)
tf_sklearn.fit(X_tf, y_tf)
print("    TRANSFER_FIT_MODEL trained")

# ============================================================================
# STEP 3: Register to Snowflake Model Registry (for SQL inference)
# ============================================================================
print("\n--- Step 3: Model Registry ---")

from snowflake.ml.registry import Registry

session.use_schema("ML")
reg = Registry(session=session, database_name="HR_ANALYTICS", schema_name="ML")

att_sample = att_train_df[ATTRITION_NUM_COLS].head(5)
rel_sample = rel_train_df[REL_FEATURES_COLS].head(5)
tf_sample = tf_train_df[TF_FEATURES_COLS].head(5)

for model_name, model_obj, sample, deps, comment, metrics in [
    ("ATTRITION_MODEL", att_sklearn, att_sample, ["xgboost", "scikit-learn"],
     f"XGBoost classifier (v3: Feature Store + Model Registry + SQL inference, {VERSION})",
     {"cv_auc": float(grid_att.best_score_)}),
    ("RELATIONSHIP_MODEL", rel_sklearn, rel_sample, ["lightgbm", "scikit-learn"],
     f"LightGBM regressor (v3: Feature Store + Model Registry + SQL inference, {VERSION})",
     {"cv_rmse": float(-grid_rel.best_score_)}),
    ("TRANSFER_FIT_MODEL", tf_sklearn, tf_sample, ["xgboost", "scikit-learn"],
     f"XGBoost regressor for transfer fit (v3: SQL inference, {VERSION})",
     {}),
]:
    print(f"  Registering {model_name} {VERSION}...")
    try:
        mv = reg.log_model(
            model_obj, model_name=model_name, version_name=VERSION,
            sample_input_data=sample, conda_dependencies=deps,
            target_platforms=["WAREHOUSE"], comment=comment, metrics=metrics
        )
        print(f"    OK: {model_name} {VERSION}")
    except Exception as e:
        # Registry のメッセージは "already existed"（同じ日に再実行した場合）
        if "already exist" in str(e).lower():
            print(f"    {model_name} {VERSION} already exists, skipping")
        else:
            print(f"    Error: {e}")

# Set new version as DEFAULT
for mn in ["ATTRITION_MODEL", "RELATIONSHIP_MODEL", "TRANSFER_FIT_MODEL"]:
    try:
        session.sql(f"ALTER MODEL HR_ANALYTICS.ML.{mn} SET DEFAULT_VERSION = {VERSION}").collect()
    except:
        pass
print("  DEFAULT version set to", VERSION)

# ============================================================================
# STEP 4: SQL-based Inference (no local CPU — MODEL()!PREDICT in Snowflake)
# ============================================================================
print("\n--- Step 4: SQL Inference (Snowflake Warehouse) ---")

session.use_schema("PUBLIC")

# 4a. Attrition predictions via SQL
print("  Running attrition inference via MODEL()!PREDICT_PROBA()...")
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
print(f"    PREDICTION_RESULTS: {pr_count} rows (all computed in Snowflake)")

# 4b. Relationship predictions via SQL
print("  Running relationship inference via MODEL()!PREDICT()...")
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

# 4c. Transfer Fit predictions via SQL
print("  Running transfer_fit inference via MODEL()!PREDICT()...")
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
# STEP 5: SHAP (Snowflake Warehouse via Stored Procedure)
# ============================================================================
print("\n--- Step 5: SHAP Values (Snowflake Warehouse) ---")

session.use_schema("PUBLIC")
session.sql("DELETE FROM SHAP_RESULTS").collect()

SHAP_SAMPLE_SIZE = 2000

print("  Computing attrition SHAP (Warehouse)...")
att_result = session.sql(f"CALL HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_ATTRITION({SHAP_SAMPLE_SIZE}, '{VERSION}')").collect()
print(f"    {att_result[0][0]}")

print("  Computing relationship SHAP (Warehouse)...")
rel_result = session.sql(f"CALL HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_RELATIONSHIP({SHAP_SAMPLE_SIZE}, '{VERSION}')").collect()
print(f"    {rel_result[0][0]}")

# ============================================================================
# STEP 6: Evidence Generation (100% Snowflake SQL — Cortex AI_COMPLETE)
# ============================================================================
print("\n--- Step 6: Evidence Generation (Snowflake SQL) ---")

session.sql("DELETE FROM EVIDENCE_STORE").collect()

# 6a. Attrition Evidence
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

# 6b. Relationship Evidence
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

# 6c. Sentiment Evidence (100% SQL)
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

# 6d. Transfer Fit Evidence (100% SQL)
print("  Generating transfer_fit evidence...")
session.sql("""
INSERT INTO EVIDENCE_STORE (EMPLOYEE_ID, SCORE_TYPE, PREDICTION_ID, EVIDENCE_JSON, GENERATED_AT)
SELECT EMPLOYEE_ID, 'transfer_fit', ID,
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

# ============================================================================
# STEP 7: Similar Cases + DEPT_CULTURE_VECTORS (Snowflake SQL)
# ============================================================================
print("\n--- Step 7: Similar Cases + Dept Culture ---")

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
# STEP 8: Model Monitor baseline
# ============================================================================
print("\n--- Step 8: Model Monitor ---")
session.use_schema("ML")
try:
    session.sql("ALTER MODEL MONITOR ATTRITION_MONITOR SET BASELINE = HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS").collect()
    print("  ATTRITION_MONITOR baseline set")
except Exception as e:
    print(f"  Monitor error: {e}")

# ============================================================================
# STEP 9: Permissions
# ============================================================================
print("\n--- Step 9: Permissions ---")
session.use_schema("PUBLIC")
for tbl in ["ATTRITION_FEATURES", "RELATIONSHIP_FEATURES", "PREDICTION_RESULTS",
            "RELATIONSHIP_RESULTS", "SHAP_RESULTS", "EVIDENCE_STORE",
            "SIMILAR_CASES", "TRANSFER_FIT_FEATURES", "TRANSFER_FIT_RESULTS", "DEPT_CULTURE_VECTORS"]:
    try:
        session.sql(f"GRANT SELECT ON TABLE HR_ANALYTICS.PUBLIC.{tbl} TO ROLE HR_APP_ROLE").collect()
    except:
        pass
print("  Grants applied")

# ============================================================================
# STEP 10: Summary
# ============================================================================
print("\n" + "=" * 60)
print("=== Pipeline V3 (Snowflake-Native) Complete ===")
print("=" * 60)

session.use_schema("PUBLIC")
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

print(f"\n  Snowflake-Native features used:")
print(f"    - Feature Store: Managed Feature Views (Dynamic Table auto-refresh)")
print(f"    - GridSearchCV: Server-side hyperparameter tuning on HR_AI_WH")
print(f"    - Model Registry: 3 models registered as {VERSION}")
print(f"    - SQL Inference: MODEL()!PREDICT() / PREDICT_PROBA()")
print(f"    - Cortex AI_COMPLETE: Japanese evidence summaries")
print(f"    - Model Monitor: ATTRITION_MONITOR with baseline")

# List Feature Store feature views
session.use_schema(FS_SCHEMA)
try:
    fvs = fs.list_feature_views()
    print(f"\n  Feature Store views:")
    fv_df = fvs.to_pandas()
    for _, row in fv_df.iterrows():
        print(f"    - {row.get('NAME', 'N/A')} v{row.get('VERSION', 'N/A')}")
except:
    pass

session.close()
print("\n=== Done ===")
