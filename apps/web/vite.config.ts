import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 53000,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: process.env.VITE_CP_URL ?? "http://localhost:58001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  preview: {
    port: 53000,
    host: "0.0.0.0",
  },
});
