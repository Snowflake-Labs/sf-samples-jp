import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const body = await request.json();
    const { employee_id, evaluator_id, period, score, grade, comment, self_comment, self_score, status } = body;

    if (!employee_id || !evaluator_id || !period || score == null || !grade) {
      return NextResponse.json({ error: "employee_id, evaluator_id, period, score, grade are required" }, { status: 400 });
    }

    const validGrades = ["S", "A", "B", "C", "D"];
    if (!validGrades.includes(grade)) {
      return NextResponse.json({ error: "grade must be S, A, B, C, or D" }, { status: 400 });
    }

    if (score < 1 || score > 5) {
      return NextResponse.json({ error: "score must be between 1 and 5" }, { status: 400 });
    }

    const result = await pgQuery<{ evaluation_id: number }>(
      `INSERT INTO hr.evaluations
        (employee_id, evaluator_id, period, score, grade, comment, self_comment, self_score, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       RETURNING evaluation_id`,
      [
        Number(employee_id), Number(evaluator_id), period, Number(score), grade,
        comment || null, self_comment || null,
        self_score != null ? Number(self_score) : null,
        status || "draft",
      ]
    );

    return NextResponse.json({
      success: true,
      evaluationId: result[0]?.evaluation_id || null,
    }, { status: 201 });
  } catch (error) {
    console.error("Create evaluation error:", error);
    return NextResponse.json({ error: "Failed to create evaluation" }, { status: 500 });
  }
}
