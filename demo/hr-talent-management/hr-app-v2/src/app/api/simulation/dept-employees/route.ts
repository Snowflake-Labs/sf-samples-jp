import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { getSession } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const deptId = searchParams.get("dept_id");

    if (!deptId) {
      return NextResponse.json({ error: "dept_id is required" }, { status: 400 });
    }
    const grade = searchParams.get("grade");
    const dId = Number(deptId);
    if (isNaN(dId)) {
      return NextResponse.json({ error: "Invalid dept_id" }, { status: 400 });
    }

    const dataPath = await getDataPath();
    const t0 = performance.now();

    const pgRowsPromise = pgQuery<{
      EMPLOYEE_ID: number; NAME: string; GRADE: string; POSITION_TITLE: string;
      TENURE_YEARS: number; AVG_EVAL: number; SKILL_COUNT: number;
    }>(`
      SELECT e.employee_id AS "EMPLOYEE_ID",
        e.last_name || e.first_name AS "NAME",
        p.grade AS "GRADE", p.title AS "POSITION_TITLE",
        EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE_YEARS",
        COALESCE(ev.avg_score, 0)::float AS "AVG_EVAL",
        COALESCE(sk.skill_count, 0)::int AS "SKILL_COUNT"
      FROM hr.employees e
      JOIN hr.positions p ON e.position_id = p.position_id
      LEFT JOIN (
        SELECT employee_id, ROUND(AVG(score)::numeric, 2)::float AS avg_score
        FROM hr.evaluations GROUP BY employee_id
      ) ev ON ev.employee_id = e.employee_id
      LEFT JOIN (
        SELECT employee_id, COUNT(*)::int AS skill_count
        FROM hr.employee_skills GROUP BY employee_id
      ) sk ON sk.employee_id = e.employee_id
      WHERE e.dept_id = $1 AND e.status = 'active'${grade ? ` AND p.grade = $2` : ''}
      ORDER BY CASE p.grade
        WHEN 'E1' THEN 1 WHEN 'D1' THEN 2 WHEN 'D2' THEN 3
        WHEN 'M1' THEN 4 WHEN 'M2' THEN 5 WHEN 'S1' THEN 6
        WHEN 'S2' THEN 7 WHEN 'J1' THEN 8 WHEN 'J2' THEN 9
        WHEN 'J3' THEN 10 ELSE 99 END,
        ev.avg_score DESC NULLS LAST
    `, grade ? [dId, grade] : [dId]);

    const riskPromise: Promise<{ EMPLOYEE_ID: number; RISK_SCORE: number; RISK_LABEL: string }[]> = dataPath === "pg_lake"
      ? pgQuery(`
          SELECT pr.employee_id AS "EMPLOYEE_ID", pr.risk_score AS "RISK_SCORE", pr.risk_label AS "RISK_LABEL"
          FROM hr_lake.prediction_results pr
          JOIN hr.employees e ON pr.employee_id = e.employee_id
          JOIN hr.positions p ON e.position_id = p.position_id
          WHERE e.dept_id = $1 AND e.status = 'active'${grade ? ` AND p.grade = $2` : ''}
        `, grade ? [dId, grade] : [dId])
      : query<{ EMPLOYEE_ID: number; RISK_SCORE: number; RISK_LABEL: string }>(
          grade
            ? `SELECT EMPLOYEE_ID, RISK_SCORE, RISK_LABEL
               FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS
               WHERE EMPLOYEE_ID IN (
                 SELECT e.EMPLOYEE_ID FROM HR_ANALYTICS.STAGING.EMPLOYEES e
                 JOIN HR_ANALYTICS.STAGING.POSITIONS p ON e.POSITION_ID = p.POSITION_ID
                 WHERE e.DEPT_ID = ? AND e.STATUS = 'active' AND p.GRADE = ?
               )`
            : `SELECT EMPLOYEE_ID, RISK_SCORE, RISK_LABEL
               FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS
               WHERE EMPLOYEE_ID IN (
                 SELECT EMPLOYEE_ID FROM HR_ANALYTICS.STAGING.EMPLOYEES
                 WHERE DEPT_ID = ? AND STATUS = 'active'
               )`,
          grade ? [dId, grade] as Binds : [dId] as Binds
        );

    const [pgRows, sfRows] = await Promise.all([pgRowsPromise, riskPromise]);
    const ms = Math.round(performance.now() - t0);

    const riskMap = new Map<number, { RISK_SCORE: number; RISK_LABEL: string }>();
    for (const r of sfRows) {
      riskMap.set(r.EMPLOYEE_ID, { RISK_SCORE: r.RISK_SCORE, RISK_LABEL: r.RISK_LABEL });
    }

    const employees = pgRows.map((row) => {
      const risk = riskMap.get(row.EMPLOYEE_ID);
      return {
        ...row,
        RISK_SCORE: risk?.RISK_SCORE ?? null,
        RISK_LABEL: risk?.RISK_LABEL ?? null,
      };
    });

    return NextResponse.json(employees);
  } catch (error) {
    console.error("Dept employees error:", error);
    return NextResponse.json({ error: "Failed to fetch department employees" }, { status: 500 });
  }
}
