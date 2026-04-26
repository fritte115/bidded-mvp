import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

const devHost = process.env.FRONTEND_DEV_HOST ?? "127.0.0.1";
const configuredDevPort = Number(process.env.FRONTEND_DEV_PORT ?? process.env.PORT ?? 8080);
const devPort = Number.isFinite(configuredDevPort) ? configuredDevPort : 8080;

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: devHost,
    port: devPort,
    strictPort: false,
    hmr: {
      overlay: false,
    },
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    dedupe: ["react", "react-dom", "react/jsx-runtime", "react/jsx-dev-runtime", "@tanstack/react-query", "@tanstack/query-core"],
  },
}));
