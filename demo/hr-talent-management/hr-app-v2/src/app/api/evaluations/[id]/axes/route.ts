import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { aiScoresOf, loadAxes } from "@/lib/my-team";
import { allowedGrades, applyAxisInputs, type AxisInputs } from "@/lib/manager-override";
import { rerankPeriod, saveScores } from "@/lib/recalculate";
import { SCORE_AXES } from "@/lib/scoring";

/**
 * The AI axis scores, corrections and recommendation for one evaluation,
 * for HR's detail view on 評価管理.
 */
export async function GET(_request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const id = Number((await ctx.params).id);
  if (!Number.isInteger(id)) return NextResponse.json({ error: "評価IDが不正です" }, { status: 400 });
  try {
    const [ev] = await pgQuery<{ COMMENT: string | null; GRADE_REASON: string | null }>(
      `SELECT comment AS "COMMENT", grade_reason AS "GRADE_REASON" FROM hr.evaluations WHERE evaluation_id = $1`,
      [id]
    );
    if (!ev) return NextResponse.json({ error: "評価が見つかりません" }, { status: 404 });
    // The latest calibration-meeting adjustment, so the detail shows what the meeting decided.
    const [cal] = await pgQuery<{ GRADE: string | null; REASON: string; SESSION_NAME: string; STATUS: string }>(
      `SELECT ca.after_grade AS "GRADE", ca.reason AS "REASON",
         cs.session_name AS "SESSION_NAME", cs.status AS "STATUS"
       FROM hr.calibration_adjustments ca
       JOIN hr.calibration_sessions cs ON cs.session_id = ca.session_id
       WHERE ca.evaluation_id = $1
       ORDER BY ca.created_at DESC LIMIT 1`,
      [id]
    );
    const axes = await loadAxes(id);
    const [note] = await pgQuery<{ NOTE: string | null }>(
      `SELECT manual_note AS "NOTE" FROM hr.eval_quantified_scores WHERE evaluation_id = $1`,
      [id]
    );
    const scored = axes.axes.every((a) => a.effective !== null);
    return NextResponse.json({
      ...axes,
      scored,
      gradeReason: ev.GRADE_REASON,
      reviewNote: note?.NOTE ?? null,
      calibration: cal
        ? { grade: cal.GRADE, reason: cal.REASON, sessionName: cal.SESSION_NAME, finalized: cal.STATUS === "finalized" }
        : null,
      // Scored from a different comment than the one saved now.
      stale: scored && axes.aiInputComment !== null && (axes.aiInputComment ?? "") !== (ev.COMMENT ?? ""),
      allowedGrades: axes.standardGrade ? allowedGrades(axes.standardGrade) : [],
    });
  } catch (error) {
    console.error("evaluation axes error:", error);
    return NextResponse.json({ error: "AI採点の取得に失敗しました" }, { status: 500 });
  }
}

/**
 * The cross-review memo (評価横断レビュー「手動修正メモ」), written from 評価管理.
 * It lives on the AI-score row, so it needs a scored evaluation.
 */
export async function PATCH(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const id = Number((await ctx.params).id);
  if (!Number.isInteger(id)) return NextResponse.json({ error: "評価IDが不正です" }, { status: 400 });
  try {
    const { reviewNote } = (await request.json()) as { reviewNote?: string | null };
    const rows = await pgQuery(
      `UPDATE hr.eval_quantified_scores SET manual_note = $2, updated_at = NOW()
       WHERE evaluation_id = $1 RETURNING evaluation_id`,
      [id, reviewNote?.trim() || null]
    );
    if (rows.length === 0) return NextResponse.json({ error: "先にAI採点してください" }, { status: 400 });
    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("review note save error:", error);
    return NextResponse.json({ error: "保存に失敗しました" }, { status: 500 });
  }
}

/**
 * HR corrects the 5 axis scores from the cross-review screen.
 * Same rules and storage as the line manager's input: an axis that differs
 * from the AI needs a reason; an axis set back to the AI value loses its override.
 */
export async function PUT(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const id = Number((await ctx.params).id);
  if (!Number.isInteger(id)) return NextResponse.json({ error: "評価IDが不正です" }, { status: 400 });
  try {
    const { axes } = (await request.json()) as { axes?: AxisInputs };
    if (!axes) return NextResponse.json({ error: "修正内容がありません" }, { status: 400 });

    const [ev] = await pgQuery<{ EMPLOYEE_ID: number; PERIOD: string; POSITION_GRADE: string }>(
      `SELECT ev.employee_id AS "EMPLOYEE_ID", ev.period AS "PERIOD", p.grade AS "POSITION_GRADE"
       FROM hr.evaluations ev
       JOIN hr.employees e ON ev.employee_id = e.employee_id
       JOIN hr.positions p ON e.position_id = p.position_id
       WHERE ev.evaluation_id = $1`,
      [id]
    );
    if (!ev) return NextResponse.json({ error: "評価が見つかりません" }, { status: 404 });

    const current = await loadAxes(id);
    const ai = aiScoresOf(current.axes);
    if (!ai) return NextResponse.json({ error: "先にAI定量化を実行してください" }, { status: 400 });
    const applied = applyAxisInputs(ai, axes);
    if (!applied.ok) return NextResponse.json({ error: applied.error }, { status: 400 });

    for (const axis of SCORE_AXES) {
      if (applied.changed.includes(axis)) {
        await pgQuery(
          `INSERT INTO hr.eval_axis_overrides (evaluation_id, axis, ai_score, manager_score, reason, updated_by)
           VALUES ($1, $2, $3, $4, $5, $6)
           ON CONFLICT (evaluation_id, axis) DO UPDATE SET
             ai_score = EXCLUDED.ai_score, manager_score = EXCLUDED.manager_score,
             reason = EXCLUDED.reason, ai_changed = false,
             updated_by = EXCLUDED.updated_by, updated_at = NOW()`,
          [id, axis, ai[axis], applied.effective[axis], axes[axis]!.reason!.trim(), auth.user.username]
        );
      } else {
        await pgQuery(`DELETE FROM hr.eval_axis_overrides WHERE evaluation_id = $1 AND axis = $2`, [id, axis]);
      }
    }
    const saved = await saveScores({
      evaluationId: id, employeeId: ev.EMPLOYEE_ID, period: ev.PERIOD,
      positionGrade: ev.POSITION_GRADE, ai, effective: applied.effective,
    });
    await rerankPeriod(ev.PERIOD);
    console.log(`[evaluation] ${auth.user.username} corrected axes of eval ${id}: ${applied.changed.join(",") || "reset"}`);
    return NextResponse.json({ ok: true, standard_grade: saved.standardGrade });
  } catch (error) {
    console.error("hr axes save error:", error);
    return NextResponse.json({ error: "保存に失敗しました" }, { status: 500 });
  }
}
