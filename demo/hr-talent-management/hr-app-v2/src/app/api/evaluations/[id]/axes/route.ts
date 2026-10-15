import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { aiScoresOf, loadAxes } from "@/lib/my-team";
import { applyAxisInputs, type AxisInputs } from "@/lib/manager-override";
import { rerankPeriod, saveScores } from "@/lib/recalculate";
import { SCORE_AXES } from "@/lib/scoring";

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
