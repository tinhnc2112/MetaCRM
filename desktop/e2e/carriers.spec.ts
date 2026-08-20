import type { Locator, Page } from "@playwright/test";

import { E2E, expect, selectPage, test } from "./fixtures";

const ACCOUNT_NAME = "M30.1 Page A Carrier";

test("keeps Manual carrier settings Page-scoped without credential actions", async ({
  authenticatedPage: page
}) => {
  await selectPage(page, E2E.pageA);
  await openCarriers(page, E2E.pageA);

  const existing = accountRow(page, ACCOUNT_NAME);
  if ((await existing.count()) === 0) {
    await page.getByRole("button", { name: "Add account" }).click();
    const dialog = page.getByRole("dialog", { name: "Add carrier account" });
    await dialog.getByLabel("Display name").fill(ACCOUNT_NAME);
    const providerSelect = dialog.getByRole("combobox", { name: "Provider" });

    await providerSelect.click();
    await providerSelect.press("ArrowDown");
    await providerSelect.press("Enter");
    await dialog.getByLabel("Configuration (JSON)").fill("{}");
    const createResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/facebook/carrier-accounts") &&
        response.request().method() === "POST"
    );
    await dialog.getByRole("button", { name: "OK", exact: true }).click();
    expect((await createResponse).status()).toBe(201);
  }

  const row = accountRow(page, ACCOUNT_NAME);
  await expect(row).toBeVisible();
  await expect(row.getByText("Active", { exact: true })).toBeVisible();
  await expect(row.getByText("Unconfigured", { exact: true })).toBeVisible();
  await expect(row.getByRole("button", { name: /credentials/i })).toHaveCount(0);

  await selectPage(page, E2E.pageB);
  await openCarriers(page, E2E.pageB);
  await expect(accountRow(page, ACCOUNT_NAME)).toHaveCount(0);

  await selectPage(page, E2E.pageA);
  await openCarriers(page, E2E.pageA);
  const reloadedRow = accountRow(page, ACCOUNT_NAME);
  await expect(reloadedRow).toBeVisible();
  await expect(reloadedRow.getByText("Unconfigured", { exact: true })).toBeVisible();
  await expect(reloadedRow.getByRole("button", { name: /credentials/i })).toHaveCount(0);

  await reloadedRow.getByRole("button", { name: "Deactivate" }).click();
  const confirmation = page.getByRole("dialog", { name: "Deactivate carrier account?" });
  const deactivateResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/facebook/carrier-accounts/") &&
      response.url().endsWith("/deactivate") &&
      response.request().method() === "POST"
  );
  await confirmation.getByRole("button", { name: "Deactivate", exact: true }).click();
  expect((await deactivateResponse).status()).toBe(200);
  await expect(reloadedRow.getByText("Inactive", { exact: true })).toBeVisible();
  await expect(reloadedRow.getByText("Unconfigured", { exact: true })).toBeVisible();
  await expect(reloadedRow.getByRole("button", { name: /credentials/i })).toHaveCount(0);
});

async function openCarriers(page: Page, pageName: string): Promise<void> {
  await page.getByRole("menuitem", { name: "Carriers" }).click();
  await expect(page).toHaveURL(/\/settings\/carriers$/);
  await expect(page.getByRole("heading", { name: "Carriers", level: 2 })).toBeVisible();
  await expect(page.getByText(`Settings for ${pageName}`, { exact: true })).toBeVisible();
}

function accountRow(page: Page, name: string): Locator {
  return page.getByRole("listitem").filter({ has: page.getByText(name, { exact: true }) });
}
