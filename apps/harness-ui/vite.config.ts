import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 53100,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: process.env.VITE_HARNESS_API_URL ?? "http://localhost:53180",
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 53100,
    host: "0.0.0.0",
  },
});
