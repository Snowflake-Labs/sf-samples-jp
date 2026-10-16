import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { scenarioId } = (await request.json()) as { scenarioId: number };
    if (!scenarioId) {
      return NextResponse.json({ error: "scenarioId is required" }, { status: 400 });
    }

    const [scenario] = await pgQuery<{ status: string }>(
      `SELECT status FROM hr.whatif_scenarios WHERE scenario_id = $1`,
      [scenarioId]
    );
    if (!scenario) {
      return NextResponse.json({ error: "シナリオが見つかりません" }, { status: 404 });
    }
    if (scenario.status !== "draft" && scenario.status !== "revision_requested") {
      return NextResponse.json(
        { error: `現在のステータス(${scenario.status})ではレビュー依頼できません` },
        { status: 400 }
      );
    }

    await pgQuery(
      `UPDATE hr.whatif_scenarios
       SET status = 'pending_review', submitted_at = NOW()
       WHERE scenario_id = $1`,
      [scenarioId]
    );

    await pgQuery(
      `UPDATE hr.whatif_scenario_actions
       SET status = 'pending'
       WHERE scenario_id = $1 AND status NOT IN ('approved', 'revised')`,
      [scenarioId]
    );

    return NextResponse.json({ success: true, scenarioId });
  } catch (error) {
    console.error("Submit error:", error);
    return NextResponse.json({ error: "レビュー依頼に失敗しました" }, { status: 500 });
  }
}
