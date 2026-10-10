import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./preview-e2e",
  workers: 1,
  use: {
    baseURL: "http://preview.test:5174",
    launchOptions: {
      executablePath: process.env.PCE_CHROMIUM_PATH || undefined,
      args: [
        "--no-proxy-server",
        "--host-resolver-rules=MAP preview.test 127.0.0.1",
      ],
    },
  },
  webServer: [
    {
      command:
        "cd .. && PCE_FRONTEND_ORIGIN=http://preview.test:5174 PYTHONPATH=backend:backend/tests .venv/bin/python backend/tests/browser_server.py",
      url: "http://127.0.0.1:8001/api/health",
      reuseExistingServer: false,
    },
    {
      command:
        "PCE_FRONTEND_ORIGIN=http://preview.test:5174 node node_modules/vite/bin/vite.js --config vite.preview-test.config.ts --clearScreen false",
      url: "http://127.0.0.1:5174/",
      reuseExistingServer: false,
    },
  ],
});
