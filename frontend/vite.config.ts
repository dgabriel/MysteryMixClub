import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Bind the IPv4 loopback explicitly. The default host ("localhost")
    // resolves to IPv6 ::1 first on Node 17+/macOS, leaving 127.0.0.1
    // unserved — and Spotify OAuth requires the 127.0.0.1 redirect host.
    host: "127.0.0.1",
    port: 5173,
  },
});
