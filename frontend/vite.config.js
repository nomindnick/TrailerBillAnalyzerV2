import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    hmr: {
      clientPort: 443
    },
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://127.0.0.1:8080',
        changeOrigin: true,
        secure: false,
        ws: true
      },
      '/socket.io': {
        target: process.env.VITE_API_URL || 'http://127.0.0.1:8080',
        changeOrigin: true,
        secure: false,
        ws: true
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    manifest: true
  }
})