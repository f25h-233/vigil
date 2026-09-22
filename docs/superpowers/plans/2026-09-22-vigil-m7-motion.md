# VIGIL M7 · 追加任务 T7「动效层」— 实施计划

> **性质**：**用户 2026-09-22 追加的范围**（原话："Material Design 现在它足够 google 了，但是不够 Android。
> 仿原生安卓的动效，按钮动画，我觉得也可以安排上"）。它**不在** spec §4.3 的四条里 ⇒ 本计划单独立卷，
> 且落地后要对**它的 diff** 单独做一次终审（delta review），以免"最后一道门"漏掉新代码。
> **用户当轮的两个选择**：① 触点反馈 = **真涟漪**（跟手指落点）；② 覆盖面 = **每套主题各给一档性格**（不是只给 material）。
> **模式**：SDD `pipeline`｜**BASE**：实施时的 HEAD（T6 之后）

---

## 0. 为什么安卓味不是"加个 transition"

M2/M3 的静（色板 / 形状 / 层次）M7 已经有了；缺的是**动**。原生安卓的"动"是这四样里**前三样**：

| # | 安卓的做法 | 本任务 |
|---|---|---|
| 1 | **触点涟漪**（从手指落点扩散）+ 状态层 | ✅ 真涟漪（委托监听 + WAAPI） |
| 2 | **M3 的时长与曲线**（不是浏览器默认 `ease`） | ✅ 4 个动效 token，每套各给一档 |
| 3 | **按下形变** | ✅ `--v-press-scale`（material = 1，M3 本来就不缩放；蒸汽波/毛玻璃 = .98） |
| 4 | 页面切换的 shared-axis 过场 | ⛔ **不做**（见 §4 不做清单：要重挂载页面 ⇒ 丢 Feed 的滚动与已加载分页） |

**每条都要能被机械验证**：涟漪能不能插进去/该不该插进去、transition 的时长是多少、brutalism 是不是真的 0ms。

---

## 1. Interfaces

- **Produces**（CSS 契约）：4 个新 token × 5 套主题（parity 会强制五块齐全）：
  `--v-motion-dur` / `--v-motion-ease` / `--v-ripple` / `--v-press-scale`
- **Produces**（`web/src/components/RippleLayer.tsx`）：默认导出一个**渲染 `null`** 的组件；
  挂载时在 `document` 上装一个 `pointerdown` 委托监听器，卸载时摘掉。**无 props、无状态、无返回值。**
- **Produces**（CSS）：`@layer base` 里的三条规则（过渡 / 涟漪容器 / 按下形变）+ `.vigil-ripple` + reduced-motion 兜底
- **Consumes**：T1 的 token 层与 `@layer base` 的既有用法、`main.tsx` 的挂载点（T6 已经在里面挂了 `SwUpdateToast`）

---

## 2. Steps

### Step 1 · 先写失败测试 `web/src/__tests__/RippleLayer.dom.test.tsx`

