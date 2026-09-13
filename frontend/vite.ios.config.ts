import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  root: path.resolve(__dirname, 'ios-web'),
  publicDir: path.resolve(__dirname, 'public'),
  plugins: [react()],
  build: { outDir: '../dist-ios', emptyOutDir: true },
  server: { host: '127.0.0.1', port: 5174, strictPort: true },
});
