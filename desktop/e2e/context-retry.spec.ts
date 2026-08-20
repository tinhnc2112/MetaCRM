import type { Locator, Page, Request, Route } from "@playwright/test";

import { E2E, expect, selectPage, test } from "./fixtures";

const API_BASE_URL = "http://127.0.0.1:8001";
const CREATE_ORDER_ROUTE = "**/api/v1/facebook/orders";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Customer = { uuid: string; name: string | null };
type Product = { uuid: string; name: string };
type Order = {
  uuid: string;
  order_number: string;
  customer_uuid: string;
  customer_name: string | null;
  conversation_uuid: string | null;
  status: "draft" | "confirmed" | "cancelled";
  payment_status: string;
};
type TimelineItem = {
  event_type?: string;
  movement_type?: string;
};
type CapturedCreate = {
  key: string;
  payload: Record<string, unknown>;
  order: Order;
};

test.setTimeout(90_000);

test("reuses one logical create after committed response loss and blocks rapid double submit", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  await openCustomer(page, E2E.customerA);
  const marker = "M28.3 Ambiguous Exact Retry";
  const dialog = await openManualOrder(page, marker, marker);

  let createRequestCount = 0;
  const countCreate = (request: Request) => {
    if (isOrderCreate(request)) {
      createRequestCount += 1;
    }
  };
  page.on("request", countCreate);
  const ambiguity = await interceptCommittedCreate(page);
  const createButton = dialog.getByRole("button", { name: "Create order" });
  await createButton.evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });

  const first = await ambiguity.committed;
  expect(first.key).toMatch(UUID_PATTERN);
  expect(first.payload.note).toBe(marker);
  await expect(dialog.getByText(/result is uncertain.*retry.*same request/i)).toBeVisible();
  await expect(createButton).toBeEnabled();
  expect(createRequestCount).toBe(1);
  await ambiguity.dispose();

  const retryRequestPromise = page.waitForRequest(isOrderCreate);
  const retryResponsePromise = page.waitForResponse(
    (response) => isOrderCreate(response.request()) && response.ok()
  );
  await createButton.click();
  const retryRequest = await retryRequestPromise;
  const retryResponse = await retryResponsePromise;
  const retryOrder = (await retryResponse.json()) as Order;
  const retryKey = idempotencyKey(retryRequest);
  const retryPayload = retryRequest.postDataJSON() as Record<string, unknown>;

  expect(retryKey).toBe(first.key);
  expect(retryPayload).toEqual(first.payload);
  expect(retryOrder.uuid).toBe(first.order.uuid);
  expect(createRequestCount).toBe(2);
  await expect(dialog).toBeHidden();
  await expect(page.getByText(first.order.order_number, { exact: true })).toBeVisible();

  const orders = await listOrders(page, accessToken, marker);
  expect(orders).toHaveLength(1);
  expect(orders[0]?.uuid).toBe(first.order.uuid);
  await expectTimelineCounts(page, accessToken, first.order.uuid, { ORDER_CREATED: 1 });
  page.off("request", countCreate);
});

