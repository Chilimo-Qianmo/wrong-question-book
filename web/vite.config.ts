import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 打包后由后端（FastAPI）在根路径下挂载 web/dist，前后端同源，
// 因此构建使用相对 base，产物可直接被静态挂载或本地打开。
// 开发模式下把 /api 代理到后端；后端端口随机时用 VITE_API_TARGET 覆盖。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || 'http://127.0.0.1:8000'

  return {
    base: './',
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      strictPort: false,
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      target: 'es2020',
      assetsDir: 'assets',
      chunkSizeWarningLimit: 900,
    },
  }
})
