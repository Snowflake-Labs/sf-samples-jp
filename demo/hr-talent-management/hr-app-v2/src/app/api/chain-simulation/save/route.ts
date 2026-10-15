import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";

interface ChainStepPayload {
  vacantDeptId: number;
  vacantGrade: string;
  selectedEmployeeId: number;
  fromDeptId: number;
  fromGrade: string;
  matchScore: number | null;
  matchReason: string | null;
}

interface SavePayload {
  triggerType: string;
  triggerEmployeeId: number | null;
  triggerDeptId: number;
  triggerGrade: string;
  steps: ChainStepPayload[];
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const body: SavePayload = await request.json();
    const { triggerType, triggerEmployeeId, triggerDeptId, triggerGrade, steps } = body;

    if (!triggerDeptId || !triggerGrade || !steps || steps.length === 0) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    // 同じ社員がチェーン内で二度動く（循環を含む）保存を拒否する
    const moved = new Set<number>(triggerEmployeeId ? [triggerEmployeeId] : []);
    for (const st of steps) {
      if (moved.has(st.selectedEmployeeId)) {
        return NextResponse.json(
          { error: "同じ社員がチェーン内で複数回選ばれています" },
          { status: 400 }
        );
      }
      moved.add(st.selectedEmployeeId);
    }
    // 各ステップの空席は、直前に選ばれた人の元の席でなければならない
    for (let i = 1; i < steps.length; i++) {
      const prev = steps[i - 1];
      if (steps[i].vacantDeptId !== prev.fromDeptId || steps[i].vacantGrade !== prev.fromGrade) {
        return NextResponse.json(
          { error: `ステップ${i + 1}の空席が、前のステップで空いた席と一致しません` },
          { status: 400 }
        );
      }
    }

    const simResult = await pgQuery<{ simulation_id: number }>(
      `INSERT INTO hr.chain_simulations
        (simulation_name, trigger_type, trigger_employee_id, status)
       VALUES ($1, $2, $3, 'finalized')
       RETURNING simulation_id`,
      [`${triggerType}_${triggerDeptId}_${triggerGrade}`, triggerType, triggerEmployeeId || null]
    );
    const simId = simResult[0].simulation_id;

    if (steps.length > 0) {
      const valueSets: string[] = [];
      const stepParams: unknown[] = [];
      let pIdx = 1;
      for (let i = 0; i < steps.length; i++) {
        const s = steps[i];
        valueSets.push(`($${pIdx++}, $${pIdx++}, $${pIdx++}, $${pIdx++}, $${pIdx++}, $${pIdx++}, $${pIdx++})`);
        stepParams.push(simId, i + 1, s.selectedEmployeeId, s.fromDeptId, s.vacantDeptId, s.matchScore || null, s.matchReason || null);
      }
      await pgQuery(
        `INSERT INTO hr.chain_simulation_steps
          (simulation_id, step_order, employee_id, from_dept_id, to_dept_id, match_score, ai_comment)
         VALUES ${valueSets.join(", ")}`,
        stepParams
      );
    }

    await pgQuery(
      `UPDATE hr.chain_simulations SET finalized_at = NOW() WHERE simulation_id = $1`,
      [simId]
    );

    return NextResponse.json({ simulationId: simId, stepCount: steps.length });
  } catch (error) {
    console.error("Chain save error:", error);
    return NextResponse.json({ error: "Failed to save chain" }, { status: 500 });
  }
}
