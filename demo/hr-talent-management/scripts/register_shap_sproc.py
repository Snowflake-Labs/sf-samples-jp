"""
Register SHAP Stored Procedures in Snowflake.

Creates two stored procedures that run SHAP calculations on Snowflake Warehouse
instead of local CPU:
  - HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_ATTRITION(sample_size INT, model_version VARCHAR)  -- sample_size <= 0 で全員分
  - HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_RELATIONSHIP(sample_size INT, model_version VARCHAR)

Usage:
    SNOWFLAKE_CONNECTION_NAME=$SNOWFLAKE_CONNECTION_NAME python3 scripts/register_shap_sproc.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from session_util import create_session
from snowflake.snowpark import Session
from snowflake.snowpark.types import IntegerType, StringType

CONNECTION = os.getenv("SNOWFLAKE_CONNECTION_NAME") or "default"
session = create_session(connection_name=CONNECTION)
session.use_database("HR_ANALYTICS")
session.use_warehouse("HR_AI_WH")
session.use_schema("PUBLIC")

ATTRITION_COLS = [
    "TENURE_MONTHS", "AVG_EVAL_SCORE", "EVAL_TREND",
    "RISK_SIGNAL_COUNT", "CAREER_CHANGE_COUNT", "SENTIMENT_AVG", "SENTIMENT_TREND",
    "MONTHS_SINCE_PROMOTION", "TEAM_SIZE", "PREVIOUS_COMPANY_COUNT",
    "COMMUTE_TIME_MINUTES", "SELF_EVAL_GAP", "PEER_COLLAB_SCORE", "EVAL_CATEGORY_LATEST"
]
REL_COLS = [
    "ONEONONE_FREQ", "ONEONONE_SENTIMENT_AVG", "ONEONONE_SENTIMENT_TREND",
    "EVAL_COMMENT_SENTIMENT", "EVAL_SCORE_TREND", "EVAL_GAP",
    "PAIR_TENURE_MONTHS", "SPAN_OF_CONTROL", "AGE_DIFF",
    "SUBORDINATE_LEADERSHIP_SCORE", "SUBORDINATE_COMMUNICATION_SCORE"
]


def compute_shap_attrition(session: Session, sample_size: int, model_version: str) -> str:
    import shap
    import pandas as pd
    from snowflake.ml.registry import Registry

    feature_cols = [
        "TENURE_MONTHS", "AVG_EVAL_SCORE", "EVAL_TREND",
        "RISK_SIGNAL_COUNT", "CAREER_CHANGE_COUNT", "SENTIMENT_AVG", "SENTIMENT_TREND",
        "MONTHS_SINCE_PROMOTION", "TEAM_SIZE", "PREVIOUS_COMPANY_COUNT",
        "COMMUTE_TIME_MINUTES", "SELF_EVAL_GAP", "PEER_COLLAB_SCORE", "EVAL_CATEGORY_LATEST"
    ]

    reg = Registry(session=session, database_name="HR_ANALYTICS", schema_name="ML")
    model_ref = reg.get_model("ATTRITION_MODEL").version(model_version)
    native_model = model_ref.load(force=True)

    # sample_size <= 0 なら全員分。CSV や詳細画面の「主要因」は全員に必要なので、離職予測は全件で計算する
    feat_tbl = session.table("HR_ANALYTICS.PUBLIC.ATTRITION_FEATURES")
    feat_df = (feat_tbl if sample_size <= 0 else feat_tbl.sample(n=sample_size)).to_pandas()
    X = feat_df[feature_cols].astype(float)

    explainer = shap.TreeExplainer(native_model)
    shap_vals = explainer.shap_values(X)

    pred_ids = session.sql("SELECT ID, EMPLOYEE_ID FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS").to_pandas()
    eid_to_pid = dict(zip(pred_ids["EMPLOYEE_ID"], pred_ids["ID"]))

    rows = []
    for idx in range(len(X)):
        eid = int(feat_df.iloc[idx]["EMPLOYEE_ID"])
        pid = eid_to_pid.get(eid)
        if pid is None:
            continue
        for fi, feat in enumerate(feature_cols):
            rows.append({
                "PREDICTION_ID": int(pid), "MODEL_TYPE": "attrition",
                "FEATURE_NAME": feat,
                "SHAP_VALUE": float(shap_vals[idx][fi]),
                "FEATURE_VALUE": float(X.iloc[idx, fi])
            })

    if rows:
        sp_df = session.create_dataframe(pd.DataFrame(rows))
        sp_df.write.mode("append").save_as_table("HR_ANALYTICS.PUBLIC.SHAP_RESULTS", column_order="name")

    return f"attrition SHAP: {len(rows)} rows"


def compute_shap_relationship(session: Session, sample_size: int, model_version: str) -> str:
    import shap
    import pandas as pd
    from snowflake.ml.registry import Registry

    feature_cols = [
        "ONEONONE_FREQ", "ONEONONE_SENTIMENT_AVG", "ONEONONE_SENTIMENT_TREND",
        "EVAL_COMMENT_SENTIMENT", "EVAL_SCORE_TREND", "EVAL_GAP",
        "PAIR_TENURE_MONTHS", "SPAN_OF_CONTROL", "AGE_DIFF",
        "SUBORDINATE_LEADERSHIP_SCORE", "SUBORDINATE_COMMUNICATION_SCORE"
    ]

    reg = Registry(session=session, database_name="HR_ANALYTICS", schema_name="ML")
    model_ref = reg.get_model("RELATIONSHIP_MODEL").version(model_version)
    native_model = model_ref.load(force=True)

    feat_df = session.table("HR_ANALYTICS.PUBLIC.RELATIONSHIP_FEATURES").sample(n=sample_size).to_pandas()
    X = feat_df[feature_cols].astype(float)

    explainer = shap.TreeExplainer(native_model)
    shap_vals = explainer.shap_values(X)

    pred_ids = session.sql("SELECT ID, EMPLOYEE_ID, MANAGER_ID FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS").to_pandas()
    em_to_rid = {}
    for _, row in pred_ids.iterrows():
        em_to_rid[(int(row["EMPLOYEE_ID"]), int(row["MANAGER_ID"]))] = int(row["ID"])

    rows = []
    for idx in range(len(X)):
        eid = int(feat_df.iloc[idx]["EMPLOYEE_ID"])
        mid = int(feat_df.iloc[idx]["MANAGER_ID"])
        pid = em_to_rid.get((eid, mid))
        if pid is None:
            continue
        for fi, feat in enumerate(feature_cols):
            rows.append({
                "PREDICTION_ID": int(pid), "MODEL_TYPE": "relationship",
                "FEATURE_NAME": feat,
                "SHAP_VALUE": float(shap_vals[idx][fi]),
                "FEATURE_VALUE": float(X.iloc[idx, fi])
            })

    if rows:
        sp_df = session.create_dataframe(pd.DataFrame(rows))
        sp_df.write.mode("append").save_as_table("HR_ANALYTICS.PUBLIC.SHAP_RESULTS", column_order="name")

    return f"relationship SHAP: {len(rows)} rows"


print("Registering COMPUTE_SHAP_ATTRITION stored procedure...")
session.sproc.register(
    func=compute_shap_attrition,
    name="HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_ATTRITION",
    input_types=[IntegerType(), StringType()],
    return_type=StringType(),
    packages=["snowflake-snowpark-python", "snowflake-ml-python", "shap", "xgboost", "scikit-learn", "pandas"],
    is_permanent=True,
    stage_location="@HR_ANALYTICS.PUBLIC.ML_SPROC_STAGE",
    replace=True,
    execute_as="CALLER",
)
print("  OK: COMPUTE_SHAP_ATTRITION")

print("Registering COMPUTE_SHAP_RELATIONSHIP stored procedure...")
session.sproc.register(
    func=compute_shap_relationship,
    name="HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_RELATIONSHIP",
    input_types=[IntegerType(), StringType()],
    return_type=StringType(),
    packages=["snowflake-snowpark-python", "snowflake-ml-python", "shap", "lightgbm", "scikit-learn", "pandas"],
    is_permanent=True,
    stage_location="@HR_ANALYTICS.PUBLIC.ML_SPROC_STAGE",
    replace=True,
    execute_as="CALLER",
)
print("  OK: COMPUTE_SHAP_RELATIONSHIP")

print("\nGranting execute to HR_APP_ROLE...")
try:
    session.sql("GRANT USAGE ON PROCEDURE HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_ATTRITION(INT, VARCHAR) TO ROLE HR_APP_ROLE").collect()
    session.sql("GRANT USAGE ON PROCEDURE HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_RELATIONSHIP(INT, VARCHAR) TO ROLE HR_APP_ROLE").collect()
    print("  Grants applied")
except Exception as e:
    print(f"  Grant skipped (HR_APP_ROLE may not exist): {e}")

session.close()
print("\n=== Stored Procedures registered ===")
print("Usage:")
print("  CALL HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_ATTRITION(0, 'V20260315');  -- 0 = 全員分")
print("  CALL HR_ANALYTICS.PUBLIC.COMPUTE_SHAP_RELATIONSHIP(2000, 'V20260315');")
