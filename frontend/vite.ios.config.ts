import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Builds the REAL app (the same frontend/src that serves web members) for
// the Capacitor iOS shell (ADR 0032) -- not the standalone MusicKit proof
// harness that lived in ios-web/ before this. VITE_PLATFORM=capacitor is
// how App.tsx knows to exclude the platform-admin routes at build time
// rather than only role-gating them.
//
// The API base always resolves to a real HTTPS backend now (staging by
// default; override with VITE_IOS_API_BASE_URL for prod or another target).
// There is no LAN/HTTP fallback -- MysteryMixClub-4vii.12 removed it and the
// matching NSAllowsLocalNetworking ATS exception from Info.plist, since a
// build carrying either could reach an App Store reviewer or a real member.
// Fail closed rather than silently falling back to a dev-only address if
// that ever regresses.
const apiBaseUrl = process.env.VITE_IOS_API_BASE_URL ?? "https://staging.mysterymixclub.com";
if (!apiBaseUrl.startsWith("https://")) {
  throw new Error(
    `vite.ios.config.ts: VITE_IOS_API_BASE_URL must be an https:// URL, got "${apiBaseUrl}". ` +
      "The iOS build has no local-network ATS exception, so a non-HTTPS backend is unreachable " +
      "by design (MysteryMixClub-4vii.12) -- this is not a build worth completing.",
  );
}

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
