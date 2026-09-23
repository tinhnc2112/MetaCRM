import type { Locator, Page } from "@playwright/test";

import { E2E, expect, test } from "./fixtures";

const API_BASE_URL = "http://127.0.0.1:8001";

type Customer = { uuid: string; name: string | null };
type Product = { uuid: string; name: string };
type Order = {
  uuid: string;
  order_number: string;
  status: "draft" | "confirmed" | "cancelled";
  shipping_status: string;
};
type Shipment = {
  uuid: string;
  shipment_number: string;
  status: "ready" | "packed" | "shipped" | "delivered" | "cancelled";
  recipient: { address_line: string; recipient_name: string };
};
type TimelineItem = {
  kind: "order_event" | "inventory_movement" | "shipment_event";
  event_type?: string;
  movement_type?: string;
  shipment_number?: string;
};

test.setTimeout(90_000);

test("creates and progresses a carrier-neutral Shipment from Order detail", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const customer = await findCustomer(page, accessToken, E2E.customerA);
  const order = await createConfirmedManualOrder(page, accessToken, customer.uuid, "M29.2 Lifecycle");

  const detail = await openOrder(page, order.order_number);
  await expect(detail.getByText("No Shipments", { exact: true })).toBeVisible();

  const createResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${order.uuid}/shipments`) &&
      response.request().method() === "POST"
  );
  await detail.getByRole("button", { name: "Create Shipment" }).click();
  const shipment = (await (await createResponse).json()) as Shipment;
  await expect(detail.getByText(shipment.shipment_number, { exact: true })).toBeVisible();
  await expect(detail.getByText("Shipment · Ready", { exact: true })).toBeVisible();
  await expect(detail.getByText("M29.2 Lifecycle 123 Street")).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "pending" });
  await expectNoInventoryMovements(page, accessToken, order.uuid);

  await updateShipmentFromDetail(page, detail, shipment.uuid, "Mark packed", "packed");
  await expect(detail.getByText(/^Shipping .* Packed$/)).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "packed" });
  await updateShipmentFromDetail(page, detail, shipment.uuid, "Mark shipped", "shipped");
  await expect(detail.getByText(/^Shipping .* Shipped$/)).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "shipped" });
  await updateShipmentFromDetail(page, detail, shipment.uuid, "Mark delivered", "delivered");
  await expect(detail.getByText(/^Shipping .* Delivered$/)).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "delivered" });

  await expect(detail.getByText("Shipment created")).toBeVisible();
  await expect(detail.getByText("Shipment packed")).toBeVisible();
  await expect(detail.getByText("Shipment shipped")).toBeVisible();
  await expect(detail.getByText("Shipment delivered")).toBeVisible();
  await expectTimelineCounts(page, accessToken, order.uuid, {
    CREATED: 1,
    PACKED: 1,
    SHIPPED: 1,
    DELIVERED: 1,
    ORDER_OUT: 0,
    ORDER_CANCEL_RESTORE: 0
  });
  await closeOrderDetail(detail);

  const reopened = await openOrder(page, order.order_number);
  await expect(reopened.getByText(shipment.shipment_number, { exact: true })).toBeVisible();
  await expect(reopened.getByText("Shipment · Delivered", { exact: true })).toBeVisible();
  await closeOrderDetail(reopened);

  await selectPage(page, E2E.pageB);
  await goToOrdersAndSearch(page, order.order_number);
  await expect(page.getByRole("button", { name: order.order_number })).toHaveCount(0);
  await expect(page.getByText("No orders match the current filters.", { exact: true })).toBeVisible();
  await selectPage(page, E2E.pageA);
});

test("blocks Order cancellation while active, then supports replacement and restores inventory once", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const customer = await findCustomer(page, accessToken, E2E.customerA);
  const product = await findProduct(page, accessToken, E2E.criticalProduct);
  const startingStock = await inventoryQuantity(page, accessToken, product.uuid);
  const order = await createConfirmedProductOrder(
    page,
    accessToken,
    customer.uuid,
    product.uuid,
    "M29.2 Replacement"
  );
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(startingStock - 1);

  const detail = await openOrder(page, order.order_number);
  const firstCreate = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${order.uuid}/shipments`) &&
      response.request().method() === "POST"
  );
  await detail.getByRole("button", { name: "Create Shipment" }).click();
  const first = (await (await firstCreate).json()) as Shipment;

  const blockedCancel = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${order.uuid}`) &&
      response.request().method() === "PATCH"
  );
  await detail.getByRole("button", { name: "Cancel Order" }).click();
  await page
    .getByRole("dialog", { name: "Cancel this Order?" })
    .getByRole("button", { name: "Cancel Order" })
    .click();
  expect((await blockedCancel).status()).toBe(409);
  await expect(detail.getByText("Order cannot be cancelled while active Shipments exist")).toBeVisible();

  await updateShipmentFromDetail(page, detail, first.uuid, "Cancel", "cancelled");
  await expect(detail.getByText(/^Shipping .* Cancelled$/)).toBeVisible();
  await detail.getByRole("button", { name: "Edit shipping information" }).click();
  const editDialog = page.getByRole("dialog", { name: "Edit shipping information" });
  await editDialog.getByLabel("Address").fill("M29.2 Replacement 999 Street");
  const editResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${order.uuid}/shipping-address`) &&
      response.request().method() === "PATCH"
  );
  await editDialog.getByRole("button", { name: "Save shipping information" }).click();
  expect((await editResponse).status()).toBe(200);

  const secondCreate = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${order.uuid}/shipments`) &&
      response.request().method() === "POST"
  );
  await detail.getByRole("button", { name: "Create Shipment" }).click();
  const second = (await (await secondCreate).json()) as Shipment;
  expect(second.recipient.address_line).toBe("M29.2 Replacement 999 Street");
  await expect(detail.getByText(first.shipment_number, { exact: true })).toBeVisible();
  await expect(detail.getByText("M29.2 Replacement 123 Street")).toBeVisible();
  await expect(detail.getByText(second.shipment_number, { exact: true })).toBeVisible();
  await expect(detail.getByText("M29.2 Replacement 999 Street")).toBeVisible();
  await updateShipmentFromDetail(page, detail, second.uuid, "Cancel", "cancelled");

  const orderCancel = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${order.uuid}`) &&
      response.request().method() === "PATCH"
  );
  await detail.getByRole("button", { name: "Cancel Order" }).click();
  await page
    .getByRole("dialog", { name: "Cancel this Order?" })
    .getByRole("button", { name: "Cancel Order" })
    .click();
  expect((await orderCancel).status()).toBe(200);
  await expect(detail.getByText(/^Order .* Cancelled$/)).toBeVisible();
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(startingStock);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    CREATED: 2,
    CANCELLED: 2,
    ORDER_OUT: 1,
    ORDER_CANCEL_RESTORE: 1
  });
  await closeOrderDetail(detail);
});

