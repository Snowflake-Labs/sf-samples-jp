import { test, expect } from "@playwright/test";

/**
 * N-06: every protected page must bounce an unauthenticated visitor to /login.
 * This is the regression test for the middleware added for C3.
 */

const PROTECTED_PATHS = [
  "/",
  "/employees",
  "/employees/new",
  "/employees/1",
  "/employees/1/skills",
  "/employees/1/notes",
  "/evaluations",
  "/evaluations/new",
  "/evaluations/batch",
  "/evaluations/1",
  "/evaluations/cross-review",
  "/agent",
  "/attrition",
  "/simulation",
  "/chain-simulation",
  "/review",
  "/snapshots",
  "/workforce-overview",
  "/governance",
];

test.describe("N-06 unauthenticated access is redirected", () => {
  for (const path of PROTECTED_PATHS) {
    test(`${path} redirects to /login`, async ({ page, context }) => {
      await context.clearCookies();
      await page.goto(path);
      await expect(page).toHaveURL(/\/login/);
    });
  }

  test("protected API returns 401 without a session", async ({ request }) => {
    const res = await request.get("/api/dashboard?honbu=1&period=2026-H1");
    expect(res.status()).toBe(401);
  });

  test("login page itself is reachable", async ({ page, context }) => {
    await context.clearCookies();
    await page.goto("/login");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.locator("body")).toBeVisible();
  });
});