test("uses a new logical identity for edited payload and again after success", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  await openCustomer(page, E2E.customerA);
  const itemName = "M28.3 Changed Payload Item";
  const firstNote = "M28.3 Changed Payload A";
  const secondNote = "M28.3 Changed Payload B";
  let dialog = await openManualOrder(page, itemName, firstNote);

  const ambiguity = await interceptCommittedCreate(page);
  await dialog.getByRole("button", { name: "Create order" }).click();
  const first = await ambiguity.committed;
  await expect(dialog.getByText(/result is uncertain/i)).toBeVisible();
  await ambiguity.dispose();

  await dialog.getByPlaceholder("Optional internal note").fill(secondNote);
  const secondRequestPromise = page.waitForRequest(isOrderCreate);
  const secondResponsePromise = page.waitForResponse(
    (response) => isOrderCreate(response.request()) && response.ok()
  );
  await dialog.getByRole("button", { name: "Create order" }).click();
  const secondRequest = await secondRequestPromise;
  const secondResponse = await secondResponsePromise;
  const secondOrder = (await secondResponse.json()) as Order;
  const secondKey = idempotencyKey(secondRequest);
  const secondPayload = secondRequest.postDataJSON() as Record<string, unknown>;

  expect(secondKey).not.toBe(first.key);
  expect(secondPayload.note).toBe(secondNote);
  expect(secondOrder.uuid).not.toBe(first.order.uuid);
  await expect(dialog).toBeHidden();

  dialog = await openManualOrder(page, itemName, secondNote);
  const thirdRequestPromise = page.waitForRequest(isOrderCreate);
  const thirdResponsePromise = page.waitForResponse(
    (response) => isOrderCreate(response.request()) && response.ok()
  );
  await dialog.getByRole("button", { name: "Create order" }).click();
  const thirdRequest = await thirdRequestPromise;
  const thirdOrder = (await (await thirdResponsePromise).json()) as Order;

  expect(idempotencyKey(thirdRequest)).not.toBe(secondKey);
  expect(thirdRequest.postDataJSON()).toEqual(secondPayload);
  expect(thirdOrder.uuid).not.toBe(secondOrder.uuid);
  expect(await listOrders(page, accessToken, "M28.3 Changed Payload")).toHaveLength(3);
  await expectTimelineCounts(page, accessToken, first.order.uuid, { ORDER_CREATED: 1 });
  await expectTimelineCounts(page, accessToken, secondOrder.uuid, { ORDER_CREATED: 1 });
  await expectTimelineCounts(page, accessToken, thirdOrder.uuid, { ORDER_CREATED: 1 });
});

test("keeps a completed Page A mutation out of Page B UI while its response is pending", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  await openOrderByNumber(page, E2E.orderA);
  const detail = page.getByRole("dialog", { name: `Order ${E2E.orderA}` });
  const order = await findOrder(page, accessToken, E2E.orderA);
  await selectOption(detail.getByRole("combobox", { name: "Payment status" }), page, "Paid");

  const delayed = await delayRealPatch(page, order.uuid);
  await detail.getByRole("button", { name: "Save statuses" }).click();
  const backendOrder = await delayed.backendCommitted;
  expect(backendOrder.payment_status).toBe("paid");
  await expect(detail.getByRole("button", { name: "Save statuses" })).toBeDisabled();

  await page.getByRole("menuitem", { name: "Facebook" }).click({ force: true });
  await selectPage(page, E2E.pageB);
  await delayed.release();
  await delayed.browserReleased;
  await page.getByRole("menuitem", { name: "Orders" }).click();
  await expect(page.getByRole("heading", { name: "Orders", level: 2 })).toBeVisible();
  await expect(page.getByText(E2E.pageB, { exact: true })).toBeVisible();
  await expect(page.getByText("0 orders", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog", { name: `Order ${E2E.orderA}` })).toHaveCount(0);
  await expect(page.getByText("Order updated.", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: E2E.orderA })).toHaveCount(0);

  await selectPage(page, E2E.pageA);
  await openOrderByNumber(page, E2E.orderA);
  const refreshedDetail = page.getByRole("dialog", { name: `Order ${E2E.orderA}` });
  await expect(refreshedDetail.getByText(/^Payment .* Paid$/)).toBeVisible();
  await expect(refreshedDetail.getByText(/Payment: Unpaid.*Paid/i)).toBeVisible();
  await expectTimelineCounts(page, accessToken, order.uuid, { PAYMENT_STATUS_CHANGED: 1 });
  await delayed.dispose();
});

