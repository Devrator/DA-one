import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Pin to IPv4 loopback: uvicorn --host 0.0.0.0 does not listen on ::1,
        // and 'localhost' re-resolution during Windows network flaps can break the proxy.
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})
