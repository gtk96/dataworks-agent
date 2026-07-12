import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        // 默认指向本地真后端 8085；Playwright e2e 通过 VITE_PROXY_TARGET
        // 注入指向 fake-server(8086)，使 e2e 不依赖真机。
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8085',
        changeOrigin: true,
      },
      '/ws': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8085',
        ws: true,
      },
      '/agent': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8085',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules/element-plus')) return 'vendor-ui'
          if (id.includes('node_modules/vue') || id.includes('node_modules/pinia') || id.includes('node_modules/vue-router')) return 'vendor-vue'
        },
      },
    },
  },
})
