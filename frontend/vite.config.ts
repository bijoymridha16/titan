import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api → FastAPI control plane (:8000), so the browser hits
// one origin and we avoid CORS surprises in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
