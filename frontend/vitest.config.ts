import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// NOTE: no ``fs.realpathSync(process.cwd())`` here — under a Windows-hosted
// node invoked from WSL the translated cwd becomes ``C:/mnt/c/...`` and
// vitest's globbing breaks ("Cannot find module '/src/...'"). ``__dirname``
// (injected by Vite) is the config's real directory on every platform.
const root = path.resolve(__dirname);

export default defineConfig({
  root,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(root, "src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      reporter: ["text", "html"],
      exclude: ["src/main.tsx", "src/embed-main.tsx", "src/routes/**"],
    },
  },
});
