import { NextResponse } from "next/server";
import { pgQuery, pool } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  const client = await pool.connect();
  try {
    const { scenarioId, label, effectiveDate, force } = (await request.json()) as {
      scenarioId: number;
      label: string;
      effectiveDate: string;
      force?: boolean;
    };

    if (!scenarioId || !label || !effectiveDate) {
      return NextResponse.json({ error: "scenarioId, label, effectiveDate are required" }, { status: 400 });
    }

    await client.query("BEGIN");

    const { rows: [scenario] } = await client.query<{ status: string; scenario_name: string }>(
      `SELECT status, scenario_name FROM hr.whatif_scenarios WHERE scenario_id = $1 FOR UPDATE`,
      [scenarioId]
    );
    if (!scenario) { await client.query("ROLLBACK"); return NextResponse.json({ error: "シナリオが見つかりません" }, { status: 404 }); }
    if (scenario.status !== "approved") { await client.query("ROLLBACK"); return NextResponse.json({ error: "承認済みのシナリオのみ確定できます" }, { status: 400 }); }

    // B3: detect employees already committed in another active scenario or chain
    const { rows: conflicts } = await client.query<{
      employee_id: number; employee_name: string; source: string; source_name: string;
    }>(
      `WITH target_emps AS (
         SELECT employee_id FROM hr.whatif_scenario_actions
         WHERE scenario_id = $1 AND status = 'approved'
       )
       SELECT a.employee_id,
              e.last_name || ' ' || e.first_name AS employee_name,
              'whatif' AS source, s.scenario_name AS source_name
       FROM hr.whatif_scenario_actions a
       JOIN hr.whatif_scenarios s ON a.scenario_id = s.scenario_id
       JOIN hr.employees e ON a.employee_id = e.employee_id
       WHERE a.employee_id IN (SELECT employee_id FROM target_emps)
         AND a.scenario_id <> $1
         AND s.status IN ('approved', 'confirmed')
         AND a.status = 'approved'
       UNION ALL
       SELECT st.employee_id,
              e.last_name || ' ' || e.first_name AS employee_name,
              'chain' AS source, c.simulation_name AS source_name
       FROM hr.chain_simulation_steps st
       JOIN hr.chain_simulations c ON st.simulation_id = c.simulation_id
       JOIN hr.employees e ON st.employee_id = e.employee_id
       WHERE st.employee_id IN (SELECT employee_id FROM target_emps)
         AND c.status IN ('approved', 'confirmed')
         AND st.status = 'approved'`,
      [scenarioId]
    );

    if (conflicts.length > 0 && !force) {
      await client.query("ROLLBACK");
      return NextResponse.json({
        error: "他のシナリオで既に確定/承認済みの社員が含まれています",
        code: "DUPLICATE_EMPLOYEE",
        conflicts: conflicts.map((c) => ({
          employeeId: c.employee_id,
          employeeName: c.employee_name,
          source: c.source === "chain" ? "玉突きシミュレーション" : "異動シナリオ",
          sourceName: c.source_name,
        })),
      }, { status: 409 });
    }

    const { rows: actions } = await client.query(
      `SELECT a.action_id, a.employee_id, a.action_type, a.from_dept_id, a.to_dept_id,
              e.last_name || ' ' || e.first_name AS employee_name, e.employee_code,
              fd.dept_name AS from_dept_name, fd.dept_code AS from_dept_code,
              td.dept_name AS to_dept_name, td.dept_code AS to_dept_code,
              -- 保存時の等級を優先する。現職位の等級は保存後に変わりうるうえ、
              -- 着任等級（昇格先）は現職位からは分からない
              COALESCE(a.from_grade, p.grade) AS from_grade,
              COALESCE(a.to_grade, CASE WHEN a.action_type = 'transfer' THEN COALESCE(a.from_grade, p.grade) END) AS to_grade
       FROM hr.whatif_scenario_actions a
       JOIN hr.employees e ON a.employee_id = e.employee_id
       LEFT JOIN hr.departments fd ON a.from_dept_id = fd.dept_id
       LEFT JOIN hr.departments td ON a.to_dept_id = td.dept_id
       LEFT JOIN hr.positions p ON e.position_id = p.position_id
       WHERE a.scenario_id = $1 AND a.status = 'approved'
       ORDER BY a.action_id`,
      [scenarioId]
    );

    const { rows: [snap] } = await client.query<{ snapshot_id: number }>(
      `INSERT INTO hr.scenario_snapshots (label, effective_date, snapshot_type, source_id, confirmed_by, data_json)
       VALUES ($1, $2, 'whatif', $3, $4, $5)
       RETURNING snapshot_id`,
      [label, effectiveDate, scenarioId, user.displayName, JSON.stringify({
        scenario: scenario.scenario_name,
        actions,
        ...(conflicts.length > 0 ? { forcedOverrideConflicts: conflicts } : {}),
      })]
    );

    await client.query(
      `UPDATE hr.whatif_scenarios SET status = 'confirmed', resolved_at = NOW() WHERE scenario_id = $1`,
      [scenarioId]
    );

    await client.query("COMMIT");
    return NextResponse.json({
      success: true,
      snapshotId: snap.snapshot_id,
      ...(conflicts.length > 0 ? { forcedWithConflicts: conflicts.length } : {}),
    });
  } catch (error) {
    await client.query("ROLLBACK");
    console.error("Confirm error:", error);
    return NextResponse.json({ error: "確定に失敗しました" }, { status: 500 });
  } finally {
    client.release();
  }
}
