import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

/** Record a grade adjustment made during a calibration session. */

const VALID_GRADES = ["S", "A", "B", "C", "D"];

export async function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  try {
    const { id } = await ctx.params;
    const sessionId = Number(id);
    const body = await request.json();
    const { evaluation_id, after_grade, reason } = body as {
      evaluation_id?: number;
      after_grade?: string;
      reason?: string;
    };

    if (!evaluation_id || !after_grade) {
      return NextResponse.json({ error: "evaluation_id と after_grade は必須です" }, { status: 400 });
    }
    if (!VALID_GRADES.includes(after_grade)) {
      return NextResponse.json({ error: "グレードは S/A/B/C/D で指定してください" }, { status: 400 });
    }
    // An adjustment without a reason is unauditable, which defeats the point
    // of holding the meeting.
    if (!reason || reason.trim().length < 5) {
      return NextResponse.json(
        { error: "調整理由は5文字以上で入力してください" },
        { status: 400 }
      );
    }

    const sessions = await pgQuery<{ STATUS: string; SCOPE_GRADE: string | null }>(
      `SELECT status AS "STATUS", scope_grade AS "SCOPE_GRADE" FROM hr.calibration_sessions WHERE session_id = $1`,
      [sessionId]
    );
    if (sessions.length === 0) {
      return NextResponse.json({ error: "調整会議が見つかりません" }, { status: 404 });
    }
    if (sessions[0].STATUS === "finalized") {
      return NextResponse.json({ error: "確定済みの調整会議は変更できません" }, { status: 409 });
    }

    // Capture the pre-adjustment state for the audit trail.
    const before = await pgQuery<{
      EMPLOYEE_ID: number;
      STANDARD_GRADE: string | null;
      MANUAL_GRADE: string | null;
      COMPOSITE_SCORE: string | null;
      MANUAL_COMPOSITE: string | null;
      POSITION_GRADE: string | null;
    }>(
      `SELECT ev.employee_id AS "EMPLOYEE_ID",
         eqs.standard_grade AS "STANDARD_GRADE", eqs.manual_grade AS "MANUAL_GRADE",
         eqs.composite_score AS "COMPOSITE_SCORE", eqs.manual_composite AS "MANUAL_COMPOSITE",
         pos.grade AS "POSITION_GRADE"
       FROM hr.evaluations ev
       JOIN hr.employees e ON ev.employee_id = e.employee_id
       LEFT JOIN hr.positions pos ON e.position_id = pos.position_id
       LEFT JOIN hr.eval_quantified_scores eqs ON eqs.evaluation_id = ev.evaluation_id
       WHERE ev.evaluation_id = $1`,
      [evaluation_id]
    );
    if (before.length === 0) {
      return NextResponse.json({ error: "評価が見つかりません" }, { status: 404 });
    }
    const b = before[0];
    const scopeGrade = sessions[0].SCOPE_GRADE;
    if (scopeGrade && b.POSITION_GRADE !== scopeGrade) {
      return NextResponse.json(
        { error: `この会議の対象は等級 ${scopeGrade} です（対象者は ${b.POSITION_GRADE ?? "-"}）` },
        { status: 400 }
      );
    }
    const beforeGrade = b.MANUAL_GRADE ?? b.STANDARD_GRADE;
    const beforeComposite = b.MANUAL_COMPOSITE ?? b.COMPOSITE_SCORE;
    if (beforeGrade === after_grade) {
      return NextResponse.json({ error: `現在のグレード（${after_grade}）と同じです。変更するグレードを選んでください` }, { status: 400 });
    }

    await pgQuery(
      `INSERT INTO hr.calibration_adjustments
         (session_id, evaluation_id, employee_id, before_grade, after_grade,
          before_composite, after_composite, reason, adjusted_by)
       VALUES ($1, $2, $3, $4, $5, $6, $6, $7, $8)`,
      [
        sessionId, evaluation_id, b.EMPLOYEE_ID,
        beforeGrade, after_grade, beforeComposite,
        reason.trim(), user.username,
      ]
    );

    // The meeting's decision becomes the manual override, which is what the
    // rest of the app already reads as the final grade.
    await pgQuery(
      `UPDATE hr.eval_quantified_scores
       SET manual_grade = $2, manual_note = $3, updated_at = NOW()
       WHERE evaluation_id = $1`,
      [evaluation_id, after_grade, `[調整会議] ${reason.trim()}`]
    );

    console.log(
      `[calibration] ${user.username} adjusted eval ${evaluation_id}: ${beforeGrade ?? "-"} -> ${after_grade}`
    );
    return NextResponse.json({ ok: true, before_grade: beforeGrade, after_grade });
  } catch (error) {
    console.error("Calibration adjust error:", error);
    return NextResponse.json({ error: "調整の記録に失敗しました" }, { status: 500 });
  }
}

export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { id } = await ctx.params;
    const rows = await pgQuery(
      `SELECT ca.adjustment_id AS "ADJUSTMENT_ID", ca.evaluation_id AS "EVALUATION_ID",
         e.last_name || e.first_name AS "NAME", e.employee_code AS "EMPLOYEE_CODE",
         ca.before_grade AS "BEFORE_GRADE", ca.after_grade AS "AFTER_GRADE",
         ca.reason AS "REASON", ca.adjusted_by AS "ADJUSTED_BY", ca.created_at AS "CREATED_AT"
       FROM hr.calibration_adjustments ca
       JOIN hr.employees e ON ca.employee_id = e.employee_id
       WHERE ca.session_id = $1
       ORDER BY ca.created_at DESC`,
      [Number(id)]
    );
    return NextResponse.json({ adjustments: rows });
  } catch (error) {
    console.error("Calibration adjustments GET error:", error);
    return NextResponse.json({ error: "調整履歴の取得に失敗しました" }, { status: 500 });
  }
}