test("does not leak ambiguous Customer A create state into Customer Beta", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const customerA = await findCustomer(page, accessToken, E2E.customerA);
  const customerBeta = await findCustomer(page, accessToken, E2E.customerBeta);
  await openCustomer(page, E2E.customerA);
  const alphaMarker = "M28.3 Customer Alpha Ambiguous";
  const betaMarker = "M28.3 Customer Beta Fresh";
  let dialog = await openManualOrder(page, alphaMarker, alphaMarker, 3);

  const ambiguity = await interceptCommittedCreate(page);
  await dialog.getByRole("button", { name: "Create order" }).click();
  const alpha = await ambiguity.committed;
  await expect(dialog.getByText(/result is uncertain/i)).toBeVisible();
  await ambiguity.dispose();
  await closeCreateDialog(dialog);

  await selectCustomerFromList(page, E2E.customerBeta);
  dialog = await openCreateDialog(page);
  await expect(dialog.getByPlaceholder("Required")).toHaveValue("");
  await expect(dialog.getByPlaceholder("Optional internal note")).toHaveValue("");
  await expect(dialog.getByRole("spinbutton", { name: "Item 1 quantity" })).toHaveValue("1");
  await expect(dialog.getByText(customerBeta.uuid, { exact: true })).toBeVisible();
  await fillManualOrder(dialog, betaMarker, betaMarker, 1);

  const betaRequestPromise = page.waitForRequest(isOrderCreate);
  const betaResponsePromise = page.waitForResponse(
    (response) => isOrderCreate(response.request()) && response.ok()
  );
  await dialog.getByRole("button", { name: "Create order" }).click();
  const betaRequest = await betaRequestPromise;
  const betaOrder = (await (await betaResponsePromise).json()) as Order;
  const betaPayload = betaRequest.postDataJSON() as Record<string, unknown>;

  expect(idempotencyKey(betaRequest)).not.toBe(alpha.key);
  expect(alpha.payload.customer_uuid).toBe(customerA.uuid);
  expect(betaPayload.customer_uuid).toBe(customerBeta.uuid);
  expect(betaPayload.note).toBe(betaMarker);
  expect(alpha.payload.conversation_uuid).toBeUndefined();
  expect(betaPayload.conversation_uuid).toBeUndefined();
  expect(alpha.order.conversation_uuid).toBeNull();
  expect(betaOrder.conversation_uuid).toBeNull();
  expect(betaOrder.customer_uuid).toBe(customerBeta.uuid);
  expect(betaOrder.customer_name).toBe(E2E.customerBeta);
  expect(await listCustomerOrders(page, accessToken, customerA.uuid, alphaMarker)).toHaveLength(1);
  expect(await listCustomerOrders(page, accessToken, customerBeta.uuid, betaMarker)).toHaveLength(1);

  await expect(page.getByText(betaOrder.order_number, { exact: true })).toBeVisible();
  await selectCustomerFromList(page, E2E.customerA);
  await expect(page.getByText(alpha.order.order_number, { exact: true })).toBeVisible();
  await expect(page.getByText(betaOrder.order_number, { exact: true })).toHaveCount(0);
});

test("confirms exactly once when stock is replenished after a 409", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const product = await findProduct(page, accessToken, E2E.lowStockProduct);
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(1);
  await openCustomer(page, E2E.customerA);
  const order = await createCatalogOrder(page, E2E.lowStockProduct, 2, "M28.3 Stock Retry");
  await openOrderByNumber(page, order.order_number);
  const detail = page.getByRole("dialog", { name: `Order ${order.order_number}` });

  const failedPatch = page.waitForResponse(
    (response) => isOrderPatch(response.request(), order.uuid)
  );
  await confirmOrder(page, detail);
  expect((await failedPatch).status()).toBe(409);
  await expect(detail.getByText(/stock|inventory|available/i).first()).toBeVisible();
  await expect(detail.getByText(/^Order .* Draft$/)).toBeVisible();
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(1);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    ORDER_CREATED: 1,
    ORDER_CONFIRMED: 0,
    ORDER_OUT: 0
  });

  await apiPost(page, accessToken, `/api/v1/facebook/products/${product.uuid}/inventory/adjustments`, {
    quantity_delta: 2,
    note: "M28.3 replenish after expected stock conflict",
    idempotency_key: crypto.randomUUID()
  });
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(3);

  const successfulPatch = page.waitForResponse(
    (response) => isOrderPatch(response.request(), order.uuid)
  );
  await confirmOrder(page, detail);
  expect((await successfulPatch).status()).toBe(200);
  await expect(detail.getByText(/^Order .* Confirmed$/)).toBeVisible();
  expect(await inventoryQuantity(page, accessToken, product.uuid)).toBe(1);
  await expectTimelineCounts(page, accessToken, order.uuid, {
    ORDER_CREATED: 1,
    ORDER_CONFIRMED: 1,
    ORDER_OUT: 1
  });
});

