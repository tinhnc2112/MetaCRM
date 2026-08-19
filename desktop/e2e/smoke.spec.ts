import { E2E, expect, test } from "./fixtures";

test("operator can navigate core routes and switch Page scope", async ({ authenticatedPage: page }) => {
  await page.getByRole("menuitem", { name: "Customers" }).click();
  await expect(page).toHaveURL(/\/customers(?:\/|\?|$)/);
  await expect(page.getByRole("heading", { name: "Customers", level: 2 })).toBeVisible();
  await expect(page.getByText(E2E.customerA, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(E2E.pageA, { exact: true }).first()).toBeVisible();

  await page.getByRole("menuitem", { name: "Products" }).click();
  await expect(page).toHaveURL(/\/products$/);
  await expect(page.getByRole("heading", { name: "Products", level: 2 })).toBeVisible();
  await expect(page.getByText(E2E.productA, { exact: true })).toBeVisible();
  await expect(page.getByText(E2E.pageA, { exact: true }).first()).toBeVisible();

  await page.getByRole("menuitem", { name: "Orders" }).click();
  await expect(page).toHaveURL(/\/orders$/);
  await expect(page.getByRole("heading", { name: "Orders", level: 2 })).toBeVisible();
  await expect(page.getByRole("button", { name: E2E.orderA })).toBeVisible();
  await expect(page.getByText(E2E.pageA, { exact: true }).first()).toBeVisible();

  await page.getByRole("menuitem", { name: "Facebook" }).click();
  await expect(page).toHaveURL(/\/settings\/facebook$/);
  await expect(page.getByRole("heading", { name: "Facebook", level: 2 })).toBeVisible();
  const pageBRow = page.getByRole("listitem").filter({ hasText: E2E.pageB });
  await expect(pageBRow).toBeVisible();
  const switchResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/facebook/pages/e2e-page-b/select") &&
      response.request().method() === "POST"
  );
  await pageBRow.getByRole("button", { name: "Select" }).click();
  expect((await switchResponse).status()).toBe(200);
  await expect(
    page.locator(".settings-section").filter({ hasText: "Current Page" }).getByText(E2E.pageB)
  ).toBeVisible();

  await page.getByRole("menuitem", { name: "Orders" }).click();
  await expect(page.getByRole("heading", { name: "Orders", level: 2 })).toBeVisible();
  await expect(page.getByText(E2E.pageB, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(E2E.orderA, { exact: true })).toHaveCount(0);
  await expect(page.getByText("No orders", { exact: true })).toBeVisible();
});
