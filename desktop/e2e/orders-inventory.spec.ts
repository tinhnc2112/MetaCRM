import type { Locator, Page } from "@playwright/test";

import { E2E, expect, selectPage, test } from "./fixtures";

const API_BASE_URL = "http://127.0.0.1:8001";

type ProductListItem = {
  uuid: string;
  name: string;
  sku: string | null;
};

type OrderResponse = {
  uuid: string;
  order_number: string;
  status: "draft" | "confirmed" | "cancelled";
  payment_status: string;
  shipping_status: string;
};

type InventoryResponse = {
  product_uuid: string;
  quantity_on_hand: number | null;
  track_inventory: boolean;
};

type TimelineItem = {
  kind: "order_event" | "inventory_movement";
  event_type?: string;
  movement_type?: string;
  quantity_delta?: number;
  quantity_before?: number;
  quantity_after?: number;
};

test.setTimeout(90_000);

test("creates, confirms, operates, cancels, and restores a tracked Product Order", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const product = await findProduct(page, accessToken, E2E.criticalProduct);
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(E2E.criticalStartingStock);

  const order = await createOrderFromCustomer(page, E2E.criticalProduct, 2);

  await goToOrdersAndSearch(page, order.order_number);
  await expectOrderInQueue(page, "Drafts", order.order_number, true);
  let detail = await openOrderFromAll(page, order.order_number);
  await expect(detail.getByText(/^Order .* Draft$/)).toBeVisible();

  const confirmResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${order.uuid}`) &&
      response.request().method() === "PATCH"
  );
  await detail.getByRole("button", { name: "Confirm Order" }).click();
  await page
    .getByRole("dialog", { name: "Confirm this Order?" })
    .getByRole("button", { name: "Confirm Order" })
    .click();
  expect((await confirmResponse).status()).toBe(200);
  await expect(detail.getByText(/^Order .* Confirmed$/)).toBeVisible();
  await expect(detail.getByText("Order confirmed", { exact: true })).toBeVisible();
  await expect(detail.getByText("Inventory consumed", { exact: true })).toBeVisible();
  await expect(
    detail
      .locator("span.ant-typography")
      .filter({ hasText: E2E.criticalProduct })
      .filter({ hasText: E2E.criticalProductSku })
      .filter({ hasText: "-2" })
      .filter({ hasText: "10" })
      .filter({ hasText: "8" })
  ).toBeVisible();
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(8);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    ORDER_CONFIRMED: 1,
    ORDER_OUT: 1
  });

  await closeOrderDetail(detail);
  await expectOrderInQueue(page, "Needs payment", order.order_number, true);
  await expectOrderInQueue(page, "Needs packing", order.order_number, true);
  detail = await openOrderFromAll(page, order.order_number);

  await selectOption(detail.getByRole("combobox", { name: "Payment status" }), page, "Paid");
  const paymentResponse = waitForOrderPatch(page, order.uuid);
  await detail.getByRole("button", { name: "Save statuses" }).click();
  expect((await paymentResponse).status()).toBe(200);
  await expect(detail.getByText(/^Payment .* Paid$/)).toBeVisible();
  await expect(detail.getByText(/Payment: Unpaid.*Paid/i)).toBeVisible();
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(8);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    PAYMENT_STATUS_CHANGED: 1,
    ORDER_OUT: 1
  });

  await closeOrderDetail(detail);
  await expectOrderInQueue(page, "Needs payment", order.order_number, false);
  await expectOrderInQueue(page, "Needs packing", order.order_number, true);
  detail = await openOrderFromAll(page, order.order_number);

  await selectOption(detail.getByRole("combobox", { name: "Shipping status" }), page, "Packed");
  const shippingResponse = waitForOrderPatch(page, order.uuid);
  await detail.getByRole("button", { name: "Save statuses" }).click();
  expect((await shippingResponse).status()).toBe(200);
  await expect(detail.getByText(/^Shipping .* Packed$/)).toBeVisible();
  await expect(detail.getByText(/Shipping: Pending.*Packed/i)).toBeVisible();
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(8);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    SHIPPING_STATUS_CHANGED: 1,
    ORDER_OUT: 1,
    ORDER_CANCELLED: 0
  });

  await closeOrderDetail(detail);
  await expectOrderInQueue(page, "Needs packing", order.order_number, false);
  await expectOrderInQueue(page, "Packed", order.order_number, true);
  detail = await openOrderFromAll(page, order.order_number);

  const cancelResponse = waitForOrderPatch(page, order.uuid);
  await detail.getByRole("button", { name: "Cancel Order" }).click();
  await page
    .getByRole("dialog", { name: "Cancel this Order?" })
    .getByRole("button", { name: "Cancel Order" })
    .click();
  expect((await cancelResponse).status()).toBe(200);
  await expect(detail.getByText(/^Order .* Cancelled$/)).toBeVisible();
  await expect(detail.getByText("Order cancelled", { exact: true })).toBeVisible();
  await expect(detail.getByText("Inventory restored", { exact: true })).toBeVisible();
  await expect(
    detail
      .locator("span.ant-typography")
      .filter({ hasText: E2E.criticalProduct })
      .filter({ hasText: E2E.criticalProductSku })
      .filter({ hasText: "+2" })
      .filter({ hasText: "8" })
      .filter({ hasText: "10" })
  ).toBeVisible();
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(10);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    ORDER_CONFIRMED: 1,
    PAYMENT_STATUS_CHANGED: 1,
    SHIPPING_STATUS_CHANGED: 1,
    ORDER_CANCELLED: 1,
    ORDER_OUT: 1,
    ORDER_CANCEL_RESTORE: 1
  });

  await closeOrderDetail(detail);
  await expectOrderInQueue(page, "Cancelled", order.order_number, true);

  await selectPage(page, E2E.pageB);
  await goToOrdersAndSearch(page, order.order_number);
  await expect(page.getByRole("button", { name: order.order_number })).toHaveCount(0);
  await expect(page.getByText("No orders match the current filters.", { exact: true })).toBeVisible();

  await selectPage(page, E2E.pageA);
  await goToOrdersAndSearch(page, order.order_number);
  await expect(page.getByRole("button", { name: order.order_number })).toBeVisible();
  detail = await openOrderFromAll(page, order.order_number);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    ORDER_OUT: 1,
    ORDER_CANCEL_RESTORE: 1
  });
  await closeOrderDetail(detail);
});

test("keeps a draft unchanged when tracked Product stock is insufficient", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const product = await findProduct(page, accessToken, E2E.lowStockProduct);
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(E2E.lowStartingStock);

  const order = await createOrderFromCustomer(page, E2E.lowStockProduct, 2);
  await goToOrdersAndSearch(page, order.order_number);
  await expectOrderInQueue(page, "Drafts", order.order_number, true);
  const detail = await openOrderFromAll(page, order.order_number);

  const failedConfirm = waitForOrderPatch(page, order.uuid);
  await detail.getByRole("button", { name: "Confirm Order" }).click();
  await page
    .getByRole("dialog", { name: "Confirm this Order?" })
    .getByRole("button", { name: "Confirm Order" })
    .click();
  expect((await failedConfirm).status()).toBe(409);
  await expect(detail.getByText(/stock|inventory|available/i).first()).toBeVisible();
  await expect(detail.getByText(/^Order .* Draft$/)).toBeVisible();
  await expect(detail.getByText("Order created", { exact: true })).toBeVisible();
  await expect(detail.getByText("Order confirmed", { exact: true })).toHaveCount(0);
  await expect(detail.getByText("Inventory consumed", { exact: true })).toHaveCount(0);

  const persistedOrder = await apiGet<OrderResponse>(
    page,
    accessToken,
    `/api/v1/facebook/orders/${order.uuid}`
  );
  expect(persistedOrder.status).toBe("draft");
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(1);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    ORDER_CREATED: 1,
    ORDER_CONFIRMED: 0,
    ORDER_OUT: 0,
    ORDER_CANCEL_RESTORE: 0
  });

  await closeOrderDetail(detail);
  await expectOrderInQueue(page, "Drafts", order.order_number, true);
});

async function createOrderFromCustomer(
  page: Page,
  productName: string,
  quantity: number
): Promise<OrderResponse> {
  await page.getByRole("menuitem", { name: "Customers" }).click();
  await expect(page.getByRole("heading", { name: "Customers", level: 2 })).toBeVisible();
  await expect(page.getByText(E2E.customerA, { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Create order" }).click();

  const dialog = page.getByRole("dialog", { name: "Create order" });
  await expect(dialog).toBeVisible();
  await dialog.getByText("Catalog Product", { exact: true }).click();
  const productPicker = dialog.getByRole("combobox", {
    name: "Search and select a catalog product"
  });
  await productPicker.click();
  await productPicker.fill(productName);
  await page.locator(".ant-select-item-option").filter({ hasText: productName }).click();
  await expect(dialog.getByText(productName, { exact: true })).toBeVisible();
  await dialog.getByRole("spinbutton", { name: "Item 1 quantity" }).fill(String(quantity));

  const createResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/facebook/orders") &&
      response.request().method() === "POST"
  );
  await dialog.getByRole("button", { name: "Create order" }).click();
  const response = await createResponse;
  expect(response.ok()).toBeTruthy();
  const order = (await response.json()) as OrderResponse;
  await expect(dialog).toBeHidden();
  await expect(page.getByText(order.order_number, { exact: true })).toBeVisible();
  return order;
}

async function goToOrdersAndSearch(page: Page, orderNumber: string): Promise<void> {
  await page.getByRole("menuitem", { name: "Orders" }).click();
  await expect(page.getByRole("heading", { name: "Orders", level: 2 })).toBeVisible();
  const search = page.getByPlaceholder(
    "Search Order number, Customer name, phone, email, address, or note"
  );
  await search.fill(orderNumber);
  await expect(search).toHaveValue(orderNumber);
}

async function closeOrderDetail(detail: Locator): Promise<void> {
  await detail
    .locator(".ant-modal-footer")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await expect(detail).toBeHidden();
}

function queueButton(page: Page, label: string): Locator {
  return page
    .getByRole("group", { name: "Operational Order queues" })
    .getByRole("button", { name: new RegExp(`^${label} \\(\\d+\\)$`) });
}

async function expectOrderInQueue(
  page: Page,
  queue: string,
  orderNumber: string,
  present: boolean
): Promise<void> {
  await queueButton(page, queue).click();
  const order = page.getByRole("button", { name: orderNumber });
  if (present) {
    await expect(order).toHaveCount(1);
    await expect(order).toBeVisible();
  } else {
    await expect(order).toHaveCount(0);
  }
}

async function openOrderFromAll(page: Page, orderNumber: string): Promise<Locator> {
  await queueButton(page, "All").click();
  await page.getByRole("button", { name: orderNumber }).click();
  const detail = page.getByRole("dialog", { name: `Order ${orderNumber}` });
  await expect(detail).toBeVisible();
  return detail;
}

async function selectOption(select: Locator, page: Page, option: string): Promise<void> {
  await select.press("ArrowDown");
  await page.getByTitle(option, { exact: true }).last().click();
}

function waitForOrderPatch(page: Page, orderUuid: string) {
  return page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${orderUuid}`) &&
      response.request().method() === "PATCH"
  );
}

