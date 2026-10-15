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
    const level = searchParams.get("level");
    const parentId = searchParams.get("parent_id");
    const orderBy = searchParams.get("order_by");

    const params: unknown[] = [];
    let where = "WHERE 1=1";
    let idx = 1;

    if (level !== null && level !== "") {
      where += ` AND d.level = $${idx++}`;
      params.push(Number(level));
    }
    if (parentId) {
      where += ` AND d.parent_dept_id = $${idx++}`;
      params.push(Number(parentId));
    }

    let sql: string;
    if (orderBy === "emp_count") {
      sql = `
        SELECT d.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME", d.dept_code AS "DEPT_CODE",
          d.parent_dept_id AS "PARENT_DEPT_ID", d.level AS "LEVEL", d.is_active AS "IS_ACTIVE",
          COALESCE(ec.emp_count, 0) AS "EMP_COUNT"
        FROM hr.departments d
        LEFT JOIN (
          SELECT COALESCE(dd.parent_dept_id, dd.dept_id) AS honbu_id,
            COUNT(e.employee_id) AS emp_count
          FROM hr.employees e
          JOIN hr.departments dd ON e.dept_id = dd.dept_id
          WHERE e.status = 'active'
          GROUP BY honbu_id
        ) ec ON ec.honbu_id = d.dept_id
        ${where}
        ORDER BY "EMP_COUNT" DESC
      `;
    } else {
      sql = `
        SELECT d.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME", d.dept_code AS "DEPT_CODE",
          d.parent_dept_id AS "PARENT_DEPT_ID", d.level AS "LEVEL", d.is_active AS "IS_ACTIVE"
        FROM hr.departments d
        ${where}
        ORDER BY d.dept_id
      `;
    }

    const departments = await pgQuery(sql, params);
    return NextResponse.json(departments);
  } catch (error) {
    console.error("Departments error:", error);
    return NextResponse.json({ error: "Failed to fetch departments" }, { status: 500 });
  }
}
