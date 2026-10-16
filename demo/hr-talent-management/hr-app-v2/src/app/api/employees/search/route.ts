import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET(req: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  const { searchParams } = new URL(req.url);
  const q = searchParams.get("q") || "";
  const limit = Math.min(Number(searchParams.get("limit")) || 10, 30);

  if (q.length < 1) {
    return NextResponse.json([]);
  }

  const rows = await pgQuery(
    `SELECT e.employee_id, e.last_name || ' ' || e.first_name AS name,
            d.dept_name, p.grade, p.title AS position_name
     FROM hr.employees e
     LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
     LEFT JOIN hr.positions p ON e.position_id = p.position_id
     WHERE e.status = 'active'
       AND (e.last_name || ' ' || e.first_name ILIKE $1
            OR e.employee_code ILIKE $1)
     ORDER BY e.last_name, e.first_name
     LIMIT $2`,
    [`%${q}%`, limit]
  );

  return NextResponse.json(rows);
}
