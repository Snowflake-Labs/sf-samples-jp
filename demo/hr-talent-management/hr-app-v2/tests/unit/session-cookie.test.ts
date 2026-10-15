import { describe, it, expect, vi, beforeEach } from "vitest";
import type { SessionUser } from "@/lib/types";

/**
 * getSession() reads from next/headers cookies(), so we mock that module
 * and drive it with values produced by the real createSessionCookie().
 * This exercises the actual HMAC sign/verify path (S-05).
 */
const cookieStore = { value: undefined as string | undefined };

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "hr-session" && cookieStore.value !== undefined
        ? { name, value: cookieStore.value }
        : undefined,
  }),
}));

const session: SessionUser = {
  userId: 2, username: "manager", role: "HR_MANAGER",
  employeeId: 6, deptScope: [10, 11], displayName: "部門長",
};

describe("session cookie sign/verify", () => {
  beforeEach(() => {
    cookieStore.value = undefined;
    vi.resetModules();
  });

  it("round-trips a session through createSessionCookie -> getSession", async () => {
    const { createSessionCookie, getSession } = await import("@/lib/session");
    const { value } = createSessionCookie(session);
    cookieStore.value = value;

    const restored = await getSession();
    expect(restored).toEqual(session);
  });

  it("sets httpOnly and an 8 hour TTL", async () => {
    const { createSessionCookie } = await import("@/lib/session");
    const { options } = createSessionCookie(session);
    expect(options.httpOnly).toBe(true);
    expect(options.maxAge).toBe(60 * 60 * 8);
    expect(options.sameSite).toBe("lax");
  });

  it("rejects a cookie whose payload was tampered with", async () => {
    const { createSessionCookie, getSession } = await import("@/lib/session");
    const { value } = createSessionCookie(session);
    const [b64, sig] = value.split(".");

    // Escalate the role inside the payload but keep the original signature
    const payload = JSON.parse(Buffer.from(b64, "base64").toString("utf-8"));
    payload.role = "HR_ADMIN";
    const forged = Buffer.from(JSON.stringify(payload)).toString("base64");

    cookieStore.value = `${forged}.${sig}`;
    expect(await getSession()).toBeNull();
  });

  it("rejects a cookie with a bogus signature", async () => {
    const { createSessionCookie, getSession } = await import("@/lib/session");
    const { value } = createSessionCookie(session);
    const [b64] = value.split(".");
    cookieStore.value = `${b64}.${"0".repeat(64)}`;
    expect(await getSession()).toBeNull();
  });

  it("returns null when no cookie is present", async () => {
    const { getSession } = await import("@/lib/session");
    expect(await getSession()).toBeNull();
  });

  it("returns null for a malformed cookie value", async () => {
    const { getSession } = await import("@/lib/session");
    cookieStore.value = "not-a-valid-cookie";
    expect(await getSession()).toBeNull();
  });

  it("rejects an unsigned JSON cookie", async () => {
    const { getSession } = await import("@/lib/session");
    cookieStore.value = JSON.stringify({ ...session, role: "HR_ADMIN" });
    expect(await getSession()).toBeNull();
  });
});