```tsx
import type { CSSProperties } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import RippleLayer from '../components/RippleLayer.tsx'

/**
 * ⭐ 这组用例守的是"动效的三个边界"，而它们每一条都**必须能红**：
 *   ① 该有涟漪时**有**（否则等于没做）；
 *   ② 该没事时**一个都没有**（主题不要 / 系统关了动效 / 右键 / disabled）；
 *   ③ jsdom 没有 Web Animations API 的现实下**不许抛**（否则挂载即崩，整站白屏）。
 *
 * ⚠️ jsdom 不加载 CSS ⇒ `getComputedStyle(el).getPropertyValue('--v-ripple')` 是空串。
 * 所以"该有涟漪"那条要在按钮上**内联**写这个自定义属性（计划期实测：jsdom 能读到内联自定义属性）。
 *
 * ⚠️ 替身必须**可还原**：直接给 `Element.prototype.animate` 赋值不是 `vi.spyOn` 的产物，
 * `vi.restoreAllMocks()` 收不回来 ⇒ 后面的"③ 没有 animate"那条会因为前一条留下的替身而假绿。
 * 所以这里显式存原值 + 显式还原（这就是"空守卫的第 8 格：反证的前置没上场"的预防）。
 */
let restoreAnimate: (() => void) | null = null

function stubAnimate() {
  const original = Element.prototype.animate
  const spy = vi.fn(() => ({ finished: Promise.resolve() }))
  Element.prototype.animate = spy as unknown as Element['animate']
  restoreAnimate = () => {
    if (original === undefined) {
      delete (Element.prototype as { animate?: unknown }).animate
    } else {
      Element.prototype.animate = original
    }
  }
  return spy
}

function rippleBtn(props: { ripple?: string; disabled?: boolean } = {}) {
  return (
    <button
      disabled={props.disabled}
      style={props.ripple === undefined ? {} : ({ '--v-ripple': props.ripple } as CSSProperties)}
    >
      按我
    </button>
  )
}

const ripples = () => document.querySelectorAll('.vigil-ripple').length

afterEach(() => {
  restoreAnimate?.()
  restoreAnimate = null
  vi.restoreAllMocks()
})

test('① 有涟漪色的主题：按下插一个，动画结束自己移除', async () => {
  const animate = stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(animate).toHaveBeenCalledTimes(1)
  expect(ripples()).toBe(1)
  await vi.waitFor(() => expect(ripples()).toBe(0)) // finished 兑现后自清
})

test('② 这套主题不要涟漪（--v-ripple 缺失 ⇒ 读到空串）⇒ 一个都不插', async () => {
  const animate = stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn()}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(animate).not.toHaveBeenCalled()
  expect(ripples()).toBe(0)
})

test('② 显式 transparent ⇒ 也不插（"关掉"要有两种写法都行）', async () => {
  stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'transparent' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(ripples()).toBe(0)
})

test('② 系统里关了动效（prefers-reduced-motion: reduce）⇒ 不插', async () => {
  stubAnimate()
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(ripples()).toBe(0)
})

test('② disabled 的按钮 ⇒ 不插（按不动的控件不该有反馈）', async () => {
  stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)', disabled: true })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(ripples()).toBe(0)
})

test('③ jsdom 的真实情况（没有 animate）⇒ 不抛、也不留残渣', async () => {
  // ⚠️ 这条**故意不打桩**（jsdom 的 Element.prototype.animate 不存在）；靠 afterEach 的还原保证前置干净
  expect(typeof Element.prototype.animate).toBe('undefined')
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  await expect(
    userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) }),
  ).resolves.toBeUndefined()
  expect(ripples()).toBe(0)
})
```

### Step 2 · 写 `web/src/components/RippleLayer.tsx`

```tsx
import { useEffect } from 'react'

/**
 * 全局触点涟漪（**事件委托**）。
 *
 * 为什么不"每个按钮包一层组件"：本仓有 60+ 个 button/chip/tab，逐个改会把「动效」这件事
 * 焊进每个调用点——而它其实是**主题资产**（每套主题自己给 `--v-ripple` 与 `--v-motion-dur`）。
 * ⇒ 一个挂在 `document` 上的委托监听器；`--v-ripple` 是空/`transparent` 时**整个机制自关**
 * （默认主题与粗野主义就是这一档：零涟漪、零开销）。
 *
 * ⚠️ 三条边界（都有测试守）：
 * 1. **jsdom 没有 Web Animations API**（`span.animate === undefined`）⇒ 必须特性检测，
 *    否则挂载即抛 ⇒ 整站白屏。检测到没有就"插了立刻移除"，不留残渣。
 * 2. **`prefers-reduced-motion` 必须尊重**——这是无障碍，不是可选装饰。
 * 3. 涟漪是**命令式**插进 React 管的 DOM 里的：它**不是** React 的子节点，
 *    所以不许给它任何 React 状态；移除只由动画结束负责（两处 `.then` 都兜住）。
 */
export default function RippleLayer() {
  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (e.button !== 0) return
      const el = e.target instanceof Element ? e.target.closest<HTMLElement>('button') : null
      if (el === null || el.disabled) return
      if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true) return

      const cs = getComputedStyle(el)
      const color = cs.getPropertyValue('--v-ripple').trim()
      if (color === '' || color === 'transparent') return

      const rect = el.getBoundingClientRect()
      const size = Math.max(rect.width, rect.height) * 2
      const span = document.createElement('span')
      span.className = 'vigil-ripple'
      span.style.width = `${size}px`
      span.style.height = `${size}px`
      span.style.left = `${e.clientX - rect.left - size / 2}px`
      span.style.top = `${e.clientY - rect.top - size / 2}px`
      span.style.background = color
      el.appendChild(span)

      if (typeof span.animate !== 'function') {
        span.remove()
        return
      }
      const durMs = Number.parseFloat(cs.getPropertyValue('--v-motion-dur').trim()) || 200
      const ease = cs.getPropertyValue('--v-motion-ease').trim() || 'ease-out'
      const anim = span.animate(
        [
          { transform: 'scale(0)', opacity: 0.9 },
          { transform: 'scale(1)', opacity: 0 },
        ],
        { duration: durMs * 2, easing: ease, fill: 'forwards' },
      )
      const done = () => span.remove()
      void anim.finished.then(done, done)
    }

    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [])

  return null
}
```

### Step 3 · `web/src/index.css`：4 个 token（五块各一份）+ `@layer base` 三条规则

