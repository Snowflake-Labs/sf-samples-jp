import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getSession } from "@/lib/session";

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const deptId = searchParams.get("dept_id");
    const honbuId = searchParams.get("honbu_id");
    const period = searchParams.get("period") || "2025-H2";
    const mode = searchParams.get("mode") || "primary";
    const deptsOnly = searchParams.get("depts_only") === "true";

    if (!deptId && !honbuId) {
      return NextResponse.json({ error: "dept_id or honbu_id required" }, { status: 400 });
    }

    if (deptsOnly && honbuId) {
      const deptRows = await pgQuery<{ DEPT_ID: number; DEPT_NAME: string }>(
        `SELECT dept_id AS "DEPT_ID", dept_name AS "DEPT_NAME"
         FROM hr.departments
         WHERE parent_dept_id = $1 AND dept_id != $1
         ORDER BY dept_name`,
        [Number(honbuId)]
      );
      return NextResponse.json({ depts: deptRows });
    }

    let targetDeptIdList: number[];
    if (mode === "secondary" && honbuId) {
      const deptRows = await pgQuery<{ dept_id: number }>(
        `SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $2`,
        [Number(honbuId), Number(honbuId)]
      );
      targetDeptIdList = deptRows.map((r) => r.dept_id);
    } else {
      targetDeptIdList = [Number(deptId)];
    }

    if (targetDeptIdList.length === 0) {
      return NextResponse.json({ employees: [], currentEvals: [], history: [], distribution: [], attritionRisks: [], depts: [] });
    }

    const deptPlaceholders = targetDeptIdList.map((_, i) => `$${i + 1}`).join(",");

    const deptsPromise = mode === "secondary" && honbuId
      ? pgQuery<{ DEPT_ID: number; DEPT_NAME: string }>(`
          SELECT dept_id AS "DEPT_ID", dept_name AS "DEPT_NAME"
          FROM hr.departments
          WHERE dept_id IN (${deptPlaceholders})
          ORDER BY dept_name
        `, targetDeptIdList)
      : Promise.resolve([]);

    const [employees, depts] = await Promise.all([
      pgQuery<{
        EMPLOYEE_ID: number;
        NAME: string;
        EMPLOYEE_CODE: string;
        DEPT_ID: number;
        DEPT_NAME: string;
        GRADE: string;
        POSITION_TITLE: string;
        MANAGER_ID: number | null;
        MANAGER_NAME: string | null;
      }>(`
        SELECT e.employee_id AS "EMPLOYEE_ID",
          e.last_name || e.first_name AS "NAME",
          e.employee_code AS "EMPLOYEE_CODE",
          e.dept_id AS "DEPT_ID",
          d.dept_name AS "DEPT_NAME",
          p.grade AS "GRADE",
          p.title AS "POSITION_TITLE",
          e.manager_id AS "MANAGER_ID",
          mgr.last_name || mgr.first_name AS "MANAGER_NAME"
        FROM hr.employees e
        JOIN hr.departments d ON e.dept_id = d.dept_id
        LEFT JOIN hr.positions p ON e.position_id = p.position_id
        LEFT JOIN hr.employees mgr ON e.manager_id = mgr.employee_id
        WHERE e.status = 'active'
          AND e.dept_id IN (${deptPlaceholders})
        ORDER BY d.dept_name, p.grade, e.last_name
      `, targetDeptIdList),
      deptsPromise,
    ]);

    const empIds = employees.map((e) => e.EMPLOYEE_ID);
    if (empIds.length === 0) {
      return NextResponse.json({ employees: [], currentEvals: [], history: [], distribution: [], attritionRisks: [], depts });
    }

    const empPlaceholders = empIds.map((_, i) => `$${i + 2}`).join(",");
    const empPlaceholdersFrom1 = empIds.map((_, i) => `$${i + 1}`).join(",");
    const distDeptPh = targetDeptIdList.map((_, i) => `$${i + 2}`).join(",");

    const [currentEvals, history, distribution, attritionRisks] = await Promise.all([
      pgQuery<{
        EVALUATION_ID: number;
        EMPLOYEE_ID: number;
        SCORE: number | null;
        GRADE: string | null;
        COMMENT: string | null;
        SELF_SCORE: number | null;
        SELF_COMMENT: string | null;
        STATUS: string;
        EVALUATOR_NAME: string | null;
      }>(`
        SELECT ev.evaluation_id AS "EVALUATION_ID",
          ev.employee_id AS "EMPLOYEE_ID",
          ev.score AS "SCORE",
          ev.grade AS "GRADE",
          ev.comment AS "COMMENT",
          ev.self_score AS "SELF_SCORE",
          ev.self_comment AS "SELF_COMMENT",
          ev.status AS "STATUS",
          mgr.last_name || mgr.first_name AS "EVALUATOR_NAME"
        FROM hr.evaluations ev
        LEFT JOIN hr.employees mgr ON ev.evaluator_id = mgr.employee_id
        WHERE ev.period = $1
          AND ev.employee_id IN (${empPlaceholders})
      `, [period, ...empIds]),

      pgQuery<{
        EMPLOYEE_ID: number;
        PERIOD: string;
        SCORE: number | null;
        GRADE: string | null;
      }>(`
        SELECT ev.employee_id AS "EMPLOYEE_ID",
          ev.period AS "PERIOD",
          ev.score AS "SCORE",
          ev.grade AS "GRADE"
        FROM hr.evaluations ev
        WHERE ev.employee_id IN (${empPlaceholdersFrom1})
        ORDER BY ev.period
      `, [...empIds]),

      pgQuery<{
        DEPT_ID: number;
        DEPT_NAME: string;
        GRADE: string;
        COUNT: number;
      }>(`
        SELECT e.dept_id AS "DEPT_ID",
          d.dept_name AS "DEPT_NAME",
          ev.grade AS "GRADE",
          COUNT(*)::int AS "COUNT"
        FROM hr.evaluations ev
        JOIN hr.employees e ON ev.employee_id = e.employee_id
        JOIN hr.departments d ON e.dept_id = d.dept_id
        WHERE ev.period = $1
          AND e.dept_id IN (${distDeptPh})
        GROUP BY e.dept_id, d.dept_name, ev.grade
        ORDER BY d.dept_name, ev.grade
      `, [period, ...targetDeptIdList]),

      (async () => {
        try {
          return await query<{
            EMPLOYEE_ID: number;
            RISK_SCORE: number;
            RISK_LABEL: string;
          }>(`
            SELECT EMPLOYEE_ID, RISK_SCORE, RISK_LABEL
            FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS
            WHERE EMPLOYEE_ID IN (${empIds.map(() => "?").join(",")})
          `, empIds);
        } catch {
          return [] as { EMPLOYEE_ID: number; RISK_SCORE: number; RISK_LABEL: string }[];
        }
      })(),
    ]);

    return NextResponse.json({
      employees,
      currentEvals,
      history,
      distribution,
      attritionRisks,
      depts,
    });
  } catch (error) {
    console.error("Batch evaluation error:", error);
    const msg = error instanceof Error ? error.message + "\n" + error.stack : String(error);
    return NextResponse.json({ error: "Failed to fetch batch data", detail: msg }, { status: 500 });
  }
}

