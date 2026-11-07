import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the HTTPS backend (self-signed certificate -> secure: false).
// In production the built files are served by FastAPI from the same origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "https://localhost:8443", changeOrigin: true, secure: false } } },
});
