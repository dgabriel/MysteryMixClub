import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Builds the REAL app (the same frontend/src that serves web members) for
// the Capacitor iOS shell (ADR 0032) -- not the standalone MusicKit proof
// harness that lived in ios-web/ before this. VITE_PLATFORM=capacitor is
// how App.tsx knows to exclude the platform-admin routes at build time
// rather than only role-gating them.
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
    // A physical device's "127.0.0.1" (services/api.ts's default) is the
    // phone itself, not the dev Mac -- override to a LAN-reachable address
    // for device testing. VITE_IOS_API_BASE_URL overrides this default;
    // this LAN IP is a local-dev convenience only, not a production value --
    // milestone 2 still needs a real staging/prod API domain here before
    // this build ships anywhere but a dev device (ADR 0030 item 4).
    "import.meta.env.VITE_API_BASE_URL": JSON.stringify(
      process.env.VITE_IOS_API_BASE_URL ?? "http://192.168.1.153:8001",
    ),
  },
  build: { outDir: "dist-ios", emptyOutDir: true },
  server: { host: "127.0.0.1", port: 5174, strictPort: true },
});
