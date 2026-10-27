import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: the FastAPI backend owns /api and the media mounts.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/uploads": "http://localhost:8000",
      "/frames": "http://localhost:8000",
      "/outputs": "http://localhost:8000",
    },
  },
});
