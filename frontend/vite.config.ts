import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";
const basePathRaw = process.env.VITE_BASE_PATH ?? "/";
const basePath = basePathRaw.endsWith("/") ? basePathRaw : `${basePathRaw}/`;

export default defineConfig({
  base: basePath,
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
});
