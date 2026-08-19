import type { Locator, Page } from "@playwright/test";

import { E2E, expect, test } from "./fixtures";

type CreatedOrder = {
  uuid: string;
  order_number: string;
  shipping_destination: {
    recipient_name: string | null;
    recipient_phone: string | null;
    address_line: string | null;
    ward: string | null;
    district: string | null;
    province: string | null;
    is_complete: boolean;
  } | null;
};

test.setTimeout(90_000);

test("creates and edits a Page-safe structured shipping destination", async ({
  authenticatedPage: page
}) => {
  await selectPage(page, E2E.pageA);
  await page.getByRole("menuitem", { name: "Customers" }).click();
  await expect(page.getByRole("heading", { name: "Customers", level: 2 })).toBeVisible();
  await page.getByRole("listitem").filter({ hasText: E2E.customerA }).first().click();
  await page.getByRole("button", { name: "Create order" }).click();

  const createDialog = page.getByRole("dialog", { name: "Create order" });
  await expect(createDialog.getByLabel("Recipient name")).toHaveValue(E2E.customerA);
  await expect(createDialog.getByLabel("Phone")).toHaveValue("0900000001");
  await createDialog.getByPlaceholder("Required").fill("M29 shipping parcel");
  await createDialog.getByRole("spinbutton", { name: "Item 1 unit price" }).fill("150000");
  await createDialog.getByLabel("Address").fill("12 Đường Hoa Mai");
  await createDialog.getByLabel("Ward").fill("Phường Bến Nghé");
  await createDialog.getByLabel("District").fill("Quận 1");
  await createDialog.getByLabel("Province").fill("Thành phố Hồ Chí Minh");
  await createDialog.getByLabel("Postal code").fill("700000");
  await createDialog.getByLabel("Delivery note").fill("Call before delivery");

  const createResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/facebook/orders") &&
      response.request().method() === "POST"
  );
  await createDialog.getByRole("button", { name: "Create order" }).click();
  const response = await createResponse;
  expect(response.ok()).toBeTruthy();
  const order = (await response.json()) as CreatedOrder;
  expect(order.shipping_destination).toMatchObject({
    recipient_name: E2E.customerA,
    recipient_phone: "0900000001",
    address_line: "12 Đường Hoa Mai",
    ward: "Phường Bến Nghé",
    district: "Quận 1",
    province: "Thành phố Hồ Chí Minh",
    is_complete: true
  });

  const detail = await openOrder(page, order.order_number);
  await expect(detail.getByText("Ready", { exact: true })).toBeVisible();
  await expect(detail.getByText("12 Đường Hoa Mai", { exact: true })).toBeVisible();
  await detail.getByRole("button", { name: "Edit shipping information" }).click();

  const editDialog = page.getByRole("dialog", { name: "Edit shipping information" });
  await editDialog.getByLabel("Address").fill("99 Đường Nguyễn Huệ");
  await editDialog.getByLabel("Delivery note").fill("Deliver after 5pm");
  const updateResponse = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith(`/api/v1/facebook/orders/${order.uuid}/shipping-address`) &&
      candidate.request().method() === "PATCH"
  );
  await editDialog.getByRole("button", { name: "Save shipping information" }).click();
  expect((await updateResponse).status()).toBe(200);
  await expect(detail.getByText("99 Đường Nguyễn Huệ", { exact: true })).toBeVisible();
  await expect(detail.getByText("Deliver after 5pm", { exact: true })).toBeVisible();

  await closeOrderDetail(detail);
  const reopened = await openOrder(page, order.order_number);
  await expect(reopened.getByText("99 Đường Nguyễn Huệ", { exact: true })).toBeVisible();
  await closeOrderDetail(reopened);

  await selectPage(page, E2E.pageB);
  await page.getByRole("menuitem", { name: "Orders" }).click();
  const search = page.getByPlaceholder(
    "Search Order number, Customer name, phone, email, address, or note"
  );
  await search.fill(order.order_number);
  await expect(page.getByRole("button", { name: order.order_number })).toHaveCount(0);
  await expect(page.getByText("No orders match the current filters.", { exact: true })).toBeVisible();

  await selectPage(page, E2E.pageA);
});

async function openOrder(page: Page, orderNumber: string): Promise<Locator> {
  await page.getByRole("menuitem", { name: "Orders" }).click();
  await expect(page.getByRole("heading", { name: "Orders", level: 2 })).toBeVisible();
  const search = page.getByPlaceholder(
    "Search Order number, Customer name, phone, email, address, or note"
  );
  await search.fill(orderNumber);
  await page.getByRole("button", { name: orderNumber }).click();
  const detail = page.getByRole("dialog", { name: `Order ${orderNumber}` });
  await expect(detail).toBeVisible();
  return detail;
}

async function closeOrderDetail(detail: Locator): Promise<void> {
  await detail
    .locator(".ant-modal-footer")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await expect(detail).toBeHidden();
}

async function selectPage(page: Page, pageName: string): Promise<void> {
  await page.getByRole("menuitem", { name: "Facebook" }).click();
  const pageRow = page.getByRole("listitem").filter({ hasText: pageName });
  await expect(pageRow).toBeVisible();
  if ((await pageRow.getByRole("button", { name: "Current Page" }).count()) > 0) {
    return;
  }
  const switchResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/facebook/pages/") &&
      response.url().endsWith("/select") &&
      response.request().method() === "POST"
  );
  await pageRow.getByRole("button", { name: "Select" }).click();
  expect((await switchResponse).status()).toBe(200);
}
