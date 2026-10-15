import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;

  const [scenario] = await pgQuery(
    `SELECT scenario_id, scenario_name, created_by, created_at, status, reviewer_id, submitted_at, resolved_at
     FROM hr.whatif_scenarios WHERE scenario_id = $1`,
    [Number(id)]
  );

  if (!scenario) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const actions = await pgQuery(
    `SELECT a.action_id, a.employee_id, a.action_type, a.from_dept_id, a.to_dept_id,
            a.status AS action_status, a.reviewer_comment, a.reviewed_at, a.revised_from_id,
            -- 画面の他の箇所（組織ツリー等）と同じく姓名を空白なしで連結する
            e.last_name || e.first_name AS employee_name,
            e.salary, e.position_id, a.match_score, a.match_reason,
            e.employee_code,
            fd.dept_name AS from_dept_name,
            td.dept_name AS to_dept_name,
            COALESCE(a.from_grade, p.grade) AS grade,
            a.to_grade,
            COALESCE(ev.avg_eval, 0) AS avg_eval,
            EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS tenure_years,
            COALESCE(pr.risk_score, 0) AS attrition_risk
     FROM hr.whatif_scenario_actions a
     JOIN hr.employees e ON a.employee_id = e.employee_id
     LEFT JOIN hr.departments fd ON a.from_dept_id = fd.dept_id
     LEFT JOIN hr.departments td ON a.to_dept_id = td.dept_id
     LEFT JOIN hr.positions p ON e.position_id = p.position_id
     LEFT JOIN (SELECT employee_id, ROUND(AVG(score)::numeric, 2)::float AS avg_eval FROM hr.evaluations GROUP BY employee_id) ev ON ev.employee_id = e.employee_id
     -- prediction_results keeps one row per run; take only the latest so
     -- actions are not duplicated
     LEFT JOIN LATERAL (
       SELECT risk_score FROM hr_lake.prediction_results
       WHERE employee_id = e.employee_id ORDER BY run_date DESC LIMIT 1
     ) pr ON TRUE
     WHERE a.scenario_id = $1 AND a.status != 'revised'
     ORDER BY a.action_id`,
    [Number(id)]
  );

  return NextResponse.json({ scenario, actions });
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;
  const scenarioId = Number(id);

  try {
    const { scenarioName, actions } = (await request.json()) as {
      scenarioName?: string;
      actions: { type: string; employeeId: number; fromDeptId: number; toDeptId: number | null }[];
    };

    const [scenario] = await pgQuery<{ status: string }>(
      `SELECT status FROM hr.whatif_scenarios WHERE scenario_id = $1`,
      [scenarioId]
    );
    if (!scenario) return NextResponse.json({ error: "Not found" }, { status: 404 });
    if (scenario.status !== "draft" && scenario.status !== "revision_requested") {
      return NextResponse.json({ error: `ステータス(${scenario.status})では編集できません` }, { status: 400 });
    }

    if (scenarioName) {
      await pgQuery(`UPDATE hr.whatif_scenarios SET scenario_name = $1 WHERE scenario_id = $2`, [scenarioName, scenarioId]);
    }

    // Delete non-revised actions and re-insert
    await pgQuery(`DELETE FROM hr.whatif_scenario_actions WHERE scenario_id = $1 AND status != 'revised'`, [scenarioId]);

    if (actions && actions.length > 0) {
      const vals: string[] = [];
      const p: unknown[] = [];
      let idx = 1;
      for (const a of actions) {
        vals.push(`($${idx++}, $${idx++}, $${idx++}, $${idx++}, NULL, NULL, $${idx++}, 'pending')`);
        p.push(scenarioId, a.employeeId, a.fromDeptId, a.toDeptId || null, a.type);
      }
      await pgQuery(
        `INSERT INTO hr.whatif_scenario_actions (scenario_id, employee_id, from_dept_id, to_dept_id, from_position_id, to_position_id, action_type, status) VALUES ${vals.join(", ")}`,
        p
      );
    }

    await pgQuery(`UPDATE hr.whatif_scenarios SET status = 'draft' WHERE scenario_id = $1`, [scenarioId]);

    return NextResponse.json({ success: true, scenarioId });
  } catch (error) {
    console.error("Scenario update error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
