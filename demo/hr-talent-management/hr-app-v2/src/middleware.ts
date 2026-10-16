import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login"];
const PUBLIC_API_PATHS = ["/api/auth/login", "/api/auth/logout", "/api/auth/session"];
const COOKIE_NAME = "hr-session";

// 上長（LINE_MANAGER）が触れてよいのは自分の部下の評価だけ。
// 既存の多くの API は「ログイン済み＝人事」を前提にロール確認をしていないため、ここで入口を絞る。
const LINE_MANAGER_PATHS = [/^\/my-team(\/|$)/, /^\/api\/my-team(\/|$)/, /^\/api\/auth\//];

/**
 * Read the role from the cookie payload without verifying it (Node crypto is
 * unavailable here). Used only to deny: a forged cookie still fails the
 * signature check in getSession() on the API side.
 */
function roleFromCookie(value: string): string | null {
  try {
    const b64 = value.split(".")[0];
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    return (JSON.parse(new TextDecoder().decode(bytes)) as { role?: string }).role ?? null;
  } catch {
    return null;
  }
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths and Next.js internals
  if (
    PUBLIC_PATHS.some((p) => pathname === p) ||
    PUBLIC_API_PATHS.some((p) => pathname === p) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    /\.(svg|png|jpg|jpeg|ico|webp|woff2?)$/.test(pathname)
  ) {
    return NextResponse.next();
  }

  const cookie = request.cookies.get(COOKIE_NAME);

  // Presence + shape check only. Signature verification happens in getSession()
  // (Node crypto is unavailable in the Edge middleware runtime).
  const hasValidShape = !!cookie?.value && cookie.value.split(".").length === 2;

  if (!hasValidShape) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
    }
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  if (roleFromCookie(cookie!.value) === "LINE_MANAGER" && !LINE_MANAGER_PATHS.some((re) => re.test(pathname))) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "この操作の権限がありません" }, { status: 403 });
    }
    return NextResponse.redirect(new URL("/my-team", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
