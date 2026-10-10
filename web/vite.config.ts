import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// the dev server forwards /api to uvicorn so the session cookie stays same-origin
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // pre-bundled up front, so the first lazy chart doesn't make the dev server re-optimize
  // mid-session and load a second copy of react
  optimizeDeps: { include: ["vega-embed", "vega", "vega-lite"] },
  // vega is the one big chunk and it only loads the first time a chart is shown
  build: { chunkSizeWarningLimit: 900 },
  server: {
    port: 5173,
    proxy: { "/api": `http://127.0.0.1:${process.env.API_PORT ?? 8000}` },
  },
})