五块各**追加**（值见下表；⚠️ 默认块也必须有——它是 parity 的基准）：

```css
  /* 动效（T7 追加）：每套主题各给一档性格 */
  --v-motion-dur: 150ms;
  --v-motion-ease: cubic-bezier(0.2, 0, 0, 1);
  --v-ripple: transparent;   /* transparent = 这套不要涟漪 */
  --v-press-scale: 1;        /* 1 = 按下不缩放 */
```

| token | default | material | brutalism | vaporwave | glass |
|---|---|---|---|---|---|
| `--v-motion-dur` | `150ms` | `180ms` | **`0ms`** | `320ms` | `240ms` |
| `--v-motion-ease` | `cubic-bezier(0.2, 0, 0, 1)` | `cubic-bezier(0.2, 0, 0, 1)` | `linear` | `cubic-bezier(0.34, 1.2, 0.64, 1)` | `cubic-bezier(0.2, 0, 0, 1)` |
| `--v-ripple` | `transparent` | **`rgba(103, 80, 164, 0.22)`** | `transparent` | `rgba(0, 229, 255, 0.28)` | `rgba(255, 255, 255, 0.25)` |
| `--v-press-scale` | `1` | `1` | `1` | `0.98` | `0.98` |

> 设计意图（写进注释）：**material = 原生安卓那一档**（有涟漪、M3 曲线、不缩放——M3 本来就不缩放按钮）；
> **粗野主义 = 0ms**（粗野主义的正确回答是"别动"）；**蒸汽波 = 慢一档且带回弹**；**毛玻璃 = 柔和**。

`@layer base` 追加：

```css
@layer base {
  /* 交互元素的状态变化走**主题的**时长与曲线（而不是浏览器默认的 ease）。
     ⚠️ 放在 base 层（T1 的教训）：这样**故意**要覆盖它的 utility（例如 `transition-none`）仍然能赢；
     不 layering 就会像那次 `font:inherit` 一样把 utilities 一起压掉。 */
  button,
  a,
  input,
  textarea,
  select {
    transition:
      background-color var(--v-motion-dur) var(--v-motion-ease),
      border-color var(--v-motion-dur) var(--v-motion-ease),
      color var(--v-motion-dur) var(--v-motion-ease),
      box-shadow var(--v-motion-dur) var(--v-motion-ease),
      transform var(--v-motion-dur) var(--v-motion-ease);
  }

  /* 涟漪的容器：必须能裁住它（否则圆角会被涟漪撑破）。
     ⚠️ `outline`（键盘焦点环）**不受** overflow:hidden 影响 ⇒ 无障碍不被这行吃掉。 */
  button {
    position: relative;
    overflow: hidden;
  }

  /* 按下形变：material/default/brutalism 的 token 是 1 ⇒ 这条对它们是恒等变换（零视觉影响） */
  button:active:not(:disabled) {
    transform: scale(var(--v-press-scale));
  }

  .vigil-ripple {
    position: absolute;
    border-radius: 50%;
    pointer-events: none;
    will-change: transform, opacity;
  }

  /* 系统里关了动效 ⇒ 一律不做。**这条不是可选项。** */
  @media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
      animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important;
    }
  }
}
```

### Step 4 · `main.tsx` 挂载

```tsx
import RippleLayer from './components/RippleLayer.tsx'
// render 里，与 SwUpdateToast 并列：
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    <SwUpdateToast />
    <RippleLayer />
  </StrictMode>,
)
```
> ⚠️ `StrictMode` 下 effect 会跑两遍（挂→卸→挂）⇒ 监听器必须**成对**增删（本实现的 cleanup 已做到）；
> 这一点写进 `RippleLayer` 的注释，别让下一个人以为双挂载是 bug。

### Step 5 · 结构值表（`themeTokens.test.ts`）追加这 4 个 token

T3 的 F3 表锁的是"主题身份"。动效是身份的一部分（0ms vs 320ms）⇒ 把 4 个新 token 的字面值加进那张表
（四套非默认主题 × 4 = 16 条，表驱动写法不变）。

### Step 6 · 收尾验证

```bash
cd web && npm test          # 期望 92 + 6（RippleLayer 的 6 条）= 98
cd web && npm run build     # 干净（tsc -b 在内）
```
契约测试（parity / 结构表 / 引用完整性）自动覆盖 4 个新 token。

---

## 2.9 ⚠️ 勘误区（T7 执行期实测，**计划里手写的测试代码有 4 处错**）

> 形态一句话：**我手写的"测试替身/断言"与本仓真实的运行时契约不符**（这是本项目第 4 次出现同一类错）。
> 每条都有实测；组件代码本身**一字未改照抄后仍有 3 条红** ⇒ 错在计划，不在实现。

