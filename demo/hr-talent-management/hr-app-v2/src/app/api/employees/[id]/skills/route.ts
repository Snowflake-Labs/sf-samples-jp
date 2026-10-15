import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { isEmployeeInScope } from "@/lib/scope";

export async function GET(
  _request: Request,
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

    const skills = await pgQuery(`
      SELECT es.id AS "ID", es.skill_id AS "SKILL_ID",
        s.skill_name AS "SKILL_NAME", s.category AS "CATEGORY",
        es.proficiency AS "PROFICIENCY",
        es.certified_at AS "CERTIFIED_AT"
      FROM hr.employee_skills es
      JOIN hr.skills s ON es.skill_id = s.skill_id
      WHERE es.employee_id = $1
      ORDER BY s.category, es.proficiency DESC
    `, [empId]);

    const allSkills = await pgQuery(`
      SELECT skill_id AS "SKILL_ID", skill_name AS "SKILL_NAME", category AS "CATEGORY"
      FROM hr.skills ORDER BY category, skill_name
    `, []);

    return NextResponse.json({ skills, allSkills });
  } catch (error) {
    console.error("Skills fetch error:", error);
    return NextResponse.json({ error: "Failed to fetch skills" }, { status: 500 });
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
    const { skill_id, proficiency, certified_at } = body;

    if (!skill_id || !proficiency) {
      return NextResponse.json({ error: "skill_id and proficiency required" }, { status: 400 });
    }

    const result = await pgQuery<{ id: number }>(`
      INSERT INTO hr.employee_skills (employee_id, skill_id, proficiency, certified_at)
      VALUES ($1, $2, $3, $4)
      ON CONFLICT (employee_id, skill_id) DO UPDATE SET proficiency = $3, certified_at = $4
      RETURNING id
    `, [empId, Number(skill_id), Number(proficiency), certified_at || null]);

    return NextResponse.json({ success: true, id: result[0]?.id }, { status: 201 });
  } catch (error) {
    console.error("Skill add error:", error);
    return NextResponse.json({ error: "Failed to add skill" }, { status: 500 });
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
    const { skill_id, proficiency, certified_at } = body;

    if (!skill_id || !proficiency) {
      return NextResponse.json({ error: "skill_id and proficiency required" }, { status: 400 });
    }

    await pgQuery(`
      UPDATE hr.employee_skills SET proficiency = $1, certified_at = $2
      WHERE employee_id = $3 AND skill_id = $4
    `, [Number(proficiency), certified_at || null, empId, Number(skill_id)]);

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Skill update error:", error);
    return NextResponse.json({ error: "Failed to update skill" }, { status: 500 });
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
    const skillId = searchParams.get("skill_id");

    if (!skillId) {
      return NextResponse.json({ error: "skill_id required" }, { status: 400 });
    }

    await pgQuery(`
      DELETE FROM hr.employee_skills WHERE employee_id = $1 AND skill_id = $2
    `, [empId, Number(skillId)]);

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Skill delete error:", error);
    return NextResponse.json({ error: "Failed to delete skill" }, { status: 500 });
  }
}
