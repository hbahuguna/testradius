import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  timeout: 45000,
  expect: { timeout: 10000 },
  reporter: [["list"]],
  use: {
    headless: false,
    trace: "off",
    screenshot: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
