import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.VITE_HARNESS_API_URL ?? "http://localhost:53180";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 53100,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
      "/artifacts": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 53100,
    host: "0.0.0.0",
  },
});
