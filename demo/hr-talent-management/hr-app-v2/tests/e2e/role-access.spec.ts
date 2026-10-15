import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * S-05 / N-07: role switching must change the server-side session, and
 * role-gated APIs must reject callers who lack the role.
 *
 * These are the regression tests for:
 *   - the switch-role endpoint (was client-only)
 *   - the requireRole guards added to the write APIs (B2)
 */

async function login(request: APIRequestContext, username: string) {
  const res = await request.post("/api/auth/login", { data: { username } });
  expect(res.ok()).toBeTruthy();
  return res.json();
}

test.describe("S-05 role switch updates the server session", () => {
  test("switch-role rewrites the session cookie", async ({ request }) => {
    const loggedIn = await login(request, "admin");
    expect(loggedIn.role).toBe("HR_ADMIN");

    const switched = await request.post("/api/auth/switch-role", {
      data: { role: "HR_VIEWER" },
    });
    expect(switched.ok()).toBeTruthy();
    expect((await switched.json()).role).toBe("HR_VIEWER");

    // The server must now report the new role, not the login role
    const session = await request.get("/api/auth/session");
    expect((await session.json()).role).toBe("HR_VIEWER");
  });

  test("switch-role rejects an unknown role", async ({ request }) => {
    await login(request, "admin");
    const res = await request.post("/api/auth/switch-role", {
      data: { role: "SUPER_ADMIN" },
    });
    expect(res.status()).toBe(400);
  });

  test("switch-role requires an existing session", async ({ request }) => {
    await request.post("/api/auth/logout");
    const res = await request.post("/api/auth/switch-role", {
      data: { role: "HR_ADMIN" },
    });
    expect(res.status()).toBe(401);
  });
});

test.describe("N-07 role-gated APIs reject unauthorized roles", () => {
  test("VIEWER cannot save a simulation scenario", async ({ request }) => {
    await login(request, "admin");
    await request.post("/api/auth/switch-role", { data: { role: "HR_VIEWER" } });

    const res = await request.post("/api/simulation/save", {
      data: { scenarioName: "test", actions: [] },
    });
    expect(res.status()).toBe(403);
  });

  test("VIEWER cannot run LLM quantification", async ({ request }) => {
    await login(request, "admin");
    await request.post("/api/auth/switch-role", { data: { role: "HR_VIEWER" } });

    const res = await request.post("/api/evaluations/quantify", {
      data: { evaluation_ids: [1] },
    });
    expect(res.status()).toBe(403);
  });

  test("MANAGER cannot approve a scenario (admin only)", async ({ request }) => {
    await login(request, "admin");
    await request.post("/api/auth/switch-role", { data: { role: "HR_MANAGER" } });

    const res = await request.post("/api/simulation/approve-scenario", {
      data: { scenarioId: 1 },
    });
    expect(res.status()).toBe(403);
  });

  test("MANAGER cannot use the AI agent (admin only)", async ({ request }) => {
    await login(request, "admin");
    await request.post("/api/auth/switch-role", { data: { role: "HR_MANAGER" } });

    const res = await request.post("/api/agent", { data: { query: "test" } });
    expect(res.status()).toBe(403);
  });

  test("ADMIN can reach an admin-only endpoint", async ({ request }) => {
    await login(request, "admin");
    // 400/404 are fine here — we only assert it is not an authz rejection
    const res = await request.post("/api/simulation/approve-scenario", {
      data: {},
    });
    expect(res.status()).not.toBe(403);
    expect(res.status()).not.toBe(401);
  });
});
