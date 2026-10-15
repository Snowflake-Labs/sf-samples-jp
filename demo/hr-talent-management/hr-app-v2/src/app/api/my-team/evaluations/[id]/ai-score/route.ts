import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { deriveProgress, isEditable, loadOwnEvaluation } from "@/lib/my-team";
import { AI_MODEL, scoreChunk, toAxisScores } from "@/lib/ai-scoring";
import { mergeWithOverrides, rerankPeriod, saveScores } from "@/lib/recalculate";

/**
 * "AIで採点" for one member. Saves the comment first so the AI reads
 * exactly what the manager sees on screen.
 */
export async function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["LINE_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const id = Number((await ctx.params).id);
  const ev = Number.isInteger(id) ? await loadOwnEvaluation(auth.user, id) : null;
  if (!ev) return NextResponse.json({ error: "評価が見つかりません" }, { status: 404 });
  if (!isEditable(deriveProgress(ev))) {
    return NextResponse.json({ error: "提出済みのため再採点できません" }, { status: 409 });
  }
  try {
    const { comment } = (await request.json().catch(() => ({}))) as { comment?: string };
    const text = (comment ?? ev.COMMENT ?? "").trim();
    // Too short and the AI is guessing; ask for something concrete.
    if (text.length < 20) {
      return NextResponse.json(
        { error: "上長コメントを20文字以上で書いてから採点してください（具体的な行動・成果があると精度が上がります）" },
        { status: 400 }
      );
    }
    await pgQuery(`UPDATE hr.evaluations SET comment = $2, updated_at = NOW() WHERE evaluation_id = $1`, [ev.EVALUATION_ID, text]);

    const scored = await scoreChunk([{ EVALUATION_ID: ev.EVALUATION_ID, COMMENT: text, SELF_COMMENT: ev.SELF_COMMENT }]);
    const ai = scored.get(ev.EVALUATION_ID);
    if (!ai) return NextResponse.json({ error: "AIの応答を読み取れませんでした。もう一度お試しください" }, { status: 502 });

    const actual = toAxisScores(ai);
    const effective = await mergeWithOverrides(ev.EVALUATION_ID, actual);
    const saved = await saveScores({
      evaluationId: ev.EVALUATION_ID, employeeId: ev.EMPLOYEE_ID, period: ev.PERIOD,
      positionGrade: ev.POSITION_GRADE, ai: actual, effective,
      reasoning: ai.reasoning, modelVersion: AI_MODEL,
    });
    await rerankPeriod(ev.PERIOD);
    await pgQuery(
      `UPDATE hr.eval_quantified_scores SET ai_input_comment = $2 WHERE evaluation_id = $1`,
      [ev.EVALUATION_ID, text]
    );
    return NextResponse.json({ ok: true, ai: actual, effective, standard_grade: saved.standardGrade });
  } catch (error) {
    console.error("my-team ai-score error:", error);
    return NextResponse.json({ error: "AI採点に失敗しました" }, { status: 500 });
  }
}
