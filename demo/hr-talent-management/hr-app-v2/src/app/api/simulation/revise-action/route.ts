import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

interface RevisePayload {
  actionId: number;
  toDeptId: number;
  actionType: string;
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { actionId, toDeptId, actionType } = (await request.json()) as RevisePayload;

    if (!actionId) {
      return NextResponse.json({ error: "actionId is required" }, { status: 400 });
    }

    const [old] = await pgQuery<{
      action_id: number;
      scenario_id: number;
      employee_id: number;
      from_dept_id: number;
      to_dept_id: number;
      action_type: string;
      status: string;
    }>(
      `SELECT action_id, scenario_id, employee_id, from_dept_id, to_dept_id, action_type, status
       FROM hr.whatif_scenario_actions WHERE action_id = $1`,
      [actionId]
    );
    if (!old) {
      return NextResponse.json({ error: "アクションが見つかりません" }, { status: 404 });
    }
    if (old.status !== "rejected") {
      return NextResponse.json(
        { error: "差し戻し済みのアクションのみ修正できます" },
        { status: 400 }
      );
    }

    await pgQuery(
      `UPDATE hr.whatif_scenario_actions SET status = 'revised' WHERE action_id = $1`,
      [actionId]
    );

    const [newAction] = await pgQuery<{ action_id: number }>(
      `INSERT INTO hr.whatif_scenario_actions
        (scenario_id, employee_id, from_dept_id, to_dept_id, from_position_id, to_position_id, action_type, status, revised_from_id)
       VALUES ($1, $2, $3, $4, NULL, NULL, $5, 'pending', $6)
       RETURNING action_id`,
      [
        old.scenario_id,
        old.employee_id,
        old.from_dept_id,
        toDeptId ?? old.to_dept_id,
        actionType ?? old.action_type,
        old.action_id,
      ]
    );

    const remaining = await pgQuery<{ cnt: string }>(
      `SELECT COUNT(*) AS cnt FROM hr.whatif_scenario_actions
       WHERE scenario_id = $1 AND status = 'rejected'`,
      [old.scenario_id]
    );
    if (Number(remaining[0].cnt) === 0) {
      await pgQuery(
        `UPDATE hr.whatif_scenarios SET status = 'pending_review' WHERE scenario_id = $1`,
        [old.scenario_id]
      );
    }

    return NextResponse.json({ success: true, newActionId: newAction.action_id });
  } catch (error) {
    console.error("Revise action error:", error);
    return NextResponse.json({ error: "修正に失敗しました" }, { status: 500 });
  }
}
