import { NextResponse } from "next/server";
import { pool } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  const client = await pool.connect();
  try {
    const { simulationId, label, effectiveDate, force } = (await request.json()) as {
      simulationId: number;
      label: string;
      effectiveDate: string;
      force?: boolean;
    };

    if (!simulationId || !label || !effectiveDate) {
      return NextResponse.json({ error: "simulationId, label, effectiveDate are required" }, { status: 400 });
    }

    await client.query("BEGIN");

    const { rows: [sim] } = await client.query<{ status: string; simulation_name: string }>(
      `SELECT status, simulation_name FROM hr.chain_simulations WHERE simulation_id = $1 FOR UPDATE`,
      [simulationId]
    );
    if (!sim) { await client.query("ROLLBACK"); return NextResponse.json({ error: "Not found" }, { status: 404 }); }
    if (sim.status !== "approved") { await client.query("ROLLBACK"); return NextResponse.json({ error: "承認済みのチェーンのみ確定できます" }, { status: 400 }); }

    // B3: detect employees already committed in another active scenario or chain
    const { rows: conflicts } = await client.query<{
      employee_id: number; employee_name: string; source: string; source_name: string;
    }>(
      `WITH target_emps AS (
         SELECT employee_id FROM hr.chain_simulation_steps
         WHERE simulation_id = $1 AND status = 'approved'
       )
       SELECT a.employee_id,
              e.last_name || ' ' || e.first_name AS employee_name,
              'whatif' AS source, s.scenario_name AS source_name
       FROM hr.whatif_scenario_actions a
       JOIN hr.whatif_scenarios s ON a.scenario_id = s.scenario_id
       JOIN hr.employees e ON a.employee_id = e.employee_id
       WHERE a.employee_id IN (SELECT employee_id FROM target_emps)
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
         AND st.simulation_id <> $1
         AND c.status IN ('approved', 'confirmed')
         AND st.status = 'approved'`,
      [simulationId]
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

    const { rows: steps } = await client.query(
      `SELECT st.step_order, st.employee_id, st.from_dept_id, st.to_dept_id, st.match_score, st.ai_comment,
              e.last_name || ' ' || e.first_name AS employee_name, e.employee_code,
              fd.dept_name AS from_dept_name, fd.dept_code AS from_dept_code,
              td.dept_name AS to_dept_name, td.dept_code AS to_dept_code,
              p.grade
       FROM hr.chain_simulation_steps st
       JOIN hr.employees e ON st.employee_id = e.employee_id
       LEFT JOIN hr.departments fd ON st.from_dept_id = fd.dept_id
       LEFT JOIN hr.departments td ON st.to_dept_id = td.dept_id
       LEFT JOIN hr.positions p ON e.position_id = p.position_id
       WHERE st.simulation_id = $1
       ORDER BY st.step_order`,
      [simulationId]
    );

    const { rows: [snap] } = await client.query<{ snapshot_id: number }>(
      `INSERT INTO hr.scenario_snapshots (label, effective_date, snapshot_type, source_id, confirmed_by, data_json)
       VALUES ($1, $2, 'chain', $3, $4, $5)
       RETURNING snapshot_id`,
      [label, effectiveDate, simulationId, user.displayName, JSON.stringify({
        simulation: sim.simulation_name,
        steps,
        ...(conflicts.length > 0 ? { forcedOverrideConflicts: conflicts } : {}),
      })]
    );

    await client.query(
      `UPDATE hr.chain_simulations SET status = 'confirmed', resolved_at = NOW() WHERE simulation_id = $1`,
      [simulationId]
    );

    await client.query("COMMIT");
    return NextResponse.json({
      success: true,
      snapshotId: snap.snapshot_id,
      ...(conflicts.length > 0 ? { forcedWithConflicts: conflicts.length } : {}),
    });
  } catch (error) {
    await client.query("ROLLBACK");
    console.error("Chain confirm error:", error);
    return NextResponse.json({ error: "確定に失敗しました" }, { status: 500 });
  } finally {
    client.release();
  }
}
