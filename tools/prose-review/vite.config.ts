import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Defaults on purpose: hashed assets under dist/assets/ and external module
// scripts/stylesheets only — no inline scripts, so the server's `script-src 'self'`
// Content-Security-Policy holds over the built page.
export default defineConfig({
  plugins: [react()],
});
