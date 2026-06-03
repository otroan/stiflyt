import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  // Prod build is served by FastAPI under /skilt/; dev keeps the default /.
  base: command === "build" ? "/skilt/" : "/",
  plugins: [react()],
  // Two entry points: the desktop app (index.html) and a separate touch-first
  // field app for phones (field.html → /skilt/field.html). The desktop app is
  // untouched; the field app reuses the api client + types.
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        field: "field.html",
      },
    },
  },
  server: {
    port: 5174,
    host: "127.0.0.1",
    // Vite 5.4+ rejects requests whose Host header doesn't match the bind
    // address. We accept any Host so SSH-tunnelled access (Host: localhost:5174)
    // and direct LAN access (Host: <ip>:5174) both work in dev. Safe locally;
    // don't ship the dev server.
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
}));