async function createConfirmedManualOrder(
  page: Page,
  token: string,
  customerUuid: string,
  label: string
): Promise<Order> {
  return apiPost<Order>(page, token, "/api/v1/facebook/orders", {
    customer_uuid: customerUuid,
    status: "confirmed",
    items: [{ item_name: `${label} item`, quantity: 1, unit_price: 1000 }],
    shipping_destination: destination(label),
    note: label
  });
}

async function createConfirmedProductOrder(
  page: Page,
  token: string,
  customerUuid: string,
  productUuid: string,
  label: string
): Promise<Order> {
  return apiPost<Order>(page, token, "/api/v1/facebook/orders", {
    customer_uuid: customerUuid,
    status: "confirmed",
    items: [{ product_uuid: productUuid, quantity: 1 }],
    shipping_destination: destination(label),
    note: label
  });
}

function destination(label: string) {
  return {
    recipient_name: `${label} Recipient`,
    recipient_phone: "0900000001",
    address_line: `${label} 123 Street`,
    ward: "Ward 1",
    district: "District 1",
    province: "HCMC",
    country_code: "VN",
    note: `${label} note`
  };
}

async function updateShipmentFromDetail(
  page: Page,
  detail: Locator,
  shipmentUuid: string,
  actionName: string,
  expectedStatus: Shipment["status"]
): Promise<void> {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/shipments/${shipmentUuid}/status`) &&
      response.request().method() === "PATCH"
  );
  await detail.getByRole("button", { name: actionName }).first().click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const shipment = (await response.json()) as Shipment;
  expect(shipment.status).toBe(expectedStatus);
}

async function openOrder(page: Page, orderNumber: string): Promise<Locator> {
  await goToOrdersAndSearch(page, orderNumber);
  await page.getByRole("button", { name: orderNumber }).click();
  const detail = page.getByRole("dialog", { name: `Order ${orderNumber}` });
  await expect(detail).toBeVisible();
  return detail;
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

async function selectPage(page: Page, name: string): Promise<void> {
  await page.getByRole("menuitem", { name: "Facebook" }).click();
  await expect(page.getByRole("heading", { name: "Facebook", level: 2 })).toBeVisible();
  const row = page.getByRole("listitem").filter({ hasText: name });
  await expect(row).toBeVisible();
  if ((await row.getByRole("button", { name: "Current Page" }).count()) > 0) {
    return;
  }
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/facebook/pages/") &&
      response.url().endsWith("/select") &&
      response.request().method() === "POST"
  );
  await row.getByRole("button", { name: "Select" }).click();
  expect((await responsePromise).status()).toBe(200);
}

async function findCustomer(page: Page, token: string, name: string): Promise<Customer> {
  const response = await apiGet<{ items: Customer[] }>(
    page,
    token,
    `/api/v1/facebook/customers?q=${encodeURIComponent(name)}&page=1&page_size=20`
  );
  const customer = response.items.find((item) => item.name === name);
  expect(customer, `Expected seeded Customer ${name}`).toBeTruthy();
  return customer as Customer;
}

async function findProduct(page: Page, token: string, name: string): Promise<Product> {
  const response = await apiGet<{ items: Product[] }>(
    page,
    token,
    `/api/v1/facebook/products?q=${encodeURIComponent(name)}&page=1&page_size=20&active=true`
  );
  const product = response.items.find((item) => item.name === name);
  expect(product, `Expected seeded Product ${name}`).toBeTruthy();
  return product as Product;
}

async function getOrder(page: Page, token: string, orderUuid: string): Promise<Order> {
  return apiGet<Order>(page, token, `/api/v1/facebook/orders/${orderUuid}`);
}

async function inventoryQuantity(page: Page, token: string, productUuid: string): Promise<number> {
  const response = await apiGet<{ quantity_on_hand: number | null }>(
    page,
    token,
    `/api/v1/facebook/products/${productUuid}/inventory`
  );
  expect(response.quantity_on_hand).not.toBeNull();
  return response.quantity_on_hand as number;
}

async function expectNoInventoryMovements(page: Page, token: string, orderUuid: string): Promise<void> {
  await expectTimelineCounts(page, token, orderUuid, {
    ORDER_OUT: 0,
    ORDER_CANCEL_RESTORE: 0
  });
}

async function expectTimelineCounts(
  page: Page,
  token: string,
  orderUuid: string,
  expected: Record<string, number>
): Promise<void> {
  const response = await apiGet<{ items: TimelineItem[] }>(
    page,
    token,
    `/api/v1/facebook/orders/${orderUuid}/timeline`
  );
  for (const [type, count] of Object.entries(expected)) {
    const actual = response.items.filter(
      (item) => item.event_type === type || item.movement_type === type
    ).length;
    expect(actual, `Expected ${count} ${type} timeline entries`).toBe(count);
  }
}

async function apiGet<T>(page: Page, token: string, path: string): Promise<T> {
  const response = await page.request.get(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  expect(response.ok(), `GET ${path} returned ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

async function apiPost<T>(
  page: Page,
  token: string,
  path: string,
  data: Record<string, unknown>
): Promise<T> {
  const response = await page.request.post(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    data
  });
  expect(response.ok(), `POST ${path} returned ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}
