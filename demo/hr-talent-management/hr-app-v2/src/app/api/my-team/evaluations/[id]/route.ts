import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import {
  aiScoresOf, deriveProgress, isEditable, loadAxes, loadOwnEvaluation, standardFor,
} from "@/lib/my-team";
import { allowedGrades, applyAxisInputs, validateFinalGrade, type AxisInputs } from "@/lib/manager-override";
import { rerankPeriod, saveScores } from "@/lib/recalculate";
import { SCORE_AXES } from "@/lib/scoring";

type Ctx = { params: Promise<{ id: string }> };

async function authorize(ctx: Ctx) {
  const session = await getSession();
  const auth = requireRole(session, ["LINE_MANAGER"]);
  if (!auth.ok) return { error: NextResponse.json(auth.body, { status: auth.status }) };
  const id = Number((await ctx.params).id);
  if (!Number.isInteger(id)) return { error: NextResponse.json({ error: "評価IDが不正です" }, { status: 400 }) };
  const ev = await loadOwnEvaluation(auth.user, id);
  // Same 404 for "not found" and "not your team", so other teams can't be probed.
  if (!ev) return { error: NextResponse.json({ error: "評価が見つかりません" }, { status: 404 }) };
  return { user: auth.user, ev };
}

/** Everything the input screen needs for one member. */
export async function GET(_req: Request, ctx: Ctx) {
  const a = await authorize(ctx);
  if ("error" in a) return a.error;
  const { ev } = a;
  try {
    const axes = await loadAxes(ev.EVALUATION_ID);
    const standard = await standardFor(ev.POSITION_GRADE);
    // Last period's review, for context ("前期はどうだったか")
    const [prev] = await pgQuery<{ PERIOD: string; GRADE: string | null; COMMENT: string | null; SCORE: string | null }>(
      `SELECT period AS "PERIOD", grade AS "GRADE", comment AS "COMMENT", score AS "SCORE"
       FROM hr.evaluations WHERE employee_id = $1 AND period < $2
       ORDER BY period DESC LIMIT 1`,
      [ev.EMPLOYEE_ID, ev.PERIOD]
    );
    const progress = deriveProgress(ev);
    return NextResponse.json({
      evaluation: ev,
      progress,
      editable: isEditable(progress),
      ...axes,
      standard,
      previous: prev ?? null,
      allowedGrades: axes.standardGrade ? allowedGrades(axes.standardGrade) : [],
    });
  } catch (error) {
    console.error("my-team detail error:", error);
    return NextResponse.json({ error: "評価の取得に失敗しました" }, { status: 500 });
  }
}

/**
 * Save a draft: comment, per-axis corrections, final grade.
 * Axis corrections need AI scores first; the comment can be saved any time.
 */
export async function PUT(request: Request, ctx: Ctx) {
  const a = await authorize(ctx);
  if ("error" in a) return a.error;
  const { ev, user } = a;
  const progress = deriveProgress(ev);
  if (!isEditable(progress)) {
    return NextResponse.json({ error: "提出済みのため編集できません。人事の差し戻しを待ってください" }, { status: 409 });
  }
  try {
    const body = (await request.json()) as {
      comment?: string;
      axes?: AxisInputs;
      final_grade?: string | null;
      grade_reason?: string | null;
    };

    if (typeof body.comment === "string") {
      await pgQuery(
        `UPDATE hr.evaluations SET comment = $2, updated_at = NOW() WHERE evaluation_id = $1`,
        [ev.EVALUATION_ID, body.comment.trim() || null]
      );
    }

    let recommended: string | null = null;
    if (body.axes) {
      const current = await loadAxes(ev.EVALUATION_ID);
      const ai = aiScoresOf(current.axes);
      if (!ai) {
        return NextResponse.json({ error: "先に「AIで採点」を実行してください" }, { status: 400 });
      }
      const applied = applyAxisInputs(ai, body.axes);
      if (!applied.ok) return NextResponse.json({ error: applied.error }, { status: 400 });

      // Replace the override set: axes back at the AI value lose their override.
      for (const axis of SCORE_AXES) {
        if (applied.changed.includes(axis)) {
          await pgQuery(
            `INSERT INTO hr.eval_axis_overrides (evaluation_id, axis, ai_score, manager_score, reason, updated_by)
             VALUES ($1, $2, $3, $4, $5, $6)
             ON CONFLICT (evaluation_id, axis) DO UPDATE SET
               ai_score = EXCLUDED.ai_score, manager_score = EXCLUDED.manager_score,
               reason = EXCLUDED.reason, ai_changed = false,
               updated_by = EXCLUDED.updated_by, updated_at = NOW()`,
            [ev.EVALUATION_ID, axis, ai[axis], applied.effective[axis], body.axes[axis]!.reason!.trim(), user.username]
          );
        } else {
          await pgQuery(`DELETE FROM hr.eval_axis_overrides WHERE evaluation_id = $1 AND axis = $2`, [ev.EVALUATION_ID, axis]);
        }
      }
      const saved = await saveScores({
        evaluationId: ev.EVALUATION_ID, employeeId: ev.EMPLOYEE_ID, period: ev.PERIOD,
        positionGrade: ev.POSITION_GRADE, ai, effective: applied.effective,
      });
      recommended = saved.standardGrade;
      await rerankPeriod(ev.PERIOD);
    }

    if (body.final_grade !== undefined) {
      recommended = recommended ?? (await loadAxes(ev.EVALUATION_ID)).standardGrade;
      if (body.final_grade && recommended) {
        const err = validateFinalGrade(body.final_grade, recommended, body.grade_reason);
        if (err) return NextResponse.json({ error: err }, { status: 400 });
      }
      await pgQuery(
        `UPDATE hr.evaluations SET grade = $2, grade_reason = $3, updated_at = NOW() WHERE evaluation_id = $1`,
        [ev.EVALUATION_ID, body.final_grade || null,
         body.final_grade && body.final_grade !== recommended ? body.grade_reason?.trim() || null : null]
      );
    }

    return NextResponse.json({ ok: true, standard_grade: recommended });
  } catch (error) {
    console.error("my-team save error:", error);
    return NextResponse.json({ error: "保存に失敗しました" }, { status: 500 });
  }
}
