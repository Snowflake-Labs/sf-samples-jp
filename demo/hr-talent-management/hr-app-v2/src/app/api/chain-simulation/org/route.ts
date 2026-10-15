import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

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
    const dId = Number(deptId);
    if (isNaN(dId)) {
      return NextResponse.json({ error: "Invalid dept_id" }, { status: 400 });
    }

    const deptInfo = await pgQuery(
      `SELECT dept_id AS "DEPT_ID", dept_name AS "DEPT_NAME", parent_dept_id AS "PARENT_DEPT_ID"
       FROM hr.departments WHERE dept_id = $1`,
      [dId]
    );

    const members = await pgQuery(`
      SELECT e.employee_id AS "EMPLOYEE_ID",
        e.last_name || e.first_name AS "NAME",
        e.employee_code AS "EMPLOYEE_CODE",
        p.grade AS "GRADE", p.title AS "POSITION_TITLE",
        e.manager_id AS "MANAGER_ID", e.status AS "STATUS",
        COALESCE(ev.avg_score, 0) AS "AVG_EVAL",
        EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE"
      FROM hr.employees e
      LEFT JOIN hr.positions p ON e.position_id = p.position_id
      LEFT JOIN (
        SELECT employee_id, ROUND(AVG(score)::numeric, 2)::float AS avg_score
        FROM hr.evaluations GROUP BY employee_id
      ) ev ON ev.employee_id = e.employee_id
      WHERE e.dept_id = $1 AND e.status = 'active'
      ORDER BY CASE p.grade
        WHEN 'E1' THEN 1 WHEN 'D1' THEN 2 WHEN 'D2' THEN 3
        WHEN 'M1' THEN 4 WHEN 'M2' THEN 5 WHEN 'S1' THEN 6
        WHEN 'S2' THEN 7 WHEN 'J1' THEN 8 WHEN 'J2' THEN 9
        WHEN 'J3' THEN 10 ELSE 99 END, e.last_name
    `, [dId]);

    return NextResponse.json({
      department: deptInfo[0] || null,
      members,
    });
  } catch (error) {
    console.error("Chain org error:", error);
    return NextResponse.json({ error: "Failed to fetch org" }, { status: 500 });
  }
}
