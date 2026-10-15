import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET(req: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const honbu = searchParams.get("honbu");
  if (!honbu) return NextResponse.json({ error: "honbu required" }, { status: 400 });

  const deptScope = session.deptScope;
  const params: unknown[] = [];
  let deptFilter = "";
  if (deptScope && deptScope.length > 0) {
    const placeholders = deptScope.map((_, i) => `$${i + 1}`).join(",");
    deptFilter = `AND d.parent_dept_id IN (${placeholders})`;
    params.push(...deptScope);
  } else {
    params.push(Number(honbu));
    deptFilter = `AND (d.dept_id = $1 OR d.parent_dept_id = $1)`;
  }

  const rows = await pgQuery<{ month: string; high: number; medium: number; low: number }>(
    `WITH current_risks AS (
       SELECT e.employee_id, pr.risk_label,
              pr.risk_score, e.hire_date
       FROM hr_lake.prediction_results pr
       JOIN hr.employees e ON pr.employee_id = e.employee_id
       LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
       WHERE pr.model_type = 'attrition'
         AND e.status = 'active'
         ${deptFilter}
     ),
     months AS (
       SELECT to_char(d, 'YYYY-MM') AS month, d AS month_date
       FROM generate_series(
         date_trunc('month', CURRENT_DATE) - interval '5 months',
         date_trunc('month', CURRENT_DATE),
         interval '1 month'
       ) AS d
     )
     SELECT m.month,
            COUNT(*) FILTER (WHERE cr.risk_label = 'high') AS high,
            COUNT(*) FILTER (WHERE cr.risk_label = 'medium') AS medium,
            COUNT(*) FILTER (WHERE cr.risk_label = 'low') AS low
     FROM months m
     CROSS JOIN current_risks cr
     WHERE cr.hire_date <= m.month_date + interval '1 month'
     GROUP BY m.month
     ORDER BY m.month`,
    params
  );

  return NextResponse.json(rows);
}
