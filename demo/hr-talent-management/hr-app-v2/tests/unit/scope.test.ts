import { describe, it, expect, vi, beforeEach } from "vitest";
import type { SessionUser } from "@/lib/types";

const pgQuery = vi.fn();
vi.mock("@/lib/postgres", () => ({ pgQuery: (...args: unknown[]) => pgQuery(...args) }));

import { resolveHonbuScope, isDeptInScope, isEmployeeInScope } from "@/lib/scope";

const admin: SessionUser = {
  userId: 1, username: "admin", role: "HR_ADMIN",
  employeeId: 1, deptScope: null, displayName: "人事",
};
const manager: SessionUser = {
  userId: 2, username: "manager", role: "HR_MANAGER",
  employeeId: 6, deptScope: [10, 11], displayName: "部門長",
};

describe("resolveHonbuScope", () => {
  it("lets an unscoped user see everything or one honbu", () => {
    expect(resolveHonbuScope(admin, null)).toEqual({ ok: true, honbuIds: null });
    expect(resolveHonbuScope(admin, 99)).toEqual({ ok: true, honbuIds: [99] });
  });

  it("limits a scoped user to their honbu when none is requested", () => {
    expect(resolveHonbuScope(manager, null)).toEqual({ ok: true, honbuIds: [10, 11] });
  });

  it("allows a requested honbu inside the scope", () => {
    expect(resolveHonbuScope(manager, 11)).toEqual({ ok: true, honbuIds: [11] });
  });

  it("rejects a requested honbu outside the scope", () => {
    expect(resolveHonbuScope(manager, 99)).toEqual({ ok: false });
  });
});

describe("isDeptInScope / isEmployeeInScope", () => {
  beforeEach(() => pgQuery.mockReset());

  it("skips the lookup for unscoped users", async () => {
    expect(await isDeptInScope(admin, 99)).toBe(true);
    expect(await isEmployeeInScope(admin, 123)).toBe(true);
    expect(pgQuery).not.toHaveBeenCalled();
  });

  it("passes the scope as a bound array and follows the row result", async () => {
    pgQuery.mockResolvedValueOnce([{ "?column?": 1 }]).mockResolvedValueOnce([]);
    expect(await isEmployeeInScope(manager, 123)).toBe(true);
    expect(await isEmployeeInScope(manager, 456)).toBe(false);
    expect(pgQuery).toHaveBeenNthCalledWith(1, expect.any(String), [123, [10, 11]]);
  });
});
