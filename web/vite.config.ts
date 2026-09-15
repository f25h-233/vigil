import { defineConfig } from 'vite'
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
})
