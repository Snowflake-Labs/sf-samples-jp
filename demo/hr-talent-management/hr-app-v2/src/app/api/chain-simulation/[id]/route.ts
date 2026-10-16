import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;
  const simId = Number(id);

  const [sim] = await pgQuery(
    `SELECT simulation_id, simulation_name, trigger_type, trigger_employee_id, status, finalized_at, submitted_at, resolved_at
     FROM hr.chain_simulations WHERE simulation_id = $1`,
    [simId]
  );
  if (!sim) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const steps = await pgQuery(
    `SELECT st.step_order, st.employee_id, st.from_dept_id, st.to_dept_id,
            st.match_score, st.ai_comment, st.status AS step_status,
            st.reviewer_comment, st.reviewed_at,
            e.last_name || ' ' || e.first_name AS employee_name, e.employee_code,
            fd.dept_name AS from_dept_name, td.dept_name AS to_dept_name,
            p.grade
     FROM hr.chain_simulation_steps st
     JOIN hr.employees e ON st.employee_id = e.employee_id
     LEFT JOIN hr.departments fd ON st.from_dept_id = fd.dept_id
     LEFT JOIN hr.departments td ON st.to_dept_id = td.dept_id
     LEFT JOIN hr.positions p ON e.position_id = p.position_id
     WHERE st.simulation_id = $1
     ORDER BY st.step_order`,
    [simId]
  );

  return NextResponse.json({ simulation: sim, steps });
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;
  const simId = Number(id);

  try {
    const { simulationName, steps } = (await request.json()) as {
      simulationName?: string;
      steps: { employeeId: number; fromDeptId: number; toDeptId: number; matchScore: number | null; aiComment: string | null }[];
    };

    const [sim] = await pgQuery<{ status: string }>(
      `SELECT status FROM hr.chain_simulations WHERE simulation_id = $1`,
      [simId]
    );
    if (!sim) return NextResponse.json({ error: "Not found" }, { status: 404 });
    if (sim.status !== "draft" && sim.status !== "revision_requested") {
      return NextResponse.json({ error: `ステータス(${sim.status})では編集できません` }, { status: 400 });
    }

    if (simulationName) {
      await pgQuery(`UPDATE hr.chain_simulations SET simulation_name = $1 WHERE simulation_id = $2`, [simulationName, simId]);
    }

    await pgQuery(`DELETE FROM hr.chain_simulation_steps WHERE simulation_id = $1`, [simId]);

    if (steps && steps.length > 0) {
      const vals: string[] = [];
      const p: unknown[] = [];
      let idx = 1;
      for (let i = 0; i < steps.length; i++) {
        const s = steps[i];
        vals.push(`($${idx++}, $${idx++}, $${idx++}, $${idx++}, $${idx++}, $${idx++}, $${idx++}, 'pending')`);
        p.push(simId, i + 1, s.employeeId, s.fromDeptId, s.toDeptId, s.matchScore, s.aiComment);
      }
      await pgQuery(
        `INSERT INTO hr.chain_simulation_steps (simulation_id, step_order, employee_id, from_dept_id, to_dept_id, match_score, ai_comment, status) VALUES ${vals.join(", ")}`,
        p
      );
    }

    await pgQuery(`UPDATE hr.chain_simulations SET status = 'draft' WHERE simulation_id = $1`, [simId]);

    return NextResponse.json({ success: true, simulationId: simId });
  } catch (error) {
    console.error("Chain update error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
