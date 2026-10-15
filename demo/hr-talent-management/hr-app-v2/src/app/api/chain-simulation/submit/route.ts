import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { simulationId } = (await request.json()) as { simulationId: number };

    const [sim] = await pgQuery<{ status: string }>(
      `SELECT status FROM hr.chain_simulations WHERE simulation_id = $1`,
      [simulationId]
    );
    if (!sim) return NextResponse.json({ error: "Not found" }, { status: 404 });
    if (sim.status !== "draft" && sim.status !== "revision_requested") {
      return NextResponse.json({ error: `ステータス(${sim.status})ではレビュー依頼できません` }, { status: 400 });
    }

    await pgQuery(
      `UPDATE hr.chain_simulations SET status = 'pending_review', submitted_at = NOW() WHERE simulation_id = $1`,
      [simulationId]
    );
    await pgQuery(
      `UPDATE hr.chain_simulation_steps SET status = 'pending' WHERE simulation_id = $1 AND status NOT IN ('approved')`,
      [simulationId]
    );

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Chain submit error:", error);
    return NextResponse.json({ error: "レビュー依頼に失敗しました" }, { status: 500 });
  }
}
