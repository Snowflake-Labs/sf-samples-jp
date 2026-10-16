import { cookies } from "next/headers";
import { createHmac, timingSafeEqual } from "crypto";
import type { SessionUser } from "@/lib/types";
import { readSecret } from "@/lib/secrets";

const COOKIE_NAME = "hr-session";
// On App Runtime this comes from the file Snowflake mounts for the SESSION_SECRET
// entry in app.yml; locally it falls back to the environment.
const SECRET = readSecret("SESSION_SECRET") || "";

function sign(payload: string): string {
  // A guessable fallback key would let anyone forge an HR_ADMIN cookie, so
  // refuse to run in production without a real secret.
  if (!SECRET && process.env.NODE_ENV === "production") {
    throw new Error("SESSION_SECRET is not set");
  }
  return createHmac("sha256", SECRET || "local-dev-only").update(payload).digest("hex");
}

function verify(payload: string, signature: string): boolean {
  const expected = sign(payload);
  try {
    return timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
  } catch {
    return false;
  }
}

export function createSessionCookie(session: SessionUser): { name: string; value: string; options: Record<string, unknown> } {
  const payload = JSON.stringify(session);
  const sig = sign(payload);
  return {
    name: COOKIE_NAME,
    value: `${Buffer.from(payload).toString("base64")}.${sig}`,
    options: {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax" as const,
      path: "/",
      maxAge: 60 * 60 * 8,
    },
  };
}

export async function getSession(): Promise<SessionUser | null> {
  const cookieStore = await cookies();
  const cookie = cookieStore.get(COOKIE_NAME);
  if (!cookie?.value) return null;

  const parts = cookie.value.split(".");
  // 署名のない cookie は受け付けない（書き換えるだけで任意のロールになれてしまう）
  if (parts.length !== 2) return null;

  const [b64, sig] = parts;
  let payload: string;
  try {
    payload = Buffer.from(b64, "base64").toString("utf-8");
  } catch {
    return null;
  }

  if (!verify(payload, sig)) return null;

  try {
    return JSON.parse(payload) as SessionUser;
  } catch {
    return null;
  }
}

export function deleteSessionCookie(): { name: string; options: Record<string, unknown> } {
  return {
    name: COOKIE_NAME,
    options: {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax" as const,
      path: "/",
      maxAge: 0,
    },
  };
}

export function getAllowedDeptIds(session: SessionUser, requestedHonbu?: number | null): number[] | null {
  if (!session.deptScope) return null;
  if (requestedHonbu && !session.deptScope.includes(requestedHonbu)) {
    return session.deptScope;
  }
  return null;
}

export function isHonbuAllowed(session: SessionUser, honbu: number): boolean {
  if (!session.deptScope) return true;
  return session.deptScope.includes(honbu);
}

/**
 * Role guard for API routes.
 *
 * Returns a discriminated union rather than null-on-success so the
 * authorized branch carries a non-null `user`. That removes the need for
 * a non-null assertion at every call site, which would otherwise be the
 * one place a genuine null could slip through unchecked.
 *
 * Usage:
 *   const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
 *   if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
 *   // auth.user is SessionUser here
 */
export type RoleDenial = { ok: false; body: { error: string }; status: number };
export type RoleGrant = { ok: true; user: SessionUser };
export type RoleCheck = RoleGrant | RoleDenial;

export function requireRole(
  session: SessionUser | null,
  allowed: SessionUser["role"][]
): RoleCheck {
  if (!session) {
    return { ok: false, body: { error: "認証が必要です" }, status: 401 };
  }
  if (!allowed.includes(session.role)) {
    return { ok: false, body: { error: "この操作の権限がありません" }, status: 403 };
  }
  return { ok: true, user: session };
}
