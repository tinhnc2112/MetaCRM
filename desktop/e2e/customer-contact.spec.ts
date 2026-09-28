import { E2E, expect, selectPage, test } from "./fixtures";

const API = "http://127.0.0.1:8001/api/v1/facebook";

test.setTimeout(90_000);

test("staff edits Customer defaults, prefills an Order, and keeps one-off edits off Customer", async ({
  authenticatedPage: page, accessToken
}) => {
  await selectPage(page, E2E.pageA);
  const headers = { Authorization: `Bearer ${accessToken}` };
  const customers = await page.request.get(`${API}/customers?q=${encodeURIComponent(E2E.customerA)}`, { headers });
  expect(customers.ok()).toBeTruthy();
  const customerId = (await customers.json()).items[0].uuid as string;
  const profileUrl = `${API}/customers/${customerId}`;
  const previous = (await (await page.request.get(profileUrl, { headers })).json()).customer;
  try {
    await page.getByRole("menuitem", { name: "Customers" }).click();
    await page.getByRole("listitem").filter({ hasText: E2E.customerA }).first().click();
    await page.getByRole("button", { name: "Edit contact" }).click();
    const editor = page.getByRole("dialog", { name: "Edit customer contact" });
    await expect(editor.getByLabel("Name")).toHaveValue(E2E.customerA);
    await editor.getByLabel("Phone").fill("0987654321");
    await editor.getByLabel("Default address").fill("M10 customer address");
    await editor.getByLabel("Ward").fill("M10 ward");
    await editor.getByLabel("District").fill("M10 district");
    await editor.getByLabel("Province").fill("M10 province");
    const save = page.waitForResponse((response) =>
      response.url() === profileUrl && response.request().method() === "PATCH");
    await editor.getByRole("button", { name: "Save customer" }).click();
    expect((await save).status()).toBe(200);
    await expect(editor).not.toBeVisible();
    await expect(page.getByText("M10 customer address", { exact: false })).toBeVisible();

    await page.getByRole("button", { name: "Create order" }).click();
    const order = page.getByRole("dialog", { name: "Create order" });
    await expect(order.getByLabel("Phone")).toHaveValue("0987654321");
    await expect(order.getByLabel("Address")).toHaveValue("M10 customer address");
    await expect(order.getByLabel("Ward")).toHaveValue("M10 ward");
    await order.getByLabel("Address").fill("One-off delivery address");
    await order.getByPlaceholder("Required").fill("M10 sample parcel");
    await order.getByRole("spinbutton", { name: "Item 1 unit price" }).fill("1000");
    const create = page.waitForResponse((response) =>
      response.url().endsWith("/api/v1/facebook/orders") && response.request().method() === "POST");
    await order.getByRole("button", { name: "Create order" }).click();
    const created = await create;
    expect(created.status()).toBe(200);
    expect((await created.json()).shipping_destination.address_line).toBe("One-off delivery address");
    expect((await (await page.request.get(profileUrl, { headers })).json()).customer
      .default_shipping_address.address_line).toBe("M10 customer address");
  } finally {
    await page.request.patch(profileUrl, { headers, data: {
      name: previous.name, phone: previous.phone, email: previous.email,
      default_shipping_address: previous.default_shipping_address
    } });
  }
});
