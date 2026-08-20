import type { Locator, Page } from "@playwright/test";

import { E2E, expect, selectPage, test } from "./fixtures";

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
  carrier_name: string | null;
  tracking_number: string | null;
  tracking_url: string | null;
  shipping_fee: string | null;
  cod_amount: string | null;
  note: string | null;
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
  const shipmentCard = shipmentCardByNumber(detail, shipment.shipment_number);
  await expect(detail.getByText(shipment.shipment_number, { exact: true })).toBeVisible();
  await expect(detail.getByText("Shipment · Ready", { exact: true })).toBeVisible();
  await expect(shipmentCard.getByText("M29.2 Lifecycle 123 Street, Ward 1, District 1, HCMC, VN", { exact: true })).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "pending" });
  await expectNoInventoryMovements(page, accessToken, order.uuid);

  await updateTrackingFromDetail(page, detail, shipment);
  await expect(
    shipmentCard.locator(".ant-descriptions-item-content").getByText("Manual Carrier", { exact: true })
  ).toBeVisible();
  await expect(
    shipmentCard.locator(".ant-descriptions-item-content").getByText("M293-TRACK-123", { exact: true })
  ).toBeVisible();
  await expect(shipmentCard.getByRole("link", { name: "https://tracking.example/M293-TRACK-123" })).toHaveAttribute(
    "href",
    "https://tracking.example/M293-TRACK-123"
  );
  await expect(detail.getByText("Shipment tracking updated")).toBeVisible();
  await expectNoInventoryMovements(page, accessToken, order.uuid);

  await updateShipmentFromDetail(page, detail, shipment, "Mark packed", "packed");
  await expect(detail.getByText(/^Shipping .* Packed$/)).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "packed" });
  await updateShipmentFromDetail(page, detail, shipment, "Mark shipped", "shipped");
  await expect(detail.getByText(/^Shipping .* Shipped$/)).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "shipped" });
  await updateShipmentFromDetail(page, detail, shipment, "Mark delivered", "delivered");
  await expect(detail.getByText(/^Shipping .* Delivered$/)).toBeVisible();
  expect(await getOrder(page, accessToken, order.uuid)).toMatchObject({ shipping_status: "delivered" });

  await expect(detail.getByText("Shipment created")).toBeVisible();
  await expect(detail.getByText("Shipment packed")).toBeVisible();
  await expect(detail.getByText("Shipment shipped")).toBeVisible();
  await expect(detail.getByText("Shipment delivered")).toBeVisible();
  await expectTimelineCounts(page, accessToken, order.uuid, {
    CREATED: 1,
    TRACKING_UPDATED: 1,
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

  const blockedCancel = await cancelOrderFromDetail(page, detail, order.uuid);
  expect(blockedCancel.status()).toBe(409);
  await expect(detail.getByText("Order cannot be cancelled while active Shipments exist")).toBeVisible();

  await updateShipmentFromDetail(page, detail, first, "Cancel", "cancelled");
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
  await expect(shipmentCardByNumber(detail, first.shipment_number).getByText("M29.2 Replacement 123 Street, Ward 1, District 1, HCMC, VN", { exact: true })).toBeVisible();
  await expect(detail.getByText(second.shipment_number, { exact: true })).toBeVisible();
  await expect(shipmentCardByNumber(detail, second.shipment_number).getByText("M29.2 Replacement 999 Street, Ward 1, District 1, HCMC, VN", { exact: true })).toBeVisible();
  await updateShipmentFromDetail(page, detail, second, "Cancel", "cancelled");

  const orderCancel = await cancelOrderFromDetail(page, detail, order.uuid);
  expect(orderCancel.status()).toBe(200);
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
  shipment: Shipment,
  actionName: string,
  expectedStatus: Shipment["status"]
): Promise<void> {
  const card = shipmentCardByNumber(detail, shipment.shipment_number);
  await expect(card).toBeVisible();
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/shipments/${shipment.uuid}/status`) &&
      response.request().method() === "PATCH"
  );
  await card.getByRole("button", { name: actionName, exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const updatedShipment = (await response.json()) as Shipment;
  expect(updatedShipment.uuid).toBe(shipment.uuid);
  expect(updatedShipment.status).toBe(expectedStatus);
}

async function updateTrackingFromDetail(
  page: Page,
  detail: Locator,
  shipment: Shipment
): Promise<void> {
  const card = shipmentCardByNumber(detail, shipment.shipment_number);
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Edit tracking", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Edit tracking" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Carrier name").fill("Manual Carrier");
  await dialog.getByLabel("Tracking number").fill("M293-TRACK-123");
  await dialog.getByLabel("Tracking URL").fill("https://tracking.example/M293-TRACK-123");
  await dialog.getByLabel("Shipping fee").fill("15000");
  await dialog.getByLabel("COD amount").fill("99000");
  await dialog.getByLabel("Tracking note").fill("Leave at front desk");
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/shipments/${shipment.uuid}/tracking`) &&
      response.request().method() === "PATCH"
  );
  await dialog.getByRole("button", { name: "Save tracking", exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const updatedShipment = (await response.json()) as Shipment;
  expect(updatedShipment.uuid).toBe(shipment.uuid);
  expect(updatedShipment.carrier_name).toBe("Manual Carrier");
  expect(updatedShipment.tracking_number).toBe("M293-TRACK-123");
  expect(updatedShipment.tracking_url).toBe("https://tracking.example/M293-TRACK-123");
}

async function cancelOrderFromDetail(
  page: Page,
  detail: Locator,
  orderUuid: string
) {
  await detail.getByRole("button", { name: "Cancel Order", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Cancel this Order?" });
  await expect(confirmation).toBeVisible();
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/facebook/orders/${orderUuid}`) &&
      response.request().method() === "PATCH"
  );
  await confirmation.getByRole("button", { name: "Cancel Order", exact: true }).click();
  const response = await responsePromise;
  await expect(confirmation).toBeHidden();
  return response;
}

function shipmentCardByNumber(detail: Locator, shipmentNumber: string): Locator {
  return detail
    .getByRole("region", { name: "Shipments" })
    .getByRole("listitem")
    .filter({ hasText: shipmentNumber });
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
