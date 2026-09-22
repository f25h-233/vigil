import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { applyTheme, readTheme } from './theme.ts'
import './index.css'

// 主题：与 index.html 的防闪脚本同一条路，但管的是**另一件事**——
// 防闪脚本只管首帧（它读不到 CSSOM，也就同步不了 theme-color），
// 这一句负责「挂属性 + 同步 <meta theme-color>」的完整动作。
applyTheme(readTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
