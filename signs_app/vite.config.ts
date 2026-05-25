import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
});
