import { mergeConfig } from "vite";
import config from "./vite.config";

// Exercise the actual development config against disposable backend storage.
export default mergeConfig(config, {
  server: {
    port: 5174,
    proxy: { "/api": { target: "http://127.0.0.1:8001" } },
  },
});
