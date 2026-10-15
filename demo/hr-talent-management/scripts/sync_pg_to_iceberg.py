import os
import psycopg2
import snowflake.connector
import time

PG_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "dbname": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.environ["POSTGRES_USER"],
    "password": os.getenv("POSTGRES_PASSWORD"),
}

TABLES = {
    "departments": {
        "pg_cols": "dept_id, dept_name, dept_code, parent_dept_id, level, is_active, created_at::timestamp, updated_at::timestamp",
        "sf_cols": "DEPT_ID, DEPT_NAME, DEPT_CODE, PARENT_DEPT_ID, LEVEL, IS_ACTIVE, CREATED_AT, UPDATED_AT",
        "placeholders": 8,
    },
    "employees": {
        "pg_cols": "employee_id, employee_code, first_name, last_name, email, phone, hire_date, birth_date, gender, dept_id, position_id, manager_id, status, salary, created_at::timestamp, updated_at::timestamp, commute_time_minutes, employment_type, last_promotion_date, entry_type",
        "sf_cols": "EMPLOYEE_ID, EMPLOYEE_CODE, FIRST_NAME, LAST_NAME, EMAIL, PHONE, HIRE_DATE, BIRTH_DATE, GENDER, DEPT_ID, POSITION_ID, MANAGER_ID, STATUS, SALARY, CREATED_AT, UPDATED_AT, COMMUTE_TIME_MINUTES, EMPLOYMENT_TYPE, LAST_PROMOTION_DATE, ENTRY_TYPE",
        "placeholders": 20,
    },
    "positions": {
        "pg_cols": "position_id, title, dept_id, grade, required_skills::text, is_vacant, headcount, created_at::timestamp",
        "sf_cols": "POSITION_ID, TITLE, DEPT_ID, GRADE, REQUIRED_SKILLS, IS_VACANT, HEADCOUNT, CREATED_AT",
        "placeholders": 8,
        "variant_indices": [4],
    },
    "evaluations": {
        "pg_cols": "evaluation_id, employee_id, evaluator_id, period, score::float, grade, comment, self_comment, status, created_at::timestamp, updated_at::timestamp, self_score::float",
        "sf_cols": "EVALUATION_ID, EMPLOYEE_ID, EVALUATOR_ID, PERIOD, SCORE, GRADE, COMMENT, SELF_COMMENT, STATUS, CREATED_AT, UPDATED_AT, SELF_SCORE",
        "placeholders": 12,
    },
    "one_on_one_notes": {
        "pg_cols": "note_id, employee_id, manager_id, note_date, content, category, is_private, created_at::timestamp",
        "sf_cols": "NOTE_ID, EMPLOYEE_ID, MANAGER_ID, NOTE_DATE, CONTENT, CATEGORY, IS_PRIVATE, CREATED_AT",
        "placeholders": 8,
    },
    "skills": {
        "pg_cols": "skill_id, skill_name, category, created_at::timestamp",
        "sf_cols": "SKILL_ID, SKILL_NAME, CATEGORY, CREATED_AT",
        "placeholders": 4,
    },
    "employee_skills": {
        "pg_cols": "id, employee_id, skill_id, proficiency, certified_at, created_at::timestamp",
        "sf_cols": "ID, EMPLOYEE_ID, SKILL_ID, PROFICIENCY, CERTIFIED_AT, CREATED_AT",
        "placeholders": 6,
    },
    "transfer_requests": {
        "pg_cols": "request_id, employee_id, from_dept_id, to_dept_id, from_position_id, to_position_id, reason, status, requested_by, approved_by, requested_at::timestamp, resolved_at::timestamp",
        "sf_cols": "REQUEST_ID, EMPLOYEE_ID, FROM_DEPT_ID, TO_DEPT_ID, FROM_POSITION_ID, TO_POSITION_ID, REASON, STATUS, REQUESTED_BY, APPROVED_BY, REQUESTED_AT, RESOLVED_AT",
        "placeholders": 12,
    },
    "app_users": {
        "pg_cols": "user_id, username, password_hash, role, employee_id, array_to_json(dept_scope)::text, is_active, last_login_at::timestamp, created_at::timestamp",
        "sf_cols": "USER_ID, USERNAME, PASSWORD_HASH, ROLE, EMPLOYEE_ID, DEPT_SCOPE, IS_ACTIVE, LAST_LOGIN_AT, CREATED_AT",
        "placeholders": 9,
        "variant_indices": [5],
    },
    "leave_records": {
        "pg_cols": "leave_id, employee_id, leave_type, start_date, end_date, days::float, status, created_at::timestamp",
        "sf_cols": "LEAVE_ID, EMPLOYEE_ID, LEAVE_TYPE, START_DATE, END_DATE, DAYS, STATUS, CREATED_AT",
        "placeholders": 8,
    },
    "candidate_lists": {
        "pg_cols": "id, employee_id, list_name, created_by, created_at::timestamp",
        "sf_cols": "ID, EMPLOYEE_ID, LIST_NAME, CREATED_BY, CREATED_AT",
        "placeholders": 5,
    },
    "action_items": {
        "pg_cols": "action_id, employee_id, action_type, description, status, assigned_to, due_date, created_at::timestamp",
        "sf_cols": "ACTION_ID, EMPLOYEE_ID, ACTION_TYPE, DESCRIPTION, STATUS, ASSIGNED_TO, DUE_DATE, CREATED_AT",
        "placeholders": 8,
    },
    "simulation_sessions": {
        "pg_cols": "session_id, scenario_name, clone_db_name, created_by, status, created_at::timestamp, dropped_at::timestamp",
        "sf_cols": "SESSION_ID, SCENARIO_NAME, CLONE_DB_NAME, CREATED_BY, STATUS, CREATED_AT, DROPPED_AT",
        "placeholders": 7,
    },
    # ML の入力（scripts/generate_ml_inputs.py で作成）。配列・JSONB は JSON 文字列で渡す
    "career_history": {
        "pg_cols": "history_id, employee_id, dept_id, position_id, manager_id, start_date, end_date, transfer_type, reason, performance_after::float, created_at::timestamp",
        "sf_cols": "HISTORY_ID, EMPLOYEE_ID, DEPT_ID, POSITION_ID, MANAGER_ID, START_DATE, END_DATE, TRANSFER_TYPE, REASON, PERFORMANCE_AFTER, CREATED_AT",
        "placeholders": 11,
    },
    "employee_profiles": {
        "pg_cols": "employee_id, education_level, education_field, university, career_aspiration, strengths_self, array_to_json(preferred_dept_ids)::text, years_of_experience, previous_company_count, entry_type, updated_at::timestamp",
        "sf_cols": "EMPLOYEE_ID, EDUCATION_LEVEL, EDUCATION_FIELD, UNIVERSITY, CAREER_ASPIRATION, STRENGTHS_SELF, PREFERRED_DEPT_IDS, YEARS_OF_EXPERIENCE, PREVIOUS_COMPANY_COUNT, ENTRY_TYPE, UPDATED_AT",
        "placeholders": 11,
        "variant_indices": [6],
    },
    "peer_feedback": {
        "pg_cols": "feedback_id, employee_id, reviewer_id, reviewer_relation, period, leadership_score, collaboration_score, communication_score, expertise_score, comment, created_at::timestamp",
        "sf_cols": "FEEDBACK_ID, EMPLOYEE_ID, REVIEWER_ID, REVIEWER_RELATION, PERIOD, LEADERSHIP_SCORE, COLLABORATION_SCORE, COMMUNICATION_SCORE, EXPERTISE_SCORE, COMMENT, CREATED_AT",
        "placeholders": 11,
    },
    "oneonone_analysis": {
        "pg_cols": "analysis_id, note_id, employee_id, manager_id, sentiment_score::float, topics::text, array_to_json(concerns)::text, array_to_json(positive_signals)::text, array_to_json(key_phrases)::text, risk_signals::text, created_at::timestamp",
        "sf_cols": "ANALYSIS_ID, NOTE_ID, EMPLOYEE_ID, MANAGER_ID, SENTIMENT_SCORE, TOPICS, CONCERNS, POSITIVE_SIGNALS, KEY_PHRASES, RISK_SIGNALS, CREATED_AT",
        "placeholders": 11,
        "variant_indices": [5, 6, 7, 8, 9],
    },
    "evaluation_analysis": {
        "pg_cols": "analysis_id, evaluation_id, employee_id, sentiment_score::float, self_sentiment_score::float, sentiment_gap::float, array_to_json(extracted_strengths)::text, array_to_json(extracted_improvements)::text, array_to_json(extracted_career_signals)::text, category, created_at::timestamp",
        "sf_cols": "ANALYSIS_ID, EVALUATION_ID, EMPLOYEE_ID, SENTIMENT_SCORE, SELF_SENTIMENT_SCORE, SENTIMENT_GAP, EXTRACTED_STRENGTHS, EXTRACTED_IMPROVEMENTS, EXTRACTED_CAREER_SIGNALS, CATEGORY, CREATED_AT",
        "placeholders": 11,
        "variant_indices": [6, 7, 8],
    },
}

