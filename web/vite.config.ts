import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The panel is served under /ui in production (mounted by the FastAPI server),
// so the build is base-pathed there. In dev, requests to the agenthook API are
// proxied to the backend so the browser stays same-origin (no CORS needed) and
// the server's loopback gate sees a 127.0.0.1 client.
const API_TARGET = process.env.AGENTHOOK_API ?? "http://127.0.0.1:8080";

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "../agenthook/static/panel",
    emptyOutDir: true,
  },
  server: {
    // Dedicated port not used by any other project under ~/dev (Vite's default
    // 5173/5174 and 4173 are taken). strictPort fails loudly instead of hopping
    // onto another project's port.
    port: 5180,
    strictPort: true,
    proxy: {
      "/admin": API_TARGET,
      "/jobs": API_TARGET,
      "/hook": API_TARGET,
      "/healthz": API_TARGET,
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
  },
});
