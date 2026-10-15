import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { getSession } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

async function viaSf(honbuNum: number | null) {
  const deptFilter = honbuNum !== null
    ? `AND e.DEPT_ID IN (SELECT DEPT_ID FROM HR_ANALYTICS.STAGING.DEPARTMENTS WHERE DEPT_ID = ? OR PARENT_DEPT_ID = ?)`
    : "";
  const binds: number[] = honbuNum !== null ? [honbuNum, honbuNum] : [];

  const rows = await query<{
    DEPT_ID: number; DEPT_NAME: string; PARENT_DEPT_ID: number | null;
    PAIR_COUNT: number; AVG_SCORE: number;
    GOOD_COUNT: number; WARN_COUNT: number; ALERT_COUNT: number;
  }>(`
    SELECT d.DEPT_ID, d.DEPT_NAME, d.PARENT_DEPT_ID,
      COUNT(*) AS PAIR_COUNT,
      ROUND(AVG(rr.RELATIONSHIP_SCORE), 3) AS AVG_SCORE,
      SUM(CASE WHEN rr.RELATIONSHIP_SCORE >= 0.6 THEN 1 ELSE 0 END) AS GOOD_COUNT,
      SUM(CASE WHEN rr.RELATIONSHIP_SCORE >= 0.3 AND rr.RELATIONSHIP_SCORE < 0.6 THEN 1 ELSE 0 END) AS WARN_COUNT,
      SUM(CASE WHEN rr.RELATIONSHIP_SCORE < 0.3 THEN 1 ELSE 0 END) AS ALERT_COUNT
    FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS rr
    JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON rr.EMPLOYEE_ID = e.EMPLOYEE_ID
    JOIN HR_ANALYTICS.STAGING.DEPARTMENTS d ON e.DEPT_ID = d.DEPT_ID
    WHERE e.STATUS = 'active' ${deptFilter}
    GROUP BY d.DEPT_ID, d.DEPT_NAME, d.PARENT_DEPT_ID
    HAVING COUNT(*) >= 3
    ORDER BY AVG_SCORE ASC
  `, binds as Binds);

  const alertPairs = await query<{
    MANAGER_NAME: string; EMPLOYEE_NAME: string; DEPT_NAME: string;
    RELATIONSHIP_SCORE: number;
    ONEONONE_FREQ: number | null; ONEONONE_SENTIMENT_AVG: number | null;
    EVAL_COMMENT_SENTIMENT: number | null; EVAL_GAP: number | null;
    PAIR_TENURE_MONTHS: number | null; SPAN_OF_CONTROL: number | null;
  }>(`
    SELECT
      m.LAST_NAME || m.FIRST_NAME AS MANAGER_NAME,
      e.LAST_NAME || e.FIRST_NAME AS EMPLOYEE_NAME,
      d.DEPT_NAME, rr.RELATIONSHIP_SCORE,
      rf.ONEONONE_FREQ, rf.ONEONONE_SENTIMENT_AVG,
      rf.EVAL_COMMENT_SENTIMENT, rf.EVAL_GAP,
      rf.PAIR_TENURE_MONTHS, rf.SPAN_OF_CONTROL
    FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS rr
    JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON rr.EMPLOYEE_ID = e.EMPLOYEE_ID
    JOIN HR_ANALYTICS.STAGING.EMPLOYEES m ON rr.MANAGER_ID = m.EMPLOYEE_ID
    JOIN HR_ANALYTICS.STAGING.DEPARTMENTS d ON e.DEPT_ID = d.DEPT_ID
    LEFT JOIN HR_ANALYTICS.PUBLIC.RELATIONSHIP_FEATURES rf
      ON rr.EMPLOYEE_ID = rf.EMPLOYEE_ID AND rr.MANAGER_ID = rf.MANAGER_ID
    WHERE e.STATUS = 'active' AND rr.RELATIONSHIP_SCORE < 0.3 ${deptFilter}
    ORDER BY rr.RELATIONSHIP_SCORE ASC LIMIT 10
  `, binds as Binds);

  return { rows, alertPairs };
}

