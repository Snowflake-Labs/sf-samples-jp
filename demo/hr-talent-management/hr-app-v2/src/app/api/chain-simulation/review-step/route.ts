import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { simulationId, stepOrder, decision, comment } = (await request.json()) as {
      simulationId: number;
      stepOrder: number;
      decision: "approved" | "rejected";
      comment?: string;
    };

    if (!simulationId || !stepOrder || !decision) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }
    if (decision === "rejected" && (!comment || !comment.trim())) {
      return NextResponse.json({ error: "差し戻し時はコメントが必須です" }, { status: 400 });
    }

    await pgQuery(
      `UPDATE hr.chain_simulation_steps
       SET status = $1, reviewer_comment = $2, reviewed_at = NOW()
       WHERE simulation_id = $3 AND step_order = $4`,
      [decision, comment || null, simulationId, stepOrder]
    );

    if (decision === "rejected") {
      await pgQuery(
        `UPDATE hr.chain_simulations SET status = 'revision_requested' WHERE simulation_id = $1 AND status = 'pending_review'`,
        [simulationId]
      );
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Chain review-step error:", error);
    return NextResponse.json({ error: "レビューに失敗しました" }, { status: 500 });
  }
}
