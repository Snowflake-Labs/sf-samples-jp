import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { isEvaluationInScope } from "@/lib/scope";

/**
 * HR sends a submitted review back to the line manager with a reason.
 * The manager can then edit and resubmit.
 */
export async function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const id = Number((await ctx.params).id);
  if (!Number.isInteger(id)) return NextResponse.json({ error: "評価IDが不正です" }, { status: 400 });
  if (!(await isEvaluationInScope(auth.user, id))) return NextResponse.json({ error: "Evaluation not found" }, { status: 404 });
  try {
    const { reason } = (await request.json()) as { reason?: string };
    if (!reason || reason.trim().length < 5) {
      return NextResponse.json({ error: "差し戻し理由を5文字以上で入力してください" }, { status: 400 });
    }
    const rows = await pgQuery<{ STATUS: string }>(
      `SELECT status AS "STATUS" FROM hr.evaluations WHERE evaluation_id = $1`, [id]
    );
    if (rows.length === 0) return NextResponse.json({ error: "評価が見つかりません" }, { status: 404 });
    if (rows[0].STATUS !== "submitted") {
      return NextResponse.json({ error: "提出済みの評価だけ差し戻せます" }, { status: 409 });
    }
    await pgQuery(
      `UPDATE hr.evaluations SET status = 'draft', return_reason = $2, returned_at = NOW(), updated_at = NOW()
       WHERE evaluation_id = $1`,
      [id, `${reason.trim()}（${auth.user.displayName}）`]
    );
    console.log(`[evaluation] ${auth.user.username} returned eval ${id}`);
    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("return error:", error);
    return NextResponse.json({ error: "差し戻しに失敗しました" }, { status: 500 });
  }
}