async function viaPgLake(honbuNum: number | null) {
  const deptFilter = honbuNum !== null
    ? `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $1)`
    : "";
  const params = honbuNum !== null ? [honbuNum] : [];

  const rows = await pgQuery<{
    DEPT_ID: number; DEPT_NAME: string; PARENT_DEPT_ID: number | null;
    PAIR_COUNT: number; AVG_SCORE: number;
    GOOD_COUNT: number; WARN_COUNT: number; ALERT_COUNT: number;
  }>(`
    SELECT d.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME", d.parent_dept_id AS "PARENT_DEPT_ID",
      COUNT(*)::int AS "PAIR_COUNT",
      ROUND(AVG(rr.relationship_score)::numeric, 3)::float AS "AVG_SCORE",
      SUM(CASE WHEN rr.relationship_score >= 0.6 THEN 1 ELSE 0 END)::int AS "GOOD_COUNT",
      SUM(CASE WHEN rr.relationship_score >= 0.3 AND rr.relationship_score < 0.6 THEN 1 ELSE 0 END)::int AS "WARN_COUNT",
      SUM(CASE WHEN rr.relationship_score < 0.3 THEN 1 ELSE 0 END)::int AS "ALERT_COUNT"
    FROM hr_lake.relationship_results rr
    JOIN hr.employees e ON rr.employee_id = e.employee_id
    JOIN hr.departments d ON e.dept_id = d.dept_id
    WHERE e.status = 'active' ${deptFilter}
    GROUP BY d.dept_id, d.dept_name, d.parent_dept_id
    HAVING COUNT(*) >= 3
    ORDER BY "AVG_SCORE" ASC
  `, params);

  const alertPairs = await pgQuery<{
    MANAGER_NAME: string; EMPLOYEE_NAME: string; DEPT_NAME: string;
    RELATIONSHIP_SCORE: number;
    ONEONONE_FREQ: number | null; ONEONONE_SENTIMENT_AVG: number | null;
    EVAL_COMMENT_SENTIMENT: number | null; EVAL_GAP: number | null;
    PAIR_TENURE_MONTHS: number | null; SPAN_OF_CONTROL: number | null;
  }>(`
    SELECT
      m.last_name || m.first_name AS "MANAGER_NAME",
      e.last_name || e.first_name AS "EMPLOYEE_NAME",
      d.dept_name AS "DEPT_NAME",
      rr.relationship_score AS "RELATIONSHIP_SCORE",
      NULL::float AS "ONEONONE_FREQ", NULL::float AS "ONEONONE_SENTIMENT_AVG",
      NULL::float AS "EVAL_COMMENT_SENTIMENT", NULL::float AS "EVAL_GAP",
      NULL::float AS "PAIR_TENURE_MONTHS", NULL::float AS "SPAN_OF_CONTROL"
    FROM hr_lake.relationship_results rr
    JOIN hr.employees e ON rr.employee_id = e.employee_id
    JOIN hr.employees m ON rr.manager_id = m.employee_id
    JOIN hr.departments d ON e.dept_id = d.dept_id
    WHERE e.status = 'active' AND rr.relationship_score < 0.3 ${deptFilter}
    ORDER BY rr.relationship_score ASC LIMIT 10
  `, params);

  return { rows, alertPairs };
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const honbu = searchParams.get("honbu") || "";
    const honbuNum = honbu ? Number(honbu) : null;

    const dataPath = await getDataPath();
    const t0 = performance.now();

    const { rows, alertPairs } = dataPath === "pg_lake"
      ? await viaPgLake(honbuNum)
      : await viaSf(honbuNum);

    const ms = Math.round(performance.now() - t0);

    return NextResponse.json({ departments: rows, alertPairs, _meta: { dataPath, ms } });
  } catch (error) {
    console.error("Heatmap error:", error);
    return NextResponse.json({ error: "Failed to fetch heatmap" }, { status: 500 });
  }
}
