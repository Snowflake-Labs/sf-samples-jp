import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

interface ReviewPayload {
  actionId: number;
  decision: "approved" | "rejected";
  comment?: string;
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { actionId, decision, comment } = (await request.json()) as ReviewPayload;

    if (!actionId || !decision) {
      return NextResponse.json({ error: "actionId and decision are required" }, { status: 400 });
    }
    if (decision === "rejected" && (!comment || comment.trim().length === 0)) {
      return NextResponse.json({ error: "差し戻し時はコメントが必須です" }, { status: 400 });
    }

    const [action] = await pgQuery<{ status: string; scenario_id: number }>(
      `SELECT status, scenario_id FROM hr.whatif_scenario_actions WHERE action_id = $1`,
      [actionId]
    );
    if (!action) {
      return NextResponse.json({ error: "アクションが見つかりません" }, { status: 404 });
    }
    if (action.status !== "pending") {
      return NextResponse.json(
        { error: `現在のステータス(${action.status})ではレビューできません` },
        { status: 400 }
      );
    }

    await pgQuery(
      `UPDATE hr.whatif_scenario_actions
       SET status = $1, reviewer_comment = $2, reviewed_at = NOW()
       WHERE action_id = $3`,
      [decision, comment || null, actionId]
    );

    if (decision === "rejected") {
      await pgQuery(
        `UPDATE hr.whatif_scenarios
         SET status = 'revision_requested'
         WHERE scenario_id = $1 AND status = 'pending_review'`,
        [action.scenario_id]
      );
    }

    return NextResponse.json({ success: true, actionId, decision });
  } catch (error) {
    console.error("Review action error:", error);
    return NextResponse.json({ error: "レビュー処理に失敗しました" }, { status: 500 });
  }
}
