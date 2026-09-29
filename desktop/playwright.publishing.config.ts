import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "publishing-mock.spec.ts",
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5173", ...devices["Desktop Chrome"] },
  webServer: {
    command: "npm run dev:e2e",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: false,
    env: { ...process.env, VITE_API_BASE_URL: "http://127.0.0.1:8001" }
  }
});
