import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getDataPath } from "@/lib/data-path";
import { getSession } from "@/lib/session";

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const honbu = searchParams.get("honbu") || "";
    const honbuNum = honbu ? Number(honbu) : null;

    if (!honbuNum) {
      return NextResponse.json({ error: "honbu parameter required" }, { status: 400 });
    }

    const deptFilter = `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $1)`;
    const posDeptFilter = `AND p.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $1)`;
    const params = [honbuNum];

    const dataPath = await getDataPath();
    const usePgLake = dataPath === "pg_lake";

    const [summaryRows, vacantRows, gradeEmpRows, gradeVacantRows, deptHeatRows, watchRows, riskRows] = await Promise.all([
      pgQuery<Record<string, unknown>>(`
        SELECT
          COUNT(*)::int AS "headcount",
          ROUND(AVG(EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date)))::numeric, 1) AS "avgTenure"
        FROM hr.employees e
        WHERE e.status = 'active' ${deptFilter}
      `, params),

      pgQuery<Record<string, unknown>>(`
        SELECT COUNT(*)::int AS "vacantCount"
        FROM hr.positions p
        WHERE p.is_vacant = true ${posDeptFilter}
      `, params),

      pgQuery<Record<string, unknown>>(`
        SELECT p.grade AS "GRADE", COUNT(*)::int AS "EMP_COUNT"
        FROM hr.employees e
        JOIN hr.positions p ON e.position_id = p.position_id
        WHERE e.status = 'active' ${deptFilter}
        GROUP BY p.grade
      `, params),

      pgQuery<Record<string, unknown>>(`
        SELECT p.grade AS "GRADE", COUNT(*)::int AS "VACANT_COUNT"
        FROM hr.positions p
        WHERE p.is_vacant = true ${posDeptFilter}
        GROUP BY p.grade
      `, params),

      pgQuery<Record<string, unknown>>(`
        WITH dept_stats AS (
          SELECT
            d.dept_id,
            d.dept_name,
            COUNT(e.employee_id)::int AS emp_count,
            ROUND(AVG(EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date)))::numeric, 1) AS avg_tenure
          FROM hr.employees e
          JOIN hr.departments d ON e.dept_id = d.dept_id
          WHERE e.status = 'active' ${deptFilter}
          GROUP BY d.dept_id, d.dept_name
        ),
        dept_vacancies AS (
          SELECT p.dept_id, COUNT(*)::int AS vacant_count
          FROM hr.positions p
          WHERE p.is_vacant = true ${posDeptFilter}
          GROUP BY p.dept_id
        ),
        dept_evals AS (
          SELECT e.dept_id,
            ROUND(AVG(ev.score)::numeric, 2) AS avg_eval
          FROM hr.evaluations ev
          JOIN hr.employees e ON ev.employee_id = e.employee_id
          WHERE ev.period = (SELECT MAX(period) FROM hr.evaluations)
            AND e.status = 'active' ${deptFilter}
          GROUP BY e.dept_id
        ),
        dept_risk AS (
          ${usePgLake ? `
          SELECT e.dept_id,
            COUNT(CASE WHEN pr.risk_label = 'high' THEN 1 END)::int AS risk_high,
            COUNT(CASE WHEN pr.risk_label = 'medium' THEN 1 END)::int AS risk_medium
          FROM hr.employees e
          LEFT JOIN hr_lake.prediction_results pr ON pr.employee_id = e.employee_id
          WHERE e.status = 'active' ${deptFilter}
          GROUP BY e.dept_id
          ` : `
          SELECT 0 AS dept_id, 0 AS risk_high, 0 AS risk_medium WHERE false
          `}
        )
        SELECT ds.dept_id AS "DEPT_ID", ds.dept_name AS "DEPT_NAME",
          ds.emp_count AS "EMP_COUNT", ds.avg_tenure AS "AVG_TENURE",
          COALESCE(dv.vacant_count, 0) AS "VACANT_COUNT",
          COALESCE(de.avg_eval, 0) AS "AVG_EVAL",
          COALESCE(dr.risk_high, 0) AS "RISK_HIGH",
          COALESCE(dr.risk_medium, 0) AS "RISK_MEDIUM"
        FROM dept_stats ds
        LEFT JOIN dept_vacancies dv ON ds.dept_id = dv.dept_id
        LEFT JOIN dept_evals de ON ds.dept_id = de.dept_id
        LEFT JOIN dept_risk dr ON ds.dept_id = dr.dept_id
        WHERE ds.emp_count > 0
        ORDER BY ds.emp_count DESC
      `, params),

      (() => {
        if (usePgLake) {
          return pgQuery<Record<string, unknown>>(`
            SELECT e.employee_id AS "EMPLOYEE_ID",
              e.last_name || e.first_name AS "NAME",
              d.dept_name AS "DEPT_NAME",
              p.grade AS "GRADE",
              p.title AS "POSITION_TITLE",
              EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE_YEARS",
              pr.risk_score AS "RISK_SCORE",
              pr.risk_label AS "RISK_LABEL",
              rr.relationship_score AS "REL_SCORE",
              COALESCE((SELECT ROUND(AVG(ev.score)::numeric, 2) FROM hr.evaluations ev WHERE ev.employee_id = e.employee_id), 0) AS "AVG_EVAL"
            FROM hr.employees e
            JOIN hr.departments d ON e.dept_id = d.dept_id
            JOIN hr.positions p ON e.position_id = p.position_id
            LEFT JOIN hr_lake.prediction_results pr ON pr.employee_id = e.employee_id
            LEFT JOIN hr_lake.relationship_results rr ON rr.employee_id = e.employee_id
            WHERE e.status = 'active'
              AND (pr.risk_label IN ('high','medium') OR rr.relationship_score < 0.3)
              ${deptFilter}
            ORDER BY pr.risk_score DESC NULLS LAST
            LIMIT 50
          `, params);
        }
        return Promise.resolve([]);
      })(),

      (() => {
        if (usePgLake) {
          return pgQuery<Record<string, unknown>>(`
            SELECT pr.risk_label AS "RISK_LABEL", COUNT(*)::int AS "CNT"
            FROM hr_lake.prediction_results pr
            JOIN hr.employees e ON pr.employee_id = e.employee_id
            WHERE e.status = 'active' ${deptFilter}
            GROUP BY pr.risk_label
          `, params);
        }
        return Promise.resolve([]);
      })(),
    ]);

    const deptSubquery = `(SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $1)`;

    const [recentChanges, monthlyFlow, deptFlow] = await Promise.all([
      pgQuery<Record<string, unknown>>(`
        SELECT ch.history_id AS "ID", ch.event_date AS "DATE", ch.event_type AS "TYPE",
          e.last_name || e.first_name AS "NAME",
          p_g.grade AS "GRADE",
          fd.dept_name AS "FROM_DEPT", td.dept_name AS "TO_DEPT",
          fp.title AS "FROM_POS", tp.title AS "TO_POS",
          ch.notes AS "NOTES"
        FROM hr.career_history ch
        JOIN hr.employees e ON ch.employee_id = e.employee_id
        JOIN hr.positions p_g ON e.position_id = p_g.position_id
        LEFT JOIN hr.departments fd ON ch.from_dept_id = fd.dept_id
        LEFT JOIN hr.departments td ON ch.to_dept_id = td.dept_id
        LEFT JOIN hr.positions fp ON ch.from_position_id = fp.position_id
        LEFT JOIN hr.positions tp ON ch.to_position_id = tp.position_id
        WHERE (ch.from_dept_id IN ${deptSubquery} OR ch.to_dept_id IN ${deptSubquery})
        ORDER BY ch.event_date DESC
        LIMIT 30
      `, params),

      pgQuery<Record<string, unknown>>(`
        SELECT TO_CHAR(ch.event_date, 'YYYY-MM') AS "MONTH",
          ch.event_type AS "TYPE",
          COUNT(*)::int AS "COUNT"
        FROM hr.career_history ch
        WHERE ch.from_dept_id IN ${deptSubquery}
           OR ch.to_dept_id IN ${deptSubquery}
        GROUP BY TO_CHAR(ch.event_date, 'YYYY-MM'), ch.event_type
        ORDER BY "MONTH"
      `, params),

      pgQuery<Record<string, unknown>>(`
        WITH inflow AS (
          SELECT td.dept_name AS dept, COUNT(*)::int AS cnt
          FROM hr.career_history ch
          JOIN hr.departments td ON ch.to_dept_id = td.dept_id
          WHERE ch.event_type = 'transfer'
            AND ch.to_dept_id IN ${deptSubquery}
            AND (ch.from_dept_id IS NULL OR ch.from_dept_id NOT IN ${deptSubquery})
          GROUP BY td.dept_name
        ),
        outflow AS (
          SELECT fd.dept_name AS dept, COUNT(*)::int AS cnt
          FROM hr.career_history ch
          JOIN hr.departments fd ON ch.from_dept_id = fd.dept_id
          WHERE ch.event_type = 'transfer'
            AND ch.from_dept_id IN ${deptSubquery}
            AND (ch.to_dept_id IS NULL OR ch.to_dept_id NOT IN ${deptSubquery})
          GROUP BY fd.dept_name
        ),
        internal AS (
          SELECT fd.dept_name AS from_dept, td.dept_name AS to_dept, COUNT(*)::int AS cnt
          FROM hr.career_history ch
          JOIN hr.departments fd ON ch.from_dept_id = fd.dept_id
          JOIN hr.departments td ON ch.to_dept_id = td.dept_id
          WHERE ch.event_type = 'transfer'
            AND ch.from_dept_id IN ${deptSubquery}
            AND ch.to_dept_id IN ${deptSubquery}
            AND ch.from_dept_id != ch.to_dept_id
          GROUP BY fd.dept_name, td.dept_name
        )
        SELECT 'inflow' AS "FLOW_TYPE", i.dept AS "DEPT", NULL AS "TO_DEPT", i.cnt AS "COUNT"
        FROM inflow i
        UNION ALL
        SELECT 'outflow', o.dept, NULL, o.cnt FROM outflow o
        UNION ALL
        SELECT 'internal', it.from_dept, it.to_dept, it.cnt FROM internal it
        ORDER BY "COUNT" DESC
      `, params),
    ]);

    const riskCounts = { high: 0, medium: 0, low: 0 };
    for (const r of riskRows) {
      const label = r.RISK_LABEL as string;
      const cnt = r.CNT as number;
      if (label === "high") riskCounts.high = cnt;
      else if (label === "medium") riskCounts.medium = cnt;
      else riskCounts.low = cnt;
    }

    const vacantMap: Record<string, number> = {};
    for (const r of gradeVacantRows) {
      vacantMap[r.GRADE as string] = r.VACANT_COUNT as number;
    }

    const GRADE_ORDER: Record<string, number> = {
      E1: 0, D1: 1, D2: 2, M1: 3, M2: 4, S1: 5, S2: 6, J1: 7, J2: 8, J3: 9,
    };
    const gradePyramid = gradeEmpRows
      .map((r) => ({
        grade: r.GRADE as string,
        empCount: r.EMP_COUNT as number,
        vacantCount: vacantMap[r.GRADE as string] || 0,
      }))
      .sort((a, b) => (GRADE_ORDER[a.grade] ?? 99) - (GRADE_ORDER[b.grade] ?? 99));

    const summary = summaryRows[0] || {};

    return NextResponse.json({
      summary: {
        headcount: summary.headcount || 0,
        avgTenure: summary.avgTenure || 0,
        vacantCount: (vacantRows[0]?.vacantCount as number) || 0,
        riskHigh: riskCounts.high,
        riskMedium: riskCounts.medium,
        riskLow: riskCounts.low,
      },
      gradePyramid,
      deptHeatmap: deptHeatRows,
      watchList: watchRows,
      careerHistory: {
        recentChanges,
        monthlyFlow,
        deptFlow,
      },
    });
  } catch (error) {
    console.error("Workforce overview error:", error);
    return NextResponse.json({ error: "Failed to fetch workforce overview" }, { status: 500 });
  }
}
