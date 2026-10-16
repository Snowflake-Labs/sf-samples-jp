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
    const triggerType = searchParams.get("type") || "all";

    const fetchTransfers = triggerType === "all" || triggerType === "transfer"
      ? pgQuery(`
        SELECT 'transfer' AS "TRIGGER_TYPE",
          tr.request_id AS "EVENT_ID",
          tr.employee_id AS "EMPLOYEE_ID",
          e.last_name || e.first_name AS "NAME",
          e.employee_code AS "EMPLOYEE_CODE",
          p.grade AS "GRADE",
          p.title AS "POSITION_TITLE",
          tr.from_dept_id AS "DEPT_ID",
          d_from.dept_name AS "DEPT_NAME",
          tr.to_dept_id AS "TO_DEPT_ID",
          d_to.dept_name AS "TO_DEPT_NAME",
          tr.reason AS "REASON",
          tr.status AS "STATUS",
          tr.resolved_at AS "EVENT_DATE"
        FROM hr.transfer_requests tr
        JOIN hr.employees e ON tr.employee_id = e.employee_id
        JOIN hr.departments d_from ON tr.from_dept_id = d_from.dept_id
        JOIN hr.departments d_to ON tr.to_dept_id = d_to.dept_id
        LEFT JOIN hr.positions p ON e.position_id = p.position_id
        WHERE tr.status IN ('approved', 'completed')
        ORDER BY tr.resolved_at DESC
        LIMIT 50
      `)
      : Promise.resolve([]);

    const fetchRetired = triggerType === "all" || triggerType === "retirement"
      ? pgQuery(`
        SELECT 'retirement' AS "TRIGGER_TYPE",
          e.employee_id AS "EVENT_ID",
          e.employee_id AS "EMPLOYEE_ID",
          e.last_name || e.first_name AS "NAME",
          e.employee_code AS "EMPLOYEE_CODE",
          p.grade AS "GRADE",
          p.title AS "POSITION_TITLE",
          e.dept_id AS "DEPT_ID",
          d.dept_name AS "DEPT_NAME",
          NULL::int AS "TO_DEPT_ID",
          NULL::text AS "TO_DEPT_NAME",
          '退職' AS "REASON",
          e.status AS "STATUS",
          NULL::timestamptz AS "EVENT_DATE"
        FROM hr.employees e
        JOIN hr.departments d ON e.dept_id = d.dept_id
        LEFT JOIN hr.positions p ON e.position_id = p.position_id
        WHERE e.status IN ('retired', 'leave')
        ORDER BY p.grade, e.last_name
        LIMIT 50
      `)
      : Promise.resolve([]);

    const [transfers, retired] = await Promise.all([fetchTransfers, fetchRetired]);
    const results = [...transfers, ...retired];
    return NextResponse.json(results);
  } catch (error) {
    console.error("Chain triggers error:", error);
    return NextResponse.json({ error: "Failed to fetch triggers" }, { status: 500 });
  }
}
