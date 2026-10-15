import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { getSession } from "@/lib/session";
import { resolveHonbuScope } from "@/lib/scope";
import type { Binds } from "snowflake-sdk";

async function viaSf(honbuIds: number[] | null, limit: number, offset: number) {
  const marks = honbuIds ? honbuIds.map(() => "?").join(",") : "";
  const sfDeptBinds = honbuIds ? [...honbuIds, ...honbuIds] : [];
  const sfDeptFilter = honbuIds
    ? `AND e.DEPT_ID IN (SELECT DEPT_ID FROM HR_ANALYTICS.STAGING.DEPARTMENTS WHERE DEPT_ID IN (${marks}) OR PARENT_DEPT_ID IN (${marks}))`
    : "";

  const [predictions, totalRes, riskDist] = await Promise.all([
    query<{
      EMPLOYEE_ID: number; RISK_SCORE: number; RISK_LABEL: string; MODEL_VERSION: string;
      LAST_NAME: string; FIRST_NAME: string; DEPT_NAME: string; POSITION_TITLE: string;
      GRADE: string; TENURE_YEARS: number;
    }>(`
      SELECT pr.EMPLOYEE_ID, pr.RISK_SCORE, pr.RISK_LABEL, pr.MODEL_VERSION,
        e.LAST_NAME, e.FIRST_NAME, d.DEPT_NAME, p.TITLE AS POSITION_TITLE, p.GRADE,
        DATEDIFF('year', e.HIRE_DATE, CURRENT_DATE()) AS TENURE_YEARS
      FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr
      JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON pr.EMPLOYEE_ID = e.EMPLOYEE_ID
      JOIN HR_ANALYTICS.STAGING.DEPARTMENTS d ON e.DEPT_ID = d.DEPT_ID
      JOIN HR_ANALYTICS.STAGING.POSITIONS p ON e.POSITION_ID = p.POSITION_ID
      WHERE e.STATUS = 'active' ${sfDeptFilter}
      ORDER BY pr.RISK_SCORE DESC
      LIMIT ? OFFSET ?
    `, [...sfDeptBinds, limit, offset] as Binds),

    query<{ CNT: number }>(`
      SELECT COUNT(*) AS CNT
      FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr
      JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON pr.EMPLOYEE_ID = e.EMPLOYEE_ID
      WHERE e.STATUS = 'active' ${sfDeptFilter}
    `, sfDeptBinds as Binds),

    query<{ RISK_LABEL: string; CNT: number }>(`
      SELECT pr.RISK_LABEL, COUNT(*) AS CNT
      FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr
      JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON pr.EMPLOYEE_ID = e.EMPLOYEE_ID
      WHERE e.STATUS = 'active' ${sfDeptFilter}
      GROUP BY pr.RISK_LABEL
    `, sfDeptBinds as Binds),
  ]);

  return { predictions, total: totalRes[0]?.CNT || 0, riskDist };
}

async function viaPgLake(honbuIds: number[] | null, limit: number, offset: number) {
  const scopeFilter = (n: number) => honbuIds
    ? `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = ANY($${n}::int[]) OR parent_dept_id = ANY($${n}::int[]))`
    : "";
  const deptFilter = scopeFilter(3);
  const baseParams = honbuIds ? [limit, offset, honbuIds] : [limit, offset];
  const countParams = honbuIds ? [honbuIds] : [];

  const [predictions, totalRes, riskDist] = await Promise.all([
    pgQuery<{
      EMPLOYEE_ID: number; RISK_SCORE: number; RISK_LABEL: string; MODEL_VERSION: string;
      LAST_NAME: string; FIRST_NAME: string; DEPT_NAME: string; POSITION_TITLE: string;
      GRADE: string; TENURE_YEARS: number;
    }>(`
      SELECT pr.employee_id AS "EMPLOYEE_ID", pr.risk_score AS "RISK_SCORE",
        pr.risk_label AS "RISK_LABEL", pr.model_version AS "MODEL_VERSION",
        e.last_name AS "LAST_NAME", e.first_name AS "FIRST_NAME",
        d.dept_name AS "DEPT_NAME", p.title AS "POSITION_TITLE", p.grade AS "GRADE",
        EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE_YEARS"
      FROM hr_lake.prediction_results pr
      JOIN hr.employees e ON pr.employee_id = e.employee_id
      JOIN hr.departments d ON e.dept_id = d.dept_id
      JOIN hr.positions p ON e.position_id = p.position_id
      WHERE e.status = 'active' ${deptFilter}
      ORDER BY pr.risk_score DESC
      LIMIT $1 OFFSET $2
    `, baseParams),

    pgQuery<{ CNT: number }>(`
      SELECT COUNT(*)::int AS "CNT"
      FROM hr_lake.prediction_results pr
      JOIN hr.employees e ON pr.employee_id = e.employee_id
      WHERE e.status = 'active' ${scopeFilter(1)}
    `, countParams),

    pgQuery<{ RISK_LABEL: string; CNT: number }>(`
      SELECT pr.risk_label AS "RISK_LABEL", COUNT(*)::int AS "CNT"
      FROM hr_lake.prediction_results pr
      JOIN hr.employees e ON pr.employee_id = e.employee_id
      WHERE e.status = 'active' ${scopeFilter(1)}
      GROUP BY pr.risk_label
    `, countParams),
  ]);

  return { predictions, total: totalRes[0]?.CNT || 0, riskDist };
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const honbu = searchParams.get("honbu") || "";
    const limit = Math.min(Number(searchParams.get("limit") || "200"), 500);
    const offset = Number(searchParams.get("offset") || "0");
    const honbuNum = honbu ? Number(honbu) : null;
    const scope = resolveHonbuScope(session, honbuNum);
    if (!scope.ok) {
      return NextResponse.json({ error: "アクセス権限がありません" }, { status: 403 });
    }

    const dataPath = await getDataPath();
    const t0 = performance.now();

    const { predictions, total, riskDist } = dataPath === "pg_lake"
      ? await viaPgLake(scope.honbuIds, limit, offset)
      : await viaSf(scope.honbuIds, limit, offset);

    const ms = Math.round(performance.now() - t0);

    return NextResponse.json({
      data: predictions,
      total,
      riskDistribution: {
        high: riskDist.find(r => r.RISK_LABEL === "high")?.CNT || 0,
        medium: riskDist.find(r => r.RISK_LABEL === "medium")?.CNT || 0,
        low: riskDist.find(r => r.RISK_LABEL === "low")?.CNT || 0,
      },
      _meta: { dataPath, ms },
    });
  } catch (error) {
    console.error("Attrition API error:", error);
    return NextResponse.json({ error: "Failed to fetch attrition data" }, { status: 500 });
  }
}
