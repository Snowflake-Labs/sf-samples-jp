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
    const honbu = searchParams.get("honbu") || "";
    const deptId = searchParams.get("dept_id") || "";

    let empWhere = "WHERE e.status = 'active'";
    const empParams: unknown[] = [];
    let empIdx = 1;
    let deptWhere = "";
    const deptParams: unknown[] = [];
    let deptIdx = 1;

    if (deptId) {
      const id = Number(deptId);
      if (isNaN(id)) {
        return NextResponse.json({ error: "Invalid dept_id" }, { status: 400 });
      }
      empWhere += ` AND e.dept_id = $${empIdx++}`;
      empParams.push(id);
    } else if (honbu) {
      const id = Number(honbu);
      if (isNaN(id)) {
        return NextResponse.json({ error: "Invalid honbu" }, { status: 400 });
      }
      empWhere += ` AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${empIdx} OR parent_dept_id = $${empIdx + 1})`;
      empParams.push(id, id);
      empIdx += 2;
      deptWhere = `WHERE d.dept_id = $${deptIdx} OR d.parent_dept_id = $${deptIdx + 1}`;
      deptParams.push(id, id);
      deptIdx += 2;
    }

    const employeesSql = `SELECT e.employee_id AS "EMPLOYEE_ID",
      e.last_name || e.first_name AS "NAME",
      e.dept_id AS "DEPT_ID", e.position_id AS "POSITION_ID",
      e.manager_id AS "MANAGER_ID", e.salary AS "SALARY",
      d.dept_name AS "DEPT_NAME", p.title AS "POSITION_TITLE", p.grade AS "GRADE",
      EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date))::int AS "AGE",
      EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE_YEARS",
      e.entry_type AS "ENTRY_TYPE"
    FROM hr.employees e
    LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
    LEFT JOIN hr.positions p ON e.position_id = p.position_id
    ${empWhere}
    ORDER BY p.grade, e.employee_id
    LIMIT 5000`;

    const deptsSql = `SELECT d.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME",
      d.dept_code AS "DEPT_CODE", d.parent_dept_id AS "PARENT_DEPT_ID", d.level AS "LEVEL",
      COUNT(e.employee_id) AS "EMP_COUNT"
    FROM hr.departments d
    LEFT JOIN hr.employees e ON d.dept_id = e.dept_id AND e.status = 'active'
    ${deptWhere}
    GROUP BY d.dept_id, d.dept_name, d.dept_code, d.parent_dept_id, d.level
    ORDER BY d.level, d.dept_name`;

    const [employees, departments] = await Promise.all([
      pgQuery(employeesSql, empParams),
      pgQuery(deptsSql, deptParams),
    ]);

    return NextResponse.json({ employees, departments });
  } catch (error) {
    console.error("Org tree error:", error);
    return NextResponse.json({ error: "Failed to fetch org data" }, { status: 500 });
  }
}
