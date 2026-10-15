import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { createSessionCookie } from "@/lib/session";
import { normalizeRole } from "@/lib/types";
import type { SessionUser } from "@/lib/types";

const DEMO_USERS: Record<string, {
  userId: number;
  username: string;
  role: string;
  employeeId: number;
  deptScope: number[] | null;
  displayName: string;
}> = {
  admin: {
    userId: 1,
    username: "admin",
    role: "HR_ADMIN",
    employeeId: 10,
    deptScope: null,
    displayName: "管理者",
  },
  manager: {
    userId: 2,
    username: "manager",
    role: "HR_MANAGER",
    employeeId: 6,
    deptScope: [10, 11, 46, 47, 95],
    displayName: "部門長",
  },
  viewer: {
    userId: 3,
    username: "viewer",
    role: "HR_VIEWER",
    employeeId: 18,
    deptScope: [10],
    displayName: "閲覧者",
  },
  // 1stラインマネージャー（課長）。自分が評価者になっている部下だけを評価する
  linemgr: {
    userId: 4,
    username: "linemgr",
    role: "LINE_MANAGER",
    employeeId: 8869,
    deptScope: [132],
    displayName: "内田洋平",
  },
};

function parseDeptScope(raw: unknown): number[] | null {
  if (!raw) return null;
  if (Array.isArray(raw)) return raw.map(Number);
  const str = String(raw);
  if (!str || str === "null") return null;
  try {
    const parsed = JSON.parse(str);
    if (Array.isArray(parsed)) return parsed.map(Number);
  } catch { /* ignore */ }
  return str.split(",").map(Number).filter((n) => !isNaN(n));
}

export async function POST(request: Request) {
  try {
    const { username } = await request.json();

    if (!username || typeof username !== "string" || username.length > 50) {
      return NextResponse.json({ error: "不正なリクエスト" }, { status: 400 });
    }

    let session;

    try {
      const users = await pgQuery<{
        user_id: number;
        username: string;
        role: string;
        employee_id: number;
        dept_scope: number[] | null;
        is_active: boolean;
      }>(
        `SELECT user_id, username, role, employee_id, dept_scope, is_active
         FROM hr.app_users
         WHERE username = $1 AND is_active = TRUE`,
        [username]
      );

      if (users.length === 0) {
        const fallback = DEMO_USERS[username];
        if (!fallback) {
          return NextResponse.json({ error: "ユーザーが見つかりません" }, { status: 401 });
        }
        session = fallback;
      } else {
        const user = users[0];
        let displayName = user.username;
        try {
          const emp = await pgQuery<{ first_name: string; last_name: string }>(
            `SELECT first_name, last_name FROM hr.employees WHERE employee_id = $1`,
            [user.employee_id]
          );
          if (emp.length > 0) displayName = `${emp[0].last_name}${emp[0].first_name}`;
        } catch { /* use username as fallback */ }

        session = {
          userId: user.user_id,
          username: user.username,
          // hr.app_users stores roles as free-form text; normalize so the
          // role checks in the API layer actually match.
          role: normalizeRole(user.role),
          employeeId: user.employee_id,
          deptScope: parseDeptScope(user.dept_scope),
          displayName,
        };
      }
    } catch {
      const fallback = DEMO_USERS[username];
      if (!fallback) {
        return NextResponse.json({ error: "ユーザーが見つかりません" }, { status: 401 });
      }
      session = fallback;
    }

    const { name, value, options } = createSessionCookie(session as SessionUser);
    const response = NextResponse.json(session);
    response.cookies.set(name, value, options);
    return response;
  } catch (error) {
    console.error("Login error:", error);
    return NextResponse.json({ error: "認証に失敗しました" }, { status: 500 });
  }
}