async function findProduct(page: Page, accessToken: string, name: string): Promise<ProductListItem> {
  const response = await apiGet<{ items: ProductListItem[] }>(
    page,
    accessToken,
    `/api/v1/facebook/products?q=${encodeURIComponent(name)}&page=1&page_size=20&active=true`
  );
  const product = response.items.find((item) => item.name === name);
  expect(product, `Expected seeded Product ${name}`).toBeTruthy();
  return product as ProductListItem;
}

async function inventoryQuantity(page: Page, accessToken: string, productUuid: string) {
  const inventory = await apiGet<InventoryResponse>(
    page,
    accessToken,
    `/api/v1/facebook/products/${productUuid}/inventory`
  );
  expect(inventory.track_inventory).toBe(true);
  return inventory.quantity_on_hand;
}

async function expectTimelineCounts(
  page: Page,
  accessToken: string,
  orderUuid: string,
  expected: Record<string, number>
): Promise<void> {
  const timeline = await apiGet<{ items: TimelineItem[] }>(
    page,
    accessToken,
    `/api/v1/facebook/orders/${orderUuid}/timeline`
  );
  for (const [type, count] of Object.entries(expected)) {
    const actual = timeline.items.filter(
      (item) => item.event_type === type || item.movement_type === type
    ).length;
    expect(actual, `Expected ${count} ${type} timeline entries`).toBe(count);
  }
}

async function apiGet<T>(page: Page, accessToken: string, path: string): Promise<T> {
  const response = await page.request.get(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` }
  });
  expect(response.ok(), `GET ${path} returned ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}
