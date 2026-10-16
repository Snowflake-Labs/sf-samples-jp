import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET() {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const rows = await pgQuery(
    `SELECT snapshot_id, label, effective_date::text AS effective_date, snapshot_type, source_id, confirmed_by, confirmed_at,
            jsonb_array_length(CASE
              WHEN snapshot_type = 'whatif' THEN data_json->'actions'
              WHEN snapshot_type = 'chain' THEN data_json->'steps'
              ELSE '[]'::jsonb END) AS item_count
     FROM hr.scenario_snapshots
     ORDER BY confirmed_at DESC
     LIMIT 100`
  );

  return NextResponse.json(rows);
}
