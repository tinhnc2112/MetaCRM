import type { Locator, Page } from "@playwright/test";

import { E2E, expect, selectPage, test } from "./fixtures";

const API_BASE_URL = "http://127.0.0.1:8001";

type Customer = { uuid: string; name: string | null };
type Order = { uuid: string; order_number: string };
type Shipment = {
  uuid: string;
  shipment_number: string;
  carrier_account_uuid: string | null;
  carrier_provider_code: string | null;
  carrier_account_display_name: string | null;
  carrier_name: string | null;
  tracking_number: string | null;
  tracking_url: string | null;
};
type ShipmentWaybillResponse = { item: null };
type CarrierOperationListResponse = { items: unknown[] };

test.setTimeout(90_000);

test("manual Shipment keeps manual tracking without showing a false integrated waybill", async ({
  authenticatedPage: page,
  accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const customer = await findCustomer(page, accessToken, E2E.customerA);
  const order = await createConfirmedOrder(page, accessToken, customer.uuid);
  const shipment = await apiPost<Shipment>(
    page,
    accessToken,
    `/api/v1/facebook/orders/${order.uuid}/shipments`
  );
  const tracked = await apiPatch<Shipment>(
    page,
    accessToken,
    `/api/v1/facebook/shipments/${shipment.uuid}/tracking`,
    {
      carrier_name: "Manual Waybill Test Carrier",
      tracking_number: "M302-MANUAL-TRACK",
      tracking_url: "https://tracking.example/M302-MANUAL-TRACK"
    }
  );
  expect(tracked.carrier_account_uuid).toBeNull();
  expect(tracked.carrier_provider_code).toBeNull();
  expect(
    await apiGet<ShipmentWaybillResponse>(
      page,
      accessToken,
      `/api/v1/facebook/shipments/${shipment.uuid}/waybill`
    )
  ).toEqual({ item: null });
  expect(
    await apiGet<CarrierOperationListResponse>(
      page,
      accessToken,
      `/api/v1/facebook/shipments/${shipment.uuid}/carrier-operations`
    )
  ).toEqual({ items: [] });

  const detail = await openOrder(page, order.order_number);
  const card = shipmentCardByNumber(detail, shipment.shipment_number);
  await expect(card).toBeVisible();
  await expect(
    card.locator(".ant-descriptions-item-content").getByText("Manual Waybill Test Carrier", {
      exact: true
    })
  ).toBeVisible();
  await expect(
    card.locator(".ant-descriptions-item-content").getByText("M302-MANUAL-TRACK", {
      exact: true
    })
  ).toBeVisible();
  await expect(
    card.getByRole("link", { name: "https://tracking.example/M302-MANUAL-TRACK" })
  ).toHaveAttribute("href", "https://tracking.example/M302-MANUAL-TRACK");
  await expect(card.getByRole("region", { name: "External waybill" })).toHaveCount(0);
  await expect(card.getByText("External waybill", { exact: true })).toHaveCount(0);
  await closeOrderDetail(detail);

  await selectPage(page, E2E.pageB);
  await goToOrdersAndSearch(page, order.order_number);
  await expect(page.getByRole("button", { name: order.order_number })).toHaveCount(0);
  await expect(page.getByText("No orders match the current filters.", { exact: true })).toBeVisible();
  await selectPage(page, E2E.pageA);
});

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

async function createConfirmedOrder(
  page: Page,
  token: string,
  customerUuid: string
): Promise<Order> {
  return apiPost<Order>(page, token, "/api/v1/facebook/orders", {
    customer_uuid: customerUuid,
    status: "confirmed",
    items: [{ item_name: "M30.2 manual waybill item", quantity: 1, unit_price: 1000 }],
    shipping_destination: {
      recipient_name: "M30.2 Recipient",
      recipient_phone: "0900000001",
      address_line: "M30.2 123 Street",
      ward: "Ward 1",
      district: "District 1",
      province: "HCMC",
      country_code: "VN"
    },
    note: "M30.2 manual read-only waybill coverage"
  });
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

function shipmentCardByNumber(detail: Locator, shipmentNumber: string): Locator {
  return detail
    .getByRole("region", { name: "Shipments" })
    .getByRole("listitem")
    .filter({ hasText: shipmentNumber });
}

async function closeOrderDetail(detail: Locator): Promise<void> {
  await detail
    .locator(".ant-modal-footer")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await expect(detail).toBeHidden();
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
  data?: Record<string, unknown>
): Promise<T> {
  const response = await page.request.post(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    data
  });
  expect(response.ok(), `POST ${path} returned ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

async function apiPatch<T>(
  page: Page,
  token: string,
  path: string,
  data: Record<string, unknown>
): Promise<T> {
  const response = await page.request.patch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    data
  });
  expect(response.ok(), `PATCH ${path} returned ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}
