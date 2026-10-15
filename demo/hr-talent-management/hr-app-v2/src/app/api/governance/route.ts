import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

const ROLE_HIERARCHY: Record<string, number> = {
  HR_ADMIN_ROLE: 3,
  HR_MANAGER_ROLE: 2,
  HR_VIEWER_ROLE: 1,
};

function sessionToGovRole(sessionRole: string): string {
  if (sessionRole === "HR_ADMIN") return "HR_ADMIN_ROLE";
  if (sessionRole === "HR_MANAGER") return "HR_MANAGER_ROLE";
  return "HR_VIEWER_ROLE";
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const maxRole = sessionToGovRole(session.role);
    const requestedRole = searchParams.get("role") || maxRole;
    const role = (ROLE_HIERARCHY[requestedRole] ?? 0) <= (ROLE_HIERARCHY[maxRole] ?? 0)
      ? requestedRole : maxRole;

    const results = await pgQuery<{
      EMPLOYEE_ID: number;
      EMPLOYEE_CODE: string;
      NAME: string;
      EMAIL: string;
      SALARY: number;
      DEPT_NAME: string;
      GRADE: string;
    }>(
      `SELECT e.employee_id AS "EMPLOYEE_ID", e.employee_code AS "EMPLOYEE_CODE",
        e.last_name || e.first_name AS "NAME",
        e.email AS "EMAIL", e.salary AS "SALARY",
        d.dept_name AS "DEPT_NAME", p.grade AS "GRADE"
      FROM hr.employees e
      LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
      LEFT JOIN hr.positions p ON e.position_id = p.position_id
      WHERE e.status = 'active'
      ORDER BY e.employee_id
      LIMIT 10`
    );

    const masked = results.map((row) => {
      const r = { ...row };
      if (role === "HR_MANAGER_ROLE") {
        r.SALARY = 0;
      } else if (role === "HR_VIEWER_ROLE") {
        r.SALARY = 0;
        r.EMAIL = "***";
      }
      return r;
    });

    return NextResponse.json({ role, data: masked });
  } catch (error) {
    console.error("Governance error:", error);
    return NextResponse.json({ error: "Failed to fetch governance data" }, { status: 500 });
  }
}
