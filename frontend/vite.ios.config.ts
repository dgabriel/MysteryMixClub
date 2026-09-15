import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { resolveIosApiBaseUrl } from "./src/lib/iosApiBaseUrl";

// Builds the REAL app (the same frontend/src that serves web members) for
// the Capacitor iOS shell (ADR 0032) -- not the standalone MusicKit proof
// harness that lived in ios-web/ before this. VITE_PLATFORM=capacitor is
// how App.tsx knows to exclude the platform-admin routes at build time
// rather than only role-gating them.
//
// HTTPS validation lives in src/lib/iosApiBaseUrl.ts (with its own tests)
// rather than inline here, since this file sits outside vitest's src/**
// coverage and couldn't otherwise be exercised directly.
const apiBaseUrl = resolveIosApiBaseUrl(process.env.VITE_IOS_API_BASE_URL);

export default defineConfig({
  publicDir: path.resolve(__dirname, "public"),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  plugins: [react()],
  define: {
    "import.meta.env.VITE_PLATFORM": JSON.stringify("capacitor"),
    "import.meta.env.VITE_API_BASE_URL": JSON.stringify(apiBaseUrl),
  },
  build: { outDir: "dist-ios", emptyOutDir: true },
  server: { host: "127.0.0.1", port: 5174, strictPort: true },
});
