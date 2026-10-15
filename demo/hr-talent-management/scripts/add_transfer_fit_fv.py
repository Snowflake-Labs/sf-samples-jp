import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from session_util import create_session

session = create_session()
session.use_database("HR_ANALYTICS")
session.use_warehouse("HR_AI_WH")

from snowflake.ml.feature_store import FeatureStore, FeatureView, Entity, CreationMode
from datetime import datetime

VERSION = f"V{datetime.now().strftime('%Y%m%d')}"

fs = FeatureStore(
    session=session,
    database="HR_ANALYTICS",
    name="FEATURE_STORE",
    default_warehouse="HR_AI_WH",
    creation_mode=CreationMode.CREATE_IF_NOT_EXIST,
)

try:
    emp_pos_entity = Entity(name="EMP_POSITION", join_keys=["EMPLOYEE_ID", "TARGET_POSITION_ID"])
    fs.register_entity(emp_pos_entity)
    print("EMP_POSITION entity registered")
except Exception as e:
    if "already exists" in str(e).lower():
        emp_pos_entity = fs.get_entity("EMP_POSITION")
        print("EMP_POSITION entity already exists")
    else:
        raise e

tf_feature_df = session.sql("""
SELECT
    EMPLOYEE_ID,
    TARGET_POSITION_ID,
    SKILL_MATCH_RATE,
    SKILL_GAP_COUNT,
    TRANSFER_COUNT,
    TARGET_AVG_TENURE,
    MGR_RELATIONSHIP_SCORE,
    EVAL_TREND,
    CULTURE_SIMILARITY,
    GRADE_DIFF,
    AGE,
    SENTIMENT_TREND
FROM HR_ANALYTICS.PUBLIC.TRANSFER_FIT_FEATURES
""")

try:
    existing = fs.get_feature_view("TRANSFER_FIT_FEATURES_FV", VERSION)
    print(f"TRANSFER_FIT_FEATURES_FV {VERSION} already exists")
except:
    try:
        tf_fv = FeatureView(
            name="TRANSFER_FIT_FEATURES_FV",
            entities=[emp_pos_entity],
            feature_df=tf_feature_df,
            refresh_freq="1 day",
            desc="Transfer fit features: skill match, culture similarity, grade diff (auto-refresh daily)"
        )
        tf_fv = tf_fv.attach_feature_desc({
            "SKILL_MATCH_RATE": "Ratio of matched skills to required skills for target position",
            "SKILL_GAP_COUNT": "Number of missing skills for target position",
            "TRANSFER_COUNT": "Number of past transfers/promotions",
            "TARGET_AVG_TENURE": "Average tenure months in target department",
            "MGR_RELATIONSHIP_SCORE": "Relationship score with current manager",
            "EVAL_TREND": "Evaluation score regression slope",
            "CULTURE_SIMILARITY": "Department culture similarity score",
            "GRADE_DIFF": "Grade level difference between current and target",
            "AGE": "Employee age",
            "SENTIMENT_TREND": "Sentiment score regression slope from 1on1 notes",
        })
        registered = fs.register_feature_view(
            feature_view=tf_fv, version=VERSION, block=True, overwrite=False
        )
        print(f"TRANSFER_FIT_FEATURES_FV {VERSION} registered (Dynamic Table)")
    except Exception as e:
        print(f"Error: {e}")

fvs = fs.list_feature_views().to_pandas()
print(f"\nFeature Store views ({len(fvs)}):")
for _, row in fvs.iterrows():
    print(f"  - {row.get('NAME', 'N/A')} v{row.get('VERSION', 'N/A')}")

session.close()
print("Done")
