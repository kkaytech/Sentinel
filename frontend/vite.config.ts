import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API is proxied so the browser sees one origin: the session cookie and CSRF header
// work exactly as they do in production.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
