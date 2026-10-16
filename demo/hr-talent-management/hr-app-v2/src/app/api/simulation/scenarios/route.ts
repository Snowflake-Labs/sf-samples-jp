import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET() {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const rows = await pgQuery(
    `SELECT s.scenario_id, s.scenario_name, s.created_by, s.created_at, s.status,
            COUNT(a.action_id) FILTER (WHERE a.status != 'revised') AS action_count,
            COUNT(a.action_id) FILTER (WHERE a.status = 'rejected') AS rejected_count,
            COUNT(a.action_id) FILTER (WHERE a.status = 'approved') AS approved_count
     FROM hr.whatif_scenarios s
     LEFT JOIN hr.whatif_scenario_actions a ON s.scenario_id = a.scenario_id
     GROUP BY s.scenario_id, s.scenario_name, s.created_by, s.created_at, s.status
     ORDER BY s.created_at DESC
     LIMIT 50`
  );

  return NextResponse.json(rows);
}
