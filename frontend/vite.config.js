import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // REST API -> FastAPI
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        // strip the /api prefix so /api/alerts -> /alerts on the backend
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // WebSocket -> FastAPI
      '/ws': {
        target: 'ws://127.0.0.1:8001',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})