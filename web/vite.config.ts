// ⚠️ `defineConfig` 必须从 `vitest/config` 导入，**不是** `vite`：
// `vite` 的那一份不认 `test` 段——TS 上不报错、运行时被忽略，于是测试
// 悄悄跑在 node 环境里，第一句 `document is not defined` 才现形。
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon-192.png', 'icon-512.png'],
      manifest: {
        name: 'VIGIL 守夜人',
        short_name: 'VIGIL',
        description: 'QQ 群信息聚合：通知、学业、活动、生活一页看完',
        lang: 'zh-CN',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#0b0f14',
        theme_color: '#0b0f14',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        // ⚠️ /api/ 的导航请求不许被兜底成 index.html——那会把一个接口
        // 404 变成一份看起来正常的 HTML，调用方解析失败却看不到原因。
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
  server: {
    // 开发期前端跑 5173、后端跑 8787，靠代理合到一个源上（免 CORS）
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },

  // ⚠️ `environment: 'jsdom'` 是**全局**的（不是只给 DOM 用例）。
  // Vitest 3+ 已把 `environmentMatchGlobs` 标记为弃用、改用 projects/workspace，
  // 而本仓的 vitest 是 5.0.1 —— 与其赌一个具体 API，不如全局开 jsdom：
  // 既有的 `api.test.ts` / `format.test.ts` 是纯逻辑，在 jsdom 下照样跑，
  // 代价是每次多初始化一个 DOM，对本仓 22 条用例完全可忽略。
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