| # | 计划的错 | 实测症状 | 修法 |
|---|---|---|---|
| **EMA** | `stubAnimate` 返回 `{ finished: Promise.resolve() }` | 微任务里就兑现 ⇒ 断言①红在 `expected +0 to be 1`（动画"还没插就被移除了"） | 用**显式 deferred** 控制何时兑现（断言一条没少，反而更强） |
| **EMB** | `vi.spyOn(window, 'matchMedia')` | `can only spy on a function`；**jsdom@30.1.0 整个 lib 里 0 处 `matchMedia`**（grep 实证） | 显式赋值 `window.matchMedia = …` + 用后还原 |
| **EMC** | `.resolves.toBeUndefined()` | 与真契约不符：`@testing-library/user-event` 的 `directApi.js:32` 兑现的是 **System 实例** | 删掉该断言；"不抛"由 `await` 承担 |
| **EMD** | `closest<HTMLElement>('button')` | **`tsc -b` 直接失败**（TS2339：`HTMLElement` 上没有 `.disabled`） | 用 `HTMLButtonElement`（**纯类型，零行为变化**） |

**另外两条实测结论（值得留给后来者）**：
- **变异①只红了 2 条而非 4 条**：另两条"不该插"的用例的 `return` 排在**颜色判断之前** ⇒ 各守各的。
  ⇒ 这不是覆盖不足，而是**判据按边界分工**；写变异时别把"红 2 条"当成"守卫漏了 2 处"。
- ⭐ **`StrictMode` 双挂载的真实形态被量到了**：`pointerdown` **add 2 / remove 1**（effect 跑两遍、cleanup 只跑一次是 React 的正常行为），
  而**一次按下插 1 个涟漪、`animate` 1 次** ⇒ **没有双监听器**（听众集合是 Set 语义/或第二次 add 被 cleanup 抵消）。
  同轮还验了"涟漪活着时宿主按钮重渲染"**不炸**（连点 3 次，文案仍正确）。
- **`overflow: hidden` 的裁切排查**：52/52 个按钮两轴全扫 ⇒ 定位/形变轴 **0 命中**、负偏移 0；
  文本轴只 1 个带宽度类且是 `ItemCard.tsx:115` 的 `w-full min-w-0`（整幅宽换行容器，非窄框）⇒ **本仓找不到可裁对象**。
  ⚠️ 但**焦点环只按规范判定、未上真浏览器** ⇒ 留给冒烟。

## 3. 渲染验证（动效**不能**靠静态截图验，必须真浏览器）

写一次性脚本（`_smoke/` 下，Playwright + msedge）：

1. **涟漪**：`page.mouse.move(x,y)` 到某按钮上 → `page.mouse.down()` → **立刻** `page.evaluate(() => document.querySelectorAll('.vigil-ripple').length)`
   - material ⇒ **≥1**；brutalism ⇒ **0**；default ⇒ **0**
2. **时长**：`getComputedStyle(document.querySelector('button')).transitionDuration`
   - material ⇒ `0.18s`；brutalism ⇒ `0s`
3. **reduced-motion**：`page.emulate_media(reduced_motion='reduce')` ⇒ material 也 **0** 个涟漪
4. **按下形变**：material 按下前后 `getBoundingClientRect().width` **不变**；vaporwave 按下时 **变小**（≈0.98）
5. 顺手复核：五套主题的首屏截图与上一轮**无回归**（除动效外不该有别的像素差）

---

## 4. 不做（明确排除）

| 项 | 为什么 |
|---|---|
| 页面/tab 切换的 shared-axis 过场 | 要 `key={tab}` 重挂载页面 ⇒ **丢 Feed 的滚动位置与已加载分页**（行为回归），收益不抵 |
| 触控目标撑到 48dp | 那要整体放大按钮密度 ⇒ 改掉用户刚验收过的观感；留作"密度"专项 |
| FAB / 按下抬升（elevation on press） | 用户没要；M3 的按钮本来也不抬升 |
| 复选框/开关的 M3 动效 | ItemCard 的多选框可做，但那是另一块（表单控件），本任务不含 |
| 主题切换的过场动画 | 上面那条全局 transition 已经把它变成一次平滑过渡（免费得到），不额外做 |

---

## 5. 逃逸舱

- 断言/数字/措辞与实现不符 ⇒ 按实际修正并报告；**需求自相矛盾 ⇒ 停下报告，不许挑一半做。**
- ⚠️ 若 `overflow: hidden` 在某个按钮上**真的**裁掉了本该外溢的东西（例如绝对定位的子元素）⇒
  停下报告该按钮的位置，别自己去改那处布局（那会越界）。
