import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET() {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const rows = await pgQuery(
    `SELECT s.simulation_id, s.simulation_name, s.trigger_type, s.status,
            s.created_at, s.finalized_at, s.submitted_at,
            COUNT(st.step_order) AS step_count,
            COUNT(st.step_order) FILTER (WHERE st.status = 'rejected') AS rejected_count,
            COUNT(st.step_order) FILTER (WHERE st.status = 'approved') AS approved_count
     FROM hr.chain_simulations s
     LEFT JOIN hr.chain_simulation_steps st ON s.simulation_id = st.simulation_id
     GROUP BY s.simulation_id
     ORDER BY s.created_at DESC
     LIMIT 50`
  );

  return NextResponse.json(rows);
}
