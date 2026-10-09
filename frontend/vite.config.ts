import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: process.env.PCE_DEV_HOST || "0.0.0.0",
    port: 5173,
    strictPort: true,
    allowedHosts: [
      ...(process.env.PCE_PREVIEW_HOSTS || "")
        .split(",")
        .map((host) => host.trim())
        .filter(Boolean),
      ...(process.env.PCE_FRONTEND_ORIGIN
        ? [new URL(process.env.PCE_FRONTEND_ORIGIN).hostname]
        : []),
    ],
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.ts*"],
  },
});
