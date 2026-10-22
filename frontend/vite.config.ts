import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const backend = "http://127.0.0.1:8000";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "./" : "/demo/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    fs: {
      allow: [repositoryRoot],
    },
    proxy: {
      "/demo/api": { target: backend, changeOrigin: true },
      "/demo/login": { target: backend, changeOrigin: true },
      "/demo/logout": { target: backend, changeOrigin: true },
      "/demo/public": { target: backend, changeOrigin: true },
    },
  },
}));
