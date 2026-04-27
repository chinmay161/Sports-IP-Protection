import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  // In production, Vite emits HTML referencing /static/index-XXX.js,
  // /static/index-XXX.css, etc. This avoids the /assets/ collision with
  // our API route GET /assets/{asset_id}.
  base: '/static/',

  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // REST API -> FastAPI
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // WebSocket -> FastAPI
      '/ws': {
        target: 'ws://127.0.0.1:8001',
        ws: true,
        changeOrigin: true,
      },
      '/live-streams/ws': {
        target: 'ws://127.0.0.1:8001',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})