#!/usr/bin/env python3
"""
semantic_models/hr_semantic_view.yaml から Semantic View（HR_SEMANTIC_VIEW）を作る

ml_pipeline_v3.py の後に実行する（推論結果のテーブルを参照するため）。
  python3 scripts/create_semantic_view.py           # 作成
  python3 scripts/create_semantic_view.py --verify  # 作らずに検証だけ
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from session_util import create_session

YAML_PATH = Path(__file__).resolve().parent.parent / "semantic_models" / "hr_semantic_view.yaml"
TARGET_SCHEMA = "HR_ANALYTICS.PUBLIC"


def main():
    verify_only = "--verify" in sys.argv[1:]
    session = create_session()
    session.use_warehouse("HR_AI_WH")
    yaml_text = YAML_PATH.read_text(encoding="utf-8")
    # YAML はバインド変数で渡す（$$ 引用だと YAML 内の $ や ' の扱いに気を使うため）
    result = session.sql(
        "CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(?, ?, ?)",
        params=[TARGET_SCHEMA, yaml_text, verify_only],
    ).collect()
    print(result[0][0])
    if not verify_only:
        for role in ("HR_ADMIN_ROLE", "HR_MANAGER_ROLE", "HR_SERVICE_ROLE"):
            session.sql(
                f"GRANT SELECT ON SEMANTIC VIEW {TARGET_SCHEMA}.HR_SEMANTIC_VIEW TO ROLE {role}"
            ).collect()
        print("権限を付与しました")
    session.close()


if __name__ == "__main__":
    main()
