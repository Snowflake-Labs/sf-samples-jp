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
    const vacantOnly = searchParams.get("vacant") === "true";

    let where = "WHERE 1=1";
    const params: unknown[] = [];
    let idx = 1;

    if (vacantOnly) {
      where += " AND p.is_vacant = true";
    }

    if (honbu) {
      const id = Number(honbu);
      if (isNaN(id)) {
        return NextResponse.json({ error: "Invalid honbu" }, { status: 400 });
      }
      where += ` AND p.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${idx} OR parent_dept_id = $${idx + 1})`;
      params.push(id, id);
      idx += 2;
    }

    const sql = `SELECT p.position_id AS "POSITION_ID", p.title AS "TITLE", p.dept_id AS "DEPT_ID",
      p.grade AS "GRADE", p.is_vacant AS "IS_VACANT", p.headcount AS "HEADCOUNT",
      d.dept_name AS "DEPT_NAME"
    FROM hr.positions p
    LEFT JOIN hr.departments d ON p.dept_id = d.dept_id
    ${where}
    ORDER BY p.grade, d.dept_name
    LIMIT 500`;

    const results = await pgQuery(sql, params);
    return NextResponse.json(results);
  } catch (error) {
    console.error("Positions error:", error);
    return NextResponse.json({ error: "Failed to fetch positions" }, { status: 500 });
  }
}
