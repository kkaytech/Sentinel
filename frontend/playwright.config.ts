import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a real API and a real PostgreSQL database. Nothing is mocked.
// `scripts/e2e-backend.sh` resets the `sentinel_e2e` database and generates reference data.
// Set E2E_BASE_URL to test an already running application (for example the built image).
const API_PORT = process.env.E2E_API_PORT ?? "8100";
const WEB_PORT = "5174";
const external = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: external ?? `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "sh ../scripts/e2e-backend.sh",
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: { E2E_API_PORT: API_PORT },
      stdout: "ignore",
      stderr: "pipe",
    },
    ...(external
      ? []
      : [
          {
            command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
            url: `http://127.0.0.1:${WEB_PORT}`,
            timeout: 60_000,
            reuseExistingServer: false,
            env: { SENTINEL_API_URL: `http://127.0.0.1:${API_PORT}` },
          },
        ]),
  ],
});
