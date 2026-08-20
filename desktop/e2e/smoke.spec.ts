import { E2E, expect, selectPage, test } from "./fixtures";

test("operator can navigate core routes and switch Page scope", async ({ authenticatedPage: page }) => {
  await selectPage(page, E2E.pageA);

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

  await selectPage(page, E2E.pageB);
  const currentPageSection = page
  .locator(".settings-section")
  .filter({ has: page.getByRole("heading", { name: "Current Page", level: 4 }) });

await expect(currentPageSection.locator("span.ant-typography", { hasText: E2E.pageB })).toBeVisible();

  await page.getByRole("menuitem", { name: "Orders" }).click();
  await expect(page.getByRole("heading", { name: "Orders", level: 2 })).toBeVisible();
  await expect(page.getByText(E2E.pageB, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(E2E.orderA, { exact: true })).toHaveCount(0);
  await expect(page.getByText("No orders", { exact: true })).toBeVisible();
});
