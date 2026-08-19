import { expect, test as base } from "@playwright/test";
import type { Page } from "@playwright/test";

export const E2E = {
  username: "e2e.operator",
  password: "MetaCRM-e2e-password",
  pageA: "E2E Page A",
  pageB: "E2E Page B",
  customerA: "E2E Customer A",
  customerBeta: "E2E Customer Beta",
  productA: "E2E Product A",
  criticalProduct: "E2E Critical Tracked Product",
  criticalProductSku: "E2E-CRITICAL-A",
  criticalStartingStock: 10,
  lowStockProduct: "E2E Low Stock Product",
  lowStockProductSku: "E2E-LOW-B",
  lowStartingStock: 1,
  orderA: "E2E-A-1001"
} as const;

type AuthenticatedSession = {
  page: Page;
  accessToken: string;
};

type Fixtures = {
  authenticatedSession: AuthenticatedSession;
  authenticatedPage: Page;
  accessToken: string;
};

export const test = base.extend<Fixtures>({
  authenticatedSession: async ({ page }, use) => {
    await page.goto("/login");
    await page.getByLabel("Username or email").fill(E2E.username);
    await page.getByLabel("Password").fill(E2E.password);
    const loginResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/auth/login") && response.request().method() === "POST"
    );
    await page.getByRole("button", { name: "Sign in" }).click();
    const response = await loginResponse;
    expect(response.status()).toBe(200);
    const tokens = (await response.json()) as { access_token: string };
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard", level: 2 })).toBeVisible();
    await use({ page, accessToken: tokens.access_token });
  },
  authenticatedPage: async ({ authenticatedSession }, use) => {
    await use(authenticatedSession.page);
  },
  accessToken: async ({ authenticatedSession }, use) => {
    await use(authenticatedSession.accessToken);
  }
});

export { expect } from "@playwright/test";
