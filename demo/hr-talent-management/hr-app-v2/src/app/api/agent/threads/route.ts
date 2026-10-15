import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const rows = await pgQuery(
      `SELECT thread_id AS "THREAD_ID", title AS "TITLE",
        created_at AS "CREATED_AT", updated_at AS "UPDATED_AT",
        COALESCE(messages, '[]'::jsonb) AS "MESSAGES",
        COALESCE(parent_message_id, '0') AS "PARENT_MESSAGE_ID"
       FROM hr.agent_threads
       ORDER BY updated_at DESC
       LIMIT 30`
    );
    const threads = (rows as Record<string, unknown>[]).map((r) => ({
      threadId: r.THREAD_ID,
      title: r.TITLE,
      parentMessageId: r.PARENT_MESSAGE_ID || "0",
      messages: typeof r.MESSAGES === "string" ? JSON.parse(r.MESSAGES) : (r.MESSAGES || []),
      createdAt: r.CREATED_AT,
      updatedAt: r.UPDATED_AT,
    }));
    return NextResponse.json(threads);
  } catch (error) {
    console.error("Thread list error:", error);
    return NextResponse.json([], { status: 500 });
  }
}

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const body = await request.json();
    const { threadId, title, parentMessageId, messages } = body;

    if (!threadId) {
      return NextResponse.json({ error: "threadId required" }, { status: 400 });
    }

    await pgQuery(
      `INSERT INTO hr.agent_threads (thread_id, title, parent_message_id, messages, updated_at)
       VALUES ($1, $2, $3, $4::jsonb, NOW())
       ON CONFLICT (thread_id) DO UPDATE SET title = $2, parent_message_id = $3, messages = $4::jsonb, updated_at = NOW()`,
      [threadId, title || "新しい会話", parentMessageId || "0", JSON.stringify(messages || [])]
    );

    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("Thread save error:", error);
    return NextResponse.json({ error: "Failed to save thread" }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const threadId = searchParams.get("threadId");
    if (!threadId) {
      return NextResponse.json({ error: "threadId required" }, { status: 400 });
    }
    await pgQuery(
      `DELETE FROM hr.agent_threads WHERE thread_id = $1`,
      [threadId]
    );
    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("Thread delete error:", error);
    return NextResponse.json({ error: "Failed to delete" }, { status: 500 });
  }
}
