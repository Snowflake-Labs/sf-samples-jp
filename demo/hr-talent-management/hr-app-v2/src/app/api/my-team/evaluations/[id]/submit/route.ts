import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { deriveProgress, isEditable, loadAxes, loadOwnEvaluation } from "@/lib/my-team";
import { validateFinalGrade } from "@/lib/manager-override";

/**
 * Hand the review to HR. Everything must be in place: comment, AI scores,
 * a final grade, and a reason if the grade departs from the recommendation.
 */
export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["LINE_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const id = Number((await ctx.params).id);
  const ev = Number.isInteger(id) ? await loadOwnEvaluation(auth.user, id) : null;
  if (!ev) return NextResponse.json({ error: "評価が見つかりません" }, { status: 404 });
  if (!isEditable(deriveProgress(ev))) {
    return NextResponse.json({ error: "すでに提出済みです" }, { status: 409 });
  }
  try {
    const missing: string[] = [];
    if (!ev.COMMENT?.trim()) missing.push("上長コメント");
    const axes = await loadAxes(ev.EVALUATION_ID);
    if (!ev.AI_SCORED || !axes.standardGrade) missing.push("AI採点");
    if (!ev.GRADE) missing.push("最終グレード");
    if (missing.length > 0) {
      return NextResponse.json({ error: `提出前に次を入力してください: ${missing.join("、")}` }, { status: 400 });
    }
    if ((axes.aiInputComment ?? "").trim() !== (ev.COMMENT ?? "").trim()) {
      return NextResponse.json({ error: "AI採点のあとにコメントが変わっています。もう一度「AIで採点」してから提出してください" }, { status: 400 });
    }
    const err = validateFinalGrade(ev.GRADE!, axes.standardGrade!, ev.GRADE_REASON);
    if (err) return NextResponse.json({ error: err }, { status: 400 });

    const [eqs] = await pgQuery<{ COMPOSITE: string }>(
      `SELECT composite_score AS "COMPOSITE" FROM hr.eval_quantified_scores WHERE evaluation_id = $1`,
      [ev.EVALUATION_ID]
    );
    await pgQuery(
      `UPDATE hr.evaluations SET status = 'submitted', score = $2, submitted_at = NOW(), updated_at = NOW()
       WHERE evaluation_id = $1`,
      [ev.EVALUATION_ID, eqs ? Number(eqs.COMPOSITE) : null]
    );
    // A manager's grade change is the starting point for HR's cross review and calibration.
    await pgQuery(
      `UPDATE hr.eval_quantified_scores SET
         manual_grade = CASE WHEN $2::text <> standard_grade THEN $2 ELSE NULL END,
         manual_note = CASE WHEN $2::text <> standard_grade THEN $3 ELSE NULL END,
         updated_at = NOW()
       WHERE evaluation_id = $1`,
      [ev.EVALUATION_ID, ev.GRADE, ev.GRADE_REASON ? `[上長] ${ev.GRADE_REASON}` : null]
    );
    console.log(`[my-team] ${auth.user.username} submitted eval ${ev.EVALUATION_ID}`);
    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("submit error:", error);
    return NextResponse.json({ error: "提出に失敗しました" }, { status: 500 });
  }
}
