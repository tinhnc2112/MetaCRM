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

export async function selectPage(page: Page, pageName: string): Promise<void> {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/settings/facebook");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page).toHaveURL(/\/settings\/facebook$/);
  await expect(page.getByRole("heading", { name: "Facebook", level: 2 })).toBeVisible();

  const currentSection = page
    .locator(".settings-section")
    .filter({ has: page.getByRole("heading", { name: "Current Page", level: 4 }) });
  await expect(currentSection).toBeVisible();
  if ((await currentSection.getByText(pageName, { exact: true }).count()) > 0) {
    return;
  }

  const pagesSection = page
    .locator(".settings-section")
    .filter({ has: page.getByRole("heading", { name: "Pages", level: 4 }) });
  await expect(pagesSection).toBeVisible();
  const pageRow = pagesSection.getByRole("listitem").filter({ hasText: pageName });
  await expect(pageRow).toBeVisible();

  let state = "pending";
  await expect
    .poll(async () => {
      if ((await currentSection.getByText(pageName, { exact: true }).count()) > 0) {
        state = "current";
        return state;
      }
      if ((await pageRow.getByRole("button", { name: "Current Page", exact: true }).count()) > 0) {
        state = "current";
        return state;
      }
      if ((await pageRow.getByRole("button", { name: "Select", exact: true }).count()) > 0) {
        state = "selectable";
        return state;
      }
      state = "pending";
      return state;
    })
    .toMatch(/^(current|selectable)$/);
  if (state === "current") {
    await expect(currentSection.getByText(pageName, { exact: true })).toBeVisible();
    return;
  }

  const selectButton = pageRow.getByRole("button", { name: "Select", exact: true });
  await expect(selectButton).toBeVisible();
  const switchResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/facebook/pages/") &&
      response.url().endsWith("/select") &&
      response.request().method() === "POST"
  );
  await selectButton.click();
  expect((await switchResponse).status()).toBe(200);
  await expect(currentSection.getByText(pageName, { exact: true })).toBeVisible();
}

export { expect } from "@playwright/test";