export async function PUT(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const body = await request.json();
    const { evaluations, period } = body as {
      evaluations: {
        employee_id: number;
        evaluator_id: number;
        score: number;
        grade: string;
        comment?: string;
        status: string;
      }[];
      period: string;
    };

    if (!evaluations?.length || !period) {
      return NextResponse.json({ error: "evaluations and period required" }, { status: 400 });
    }

    const results: { employee_id: number; evaluation_id: number; action: string }[] = [];

    for (const ev of evaluations) {
      if (ev.score == null || !ev.grade) continue;

      const existing = await pgQuery<{ evaluation_id: number }>(`
        SELECT evaluation_id FROM hr.evaluations
        WHERE employee_id = $1 AND period = $2
      `, [ev.employee_id, period]);

      if (existing.length > 0) {
        await pgQuery(`
          UPDATE hr.evaluations
          SET score = $1, grade = $2, comment = $3, status = $4, evaluator_id = $5, updated_at = NOW()
          WHERE employee_id = $6 AND period = $7
        `, [ev.score, ev.grade, ev.comment || null, ev.status, ev.evaluator_id, ev.employee_id, period]);
        results.push({ employee_id: ev.employee_id, evaluation_id: existing[0].evaluation_id, action: "updated" });
      } else {
        const ins = await pgQuery<{ evaluation_id: number }>(`
          INSERT INTO hr.evaluations (employee_id, evaluator_id, period, score, grade, comment, status)
          VALUES ($1, $2, $3, $4, $5, $6, $7)
          RETURNING evaluation_id
        `, [ev.employee_id, ev.evaluator_id, period, ev.score, ev.grade, ev.comment || null, ev.status]);
        results.push({ employee_id: ev.employee_id, evaluation_id: ins[0]?.evaluation_id, action: "created" });
      }
    }

    return NextResponse.json({ success: true, results });
  } catch (error) {
    console.error("Batch evaluation save error:", error);
    return NextResponse.json({ error: "Failed to save evaluations" }, { status: 500 });
  }
}