BATCH_SIZE = 5000


def build_batch_insert(table_name, conf, rows):
    """複数行を 1 回の INSERT にまとめる。

    PARSE_JSON は VALUES 句の中に書けないため、VARIANT 列があるテーブルも
    INSERT ... SELECT ... FROM VALUES の形でまとめて入れる。
    """
    variant_indices = set(conf.get("variant_indices", []))
    sf_cols = conf["sf_cols"]
    n_cols = len(sf_cols.split(","))

    all_params = []
    value_clauses = []
    for row in rows:
        value_clauses.append("(" + ", ".join(["%s"] * n_cols) + ")")
        all_params.extend(row)

    select_cols = ", ".join(
        f"PARSE_JSON(${i + 1})" if i in variant_indices else f"${i + 1}"
        for i in range(n_cols)
    )
    values_str = ",\n".join(value_clauses)
    sql = (
        f"INSERT INTO {table_name.upper()} ({sf_cols}) "
        f"SELECT {select_cols} FROM VALUES {values_str}"
    )
    return sql, all_params


def main():
    sf_conn = snowflake.connector.connect(
        connection_name=os.getenv("SNOWFLAKE_CONNECTION_NAME") or "default"
    )

    sf_cur = sf_conn.cursor()
    sf_cur.execute("USE ROLE SYSADMIN")
    sf_cur.execute("USE WAREHOUSE HR_APP_WH")
    sf_cur.execute("USE DATABASE HR_ANALYTICS")
    sf_cur.execute("USE SCHEMA STAGING")

    total_start = time.time()

    for table_name, conf in TABLES.items():
        t0 = time.time()
        # テーブルごとに接続し直す（Snowflake への書き込み中に接続が切れないように）
        pg_conn = psycopg2.connect(**PG_CONFIG)
        pg_cur = pg_conn.cursor()
        pg_cur.execute(f"SELECT {conf['pg_cols']} FROM hr.{table_name}")
        rows = pg_cur.fetchall()
        pg_conn.close()

        if not rows:
            print(f"  {table_name}: 0 rows (skip)")
            continue

        sf_cur.execute(f"DELETE FROM {table_name.upper()}")

        loaded = 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            sql, params = build_batch_insert(table_name, conf, batch)
            sf_cur.execute(sql, params)
            loaded += len(batch)

        elapsed = time.time() - t0
        print(f"  {table_name}: {loaded:,} rows ({elapsed:.1f}s)")

    total_elapsed = time.time() - total_start
    print(f"\nSync complete! ({total_elapsed:.0f}s total)")

    sf_cur.close()
    sf_conn.close()


if __name__ == "__main__":
    main()
