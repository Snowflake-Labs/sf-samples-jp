import { NextResponse } from "next/server";
import { pgQuery, pool } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
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
    if (scenario.status !== "pending_review") {
      return NextResponse.json(
        { error: `現在のステータス(${scenario.status})では最終承認できません` },
        { status: 400 }
      );
    }

    const pendingOrRejected = await pgQuery<{ cnt: string }>(
      `SELECT COUNT(*) AS cnt FROM hr.whatif_scenario_actions
       WHERE scenario_id = $1 AND status IN ('pending', 'rejected')`,
      [scenarioId]
    );
    if (Number(pendingOrRejected[0].cnt) > 0) {
      return NextResponse.json(
        { error: "未レビューまたは差し戻し中のアクションがあります" },
        { status: 400 }
      );
    }

    // 承認と異動申請の登録は一緒に成功させる。片方だけ通ると承認済みなのに申請がない状態になる
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        `UPDATE hr.whatif_scenarios
         SET status = 'approved', resolved_at = NOW(), reviewer_id = $1
         WHERE scenario_id = $2`,
        [user.employeeId, scenarioId]
      );

      // transfer_requests へ確定レコードをINSERT。退職は異動先がないので対象外
      await client.query(
        `INSERT INTO hr.transfer_requests
          (employee_id, from_dept_id, to_dept_id, from_position_id, to_position_id, reason, status, requested_by, approved_by, resolved_at)
         SELECT
           a.employee_id, a.from_dept_id, a.to_dept_id, a.from_position_id, a.to_position_id,
           s.description, 'approved', $1, $1, NOW()
         FROM hr.whatif_scenario_actions a
         JOIN hr.whatif_scenarios s ON a.scenario_id = s.scenario_id
         WHERE a.scenario_id = $2 AND a.status = 'approved' AND a.to_dept_id IS NOT NULL`,
        [user.employeeId, scenarioId]
      );
      await client.query("COMMIT");
    } catch (e) {
      await client.query("ROLLBACK");
      throw e;
    } finally {
      client.release();
    }

    return NextResponse.json({ success: true, scenarioId });
  } catch (error) {
    console.error("Approve scenario error:", error);
    return NextResponse.json({ error: "最終承認に失敗しました" }, { status: 500 });
  }
}
