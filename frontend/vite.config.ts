import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API is proxied so the browser sees one origin: the session cookie and CSRF header
// work exactly as they do in production. SENTINEL_API_URL points the proxy elsewhere
// (the end-to-end tests use their own backend).
const api = process.env.SENTINEL_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": api, "/health": api },
  },
});
