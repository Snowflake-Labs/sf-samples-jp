import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, isHonbuAllowed, requireRole } from "@/lib/session";
import { isDeptInScope } from "@/lib/scope";

export async function POST(request: Request) {
  const session = await getSession();
  // 社員の登録は人事管理者・部門マネージャーだけ。閲覧専用ロールは不可
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const body = await request.json();
    const {
      EMPLOYEE_CODE, FIRST_NAME, LAST_NAME, EMAIL, PHONE,
      HIRE_DATE, BIRTH_DATE, GENDER, DEPT_ID, POSITION_ID,
      MANAGER_ID, SALARY, EMPLOYMENT_TYPE, COMMUTE_TIME_MINUTES,
    } = body;

    if (!EMPLOYEE_CODE || !FIRST_NAME || !LAST_NAME || !HIRE_DATE || !DEPT_ID) {
      return NextResponse.json({ error: "必須項目が不足しています" }, { status: 400 });
    }
    if (!(await isDeptInScope(auth.user, Number(DEPT_ID)))) {
      return NextResponse.json({ error: "アクセス権限がありません" }, { status: 403 });
    }

    const existing = await pgQuery(
      `SELECT employee_id FROM hr.employees WHERE employee_code = $1`,
      [EMPLOYEE_CODE]
    );
    if (existing.length > 0) {
      return NextResponse.json({ error: "この社員番号は既に使用されています" }, { status: 409 });
    }

    const result = await pgQuery<{ employee_id: number }>(
      `INSERT INTO hr.employees (
        employee_code, first_name, last_name, email, phone,
        hire_date, birth_date, gender, dept_id, position_id, manager_id,
        status, salary, employment_type, commute_time_minutes
      ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'active',$12,$13,$14)
      RETURNING employee_id`,
      [
        EMPLOYEE_CODE, FIRST_NAME, LAST_NAME, EMAIL || '', PHONE || '',
        HIRE_DATE, BIRTH_DATE || null, GENDER || null, Number(DEPT_ID),
        POSITION_ID ? Number(POSITION_ID) : null, MANAGER_ID ? Number(MANAGER_ID) : null,
        SALARY ? Number(SALARY) : null, EMPLOYMENT_TYPE || null,
        COMMUTE_TIME_MINUTES ? Number(COMMUTE_TIME_MINUTES) : null,
      ]
    );
    const newId = result[0].employee_id;

    await pgQuery(
      `INSERT INTO hr.career_history (employee_id, event_type, event_date, to_dept_id, to_position_id, notes)
       VALUES ($1, 'hire', $2, $3, $4, '入社配属')`,
      [newId, HIRE_DATE, Number(DEPT_ID), POSITION_ID ? Number(POSITION_ID) : null]
    );

    return NextResponse.json({ EMPLOYEE_ID: newId, message: "登録完了" }, { status: 201 });
  } catch (error) {
    console.error("Employee create error:", error);
    return NextResponse.json({ error: "社員登録に失敗しました" }, { status: 500 });
  }
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const q = searchParams.get("q") || "";
    const dept = searchParams.get("dept") || "";
    const honbu = searchParams.get("honbu") || "";
    const status = searchParams.get("status") || "active";
    const limit = Math.min(Number(searchParams.get("limit")) || 50, 200);
    const offset = Number(searchParams.get("offset")) || 0;

    let where = "WHERE 1=1";
    const params: unknown[] = [];
    let idx = 1;

    if (status) {
      where += ` AND e.status = $${idx++}`;
      params.push(status);
    }
    if (honbu) {
      if (!isHonbuAllowed(session, Number(honbu))) {
        return NextResponse.json({ error: "アクセス権限がありません" }, { status: 403 });
      }
      where += ` AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${idx} OR parent_dept_id = $${idx + 1})`;
      params.push(Number(honbu), Number(honbu));
      idx += 2;
    } else if (session.deptScope) {
      const placeholders = session.deptScope.map(() => `$${idx++}`).join(",");
      where += ` AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id IN (${placeholders}) OR parent_dept_id IN (${placeholders}))`;
      params.push(...session.deptScope);
    }
    if (dept) {
      where += ` AND e.dept_id = $${idx++}`;
      params.push(Number(dept));
    }
    if (q) {
      const likeQ = `%${q}%`;
      where += ` AND (e.last_name ILIKE $${idx} OR e.first_name ILIKE $${idx + 1} OR e.employee_code ILIKE $${idx + 2})`;
      params.push(likeQ, likeQ, likeQ);
      idx += 3;
    }

    const countParams = [...params];
    params.push(limit, offset);

    const countSql = `SELECT COUNT(*) AS "TOTAL" FROM hr.employees e ${where}`;
    const dataSql = `
      SELECT e.employee_id AS "EMPLOYEE_ID", e.employee_code AS "EMPLOYEE_CODE",
        e.first_name AS "FIRST_NAME", e.last_name AS "LAST_NAME",
        e.email AS "EMAIL", e.hire_date AS "HIRE_DATE", e.birth_date AS "BIRTH_DATE",
        e.gender AS "GENDER", e.dept_id AS "DEPT_ID",
        e.position_id AS "POSITION_ID", e.manager_id AS "MANAGER_ID",
        e.status AS "STATUS", e.salary AS "SALARY",
        d.dept_name AS "DEPT_NAME", p.title AS "POSITION_TITLE", p.grade AS "GRADE"
      FROM hr.employees e
      LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
      LEFT JOIN hr.positions p ON e.position_id = p.position_id
      ${where}
      ORDER BY e.employee_id
      LIMIT $${idx++} OFFSET $${idx++}
    `;

    const [countResult, employees] = await Promise.all([
      pgQuery<{ TOTAL: string }>(countSql, countParams),
      pgQuery(dataSql, params),
    ]);

    const total = Number(countResult[0]?.TOTAL || 0);
    return NextResponse.json({
      data: employees,
      total,
      limit,
      offset,
      hasMore: offset + limit < total,
    });
  } catch (error) {
    console.error("Employees error:", error);
    return NextResponse.json({ error: "Failed to fetch employees" }, { status: 500 });
  }
}