async function interceptCommittedCreate(page: Page) {
  let resolveCommitted!: (value: CapturedCreate) => void;
  let rejectCommitted!: (reason: unknown) => void;
  const committed = new Promise<CapturedCreate>((resolve, reject) => {
    resolveCommitted = resolve;
    rejectCommitted = reject;
  });
  const handler = async (route: Route) => {
    const request = route.request();
    try {
      const key = idempotencyKey(request);
      const payload = request.postDataJSON() as Record<string, unknown>;
      const response = await route.fetch();
      expect(response.ok()).toBeTruthy();
      const order = (await response.json()) as Order;
      resolveCommitted({ key, payload, order });
      await route.abort("failed");
    } catch (error) {
      rejectCommitted(error);
      await route.abort("failed").catch(() => undefined);
    }
  };
  await page.route(CREATE_ORDER_ROUTE, handler, { times: 1 });
  return {
    committed,
    dispose: () => page.unroute(CREATE_ORDER_ROUTE, handler)
  };
}

async function delayRealPatch(page: Page, orderUuid: string) {
  let releaseResponse!: () => void;
  let resolveCommitted!: (order: Order) => void;
  let rejectCommitted!: (reason: unknown) => void;
  let resolveReleased!: () => void;
  const gate = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  const backendCommitted = new Promise<Order>((resolve, reject) => {
    resolveCommitted = resolve;
    rejectCommitted = reject;
  });
  const browserReleased = new Promise<void>((resolve) => {
    resolveReleased = resolve;
  });
  const routePattern = `**/api/v1/facebook/orders/${orderUuid}`;
  const handler = async (route: Route) => {
    try {
      const response = await route.fetch();
      expect(response.ok()).toBeTruthy();
      resolveCommitted((await response.json()) as Order);
      await gate;
      await route.fulfill({ response });
    } catch (error) {
      rejectCommitted(error);
    } finally {
      resolveReleased();
    }
  };
  await page.route(routePattern, handler, { times: 1 });
  return {
    backendCommitted,
    browserReleased,
    release: async () => releaseResponse(),
    dispose: () => page.unroute(routePattern, handler)
  };
}

async function openCustomer(page: Page, name: string): Promise<void> {
  await page.getByRole("menuitem", { name: "Customers" }).click();
  await expect(page.getByRole("heading", { name: "Customers", level: 2 })).toBeVisible();
  await selectCustomerFromList(page, name);
}

async function selectCustomerFromList(page: Page, name: string): Promise<void> {
  const row = page.getByRole("listitem").filter({ hasText: name }).first();
  await expect(row).toBeVisible();
  await row.click();
  await expect(
    page.locator(".messenger-profile-header").getByRole("heading", { name, level: 4 })
  ).toBeVisible();
}

