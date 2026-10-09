import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8001",
    viewport: { width: 1440, height: 1000 },
    launchOptions: {
      executablePath: process.env.PCE_CHROMIUM_PATH || undefined,
    },
  },
  webServer: {
    command:
      "cd .. && PYTHONPATH=backend:backend/tests .venv/bin/python backend/tests/browser_server.py",
    url: "http://127.0.0.1:8001/api/health",
    reuseExistingServer: false,
  },
});
