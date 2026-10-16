import { NextResponse } from "next/server";
import { getSession, createSessionCookie } from "@/lib/session";
import type { UserRole } from "@/lib/types";

const VALID_ROLES: UserRole[] = ["HR_ADMIN", "HR_MANAGER", "HR_VIEWER"];

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  // 上長は評価者本人としてログインしている。人事ロールへ切り替えると全社データが見えてしまう
  if (session.role === "LINE_MANAGER") {
    return NextResponse.json({ error: "評価者アカウントはロールを切り替えられません" }, { status: 403 });
  }

  try {
    const { role } = await request.json();

    if (!role || !VALID_ROLES.includes(role)) {
      return NextResponse.json({ error: "不正なロール" }, { status: 400 });
    }

    const updated = { ...session, role: role as UserRole };
    const { name, value, options } = createSessionCookie(updated);
    const response = NextResponse.json(updated);
    response.cookies.set(name, value, options);
    return response;
  } catch (error) {
    console.error("Switch role error:", error);
    return NextResponse.json({ error: "ロール切替に失敗しました" }, { status: 500 });
  }
}
