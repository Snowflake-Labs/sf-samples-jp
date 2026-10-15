import { NextResponse } from "next/server";
import { getSession, requireRole } from "@/lib/session";
import { recalculatePeriod } from "@/lib/recalculate";

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  try {
    const body = await request.json().catch(() => ({}));
    const { period } = body as { period?: string };

    const result = await recalculatePeriod(period ?? null);

    console.log(
      `[recalculate] ${user.username} updated ${result.updated} rows (skipped ${result.skipped}) across ${result.periods.length} periods`
    );

    return NextResponse.json({
      ...result,
      note: "LLMは再実行していません。保存済みの絶対スコアから期待比のみ再計算しています。",
    });
  } catch (error) {
    console.error("Recalculate error:", error);
    return NextResponse.json({ error: "再計算に失敗しました" }, { status: 500 });
  }
}
