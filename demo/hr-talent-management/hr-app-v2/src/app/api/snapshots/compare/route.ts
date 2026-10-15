import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(request.url);
  const aId = searchParams.get("a");
  const bId = searchParams.get("b");

  if (!aId || !bId) {
    return NextResponse.json({ error: "a and b snapshot IDs are required" }, { status: 400 });
  }

  const snaps = await pgQuery(
    `SELECT *, effective_date::text AS effective_date FROM hr.scenario_snapshots WHERE snapshot_id IN ($1, $2) ORDER BY snapshot_id`,
    [Number(aId), Number(bId)]
  );

  if (snaps.length < 2) {
    return NextResponse.json({ error: "1つ以上のスナップショットが見つかりません" }, { status: 404 });
  }

  return NextResponse.json({ a: snaps.find((s: Record<string, unknown>) => s.snapshot_id === Number(aId)), b: snaps.find((s: Record<string, unknown>) => s.snapshot_id === Number(bId)) });
}
