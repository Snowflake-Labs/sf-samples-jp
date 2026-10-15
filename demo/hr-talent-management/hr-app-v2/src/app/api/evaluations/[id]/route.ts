import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { loadAxes } from "@/lib/my-team";
import { validateFinalGrade } from "@/lib/manager-override";

const EVAL_DETAIL_SQL = `
  SELECT ev.evaluation_id AS "EVALUATION_ID", ev.employee_id AS "EMPLOYEE_ID",
    ev.evaluator_id AS "EVALUATOR_ID", ev.period AS "PERIOD",
    ev.score AS "SCORE", ev.grade AS "GRADE", ev.comment AS "COMMENT",
    ev.self_comment AS "SELF_COMMENT", ev.self_score AS "SELF_SCORE",
    ev.status AS "STATUS", ev.grade_reason AS "GRADE_REASON", ev.created_at AS "CREATED_AT", ev.updated_at AS "UPDATED_AT",
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
  WHERE ev.evaluation_id = $1
`;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { id } = await params;
    const evaluations = await pgQuery(EVAL_DETAIL_SQL, [Number(id)]);

    if (evaluations.length === 0) {
      return NextResponse.json({ error: "Evaluation not found" }, { status: 404 });
    }
    return NextResponse.json(evaluations[0]);
  } catch (error) {
    console.error("Evaluation detail error:", error);
    return NextResponse.json({ error: "Failed to fetch evaluation" }, { status: 500 });
  }
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { id } = await params;
    const idNum = Number(id);
    if (!Number.isInteger(idNum)) return NextResponse.json({ error: "評価IDが不正です" }, { status: 400 });
    const body = await request.json();

    // Once AI scores exist, the final grade follows the same rule as the line
    // manager's: within one step of the recommendation, with a reason if moved.
    if (body.GRADE !== undefined && body.GRADE) {
      const { standardGrade } = await loadAxes(idNum);
      if (standardGrade) {
        const err = validateFinalGrade(body.GRADE, standardGrade, body.GRADE_REASON);
        if (err) return NextResponse.json({ error: err }, { status: 400 });
        if (body.GRADE === standardGrade) body.GRADE_REASON = null;
      }
    }

    const allowedFields = ["SCORE", "GRADE", "GRADE_REASON", "COMMENT", "SELF_COMMENT", "STATUS"];
    const pgFields: Record<string, string> = {
      SCORE: "score", GRADE: "grade", GRADE_REASON: "grade_reason", COMMENT: "comment",
      SELF_COMMENT: "self_comment", STATUS: "status",
    };
    const sets: string[] = [];
    const binds: unknown[] = [];
    let idx = 1;

    for (const field of allowedFields) {
      if (body[field] !== undefined) {
        sets.push(`${pgFields[field]} = $${idx++}`);
        binds.push(body[field]);
      }
    }

    if (sets.length === 0) {
      return NextResponse.json({ error: "No fields to update" }, { status: 400 });
    }

    sets.push("updated_at = NOW()");
    binds.push(idNum);

    await pgQuery(
      `UPDATE hr.evaluations SET ${sets.join(", ")} WHERE evaluation_id = $${idx}`,
      binds
    );

    const updated = await pgQuery(EVAL_DETAIL_SQL, [idNum]);
    return NextResponse.json(updated[0] || { success: true });
  } catch (error) {
    console.error("Evaluation update error:", error);
    return NextResponse.json({ error: "Failed to update evaluation" }, { status: 500 });
  }
}
