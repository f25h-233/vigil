import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import App from './App.tsx'
import SwUpdateToast from './components/SwUpdateToast.tsx'
import { markNeedRefresh } from './swUpdate.ts'
import { applyTheme, readTheme } from './theme.ts'
import './index.css'

applyTheme(readTheme())

// ⚠️ 全仓**唯一**的 virtual:pwa-register 引用点（E4：vitest 解析不了它，
// 所以它必须待在测试不 import 的文件里；能测的部分全在 swUpdate.ts）。
//
// 副作用（实测，插件 dist/index.js:254）：一旦这里出现 import，
// `injectRegister: 'auto'` 就不再往 index.html 注入 `registerSW.js`
// ⇒ **不会有第二次注册**。构建后 dist/index.html 里那个
// `<script id="vite-plugin-pwa:register-sw">` 应当消失——这是本任务的一条核对项。
const updateSW = registerSW({
  onNeedRefresh() {
    markNeedRefresh(() => {
      void updateSW(true) // true = 让新 SW 立刻接管并重新加载
    })
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    <SwUpdateToast />
  </StrictMode>,
)
