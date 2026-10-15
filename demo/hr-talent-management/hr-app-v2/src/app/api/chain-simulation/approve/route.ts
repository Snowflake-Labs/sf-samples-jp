import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  try {
    const { simulationId } = (await request.json()) as { simulationId: number };

    const [sim] = await pgQuery<{ status: string }>(
      `SELECT status FROM hr.chain_simulations WHERE simulation_id = $1`,
      [simulationId]
    );
    if (!sim) return NextResponse.json({ error: "Not found" }, { status: 404 });
    if (sim.status !== "pending_review") {
      return NextResponse.json({ error: `ステータス(${sim.status})では承認できません` }, { status: 400 });
    }

    const pending = await pgQuery<{ cnt: string }>(
      `SELECT COUNT(*) AS cnt FROM hr.chain_simulation_steps WHERE simulation_id = $1 AND status IN ('pending', 'rejected')`,
      [simulationId]
    );
    if (Number(pending[0].cnt) > 0) {
      return NextResponse.json({ error: "未レビューまたは差し戻し中のステップがあります" }, { status: 400 });
    }

    await pgQuery(
      `UPDATE hr.chain_simulations SET status = 'approved', resolved_at = NOW(), reviewer_id = $1 WHERE simulation_id = $2`,
      [user.employeeId, simulationId]
    );

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Chain approve error:", error);
    return NextResponse.json({ error: "承認に失敗しました" }, { status: 500 });
  }
}
