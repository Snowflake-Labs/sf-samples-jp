import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, isHonbuAllowed } from "@/lib/session";

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const period = searchParams.get("period") || "";
    const status = searchParams.get("status") || "";
    const honbu = searchParams.get("honbu") || "";
    const grade = searchParams.get("grade") || "";
    const search = searchParams.get("search") || "";
    const employeeId = searchParams.get("employee_id") || "";
    const limit = Math.min(Number(searchParams.get("limit")) || 50, 200);
    const offset = Number(searchParams.get("offset")) || 0;

    let where = "WHERE 1=1";
    const params: unknown[] = [];
    let idx = 1;

    if (employeeId) {
      where += ` AND ev.employee_id = $${idx++}`;
      params.push(Number(employeeId));
    }
    if (period) {
      where += ` AND ev.period = $${idx++}`;
      params.push(period);
    }
    if (status) {
      where += ` AND ev.status = $${idx++}`;
      params.push(status);
    }
    if (honbu) {
      if (!isHonbuAllowed(session, Number(honbu))) {
        return NextResponse.json({ error: "アクセス権限がありません" }, { status: 403 });
      }
      where += ` AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${idx} OR parent_dept_id = $${idx + 1})`;
      params.push(Number(honbu), Number(honbu));
      idx += 2;
    } else if (session.deptScope) {
      const placeholders = session.deptScope.map(() => `$${idx++}`).join(",");
      where += ` AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id IN (${placeholders}) OR parent_dept_id IN (${placeholders}))`;
      params.push(...session.deptScope);
    }
    const deptId = searchParams.get("dept_id") || "";
    if (deptId) {
      where += ` AND e.dept_id = $${idx++}`;
      params.push(Number(deptId));
    }
    if (grade) {
      where += ` AND ev.grade = $${idx++}`;
      params.push(grade);
    }
    if (search) {
      where += ` AND (e.last_name || e.first_name) ILIKE $${idx++}`;
      params.push(`%${search}%`);
    }

    const countParams = [...params];

    const countSql = `
      SELECT COUNT(*) AS "TOTAL"
      FROM hr.evaluations ev
      JOIN hr.employees e ON ev.employee_id = e.employee_id
      ${where}
    `;

    const dataSql = `
      SELECT ev.evaluation_id AS "EVALUATION_ID", ev.employee_id AS "EMPLOYEE_ID",
        ev.period AS "PERIOD", ev.score AS "SCORE", ev.grade AS "GRADE", ev.status AS "STATUS",
        SUBSTR(ev.comment, 1, 100) AS "COMMENT",
        e.last_name || e.first_name AS "EMPLOYEE_NAME",
        e.employee_code AS "EMPLOYEE_CODE",
        d.dept_name AS "DEPT_NAME",
        p.title AS "POSITION_TITLE",
        p.grade AS "POSITION_GRADE",
        m.last_name || m.first_name AS "EVALUATOR_NAME"
      FROM hr.evaluations ev
      JOIN hr.employees e ON ev.employee_id = e.employee_id
      LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
      LEFT JOIN hr.positions p ON e.position_id = p.position_id
      LEFT JOIN hr.employees m ON ev.evaluator_id = m.employee_id
      ${where}
      ORDER BY ev.period DESC, e.employee_id
      LIMIT $${idx++} OFFSET $${idx++}
    `;

    params.push(limit, offset);

    const [countResult, evaluations] = await Promise.all([
      pgQuery<{ TOTAL: string }>(countSql, countParams),
      pgQuery(dataSql, params),
    ]);

    const total = Number(countResult[0]?.TOTAL || 0);
    return NextResponse.json({
      data: evaluations,
      total,
      limit,
      offset,
      hasMore: offset + limit < total,
    });
  } catch (error) {
    console.error("Evaluations error:", error);
    return NextResponse.json({ error: "Failed to fetch evaluations" }, { status: 500 });
  }
}
