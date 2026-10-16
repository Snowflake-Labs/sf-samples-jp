import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { getSession, isHonbuAllowed } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const honbu = searchParams.get("honbu") || "";
    const period = searchParams.get("period") || "";
    const drillDeptId = searchParams.get("drillDept") ? Number(searchParams.get("drillDept")) : null;

    const honbuNum = honbu ? Number(honbu) : null;

    if (honbuNum !== null && !isHonbuAllowed(session, honbuNum)) {
      return NextResponse.json({ error: "アクセス権限がありません" }, { status: 403 });
    }

    let pgDeptFilter = "";
    const pgDeptParams: unknown[] = [];
    let pgIdx = 1;
    if (honbuNum !== null) {
      pgDeptFilter = `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${pgIdx} OR parent_dept_id = $${pgIdx + 1})`;
      pgDeptParams.push(honbuNum, honbuNum);
      pgIdx += 2;
    }

    let evalPeriodClause: string;
    const evalParams: unknown[] = [];
    let evalIdx = 1;
    if (period) {
      evalPeriodClause = `ev.period = $${evalIdx++}`;
      evalParams.push(period);
    } else {
      evalPeriodClause = `ev.period = (SELECT MAX(period) FROM hr.evaluations)`;
    }
    let evalDeptFilter = "";
    if (honbuNum !== null) {
      evalDeptFilter = `AND ev.employee_id IN (SELECT employee_id FROM hr.employees WHERE dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${evalIdx} OR parent_dept_id = $${evalIdx + 1}))`;
      evalParams.push(honbuNum, honbuNum);
      evalIdx += 2;
    }

    const pgStatsPromise = pgQuery<Record<string, unknown>>(`
      WITH base AS (
        SELECT e.employee_id, e.gender, e.birth_date, e.hire_date, e.dept_id,
               e.position_id, d.dept_name, p.grade
        FROM hr.employees e
        JOIN hr.departments d ON e.dept_id = d.dept_id
        JOIN hr.positions p ON e.position_id = p.position_id
        WHERE e.status = 'active' ${pgDeptFilter}
      )
      SELECT
        (SELECT COUNT(*) FROM base) AS "headcount",
        (SELECT COUNT(*) FROM base WHERE gender = 'M') AS "male",
        (SELECT COUNT(*) FROM base WHERE gender = 'F') AS "female",
        (SELECT ROUND(AVG(EXTRACT(YEAR FROM AGE(CURRENT_DATE, hire_date)))::numeric, 1) FROM base) AS "avgTenure"
    `, pgDeptParams);

    let pgDeptDistPromise: Promise<{ DEPT_ID: number; DEPT_NAME: string; COUNT: string }[]>;
    let drillIsLeaf = false;

    if (drillDeptId) {
      const childCheck = await pgQuery<{ cnt: string }>(`SELECT COUNT(*)::int AS cnt FROM hr.departments WHERE parent_dept_id = $1`, [drillDeptId]);
      const hasChildren = Number(childCheck[0]?.cnt) > 0;

      if (hasChildren) {
        pgDeptDistPromise = pgQuery<{ DEPT_ID: number; DEPT_NAME: string; COUNT: string }>(`
          SELECT d.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME", COUNT(e.employee_id)::int AS "COUNT"
          FROM hr.employees e
          JOIN hr.departments d ON e.dept_id = d.dept_id
          JOIN hr.positions p ON e.position_id = p.position_id
          WHERE e.status = 'active'
            AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE parent_dept_id = $1)
          GROUP BY d.dept_id, d.dept_name ORDER BY "COUNT" DESC LIMIT 10
        `, [drillDeptId]);
      } else {
        drillIsLeaf = true;
        pgDeptDistPromise = pgQuery<{ DEPT_ID: number; DEPT_NAME: string; COUNT: string }>(`
          SELECT 0 AS "DEPT_ID", p.grade AS "DEPT_NAME", COUNT(*)::int AS "COUNT"
          FROM hr.employees e
          JOIN hr.positions p ON e.position_id = p.position_id
          WHERE e.status = 'active' AND e.dept_id = $1
          GROUP BY p.grade ORDER BY "COUNT" DESC
        `, [drillDeptId]);
      }
    } else {
      pgDeptDistPromise = pgQuery<{ DEPT_ID: number; DEPT_NAME: string; COUNT: string }>(`
        SELECT d.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME", COUNT(e.employee_id)::int AS "COUNT"
        FROM hr.employees e
        JOIN hr.departments d ON e.dept_id = d.dept_id
        JOIN hr.positions p ON e.position_id = p.position_id
        WHERE e.status = 'active' ${pgDeptFilter}
        GROUP BY d.dept_id, d.dept_name ORDER BY "COUNT" DESC LIMIT 10
      `, pgDeptParams);
    }

    const pgGradeDistPromise = pgQuery<{ GRADE: string; COUNT: string }>(`
      SELECT p.grade AS "GRADE", COUNT(*)::int AS "COUNT"
      FROM hr.employees e
      JOIN hr.positions p ON e.position_id = p.position_id
      WHERE e.status = 'active' ${pgDeptFilter}
      GROUP BY p.grade ORDER BY p.grade
    `, pgDeptParams);

    const pgAgeDistPromise = pgQuery<{ AGE_BUCKET: string; COUNT: string }>(`
      SELECT
        CASE
          WHEN EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date)) < 30 THEN '20代'
          WHEN EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date)) < 40 THEN '30代'
          WHEN EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date)) < 50 THEN '40代'
          WHEN EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date)) < 60 THEN '50代'
          ELSE '60代'
        END AS "AGE_BUCKET",
        COUNT(*)::int AS "COUNT"
      FROM hr.employees e
      WHERE e.status = 'active' ${pgDeptFilter} AND e.birth_date IS NOT NULL
      GROUP BY "AGE_BUCKET" ORDER BY "AGE_BUCKET"
    `, pgDeptParams);

    const pgEvalDistPromise = pgQuery<{ GRADE: string; COUNT: string }>(`
      SELECT ev.grade AS "GRADE", COUNT(*)::int AS "COUNT"
      FROM hr.evaluations ev
      WHERE ${evalPeriodClause} ${evalDeptFilter}
      GROUP BY ev.grade
    `, evalParams);

    const evalParamsForRecent = period ? [period] : [];
    let recentEvalPeriodClause = period ? `ev.period = $1` : `ev.period = (SELECT MAX(period) FROM hr.evaluations)`;
    let recentEvalDeptFilter = "";
    const recentParams: unknown[] = [...evalParamsForRecent];
    let recentIdx = recentParams.length + 1;
    if (honbuNum !== null) {
      recentEvalDeptFilter = `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${recentIdx} OR parent_dept_id = $${recentIdx + 1})`;
      recentParams.push(honbuNum, honbuNum);
      recentIdx += 2;
    }

    const pgRecentEvalsPromise = pgQuery<Record<string, unknown>>(`
      SELECT ev.employee_id AS "EMPLOYEE_ID", e.last_name || e.first_name AS "NAME",
        ev.period AS "PERIOD", ev.score AS "SCORE", ev.grade AS "GRADE", d.dept_name AS "DEPT_NAME"
      FROM hr.evaluations ev
      JOIN hr.employees e ON ev.employee_id = e.employee_id
      JOIN hr.departments d ON e.dept_id = d.dept_id
      WHERE ${recentEvalPeriodClause} ${recentEvalDeptFilter}
      ORDER BY ev.score DESC LIMIT 10
    `, recentParams);

    const dataPath = await getDataPath();

    const sfDeptBinds = honbuNum !== null ? [honbuNum, honbuNum] : [];
    const sfDeptFilter = honbuNum !== null
      ? `AND e.DEPT_ID IN (SELECT DEPT_ID FROM HR_ANALYTICS.STAGING.DEPARTMENTS WHERE DEPT_ID = ? OR PARENT_DEPT_ID = ?)`
      : "";

    type AlertRow = { EMPLOYEE_ID: number; NAME: string; DEPT_NAME: string; GRADE: string; RISK_SCORE: number; RISK_LABEL: string };

    const attritionPromise: Promise<AlertRow[]> = dataPath === "pg_lake"
      ? pgQuery<AlertRow>(`
          SELECT pr.employee_id AS "EMPLOYEE_ID", e.last_name || e.first_name AS "NAME",
            d.dept_name AS "DEPT_NAME", p.grade AS "GRADE",
            pr.risk_score AS "RISK_SCORE", pr.risk_label AS "RISK_LABEL"
          FROM hr_lake.prediction_results pr
          JOIN hr.employees e ON pr.employee_id = e.employee_id
          JOIN hr.departments d ON e.dept_id = d.dept_id
          JOIN hr.positions p ON e.position_id = p.position_id
          WHERE pr.risk_label IN ('high', 'medium') AND e.status = 'active'
            ${honbuNum !== null ? `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $1)` : ""}
          ORDER BY pr.risk_score DESC LIMIT 5
        `, honbuNum !== null ? [honbuNum] : [])
      : query<AlertRow>(`
          SELECT pr.EMPLOYEE_ID, e.LAST_NAME || e.FIRST_NAME AS NAME,
            d.DEPT_NAME, p.GRADE, pr.RISK_SCORE, pr.RISK_LABEL
          FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr
          JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON pr.EMPLOYEE_ID = e.EMPLOYEE_ID
          JOIN HR_ANALYTICS.STAGING.DEPARTMENTS d ON e.DEPT_ID = d.DEPT_ID
          JOIN HR_ANALYTICS.STAGING.POSITIONS p ON e.POSITION_ID = p.POSITION_ID
          WHERE pr.RISK_LABEL IN ('high', 'medium') AND e.STATUS = 'active' ${sfDeptFilter}
          ORDER BY pr.RISK_SCORE DESC LIMIT 5
        `, sfDeptBinds as Binds);

    const [statsRow, deptDist, gradeDist, ageDist, evalDist, recentEvals, attritionAlerts] = await Promise.all([
      pgStatsPromise, pgDeptDistPromise, pgGradeDistPromise, pgAgeDistPromise,
      pgEvalDistPromise, pgRecentEvalsPromise, attritionPromise,
    ]);

    const stats = statsRow[0] || {};

    return NextResponse.json({
      headcount: Number(stats.headcount) || 0,
      genderRatio: { male: Number(stats.male) || 0, female: Number(stats.female) || 0 },
      avgTenure: Number(stats.avgTenure) || 0,
      deptDistribution: deptDist,
      gradeDistribution: gradeDist,
      evalDistribution: evalDist,
      ageDistribution: ageDist,
      recentEvals,
      attritionAlerts,
      ...(drillDeptId ? { drillIsLeaf } : {}),
    });
  } catch (error) {
    console.error("Dashboard error:", error);
    return NextResponse.json({ error: "Failed to fetch dashboard" }, { status: 500 });
  }
}
