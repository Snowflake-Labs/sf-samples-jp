import { describe, it, expect } from "vitest";
import { requireRole, getAllowedDeptIds, isHonbuAllowed } from "@/lib/session";
import type { SessionUser } from "@/lib/types";

const admin: SessionUser = {
  userId: 1, username: "admin", role: "HR_ADMIN",
  employeeId: 10, deptScope: null, displayName: "管理者",
};
const manager: SessionUser = {
  userId: 2, username: "manager", role: "HR_MANAGER",
  employeeId: 6, deptScope: [10, 11, 46], displayName: "部門長",
};
const viewer: SessionUser = {
  userId: 3, username: "viewer", role: "HR_VIEWER",
  employeeId: 18, deptScope: [10], displayName: "閲覧者",
};

describe("requireRole (S-05, S-08, N-07)", () => {
  it("returns 401 for an unauthenticated request", () => {
    const auth = requireRole(null, ["HR_ADMIN"]);
    expect(auth.ok).toBe(false);
    if (!auth.ok) expect(auth.status).toBe(401);
  });

  it("allows a role that is in the allow-list and hands back the user", () => {
    const a = requireRole(admin, ["HR_ADMIN"]);
    expect(a.ok).toBe(true);
    if (a.ok) expect(a.user.username).toBe("admin");

    const m = requireRole(manager, ["HR_ADMIN", "HR_MANAGER"]);
    expect(m.ok).toBe(true);
    if (m.ok) expect(m.user.username).toBe("manager");
  });

  it("returns 403 for a role that is not in the allow-list", () => {
    const auth = requireRole(viewer, ["HR_ADMIN", "HR_MANAGER"]);
    expect(auth.ok).toBe(false);
    if (!auth.ok) expect(auth.status).toBe(403);
  });

  it("blocks VIEWER from admin-only operations", () => {
    const auth = requireRole(viewer, ["HR_ADMIN"]);
    expect(auth.ok).toBe(false);
    if (!auth.ok) expect(auth.status).toBe(403);
  });

  it("blocks MANAGER from admin-only approval operations", () => {
    const auth = requireRole(manager, ["HR_ADMIN"]);
    expect(auth.ok).toBe(false);
    if (!auth.ok) expect(auth.status).toBe(403);
  });

  it("does not leak which role would have been accepted", () => {
    const auth = requireRole(viewer, ["HR_ADMIN"]);
    expect(auth.ok).toBe(false);
    if (!auth.ok) expect(auth.body.error).not.toContain("HR_ADMIN");
  });

  it("distinguishes unauthenticated (401) from unauthorized (403)", () => {
    const anon = requireRole(null, ["HR_ADMIN"]);
    const wrongRole = requireRole(viewer, ["HR_ADMIN"]);
    expect(anon.ok).toBe(false);
    expect(wrongRole.ok).toBe(false);
    if (!anon.ok && !wrongRole.ok) {
      expect(anon.status).not.toBe(wrongRole.status);
    }
  });
});

describe("getAllowedDeptIds (S-08 dept scoping)", () => {
  it("returns null (unrestricted) for an admin with no deptScope", () => {
    expect(getAllowedDeptIds(admin)).toBeNull();
  });

  it("returns null when the requested honbu is inside the user's scope", () => {
    expect(getAllowedDeptIds(manager, 10)).toBeNull();
  });

  it("falls back to the user's own scope when they request an out-of-scope honbu", () => {
    expect(getAllowedDeptIds(manager, 999)).toEqual([10, 11, 46]);
  });

  it("restricts a viewer to their single department", () => {
    expect(getAllowedDeptIds(viewer, 999)).toEqual([10]);
  });
});

describe("isHonbuAllowed (S-08)", () => {
  it("allows any honbu for an unrestricted admin", () => {
    expect(isHonbuAllowed(admin, 1)).toBe(true);
    expect(isHonbuAllowed(admin, 99999)).toBe(true);
  });

  it("allows in-scope honbu for a scoped user", () => {
    expect(isHonbuAllowed(manager, 46)).toBe(true);
  });

  it("rejects out-of-scope honbu for a scoped user", () => {
    expect(isHonbuAllowed(manager, 999)).toBe(false);
    expect(isHonbuAllowed(viewer, 11)).toBe(false);
  });
});
