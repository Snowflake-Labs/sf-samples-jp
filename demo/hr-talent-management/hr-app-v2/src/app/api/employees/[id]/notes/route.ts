import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { isEmployeeInScope } from "@/lib/scope";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { id } = await params;
    const empId = Number(id);
    if (!(await isEmployeeInScope(session, empId))) {
      return NextResponse.json({ error: "Employee not found" }, { status: 404 });
    }
    const { searchParams } = new URL(request.url);
    const category = searchParams.get("category") || "";
    const limit = Math.min(Number(searchParams.get("limit")) || 50, 200);
    const offset = Number(searchParams.get("offset")) || 0;

    let where = "WHERE n.employee_id = $1";
    const binds: unknown[] = [empId];
    let idx = 2;

    if (category) {
      where += ` AND n.category = $${idx++}`;
      binds.push(category);
    }

    const countResult = await pgQuery<{ TOTAL: string }>(`
      SELECT COUNT(*) AS "TOTAL" FROM hr.one_on_one_notes n ${where}
    `, binds);

    const notes = await pgQuery(`
      SELECT n.note_id AS "NOTE_ID", n.employee_id AS "EMPLOYEE_ID",
        n.manager_id AS "MANAGER_ID", n.note_date AS "NOTE_DATE",
        n.content AS "CONTENT", n.category AS "CATEGORY",
        n.is_private AS "IS_PRIVATE", n.created_at AS "CREATED_AT",
        m.last_name || m.first_name AS "MANAGER_NAME"
      FROM hr.one_on_one_notes n
      LEFT JOIN hr.employees m ON n.manager_id = m.employee_id
      ${where}
      ORDER BY n.note_date DESC
      LIMIT $${idx++} OFFSET $${idx++}
    `, [...binds, limit, offset]);

    const total = Number(countResult[0]?.TOTAL || 0);
    return NextResponse.json({ notes, total, hasMore: offset + limit < total });
  } catch (error) {
    console.error("Notes fetch error:", error);
    return NextResponse.json({ error: "Failed to fetch notes" }, { status: 500 });
  }
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  // 更新は人事管理者・部門マネージャーだけ。部署スコープ外の社員は不可
  const auth = requireRole(await getSession(), ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { id } = await params;
    const empId = Number(id);
    if (!(await isEmployeeInScope(auth.user, empId))) {
      return NextResponse.json({ error: "Employee not found" }, { status: 404 });
    }
    const body = await request.json();
    const { manager_id, note_date, content, category, is_private } = body;

    if (!manager_id || !note_date || !content) {
      return NextResponse.json({ error: "manager_id, note_date, content required" }, { status: 400 });
    }

    const result = await pgQuery<{ note_id: number }>(`
      INSERT INTO hr.one_on_one_notes (employee_id, manager_id, note_date, content, category, is_private)
      VALUES ($1, $2, $3, $4, $5, $6)
      RETURNING note_id
    `, [empId, Number(manager_id), note_date, content, category || null, is_private || false]);

    return NextResponse.json({ success: true, noteId: result[0]?.note_id }, { status: 201 });
  } catch (error) {
    console.error("Note create error:", error);
    return NextResponse.json({ error: "Failed to create note" }, { status: 500 });
  }
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  // 更新は人事管理者・部門マネージャーだけ。部署スコープ外の社員は不可
  const auth = requireRole(await getSession(), ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { id } = await params;
    const empId = Number(id);
    if (!(await isEmployeeInScope(auth.user, empId))) {
      return NextResponse.json({ error: "Employee not found" }, { status: 404 });
    }
    const body = await request.json();
    const { note_id, content, category, is_private } = body;

    if (!note_id || !content) {
      return NextResponse.json({ error: "note_id and content required" }, { status: 400 });
    }

    await pgQuery(`
      UPDATE hr.one_on_one_notes SET content = $1, category = $2, is_private = $3
      WHERE note_id = $4 AND employee_id = $5
    `, [content, category || null, is_private || false, Number(note_id), empId]);

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Note update error:", error);
    return NextResponse.json({ error: "Failed to update note" }, { status: 500 });
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  // 更新は人事管理者・部門マネージャーだけ。部署スコープ外の社員は不可
  const auth = requireRole(await getSession(), ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { id } = await params;
    const empId = Number(id);
    if (!(await isEmployeeInScope(auth.user, empId))) {
      return NextResponse.json({ error: "Employee not found" }, { status: 404 });
    }
    const { searchParams } = new URL(request.url);
    const noteId = searchParams.get("note_id");

    if (!noteId) {
      return NextResponse.json({ error: "note_id required" }, { status: 400 });
    }

    await pgQuery(`DELETE FROM hr.one_on_one_notes WHERE note_id = $1 AND employee_id = $2`, [Number(noteId), empId]);
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Note delete error:", error);
    return NextResponse.json({ error: "Failed to delete note" }, { status: 500 });
  }
}
