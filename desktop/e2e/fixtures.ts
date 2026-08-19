import { expect, test as base } from "@playwright/test";
import type { Page } from "@playwright/test";

export const E2E = {
  username: "e2e.operator",
  password: "MetaCRM-e2e-password",
  pageA: "E2E Page A",
  pageB: "E2E Page B",
  customerA: "E2E Customer A",
  productA: "E2E Product A",
  orderA: "E2E-A-1001"
} as const;

type Fixtures = {
  authenticatedPage: Page;
};

export const test = base.extend<Fixtures>({
  authenticatedPage: async ({ page }, use) => {
    await page.goto("/login");
    await page.getByLabel("Username or email").fill(E2E.username);
    await page.getByLabel("Password").fill(E2E.password);
    const loginResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/auth/login") && response.request().method() === "POST"
    );
    await page.getByRole("button", { name: "Sign in" }).click();
    expect((await loginResponse).status()).toBe(200);
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard", level: 2 })).toBeVisible();
    await use(page);
  }
});

export { expect } from "@playwright/test";
