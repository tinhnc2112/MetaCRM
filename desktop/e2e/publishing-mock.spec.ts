import { expect, test } from "@playwright/test";

test("publishing queue syncs and offers state-safe actions", async ({ page }) => {
  let status = "SCHEDULED";
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/v1/auth/login") return json({ access_token: "fake", refresh_token: "fake", token_type: "bearer" });
    if (path === "/api/v1/publishing/config") return json({ configured: true, spreadsheet_id: "sheet", worksheet: "Posts", timezone: "Asia/Ho_Chi_Minh", last_synced_at: "2026-09-29T10:00:00Z", last_sync_error: null });
    if (path === "/api/v1/facebook/pages") return json({ items: [{ page_id: "page1", name: "Demo Page" }] });
    if (path === "/api/v1/publishing/sync") return json({ created: 1, updated: 0, unchanged: 0, invalid: 0 });
    if (path === "/api/v1/publishing/posts") return json({ items: [{ id: "post1", external_id: "sheet1", page_id: "page1", page_name: "Demo Page", caption: "Xin chào\nTomorrow", image_url: null, scheduled_for_utc: "2026-10-01T03:00:00Z", source_timezone: "Asia/Ho_Chi_Minh", status, attempt_count: 1, facebook_post_id: null, last_error_code: null, last_error_message: null, writeback_error: null }] });
    if (path.endsWith("/cancel")) { status = "CANCELLED"; return json({ status }); }
    return route.fulfill({ status: 404 });
  });
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("demo");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("menuitem", { name: "Scheduled Publishing" }).click();
  await expect(page.getByText("Xin chào")).toBeVisible();
  await page.getByRole("button", { name: "Sync Google Sheet" }).click();
  await expect(page.getByText("Created 1, updated 0, invalid 0")).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("CANCELLED")).toBeVisible();
  status = "UNCERTAIN";
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("demo");
  await page.getByLabel("Password").fill("demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("menuitem", { name: "Scheduled Publishing" }).click();
  await expect(page.getByRole("button", { name: "Mark published" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
});
