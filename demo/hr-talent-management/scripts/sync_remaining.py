#!/usr/bin/env python3
"""Sync only POSITIONS and APP_USERS to Snowflake STAGING"""
import os
import psycopg2
import snowflake.connector

PG_PASS = os.environ["POSTGRES_PASSWORD"]
PG_HOST = os.environ["POSTGRES_HOST"]

pg = psycopg2.connect(host=PG_HOST, port=5432, dbname="postgres", user=os.environ["POSTGRES_USER"], password=PG_PASS, sslmode="require")
sf = snowflake.connector.connect(connection_name=os.getenv("SNOWFLAKE_CONNECTION_NAME", "default"))
sc = sf.cursor()
sc.execute("USE ROLE SYSADMIN")
sc.execute("USE WAREHOUSE HR_APP_WH")
sc.execute("USE DATABASE HR_ANALYTICS")
sc.execute("USE SCHEMA STAGING")

# POSITIONS - no VARIANT, just insert with NULL for required_skills
print("POSITIONS sync...", flush=True)
sc.execute("DELETE FROM POSITIONS")
pc = pg.cursor()
pc.execute("SELECT position_id, title, dept_id, grade, is_vacant, headcount, created_at::timestamp FROM hr.positions")
rows = pc.fetchall()
pc.close()
print(f"  PG rows: {len(rows)}", flush=True)

BATCH = 1000
for i in range(0, len(rows), BATCH):
    batch = rows[i:i+BATCH]
    vals = []
    params = []
    for r in batch:
        vals.append("(%s, %s, %s, %s, NULL, %s, %s, %s)")
        params.extend([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])
    sql = f"INSERT INTO POSITIONS (POSITION_ID, TITLE, DEPT_ID, GRADE, REQUIRED_SKILLS, IS_VACANT, HEADCOUNT, CREATED_AT) VALUES {','.join(vals)}"
    sc.execute(sql, params)
    print(f"  ... {min(i+BATCH, len(rows))}/{len(rows)}", flush=True)

print(f"  POSITIONS: {len(rows)} rows loaded", flush=True)

# APP_USERS
print("APP_USERS sync...", flush=True)
sc.execute("DELETE FROM APP_USERS")
pc = pg.cursor()
pc.execute("SELECT user_id, username, password_hash, role, employee_id, array_to_json(dept_scope)::text, is_active, last_login_at::timestamp, created_at::timestamp FROM hr.app_users")
for r in pc.fetchall():
    parts = []
    p = []
    for i, v in enumerate(r):
        if i == 5:  # dept_scope VARIANT
            if v is None:
                parts.append("NULL")
            else:
                parts.append("PARSE_JSON(%s)")
                p.append(v)
        else:
            parts.append("%s")
            p.append(v)
    sc.execute(f"INSERT INTO APP_USERS (USER_ID, USERNAME, PASSWORD_HASH, ROLE, EMPLOYEE_ID, DEPT_SCOPE, IS_ACTIVE, LAST_LOGIN_AT, CREATED_AT) SELECT {','.join(parts)}", p)
pc.close()
print("  APP_USERS: done", flush=True)

sc.close()
sf.close()
pg.close()
print("Sync complete!", flush=True)
