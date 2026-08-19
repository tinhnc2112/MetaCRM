import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const frontendUrl = "http://127.0.0.1:5173";
const backendUrl = "http://127.0.0.1:8001";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  outputDir: "test-results",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: frontendUrl,
    locale: "en-US",
    timezoneId: "Asia/Ho_Chi_Minh",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }
    }
  ],
  webServer: [
    {
      command: "python scripts/e2e_harness.py serve",
      cwd: path.resolve(__dirname, "../backend"),
      url: `${backendUrl}/api/v1/system/health/database`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        ...process.env,
        METACRM_E2E: "true",
        APP_ENV: "test"
      }
    },
    {
      command: "npm run dev:e2e",
      cwd: __dirname,
      url: frontendUrl,
      timeout: 60_000,
      reuseExistingServer: false,
      env: {
        ...process.env,
        VITE_API_BASE_URL: backendUrl
      }
    }
  ]
});
