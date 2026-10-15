import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { CURRENT_PERIOD, EVAL_DEADLINES, deriveProgress } from "@/lib/my-team";

interface Row {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  POSITION_GRADE: string;
  POSITION_TITLE: string;
  STATUS: string;
  COMMENT: string | null;
  HAS_SELF: boolean;
  AI_SCORED: boolean;
  RETURN_REASON: string | null;
  FINAL_GRADE: string | null;
  STANDARD_GRADE: string | null;
  OVERRIDES: number;
  UPDATED_AT: string;
}

/** The manager's team for one period, with where each review stands. */
export async function GET(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["LINE_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const period = new URL(request.url).searchParams.get("period") || CURRENT_PERIOD;
    const rows = await pgQuery<Row>(
      `SELECT ev.evaluation_id AS "EVALUATION_ID", e.employee_id AS "EMPLOYEE_ID",
         e.last_name || e.first_name AS "NAME", e.employee_code AS "EMPLOYEE_CODE",
         p.grade AS "POSITION_GRADE", p.title AS "POSITION_TITLE",
         ev.status AS "STATUS", ev.comment AS "COMMENT",
         (COALESCE(ev.self_comment, '') <> '') AS "HAS_SELF",
         (eqs.evaluation_id IS NOT NULL) AS "AI_SCORED",
         ev.return_reason AS "RETURN_REASON", ev.grade AS "FINAL_GRADE",
         eqs.standard_grade AS "STANDARD_GRADE",
         (SELECT COUNT(*)::int FROM hr.eval_axis_overrides o WHERE o.evaluation_id = ev.evaluation_id) AS "OVERRIDES",
         ev.updated_at AS "UPDATED_AT"
       FROM hr.evaluations ev
       JOIN hr.employees e ON ev.employee_id = e.employee_id
       JOIN hr.positions p ON e.position_id = p.position_id
       LEFT JOIN hr.eval_quantified_scores eqs ON eqs.evaluation_id = ev.evaluation_id
       WHERE ev.evaluator_id = $1 AND ev.period = $2
       ORDER BY e.employee_code`,
      [auth.user.employeeId, period]
    );

    const members = rows.map((r) => ({ ...r, PROGRESS: deriveProgress(r), COMMENT: undefined, HAS_COMMENT: !!r.COMMENT?.trim() }));
    const counts: Record<string, number> = {};
    for (const m of members) counts[m.PROGRESS] = (counts[m.PROGRESS] ?? 0) + 1;

    return NextResponse.json({ period, deadline: EVAL_DEADLINES[period] ?? null, members, counts });
  } catch (error) {
    console.error("my-team GET error:", error);
    return NextResponse.json({ error: "マイチームの取得に失敗しました" }, { status: 500 });
  }
}
