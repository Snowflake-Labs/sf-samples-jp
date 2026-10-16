import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { buildVacancyLedger, type LedgerActionType } from "@/lib/vacancy-ledger";

interface ActionPayload {
  type: string;
  employeeId: number;
  employeeName: string;
  fromGrade: string;
  toGrade: string | null;
  fromDeptId: number;
  toDeptId: number | null;
  fromDeptName: string;
  toDeptName: string | null;
  matchScore: number | null;
  matchReason: string | null;
}

interface SavePayload {
  scenarioName: string;
  honbuDeptId: number;
  actions: ActionPayload[];
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const body: SavePayload = await request.json();
    const { scenarioName, honbuDeptId, actions } = body;

    if (!honbuDeptId || !actions || actions.length === 0) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    // 画面と同じ台帳でサーバー側でも検証する。画面を経由しない呼び出しで
    // 二重充足や同一社員の重複を保存させないため。
    const VALID_TYPES: LedgerActionType[] = ["promote", "transfer", "retire"];
    if (actions.some((a) => !VALID_TYPES.includes(a.type as LedgerActionType))) {
      return NextResponse.json({ error: "不正なアクション種別が含まれています" }, { status: 400 });
    }
    const seen = new Set<number>();
    for (const a of actions) {
      if (seen.has(a.employeeId)) {
        return NextResponse.json(
          { error: `${a.employeeName} が複数回登場しています。1つのシナリオで同じ社員は1回しか動かせません` },
          { status: 400 }
        );
      }
      seen.add(a.employeeId);
    }

    const deptIds = [...new Set(actions.flatMap((a) => [a.fromDeptId, ...(a.toDeptId ? [a.toDeptId] : [])]))];
    const existing = await pgQuery<{ position_id: number; title: string; dept_id: number; dept_name: string; grade: string }>(
      `SELECT p.position_id, p.title, p.dept_id, d.dept_name, p.grade
       FROM hr.positions p LEFT JOIN hr.departments d ON p.dept_id = d.dept_id
       WHERE p.is_vacant = true AND p.dept_id = ANY($1::int[])`,
      [deptIds]
    );
    const ledger = buildVacancyLedger(
      actions.map((a, i) => ({
        id: String(i),
        type: a.type as LedgerActionType,
        employeeId: a.employeeId,
        employeeName: a.employeeName,
        fromDeptId: a.fromDeptId,
        fromDeptName: a.fromDeptName,
        fromGrade: a.fromGrade,
        toDeptId: a.toDeptId ?? undefined,
        toDeptName: a.toDeptName ?? undefined,
        toGrade: a.toGrade ?? undefined,
      })),
      existing.map((v) => ({
        positionId: v.position_id, title: v.title, deptId: v.dept_id, deptName: v.dept_name, grade: v.grade,
      }))
    );
    if (ledger.overfills.length > 0) {
      const o = ledger.overfills[0];
      return NextResponse.json(
        {
          error: `${o.employeeName} の異動先 ${o.deptName} ${o.grade} に空いている枠がありません`,
          overfills: ledger.overfills,
        },
        { status: 400 }
      );
    }

    const scenResult = await pgQuery<{ scenario_id: number }>(
      `INSERT INTO hr.whatif_scenarios (scenario_name, description, created_by)
       VALUES ($1, $2, 'app')
       RETURNING scenario_id`,
      [scenarioName || "What-ifシナリオ", `本部ID:${honbuDeptId}, ${actions.length}件`]
    );
    const scenarioId = scenResult[0].scenario_id;

    if (actions.length > 0) {
      const valueSets: string[] = [];
      const actionParams: unknown[] = [];
      let pIdx = 1;
      for (const a of actions) {
        valueSets.push(`($${pIdx++}, $${pIdx++}, $${pIdx++}, $${pIdx++}, NULL, NULL, $${pIdx++}, $${pIdx++}, $${pIdx++}, $${pIdx++}, $${pIdx++})`);
        // Grades are stored so a reloaded scenario can rebuild the vacancy chain
        actionParams.push(scenarioId, a.employeeId, a.fromDeptId, a.toDeptId || null, a.type, a.fromGrade || null, a.toGrade || null,
          a.matchScore == null ? null : Math.round(a.matchScore), a.matchReason || null);
      }
      await pgQuery(
        `INSERT INTO hr.whatif_scenario_actions
          (scenario_id, employee_id, from_dept_id, to_dept_id, from_position_id, to_position_id, action_type, from_grade, to_grade, match_score, match_reason)
         VALUES ${valueSets.join(", ")}`,
        actionParams
      );
    }

    return NextResponse.json({ scenarioId, actionCount: actions.length });
  } catch (error) {
    console.error("Scenario save error:", error);
    return NextResponse.json({ error: "Failed to save scenario" }, { status: 500 });
  }
}
