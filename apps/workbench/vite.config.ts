import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  root: ".",
  base: "./",
  server: {
    host: "0.0.0.0",
    port: 5174,
    allowedHosts: true,
    proxy: {
      "/v/": {
        target: process.env.VITE_PROXY_TARGET || "http://localhost:8004",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
