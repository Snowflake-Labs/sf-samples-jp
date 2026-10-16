import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;

  const [snap] = await pgQuery(
    `SELECT * FROM hr.scenario_snapshots WHERE snapshot_id = $1`,
    [Number(id)]
  );
  if (!snap) return NextResponse.json({ error: "Not found" }, { status: 404 });

  return NextResponse.json(snap);
}
