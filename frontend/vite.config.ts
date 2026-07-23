import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://172.27.173.1:8000",
        changeOrigin: true,
        proxyTimeout: 0,
        timeout: 0,
      },
      "/ws": { target: "ws://172.27.173.1:8000", ws: true },
    },
  },
});
