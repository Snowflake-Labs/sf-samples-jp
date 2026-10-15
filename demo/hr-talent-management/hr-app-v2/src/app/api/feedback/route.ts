import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { page, rating, comment } = await request.json();
    if (!page || !rating || rating < 1 || rating > 5) {
      return NextResponse.json({ error: "Invalid input" }, { status: 400 });
    }
    await pgQuery(
      `INSERT INTO hr.user_feedback (page, rating, comment, user_id) VALUES ($1, $2, $3, $4)`,
      [page, rating, comment || null, session.username]
    );
    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("Feedback error:", error);
    return NextResponse.json({ error: "Failed to save feedback" }, { status: 500 });
  }
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const page = searchParams.get("page");
    let sql = `SELECT page, COUNT(*) AS count, ROUND(AVG(rating), 1) AS avg_rating FROM hr.user_feedback`;
    const params: unknown[] = [];
    if (page) {
      sql += ` WHERE page = $1`;
      params.push(page);
    }
    sql += ` GROUP BY page ORDER BY page`;
    const results = await pgQuery(sql, params);
    return NextResponse.json(results);
  } catch (error) {
    console.error("Feedback fetch error:", error);
    return NextResponse.json({ error: "Failed to fetch feedback" }, { status: 500 });
  }
}
