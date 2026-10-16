import { NextResponse } from "next/server";
import { query } from "@/lib/sf-client";
import { getSession } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { query: searchQuery } = await request.json();

    if (!searchQuery || typeof searchQuery !== "string" || searchQuery.length > 500) {
      return NextResponse.json({ error: "不正な検索クエリ" }, { status: 400 });
    }

    const sanitized = searchQuery.trim();
    if (!sanitized) {
      return NextResponse.json([]);
    }

    const searchParams = JSON.stringify({
      query: sanitized,
      columns: ["EMPLOYEE_ID", "EMPLOYEE_NAME", "DEPT_NAME", "POSITION_TITLE", "GRADE", "SKILLS_TEXT"],
      limit: 10,
    });

    const rows = await query(`
      SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
        'HR_ANALYTICS.PUBLIC.TALENT_SEARCH_SERVICE',
        ?
      ) AS RESULT
    `, [searchParams] as Binds);

    if (!rows || rows.length === 0) {
      return NextResponse.json([]);
    }

    const raw = (rows[0] as Record<string, unknown>).RESULT;
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    const results = (parsed.results || []).map((r: Record<string, unknown>) => ({
      EMPLOYEE_CODE: r.EMPLOYEE_ID || "",
      FULL_NAME: r.EMPLOYEE_NAME || "",
      DEPT_NAME: r.DEPT_NAME || "",
      POSITION_TITLE: r.POSITION_TITLE || "",
      GRADE: r.GRADE || "",
      SKILLS: r.SKILLS_TEXT || "",
    }));

    return NextResponse.json(results);
  } catch (error) {
    console.error("Search error:", error);
    return NextResponse.json({ error: "検索に失敗しました" }, { status: 500 });
  }
}