async function openCreateDialog(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Create order" }).click();
  const dialog = page.getByRole("dialog", { name: "Create order" });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function openManualOrder(
  page: Page,
  itemName: string,
  note: string,
  quantity = 1
): Promise<Locator> {
  const dialog = await openCreateDialog(page);
  await fillManualOrder(dialog, itemName, note, quantity);
  return dialog;
}

async function fillManualOrder(
  dialog: Locator,
  itemName: string,
  note: string,
  quantity = 1
): Promise<void> {
  await dialog.getByPlaceholder("Required").fill(itemName);
  await dialog.getByPlaceholder("Optional internal note").fill(note);
  await dialog.getByRole("spinbutton", { name: "Item 1 quantity" }).fill(String(quantity));
  await dialog.getByRole("spinbutton", { name: "Item 1 unit price" }).fill("1000");
}

async function closeCreateDialog(dialog: Locator): Promise<void> {
  await dialog
    .locator(".ant-modal-footer")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await expect(dialog).toBeHidden();
}

async function createCatalogOrder(
  page: Page,
  productName: string,
  quantity: number,
  note: string
): Promise<Order> {
  const dialog = await openCreateDialog(page);
  await dialog.getByText("Catalog Product", { exact: true }).click();
  const picker = dialog.getByRole("combobox", { name: "Search and select a catalog product" });
  await picker.click();
  await picker.fill(productName);
  await page.locator(".ant-select-item-option").filter({ hasText: productName }).click();
  await dialog.getByRole("spinbutton", { name: "Item 1 quantity" }).fill(String(quantity));
  await dialog.getByPlaceholder("Optional internal note").fill(note);
  const responsePromise = page.waitForResponse(
    (response) => isOrderCreate(response.request()) && response.ok()
  );
  await dialog.getByRole("button", { name: "Create order" }).click();
  const order = (await (await responsePromise).json()) as Order;
  await expect(dialog).toBeHidden();
  return order;
}

async function openOrderByNumber(page: Page, orderNumber: string): Promise<void> {
  await page.getByRole("menuitem", { name: "Orders" }).click();
  await expect(page.getByRole("heading", { name: "Orders", level: 2 })).toBeVisible();
  const search = page.getByPlaceholder(
    "Search Order number, Customer name, phone, email, address, or note"
  );
  await search.fill(orderNumber);
  await page.getByRole("button", { name: orderNumber }).click();
  await expect(page.getByRole("dialog", { name: `Order ${orderNumber}` })).toBeVisible();
}

async function confirmOrder(page: Page, detail: Locator): Promise<void> {
  await detail.getByRole("button", { name: "Confirm Order" }).click();
  await page
    .getByRole("dialog", { name: "Confirm this Order?" })
    .getByRole("button", { name: "Confirm Order" })
    .click();
}

async function selectOption(select: Locator, page: Page, option: string): Promise<void> {
  await select.press("ArrowDown");
  await page.getByTitle(option, { exact: true }).last().click();
}

function isOrderCreate(request: Request): boolean {
  return request.method() === "POST" && request.url().endsWith("/api/v1/facebook/orders");
}

function isOrderPatch(request: Request, orderUuid: string): boolean {
  return (
    request.method() === "PATCH" &&
    request.url().endsWith(`/api/v1/facebook/orders/${orderUuid}`)
  );
}

function idempotencyKey(request: Request): string {
  const key = request.headers()["idempotency-key"];
  expect(key).toBeTruthy();
  return key;
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

async function findOrder(page: Page, token: string, orderNumber: string): Promise<Order> {
  const orders = await listOrders(page, token, orderNumber);
  expect(orders).toHaveLength(1);
  return orders[0] as Order;
}

async function listOrders(page: Page, token: string, query: string): Promise<Order[]> {
  const response = await apiGet<{ items: Order[] }>(
    page,
    token,
    `/api/v1/facebook/orders?q=${encodeURIComponent(query)}&page=1&page_size=100`
  );
  return response.items;
}

async function listCustomerOrders(
  page: Page,
  token: string,
  customerUuid: string,
  query: string
): Promise<Order[]> {
  const response = await apiGet<{ items: Order[] }>(
    page,
    token,
    `/api/v1/facebook/orders?customer_uuid=${customerUuid}&q=${encodeURIComponent(query)}&page=1&page_size=100`
  );
  return response.items;
}

async function inventoryQuantity(page: Page, token: string, productUuid: string): Promise<number | null> {
  const response = await apiGet<{ quantity_on_hand: number | null }>(
    page,
    token,
    `/api/v1/facebook/products/${productUuid}/inventory`
  );
  return response.quantity_on_hand;
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
    expect(
      response.items.filter((item) => item.event_type === type || item.movement_type === type)
    ).toHaveLength(count);
  }
}

async function apiGet<T>(page: Page, token: string, path: string): Promise<T> {
  const response = await page.request.get(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  expect(response.ok(), `GET ${path} returned ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

async function apiPost(
  page: Page,
  token: string,
  path: string,
  data: Record<string, unknown>
): Promise<unknown> {
  const response = await page.request.post(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    data
  });
  expect(response.ok(), `POST ${path} returned ${response.status()}`).toBeTruthy();
  return response.json();
}
