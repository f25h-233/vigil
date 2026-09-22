# VIGIL M7 · 外观（语义化 + 五套主题 + 持久化 + PWA 更新链路）— 实施计划

> **模式**：SDD `pipeline`（线性实现 + 审查流水化）
> **BASE**：`8c3a0d3`（M6 收尾后、本计划提交前）
> **范围来源**：spec `docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md` §4.3（四条）+ §5「M7 · 外观」出口证据（四条）+ §1.5（工作量实测）
> **用户裁定（2026-09-22）**：① 范围 = 外观 + 前端遗留；② 切换器放**顶栏**；③ **结构/美术层完全放开**（"完全可以部分甚至全部美术资产互不通用，要的是美观而非开发效率"）
> **⚠️ 先读「勘误区」再读任务正文。**

---

## 0. 勘误区（计划期实测，逐条有命令；E1/E2 会让人白干一整轮）

### E1 ⚠️ 接力文件的「M6 前端遗留 4 条」**全部已收**，一条都不剩

接力文件 §三-1 列了 4 条"该接手"的前端遗留。计划期逐条复核（2026-09-22）：

| 清单条目 | 实测现状 | 证据 |
|---|---|---|
| `@testing-library/dom` 未进 devDependencies | **已收** | `web/package.json` 的 devDependencies 里有 `"@testing-library/dom": "10.4.2"` |
| `App.dom.test.tsx` 的 `before` 取在请求**发出**时 | **已收** | `App.dom.test.tsx` 现在 `await screen.findByText('还没有任何条目。', …)` 之后才取 `before`，并带 M6 终审 #20 的说明注释 |
| `Reorder.dom.test.tsx` 漏 `{timeout:5000}`（约 1/9 假红） | **已收** | `Reorder.dom.test.tsx:470` 已是 `findByText(/4 条改了类目/, undefined, { timeout: 5000 })`，同样带 #21 注释 |
| 工作区 `Feed.tsx` 是 CRLF | **已收** | `git ls-files --eol web/src/views/Feed.tsx` = `i/lf w/lf`；`final-fix-report.md` #22 给了 sha256 双侧相等的证据 |

⇒ **用户选的「外观 + 前端遗留」里的"遗留"这一半没有对象**（这是 M6 自己记过的「清单没销账」形态的第 N 次复发）。
⇒ 本计划因此**不含**"清理遗留"任务。真实剩下的只有一条**行尾纪律**（见 Global Constraints G5）——它不是遗留缺陷，是 M7 自己的工具要遵守的约束。

### E2 ⚠️ spec §1.5 的数字已过期；现行基线是 **227 处 / 8 文件**

| 项 | spec §1.5 | **M7 计划期实测** |
|---|---|---|
| 裸调色板类名 | 「几十处」 | **227 处 / 8 文件**（逐文件数见下） |
| `web/src/index.css` | 13 行 / 2 个变量 | **13 行 / 2 个变量（M6 一行没动）** |

逐文件基线（T2 的红相位证据要用到这些数）：

```
 8  src/App.tsx                        22  src/components/ItemCard.tsx
19  src/components/PersonPicker.tsx     4  src/components/SourceList.tsx
11  src/views/Categories.tsx           20  src/views/Digests.tsx
29  src/views/Feed.tsx                114  src/views/Settings.tsx
                                      ── 总计 227
```

另：**裸 `rounded`（无后缀）7 处，全在 `src/views/Settings.tsx`**（183/187/196/201/300/509/516 行）。
`rounded-l-full` / `rounded-r-full` 各 1 处（`PersonPicker.tsx:119/131`）——**不在搬迁范围**。

### E3 ⚠️ 语义 token **一律不许**用透明度修饰符

计划期空针（临时 `@theme` 块 + `npm run build` + grep 产物）：

```
.bg-probe{background-color:var(--v-probe-bg)}                    ← @theme inline 生效
.rounded-lg,.rounded-probe{border-radius:var(--v-probe-radius)}  ← 覆盖内置刻度也生效
.bg-vigil-bg\/90{background-color:#0b0f14e6}                     ← ⛔ 构建期烘死的 fallback
.bg-vigil-bg\/90{background-color:color-mix(in oklab, var(--color-vigil-bg) 90%, transparent)}
```

⇒ `bg-vigil-surface/50` 这类写法会让产物里多出一条**钉死构建期主题色**的规则。
⚠️ 空针只覆盖了"值是字面量"那一支；值是 `var()` 的那一支**没人验过**——而 M7 只需要这 23 个 token 就够用 ⇒ **直接禁掉**，把未验证的路径关在门外（T2 的守卫里有机械检查）。

### E4 ⚠️ vitest **解析不了** `virtual:pwa-register*`（PWA 接线只能待在 main.tsx）

计划期空针（临时用例 import `virtual:pwa-register/react` + `npx vitest run`）：

```
TypeError: The argument 'filename' must be a file URL object, file URL string, or absolute
path string. Received 'file:///@vite-plugin-pwa/virtual:pwa-register/react'
```

⇒ 任何**被测试 import** 的文件都不许 import 虚拟模块。能测的部分必须解耦到 `src/swUpdate.ts`（T6）。

### E5 裸 `rounded` / `border` 的宽度**不可主题化**（字面量，不是变量）

```
.rounded{border-radius:.25rem}                                            ← 没有 var
.border-t{border-top-style:var(--tw-border-style);border-top-width:1px}   ← 宽度是字面量
```

⇒ 裸 `rounded` 由 T2 换成 `rounded-md`；**粗野主义的"厚边框"由 `--v-shadow-card` 的硬阴影承担**（`4px 4px 0 0`），不是 border-width。

### E8 ⚠️ 计划期的一条**错论证**（T4 的动机）：375px 下今天**没有"溢出被裁"**，真实症状是**被挤扁**

T4 原写「375px 下现有单行 ≈ 426px > 375 ⇒ `overflow-x:hidden` 会静默裁掉右边内容」。
**仪器校准没有被复现**（2026-09-22，真 Edge + 375×667 + 页内探针，`_smoke/m7-instrument-check.md`）：

| 量 | 修前实测 |
|---|---|
| 被裁元素（逐元素 bounding rect） | **0 个**（`clippedHeaderCount=0` / `clippedCount=0`） |
| 撤销右缘 / 末个 tab 右缘 / 视口 | 136 / 359 / 375 ⇒ 右侧还余 **16px** |
| ⭐ **真实症状** | 顶栏高 **77px**、5 个标签**全折成两行**、每个 tab 只剩 **48px 宽** |

⇒ 426px 是**不换行的内在宽度**，flex 收缩 + 文字换行把它吸收了。
⇒ **算术推出来的症状不算实测**（M6「没有实测支撑的理由不许写成结论」的同族，这次落在我自己的论证上）。
⇒ 连带两条：
① T4 的验收**不许**用"没有控件被裁"——**修前就已满足**，那是不会失败的判据；
② 改用「每个 tab 按钮**高 ≤ 40px**（= 标签只占一行）」——修前实测**按钮高 52px**（两行），修后 **32px**（单行）⇒ 必红可绿。
   ⚠️ **E8-补（T4 执行期实测）**：我原来写的「tab 宽 **≥ 56px**」是**按错字号算的门槛**——
   行高 20 ⇒ 字号 14px ⇒ 两字 tab 的自然宽 = 2×14 + 2×12(`px-3`) = **52px**；而 56 = 2×**16**+24，
   等于按 16px 字号算的。实现者**没有擅自加 `min-w-14`/`px-4`**（守住了"算术不算实测"这条纪律）✅。
   宽度只作**参考量**（48 → 52/66），判据落在**高度**上。

### E9 ⚠️ 两条**只有实测才发现**的墙：Node 内置模块的 import 写法、`new URL` 的基准

T1 执行期实测（报告 §4 偏差 4/5），**T2/T3 的测试会撞上同一对**：

```
src/__tests__/theme.test.ts(1,30): error TS2307: Cannot find module 'node:fs' or its corresponding type declarations.
2 new URL('../../index.html', import.meta.url) → http://localhost:3000/index.html     ← ⛔ jsdom 的 document base
1 const HERE = import.meta.url; new URL('../../index.html', HERE) → file:///D:/github/VIGIL/web/index.html   ← ✅
```

- ① 本仓**没有 `@types/node`**，而 `tsc -b`（`npm run build` 里）**会编译测试文件** ⇒
  `import { readFileSync } from 'node:fs'` 让构建直接失败。
- ② `new URL(x, import.meta.url)` 的第二个参数写成**字面量**时，Vite 的
  asset-import-meta-url 变换会接管它，把基准换成 jsdom 的 document base。
  加一层 `const HERE = import.meta.url` 就绕开（同一文件同一行，只差一个间接层）。
- **惯例（T2/T3 直接照抄）**：具名变量说明符 + `as` 写死类型，**不用 `@ts-expect-error`**
  （将来真装了 `@types/node` 会变成 TS2578，又把构建搞坏一次）。
- **裁决 R3：不装 `@types/node`**（`web/package.json` + `web/tsconfig.json` 是共享配置，
  改动影响面未知；而这条惯用写法只有 3 行、且已附理由注释）。

### E3-补 ⚠️ 实测收窄：`var()` 形态下**不**烘 hex —— 但禁用透明度修饰符仍是**设计决定**

T1 执行期实测（报告 §4 偏差 1）：把 `--color-vigil-bg` 从字面量改成 `var(--v-bg)` 之后，
产物里那条**构建期烘死的** `#0b0f14e6` **消失了**，只剩 `color-mix(...)`（解析值与它逐字节相同）。

⇒ E3 原来的理由（"会烘死"）**只对"值是字面量"那一支成立**，不是普适结论。
⇒ **G2 照旧**，但理由要照实写：① 透明度是**主题资产**（该由 token 值决定，不该出现在调用点）；
② `var()` 那一支的 color-mix 行为**只在一个类上验过**，而我们只需要这 23 个 token ⇒ 把未完全验证的路径关掉。

### E10 ⭐ 默认主题的字体栈必须 `'Segoe UI'` 打头（保住"默认主题 = 基线"）

T1 执行期实测（报告 §4 发现 B）：`'AaBbGg123 !@#'` 的宽度指纹 —— `"Segoe UI"` 单独用 = **146.221**
= Tailwind 旧栈（**相同**）⇒ **今天渲染拉丁文的就是 Segoe UI**；而 `system-ui` 在本机
（zh-CN Windows）解析到雅黑（**158.857**），后果：拉丁串 +8.6% 宽、整页 +5px、
**4.983% 像素不同**（纯 CJK 不变）。

⇒ **默认主题**（`:root, [data-theme='default']`）的 `--v-font-sans` 必须写成
`'Segoe UI', system-ui, -apple-system, 'Microsoft YaHei', sans-serif`——
T1 自己写的目标是「默认主题与今天**逐像素相同**」，字体栈是唯一残留差异。
⇒ **另外四套主题不受此限**（它们本来就该长得不一样；T3 的 `system-ui` / `Roboto` / 等宽栈照旧）。

### E11 ⭐ 档位合并的**完整清单**——计划正文只声明了白系，另三族**也塌缩了**

T2 的映射表把 35 个裸类名收成 23 个 token，**每一族都有"多档 → 少档"的合并**。
计划正文只写了「白系 13 档 → 4 档」，reviewer 实测**另三族同样塌缩**（共 11 个调用点，它判为 Important：
不是映射错，而是**"观感不变"这句承诺留了未批准的缺口**）：

| 原类 | 去处 | 实际落到 | 调用点 |
|---|---|---|---|
| `text-sky-300` | `text-vigil-accent-text` | = sky-200（`#bae6fd`） | 6 |
| `text-red-300` | `text-vigil-danger` | = red-400（`#f87171`） | 3 |
| `text-amber-100` | `text-vigil-warn-text` | = amber-200 | 1 |
| `bg-red-500/20` | `bg-vigil-danger-btn` | α 0.20 → 0.15 | 1 |

白系那一族里 **12/35 个类有数值漂移**（分 9 组；T2 报告只报了 3 组）——最大的一处是
`text-white/75 → #e6edf3`（≈ **+40/通道**，落在**日报正文**）。

⇒ **裁决 R5**：① 这份清单**照实入计划**（合并是设计决定，不是误差，但必须说出来）；
② **最大的一处回正**：`text-white/75` → `text-vigil-fg-2`（0.72，与原 0.75 差 0.03）；
③ 其余保留（族内同色；用户人眼验收时一并看，见 §1 判据 1）。

### E12 ⭐ **Tailwind 的扫描根是 Vite root（`web/`），不是 CSS 入口**——工具脚本会把类名漏进产物

T2 实测（reviewer 独立复现 + fix 做了**规则级 A/B**）：`web/tools/retheme_m7.py` 映射表里的
**类名字面量**被 Tailwind 当成候选扫描到 ⇒ dist CSS 里凭空多出 **35 条没人用的裸调色板规则**
（`web/src` 里 0 条；移走该文件重建 ⇒ 0 条，移回 ⇒ 35 条；探针 `bg-fuchsia-700` 放 `<repo>/scripts/` ⇒ 0 条、
同内容放 `web/` ⇒ 36 条）。

- **修法**：`web/src/index.css` 里一行 `@source not "../tools";`（路径基准 = **CSS 文件所在目录**）⇒ 73 → 0，
  dist CSS **22,342 → 15,717 B**。
- ⭐ **反着再问的一句**：新写的注释里也含 `rounded` / `.filter` / `text-vigil-fg/40` 字面量 ⇒ 实测 **0 条**
  ⇒ **CSS 入口本身不被当候选来源**（所以注释安全）。
- ⇒ **M7 之后的约束**：任何放在 `web/` 下的**非前端源码**（工具脚本、说明文件）只要含类名字面量，
  就会进产物。要么别放 `web/`，要么加 `@source not`。
- ⚠️ **量法**：压缩后的 CSS 是**一行**，`grep -c` 只能给 0/1；必须 `grep -o … | wc -l`。

### E13 ⚠️ 计划给 T3 写的对比度断言**自带假红**：半透明的软底色值必须先**合成**

T3 执行期实测（报告偏差 1）：计划里那两条断言
`contrast(--v-accent-text, --v-accent-soft)` 与 `contrast(--v-danger-text, --v-danger-btn)`
**直接拿了半透明色值当不透明比**（`--v-accent-soft` 是 `rgba(…,0.2)`）⇒ **6 条假红**，
其中**默认主题 2 条无解**（它是冻结基线，改值就等于破 T1 的"逐像素相同"目标）。

- 讽刺的是：**计划自己的代码注释就写着**「半透明层叠在不透明底上（默认主题的面几乎都是 rgba，**不算这步就全错**）」——
  那句话说对了，而断言没照做。
- 修法（T3 已做）：软底先 `over()` 合成到卡片/底色上再比，**阈值（4.5 / 3）一字未动、32 个色值一个没改**，五套全过。
- ⇒ **可执行的教训**：判据里的"输入"也要按同一套物理假设处理；一条**恒假/恒真**的断言与一条空守卫同价。

**同批的第二处**：计划 brief 自带的内层 `v()` 要求"选择器恰为 `[data-theme='default']` 的块"，
而默认块与 `:root` **共用一块** ⇒ **恒假**。这与 T1 parity 循环那个坑（§0 前面那条）**是同一个形状**：
**"默认块共用选择器"这个设计，会让所有"精确匹配选择器"的助手/断言失效**。⇒ 一律用 `includes` 或复用模块级助手。

### E14 ⚠️ 对比度判据的模型**不含壁纸层** ⇒「测试全绿、屏幕上读不出来」

主题修订期实测（报告 §0）：把蒸汽波的落日**固定到视口**（P4）之后，**首屏卡片正压在太阳的亮半部**上
⇒ 正文 **1.04:1**、弱化文字 **2.34:1**（= 读不出来），而**所有对比度断言全绿**。

根因：那条判据把"面"合成到 **`--v-bg`（一个纯色）**，而壁纸是**渐变栈**（解析不了）⇒ 判据里**没有壁纸这一层**。

- ⇒ **规则（设计层，判据里补不上）**：**有亮壁纸的主题，面板必须压得住它**（暗色半透明、alpha 足够）。
  蒸汽波与毛玻璃都已按此处置（`--v-surface: rgba(10,4,26,.72)` 一类）。
- ⇒ **渲染轮必须核对**：壁纸主题的**首屏**（卡片压在壁纸亮处时）正文是否读得出。**这条只靠眼睛。**
- ⚠️ 与 P0 那个「白字白底」是**同一族**：判据的**语境模型**漏了整个图层 / 整个用法
  （那个漏的是"accent-text 单独用"，这个漏的是"壁纸层"）。
  ⇒ 加判据时要问一句：**"屏幕上这块文字后面到底有什么？"** —— 模型里缺一层，就等于没判。

### E15 🔴 计划对 `registerType` 的假设是**错的**——`autoUpdate` 让 `onNeedRefresh` 编成死支

计划 §Task 6 写的是「`registerType: 'autoUpdate'` 会让新 SW 立刻接管，而 `onNeedRefresh` 会被触发 ⇒ 可以提示」。
**T6 reviewer 从插件源码证伪了它**（三层证据）：

1. 配置 `registerType: 'autoUpdate'` ⇒
2. 插件 `dist/index.js:169` 把 `__SW_AUTO_UPDATE__` 替换成 `"true"` ⇒
3. 出厂 bundle 里那个常量是 `C=true`，而 `onNeedRefresh` 的唯一调用点 `r?.()` 落在 `if (C) { … } else { … }` 的**死支**里。

**后果**：提示条**永不出现**；`updateSW(true)` 因 `C || u?.()` **连 `messageSkipWaiting` 都不发**（点了白点）；
实际生效的是 `window.location.reload()` **自动刷新**——正是吐司 docstring 里明文拒绝的行为。
⇒ **裁决 R9**：`registerType` 改 **`'prompt'`**（一行）。副作用如实写进配置注释：版本更新要用户**点一次**。

**同轮三条读源码得出的判断（比直觉值钱，一并记下）**：
- `registerSW` 在无 `serviceWorker` 的环境下**静默返回、不同步抛**（整个函数体在 `if ("serviceWorker" in navigator)` 里，
  且 `register()` 是 async）⇒ **不该加 try/catch**：那会是**永不执行的空守卫**。要错误处理该用插件已给的 `onRegisterError`。
- 实现者担心的 TDZ **不可达**：`updateSW` 只在**用户点击时**才被读（闭包延迟求值）。
- 判"有没有二次注册"的判据：`grep registerSW.js == 0` **拦不住 `injectRegister:'inline'`**（inline 用另一个 id、不产那个文件）
  ⇒ 更硬的判据是 **`index.html` 里不出现 `navigator.serviceWorker.register`**。

### E6 `bg-black/30` 的 12 处里有 10 处是**输入框底**，不是遮罩

实测分布：`ItemCard.tsx:167`、`PersonPicker.tsx:147/153`、`Feed.tsx:302`、`Settings.tsx:532/534/536/539/579/968/991`（输入框/文本域）、`SourceList.tsx:15`（源消息条目）。**本应用没有模态遮罩**。
⇒ token 命名取 **`--v-inset`（凹面）**而不是 `overlay`——命名要说实话，否则下一个人会按"遮罩"去用它。

---

## 1. 出口判据（spec §5 逐字 + 本计划的机械半边）

| # | spec 原文 | 本计划怎么让它可验 |
|---|---|---|
| 1 | 五套主题**人眼验收**（用户本人判定） | 冒烟产出 5 张截图（`?theme=` 覆盖，desktop + 375px 各一套）交用户；用户判定不通过 ⇒ 进一次**只改 `index.css` 调色**的 fix 轮 |
| 2 | 切换后刷新页面仍在（持久化） | `theme.test.ts`（读回）+ `ThemePicker.dom.test.tsx`（点 → 落盘 → 重挂载仍是它）+ 冒烟真刷新 |
| 3 | 手机 PWA 下五套都不白屏；新版本部署后**无需手动清缓存** | 5 张截图非空白（机械）+ `/sw.js` 带 `Cache-Control: no-cache`（后端用例）+ `onNeedRefresh` 提示（前端用例） |
| 4 | 浅色主题下无「深色残留」 | ① `noRawPalette` 守卫（227 → 0）；② token parity（缺一个 token ⇒ 继承默认主题的深色值）；③ 明暗断言（material/brutalism 的 `--v-bg` 亮度 > 0.5）；④ 对比度断言（fg/fg-3/accent-text/danger-text 在各自底上可读） |

---

## 2. Global Constraints（reviewer 拿这张表当注意力透镜）

- **G1 · 两层结构不许混**：调用点只许用**语义类名**（`bg-vigil-*` / `text-vigil-*` / `border-vigil-*` / `shadow-vigil-card` / `backdrop-blur-vigil-*` / 内置 `rounded-*`）；颜色值只许出现在 `index.css` 的 `--v-*` 定义里。
- **G2 · 语义 token 禁用透明度修饰符**（E3）。
- **G3 · 每套主题必须给**全部** `--v-*` 一份值**（parity 测试）；值相同时**也要显式写出来**——"没写"与"想继承"在 CSS 里长得一样，而继承的后果是「浅色主题里冒出默认主题的深色」。
- **G4 · 不许把虚拟模块 import 进被测试的模块**（E4）。
- **G5 · 行尾原样保留**：codemod 与所有编辑都按**字节**读写（`read_bytes()` → decode → 处理 → encode → `write_bytes()`），不得引入换行转换。计划期实测：`web/src` 里 19 个文件是 `w/lf`、3 个是 `w/crlf`（`App.tsx` / `__tests__/Feed.dom.test.tsx` / `test-setup.ts`），而 **blob 全是 `i/lf`** ⇒ `git diff` 看不见行尾差异，但逐字节工具会。**不许顺手"统一行尾"**（那是另一件事，会污染 M7 的 diff）。
- **G6 · 前端验证三件套**：每个改前端的任务收尾必须 `cd web && npm test`（全量，不是 `-t`）+ `npm run build`（`tsc -b` 在里面 ⇒ 类型错误会拦下）。
- **G7 · 后端任务**：`uv run pytest`（全量）；**不许**碰 `data/`（D11）。
- **G8 · 不许在测试里断言"我改的实现"**：期望值逐字写死（本项目已有先例：`api._MIME` 那张表就是被逐字钉死的）。
- **G9 · 中文注释说"为什么"**；**没有实测支撑的理由一律不许写成结论**（M6 的 E7 硬要求）。写不出理由时，写"我们选了这个形状"。

---

## 3. 任务总览

> 下面的 `T1`–`T6` 就是 `Task 1`–`Task 6`（两处写法同指，标题用后者是因为 `task-brief` 脚本按它切分）。

| # | 任务 | Dependencies | Touches（本任务将写的全部文件） |
|---|---|---|---|
| T1 | 主题底座：token 层 + 防闪 + 状态源 | — | `web/src/index.css`、`web/src/theme.ts`(新)、`web/index.html`、`web/src/main.tsx`、`web/src/__tests__/theme.test.ts`(新)、`web/src/__tests__/themeTokens.test.ts`(新) |
| T2 | 227 处语义化搬迁（codemod + 守卫） | T1 | 8 个 tsx、`web/src/index.css`、`web/tools/retheme_m7.py`(新)、`web/src/__tests__/noRawPalette.test.ts`(新) |
| T3 | 五套主题的视觉（结构 + 调色 + 页面资产 + 面板站点） | T2 | `web/src/index.css`、`src/components/ItemCard.tsx`、`src/components/PersonPicker.tsx`、`src/views/Categories.tsx`、`src/views/Digests.tsx`、`src/views/Feed.tsx`、`web/src/__tests__/themeTokens.test.ts`、`web/src/__tests__/themePalette.test.ts`(新) |
| T4 | 顶栏主题切换器 + 头部两行化 | T1 | `web/src/components/ThemePicker.tsx`(新)、`web/src/App.tsx`、`web/src/__tests__/ThemePicker.dom.test.tsx`(新) |
| T5 | 视图状态持久化（tab / kinds / persons） | T4 | `web/src/uiState.ts`(新)、`web/src/App.tsx`、`web/src/__tests__/uiState.test.ts`(新)、`web/src/__tests__/AppPersist.dom.test.tsx`(新) |
| T6 | PWA 更新链路（前端提示 + `/sw.js` no-cache） | T5 | `web/src/swUpdate.ts`(新)、`web/src/components/SwUpdateToast.tsx`(新)、`web/src/main.tsx`、`web/src/__tests__/swUpdate.test.tsx`(新)、`vigil/api.py`、`tests/test_api.py` |

**为什么是这个顺序**：T2 的 codemod 必须在 T3 之前（T3 要在**新**类名的元素上挂面板类）；T4/T5/T6 都改 `App.tsx`，线性流水天然不打架。

---

## 4. 任务详情

## Task 1: 主题底座（token 层 + 防闪 + 状态源）

**目标**：五套主题的**机制**跑通——默认主题观感与今天**逐像素相同**，另四套先等于默认（T3 再换成各自的值）。刷新页面主题仍在。

**Interfaces**

- **Produces**（`web/src/theme.ts`）：
  ```ts
  export type ThemeId = 'default' | 'material' | 'brutalism' | 'vaporwave' | 'glass'
  export const THEMES: { id: ThemeId; label: string }[]
  export const THEME_STORAGE_KEY = 'vigil.theme'
  export function isThemeId(v: unknown): v is ThemeId
  export function readTheme(): ThemeId          // 默认 'default'；非法/读不到 ⇒ 'default'
  export function applyTheme(id: ThemeId): void // 挂 data-theme + 落盘 + 同步 <meta theme-color>
  ```
- **Produces**（CSS 契约）：33 个 `--v-*` token 名（T1 的默认块逐行给出）+ `:root, [data-theme='default']` 与 4 个 `[data-theme='x']` 块 + `@theme inline` 映射。
- **Consumes**：无。

**Steps**

**1) 先写失败测试** `web/src/__tests__/theme.test.ts`（`theme.ts` 还不存在 ⇒ 红）：

```ts
import { readFileSync } from 'node:fs'
import { afterEach, expect, test, vi } from 'vitest'
import { THEMES, THEME_STORAGE_KEY, applyTheme, isThemeId, readTheme } from '../theme.ts'

afterEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('style')
})

test('没存过 ⇒ 默认主题', () => {
  expect(readTheme()).toBe('default')
})

test('存过合法值 ⇒ 读回它', () => {
  localStorage.setItem(THEME_STORAGE_KEY, 'vaporwave')
  expect(readTheme()).toBe('vaporwave')
})

test('⚠️ 存了非法值 ⇒ 回落默认，不许把垃圾挂到 DOM 上', () => {
  // 旧版本遗留 / 手改 / 别的应用写串了键——这些都不是"异常"，是**输入**。
  // 不校验的话 `data-theme` 会挂上垃圾值，而 CSS 侧静默回落到 :root
  //（看起来"正常"），排查时毫无线索。
  localStorage.setItem(THEME_STORAGE_KEY, '{"theme":"dark"}')
  expect(readTheme()).toBe('default')
})

test('isThemeId 认五套、拒其余', () => {
  expect(THEMES).toHaveLength(5)
  for (const t of THEMES) expect(isThemeId(t.id)).toBe(true)
  expect(isThemeId('dark')).toBe(false)
  expect(isThemeId(null)).toBe(false)
})

test('applyTheme：挂属性 + 落盘 + 同步 <meta name="theme-color">', () => {
  const meta = document.createElement('meta')
  meta.setAttribute('name', 'theme-color')
  document.head.appendChild(meta)
  // ⚠️ theme-color 的值**从 CSS 现读**（`getComputedStyle` 取 `--v-bg`），
  // 不在 TS 里抄一份色表——抄一份就是两处真相，必然漂移。
  // jsdom 不加载 index.css，所以这里用**内联**自定义属性模拟"CSS 已经给了值"。
  // 计划期空针实测：jsdom 的 getComputedStyle 能读到内联自定义属性（断言 `toBe('#123456')` 通过）。
  document.documentElement.style.setProperty('--v-bg', '#123456')

  applyTheme('glass')

  expect(document.documentElement.getAttribute('data-theme')).toBe('glass')
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('glass')
  expect(meta.getAttribute('content')).toBe('#123456')
  meta.remove()
})

test('localStorage 抛错时（无痕/被策略挡）不许把切换本身搞崩', () => {
  const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('denied')
  })
  expect(readTheme()).toBe('default')
  spy.mockRestore()

  const spy2 = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('denied')
  })
  expect(() => applyTheme('material')).not.toThrow()
  expect(document.documentElement.getAttribute('data-theme')).toBe('material')
  spy2.mockRestore()
})

test('index.html 的防闪白名单不许与 THEMES 漂移', () => {
  // 白名单是**手写的第二份真相**（第一份是本文件的 THEMES）。两份必然漂移，
  // 所以钉一条机械比对——它红的时候，改哪一份都对，但不能只有一份对。
  const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8')
  const m = html.match(/var ALLOWED = \[([^\]]*)\]/)
  expect(m, 'index.html 里找不到 ALLOWED 白名单').toBeTruthy()
  const ids = m![1]
    .split(',')
    .map((s) => s.trim().replace(/^'|'$/g, ''))
    .filter(Boolean)
  expect(ids).toEqual(THEMES.map((t) => t.id))
})
```

**2) 写 `web/src/theme.ts`**：

```ts
/**
 * 主题的**状态源**：id 列表、读取、落盘、应用。
 *
 * 三层分工（M7 全局约定）：
 *   ① 原始变量 `--v-*` 定义在 `index.css` 的 `:root` / `[data-theme='x']` 里；
 *   ② `@theme inline` 把它们接进 Tailwind 命名空间（调用点的类名固定，值随主题走）；
 *   ③ 这个文件只管「读 localStorage → 挂 `data-theme` → 同步 `<meta theme-color>`」。
 *
 * ⚠️ `theme-color` 的值**从 CSS 现读**，不在 TS 里再抄一份色表：抄一份就是两处真相，
 * 而 `index.html` 的防闪脚本已经证明这种重复必然漂移（那条白名单有测试钉着）。
 */

export type ThemeId = 'default' | 'material' | 'brutalism' | 'vaporwave' | 'glass'

export const THEMES: { id: ThemeId; label: string }[] = [
  { id: 'default', label: '默认' },
  { id: 'material', label: 'Material Design' },
  { id: 'brutalism', label: '粗野主义' },
  { id: 'vaporwave', label: '蒸汽波' },
  { id: 'glass', label: '毛玻璃' },
]

export const THEME_STORAGE_KEY = 'vigil.theme'

export function isThemeId(v: unknown): v is ThemeId {
  return typeof v === 'string' && THEMES.some((t) => t.id === v)
}

/** localStorage 可能整个不可用（无痕/被策略挡）——读写都要能静默失败。 */
function stored(): unknown {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY)
  } catch {
    return null
  }
}

export function readTheme(): ThemeId {
  const v = stored()
  return isThemeId(v) ? v : 'default'
}

/** 挂属性 + 落盘 + 同步 `theme-color`。出口判据 2「刷新后仍在」靠它。 */
export function applyTheme(id: ThemeId): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.setAttribute('data-theme', id)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, id)
  } catch {
    // 存不下只影响「下次还记得」这一件事，不该让当前这次切换失败
  }
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta !== null) {
    // 属性刚改完，getComputedStyle 会强制样式重算 ⇒ 拿到的就是新主题的 --v-bg
    const bg = getComputedStyle(root).getPropertyValue('--v-bg').trim()
    if (bg !== '') meta.setAttribute('content', bg)
  }
}
```

**3) 写失败测试** `web/src/__tests__/themeTokens.test.ts`（此刻 `index.css` 里没有 `--v-*` ⇒ 红）：

```ts
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'
import { THEMES } from '../theme.ts'

/**
 * ⭐ 主题层的**结构性守卫**。它守两条只有机械检查才抓得住的东西：
 *   ① **parity**：每套主题必须给**全部** token 一份值。缺一个 ⇒ CSS 继承
 *      `:root` 那一份（默认主题的值）⇒ **浅色主题里冒出深色残留**
 *      （出口判据 4 的真实形态），而肉眼要翻到那一页才看得见。
 *   ② **引用完整性**：`@theme inline` / `body{}` 里引用的 `--v-*` 必须存在。
 *      拼错的 token 名 **Tailwind 不会报错**，它只是不生成那个类 ⇒ 元素没样式、
 *      控制台一片安静。
 *
 * ⚠️ 解析用「选择器 + 花括号体」的粗切（本文件的 CSS 值都**不含嵌套花括号**；
 * 哪天有人写 `@media` 嵌进来，这条解析会先红——那是好事，它逼你换解析器）。
 * ⚠️ **必须先剥注释再解析**：本文件顶部那段说明里就含**示例 CSS**
 * （`{…}` 与 `var(--v-probe-radius)`），不剥的话它会被当成一个选择器块，
 * 而那个 `var(--v-probe-radius)` 会进"被引用但没定义"的名单 ⇒ **假红**。
 */
export const CSS = readFileSync(new URL('../index.css', import.meta.url), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

export type Block = { selector: string; body: string }

export function blocks(css: string): Block[] {
  return [...css.matchAll(/([^{}]*)\{([^{}]*)\}/g)].map((m) => ({
    selector: m[1].trim(),
    body: m[2],
  }))
}

function tokenNames(body: string): string[] {
  return [...body.matchAll(/(--v-[a-z0-9-]+)\s*:/g)].map((m) => m[1]).sort()
}

const ALL = blocks(CSS)
const root = ALL.find((b) => b.selector.includes("[data-theme='default']"))

describe('token 层', () => {
  test(':root 与默认主题共用一块（否则"默认值"有两份）', () => {
    expect(root).toBeTruthy()
    expect(root!.selector).toContain(':root')
    expect(tokenNames(root!.body).length).toBeGreaterThanOrEqual(30)
  })

  for (const t of THEMES) {
    test(`[data-theme='${t.id}'] 的 token 集合与默认**逐字相等**`, () => {
      const b = ALL.find((x) => x.selector === `[data-theme='${t.id}']`)
      expect(b, `index.css 缺 [data-theme='${t.id}'] 块`).toBeTruthy()
      expect(tokenNames(b!.body)).toEqual(tokenNames(root!.body))
    })
  }

  test('@theme inline 与 body 引用的每个 --v-* 都有定义', () => {
    const defined = new Set(tokenNames(root!.body))
    const referenced = [...CSS.matchAll(/var\(\s*(--v-[a-z0-9-]+)/g)].map((m) => m[1])
    expect(referenced.length).toBeGreaterThan(20)
    const missing = [...new Set(referenced)].filter((n) => !defined.has(n))
    expect(missing, `这些 token 被引用但没有定义：${missing.join(', ')}`).toEqual([])
  })
})
```

**4) 改 `web/src/index.css`**（全文；原有的 `html{}` 规则与两句注释保留）：

```css
@import 'tailwindcss';

/* ═══════════════════════════════════════════════════════════════════════
   M7 · 主题层：两层结构（调用点的类名固定，值随主题走）
   ───────────────────────────────────────────────────────────────────────
   ① 原始变量层（`--v-*`）：每套主题各给一份**完整**的值。`[data-theme='x']`
      挂在 `<html>` 上；`:root, [data-theme='default']` 那一份就是默认主题。
   ② 映射层（`@theme inline`）：把原始变量接进 Tailwind 的命名空间，于是
      `bg-vigil-surface` / `text-vigil-fg-2` / `shadow-vigil-card` /
      `backdrop-blur-vigil-panel` 这些**调用点的类名不变**，值随主题走；
      `--radius-{md,lg,xl}` 是**覆盖内置刻度**，所以 `rounded-lg` 一个字都不用改。

   ⚠️ 计划期实测（2026-09-22，vite build 产物 grep）——这几条都是踩过的：
   * `@theme inline { --color-x: var(--v-x) }` ⇒ `.bg-x{background-color:var(--v-x)}`。
     **必须**是 `inline`，否则产物里会烘进一个**构建期**的 hex fallback。
   * ⛔ 由此：**语义 token 一律不许带透明度修饰符**（`bg-vigil-surface/50`）。
     实测 `bg-vigil-bg/90` 在产物里同时出现 `#0b0f14e6`（构建期烘死）
     与 `color-mix(...)` 两条——前者的值来自构建那一刻的主题，切了也不变。
     值是 `var()` 的那一支没人验过 ⇒ 整条路直接禁用（守卫有机械检查）。
   * 覆盖内置刻度同样生效：实测 `.rounded-lg{border-radius:var(--v-probe-radius)}`。
   * ⛔ 裸 `rounded` 是**字面量**（产物 `.rounded{border-radius:.25rem}`）、
     `border` 的宽度也是（`.border-t{border-top-width:1px}`）⇒ 这两样**不可主题化**。
     裸 `rounded` 由 T2 换成 `rounded-md`；「厚边框」由各主题的 `--v-shadow-card`
     承担（粗野主义用 `4px 4px 0 0` 的硬阴影）。
   ═══════════════════════════════════════════════════════════════════════ */

/* ── ① 原始变量：默认主题（`:root` 与显式 `[data-theme='default']` 共用一块） ── */
:root,
[data-theme='default'] {
  /* 页面与浮层底 */
  --v-bg: #0b0f14;
  --v-header: rgba(11, 15, 20, 0.9);
  --v-page-image: none;
  /* 文字四级（1 最强 → 4 最弱） */
  --v-fg: #e6edf3;
  --v-fg-2: rgba(255, 255, 255, 0.72);
  --v-fg-3: rgba(255, 255, 255, 0.55);
  --v-fg-4: rgba(255, 255, 255, 0.4);
  /* 面（solid = 浮层用，必须不透明，否则菜单背后透出正文） */
  --v-surface: rgba(255, 255, 255, 0.05);
  --v-surface-2: rgba(255, 255, 255, 0.1);
  --v-surface-solid: #141a22;
  --v-inset: rgba(0, 0, 0, 0.3);
  --v-border: rgba(255, 255, 255, 0.1);
  --v-border-soft: rgba(255, 255, 255, 0.05);
  /* 强调（链接 / 主按钮 / 选中态） */
  --v-accent: #38bdf8;
  --v-accent-soft: rgba(56, 189, 248, 0.2);
  --v-accent-text: #bae6fd;
  /* 危险（错误框 / 重试 / 危险按钮） */
  --v-danger: #f87171;
  --v-danger-soft: rgba(239, 68, 68, 0.1);
  --v-danger-btn: rgba(239, 68, 68, 0.15);
  --v-danger-btn-active: rgba(239, 68, 68, 0.25);
  --v-danger-text: #fecaca;
  /* 提醒（公告框 / 死线 / 警告按钮） */
  --v-warn: #fbbf24;
  --v-warn-soft: rgba(245, 158, 11, 0.1);
  --v-warn-btn: rgba(245, 158, 11, 0.2);
  --v-warn-text: #fde68a;
  /* 结构：圆角（覆盖内置刻度）/ 阴影 / 模糊 / 字体 / 字距 */
  --v-radius-md: 0.375rem;
  --v-radius-lg: 0.5rem;
  --v-radius-xl: 0.75rem;
  --v-shadow-card: none;
  --v-header-blur: 8px;
  --v-panel-blur: 0px;
  --v-font-sans: system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  --v-tracking: normal;
}

/* ── ② 映射层 ── */
@theme inline {
  --color-vigil-fg: var(--v-fg);
  --color-vigil-fg-2: var(--v-fg-2);
  --color-vigil-fg-3: var(--v-fg-3);
  --color-vigil-fg-4: var(--v-fg-4);
  --color-vigil-header: var(--v-header);
  --color-vigil-surface: var(--v-surface);
  --color-vigil-surface-2: var(--v-surface-2);
  --color-vigil-surface-solid: var(--v-surface-solid);
  --color-vigil-inset: var(--v-inset);
  --color-vigil-border: var(--v-border);
  --color-vigil-border-soft: var(--v-border-soft);
  --color-vigil-accent: var(--v-accent);
  --color-vigil-accent-soft: var(--v-accent-soft);
  --color-vigil-accent-text: var(--v-accent-text);
  --color-vigil-danger: var(--v-danger);
  --color-vigil-danger-soft: var(--v-danger-soft);
  --color-vigil-danger-btn: var(--v-danger-btn);
  --color-vigil-danger-btn-active: var(--v-danger-btn-active);
  --color-vigil-danger-text: var(--v-danger-text);
  --color-vigil-warn: var(--v-warn);
  --color-vigil-warn-soft: var(--v-warn-soft);
  --color-vigil-warn-btn: var(--v-warn-btn);
  --color-vigil-warn-text: var(--v-warn-text);

  /* 覆盖内置刻度 ⇒ 调用点的 `rounded-md/lg/xl` 一个字都不用改 */
  --radius-md: var(--v-radius-md);
  --radius-lg: var(--v-radius-lg);
  --radius-xl: var(--v-radius-xl);

  --shadow-vigil-card: var(--v-shadow-card);
  --blur-vigil-header: var(--v-header-blur);
  --blur-vigil-panel: var(--v-panel-blur);
}

/* ── ③ 页面层：不进 Tailwind（body 上一次用掉），因此能承载"美术资产"
      ——渐变 / 网格纸 / 辉光都是任意 CSS，只受"每套主题各给一份"约束 ── */
body {
  background-color: var(--v-bg);
  background-image: var(--v-page-image);
  color: var(--v-fg);
  font-family: var(--v-font-sans);
  letter-spacing: var(--v-tracking);
  min-height: 100vh;
}

/* ⚠️ 表单控件**不继承** font-family / letter-spacing（UA 样式给它们另设了一套）。
   不写这一段，粗野主义的等宽字体只作用在正文上，而所有按钮/输入框还是系统字体
   ——就是「主题看着没生效」的典型形态。 */
button,
input,
textarea,
select {
  font: inherit;
  letter-spacing: inherit;
}

/* ── ④ 另外四套主题：**先逐字等于默认**（机制先跑通）。
      T3 把它们换成各自的值——注意 T3 换的是**整块 33 个 token**，
      不是"只改颜色那几行"。 ── */
[data-theme='material'] {
  --v-bg: #0b0f14;
  --v-header: rgba(11, 15, 20, 0.9);
  --v-page-image: none;
  --v-fg: #e6edf3;
  --v-fg-2: rgba(255, 255, 255, 0.72);
  --v-fg-3: rgba(255, 255, 255, 0.55);
  --v-fg-4: rgba(255, 255, 255, 0.4);
  --v-surface: rgba(255, 255, 255, 0.05);
  --v-surface-2: rgba(255, 255, 255, 0.1);
  --v-surface-solid: #141a22;
  --v-inset: rgba(0, 0, 0, 0.3);
  --v-border: rgba(255, 255, 255, 0.1);
  --v-border-soft: rgba(255, 255, 255, 0.05);
  --v-accent: #38bdf8;
  --v-accent-soft: rgba(56, 189, 248, 0.2);
  --v-accent-text: #bae6fd;
  --v-danger: #f87171;
  --v-danger-soft: rgba(239, 68, 68, 0.1);
  --v-danger-btn: rgba(239, 68, 68, 0.15);
  --v-danger-btn-active: rgba(239, 68, 68, 0.25);
  --v-danger-text: #fecaca;
  --v-warn: #fbbf24;
  --v-warn-soft: rgba(245, 158, 11, 0.1);
  --v-warn-btn: rgba(245, 158, 11, 0.2);
  --v-warn-text: #fde68a;
  --v-radius-md: 0.375rem;
  --v-radius-lg: 0.5rem;
  --v-radius-xl: 0.75rem;
  --v-shadow-card: none;
  --v-header-blur: 8px;
  --v-panel-blur: 0px;
  --v-font-sans: system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  --v-tracking: normal;
}

/* [data-theme='brutalism'] / [data-theme='vaporwave'] / [data-theme='glass']
   三块与上面 material 那块**逐字相同**（33 行 × 3）。
   ⚠️ 四块都要在 T1 里写全——parity 测试要求「五套主题的 token 集合逐字相等」。 */

html {
  /* 手机上禁掉横向滚动：源消息里偶有长链接，别把整页撑歪 */
  overflow-x: hidden;
}
```

**5) 改 `web/index.html`** —— 加防闪脚本（`<head>` 内、其它脚本之前）：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1.0, viewport-fit=cover"
    />
    <meta name="theme-color" content="#0b0f14" />
    <link rel="icon" href="/icon-192.png" />
    <link rel="apple-touch-icon" href="/icon-192.png" />
    <title>VIGIL 守夜人</title>
    <!--
      ⚠️ 防闪（FOUC）：主题属性必须在**首帧之前**挂上，否则默认主题会先画一帧
      再跳成用户选的那套——手机上就是一道闪。

      ⚠️ 白名单是**手写的第二份真相**（第一份是 src/theme.ts 的 THEMES）
      ⇒ `theme.test.ts` 里有一条逐字比对。不校验的话，垃圾值会挂到
      data-theme 上、CSS 静默回落——排查时零线索。
    -->
    <script>
      ;(function () {
        var ALLOWED = ['default', 'material', 'brutalism', 'vaporwave', 'glass']
        try {
          var t = localStorage.getItem('vigil.theme')
          if (t && ALLOWED.indexOf(t) !== -1) {
            document.documentElement.setAttribute('data-theme', t)
          }
        } catch (e) {
          /* 读不到就保持默认主题：防闪脚本**不该**是任何功能失败的原因 */
        }
      })()
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**6) 改 `web/src/main.tsx`**（T6 还会再动它一次；这一轮只加 theme 那两行）：

```tsx
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
```

**7) 验证与提交**

```bash
cd web && npm test        # 期望全绿（55 原有 + 新增）
cd web && npm run build   # 期望成功（tsc -b 也在里面）
```
- 目视：`npm run build` 后开 `http://127.0.0.1:8787/`（自启服务托管 `web/dist`），观感应**与改动前逐像素相同**。
- commit：`feat(web): 主题底座——--v-* 两层 token 层 + 防闪 + theme-color 同步`

---

## Task 2: 227 处语义化搬迁

**目标**：`web/src` 里的裸调色板类名 **227 → 0**，观感不变（默认主题值 = 今天的值）。

**Interfaces**

- **Consumes**：T1 的全部 token 名与 `@theme inline` 映射。
- **Produces**：`web/tools/retheme_m7.py`（一次性搬迁脚本，`--check` / `--apply`）；`web/src/__tests__/noRawPalette.test.ts`（两条守卫：零残留 + 零透明度修饰符）。

**Steps**

**1) 先写守卫测试** `web/src/__tests__/noRawPalette.test.ts`：

```ts
import { expect, test } from 'vitest'

/**
 * ⚠️ Node 内置模块在本仓**必须**用「具名变量说明符」动态 import——两条实测出来的墙
 * （T1 报告 §4 偏差 4/5；M7 勘误 E9）：
 *   ① 本仓没有 `@types/node`，而 `tsc -b`（`npm run build` 会跑）**会编译测试文件**
 *      ⇒ `import { readFileSync } from 'node:fs'` 直接 TS2307 让构建失败；
 *   ② `new URL('..', import.meta.url)` 第二个参数写成**字面量**时，Vite 的
 *      asset-import-meta-url 变换会接管，基准被换成 jsdom 的 document base
 *      （实测 → `http://localhost:3000/index.html`）；先取 `const HERE = import.meta.url` 再传就正常。
 * 故意**不用** `// @ts-expect-error`：将来真装了 @types/node 会变成 TS2578，又把构建搞坏一次。
 */
const NODE_FS = 'node:' + 'fs'
const NODE_PATH = 'node:' + 'path'
const NODE_URL = 'node:' + 'url'
const HERE = import.meta.url

const { readdirSync, readFileSync } = (await import(/* @vite-ignore */ NODE_FS)) as {
  readdirSync: (p: string, o: { withFileTypes: true }) => { name: string; isDirectory(): boolean }[]
  readFileSync: (p: string, enc: string) => string
}
const { join, relative } = (await import(/* @vite-ignore */ NODE_PATH)) as {
  join: (...p: string[]) => string
  relative: (a: string, b: string) => string
}
const { fileURLToPath } = (await import(/* @vite-ignore */ NODE_URL)) as {
  fileURLToPath: (u: URL) => string
}

/**
 * ⭐ 出口判据 4（浅色主题下无「深色残留」）的**入口守卫**：
 * 只要还有一处写死的 Tailwind 调色板类名，那处就在浅色主题里保持深色
 * ——而它可能藏在 1,023 行的 Settings.tsx 里，肉眼翻不到。
 *
 * ⚠️ 它**只证明"没有残留"，证明不了"映射对不对"**。映射的正确性由
 * `web/tools/retheme_m7.py` 的映射表（可审查）+ T3 的主题值 + 冒烟截图承担。
 */
const SRC = fileURLToPath(new URL('..', HERE))

// 与 codemod 的 --check 用**同一条**正则（两份副本；漂移由本测试兜底：它说了算）
const PALETTE =
  /\b(?:bg|text|border|ring|divide|from|to|via|placeholder|fill|stroke|shadow|outline|decoration|accent|caret)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)(?:-\d{2,3})?(?:\/\d{1,3})?\b/g

// 语义 token 上的透明度修饰符：**禁用**（见 index.css 顶部 E3 的实测）
const TOKEN_WITH_ALPHA =
  /\b(?:bg|text|border|ring|from|to|via|placeholder|fill|stroke|decoration|accent|caret)-vigil-[a-z0-9-]+\/\d{1,3}\b/g

// 本文件自己带着这两条正则的字面量，必须排除（否则自己匹配自己）
const ALLOW = new Set(['__tests__/noRawPalette.test.ts'])

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name)
    if (e.isDirectory()) return walk(p)
    return /\.(ts|tsx)$/.test(e.name) ? [p] : []
  })
}

function scan(re: RegExp): string[] {
  const hits: string[] = []
  for (const f of walk(SRC)) {
    const rel = relative(SRC, f).replace(/\\/g, '/')
    if (ALLOW.has(rel)) continue
    const text = readFileSync(f, 'utf8')
    for (const m of text.matchAll(re)) {
      const line = text.slice(0, m.index).split('\n').length
      hits.push(`${rel}:${line}  ${m[0]}`)
    }
  }
  return hits
}

test('src 里不许再出现裸调色板类名（227 → 0）', () => {
  const hits = scan(PALETTE)
  expect(hits, `还有 ${hits.length} 处裸调色板类名：\n${hits.join('\n')}`).toEqual([])
})

test('语义 token 不许带透明度修饰符（E3：构建期会烘死一个 fallback）', () => {
  const hits = scan(TOKEN_WITH_ALPHA)
  expect(hits, `这些地方给 token 加了透明度：\n${hits.join('\n')}`).toEqual([])
})
```

**2) 跑一次，把红色输出里的数记进报告**（期望 227 处、逐文件 `8/22/19/4/11/20/29/114`）——这是本任务的**红相位证据**。

**3) 写 `web/tools/retheme_m7.py`**（完整代码）：

```python
#!/usr/bin/env python3
"""M7 一次性搬迁：裸 Tailwind 调色板类名 → 语义 token 类名。

⚠️ **这是一次性脚本，不是常驻工具**（跑完就该没人再用它）。保留它的唯一理由是：
守卫测试只能证明「没有残留」，**证明不了「映射对不对」**——而这张映射表
是可审查的机械形式（把"为什么 sky-300 与 sky-200 合成同一个 token"这类判断
留在代码里，而不是留在某个人的记忆里）。

用法（在 `web/` 下）：
    python tools/retheme_m7.py --check     # 只报命中数（逐文件）
    python tools/retheme_m7.py --apply     # 落地

⚠️ 按**字节**读写（不经过文本换行转换）——见 M7 Global Constraints G5：
本仓 `web/src` 里 `w/lf` 与 `w/crlf` 混着，而 blob 全是 `i/lf`。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# 与 src/__tests__/noRawPalette.test.ts 的 PALETTE 同源（两份副本，测试那份说了算）
PALETTE = re.compile(
    r"\b(?:bg|text|border|ring|divide|from|to|via|placeholder|fill|stroke|shadow"
    r"|outline|decoration|accent|caret)-"
    r"(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald"
    r"|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)"
    r"(?:-\d{2,3})?(?:/\d{1,3})?\b"
)

# ⚠️ 按**键长降序**替换：`text-white/40` 必须先于 `text-white`
#（否则前者被后者的前缀吃掉，产出 `text-vigil-fg/40`——一个不存在的类名，
# 而 Tailwind 对不存在的类名**不报错**，只是不生成 ⇒ 元素没颜色、控制台安静）。
MAPPING: dict[str, str] = {
    # 面
    "bg-white/5": "bg-vigil-surface",
    "bg-white/10": "bg-vigil-surface-2",
    "bg-black/30": "bg-vigil-inset",
    "bg-vigil-bg/90": "bg-vigil-header",
    # 边框
    "border-white/10": "border-vigil-border",
    "border-white/5": "border-vigil-border-soft",
    # 文字四级（白系 13 档 → 4 档）。
    # ⚠️ **档位合并遍及四族，不只是白系**（reviewer 实测，见 §0 E11）：
    #   text-sky-300 → accent-text（= sky-200，6 处）/ text-red-300 → danger（= red-400，3 处）/
    #   text-amber-100 → warn-text（= amber-200，1 处）/ bg-red-500/20 → danger-btn（α .20→.15，1 处）。
    #   白系里 **12/35 个类有数值漂移**（分 9 组）；最大的一处 `text-white/75` 已按 R5 回正为 fg-2。
    "text-white/95": "text-vigil-fg",
    "text-white/90": "text-vigil-fg",
    "text-white/85": "text-vigil-fg",
    "text-white/80": "text-vigil-fg",
    "text-white/75": "text-vigil-fg-2",   # R5：原来映到 fg（#e6edf3）≈ +40/通道，是全部漂移里最大的一处
    "text-white/70": "text-vigil-fg-2",
    "text-white/60": "text-vigil-fg-2",
    "text-white/55": "text-vigil-fg-3",
    "text-white/50": "text-vigil-fg-3",
    "text-white/45": "text-vigil-fg-3",
    "text-white/40": "text-vigil-fg-4",
    "text-white/35": "text-vigil-fg-4",
    "text-white/30": "text-vigil-fg-4",
    "text-white": "text-vigil-fg",
    # 强调
    "bg-sky-500/20": "bg-vigil-accent-soft",
    "text-sky-400": "text-vigil-accent",
    "text-sky-300": "text-vigil-accent-text",
    "text-sky-200": "text-vigil-accent-text",
    # 危险
    "bg-red-500/25": "bg-vigil-danger-btn-active",
    "bg-red-500/20": "bg-vigil-danger-btn",
    "bg-red-500/15": "bg-vigil-danger-btn",
    "bg-red-500/10": "bg-vigil-danger-soft",
    "text-red-400": "text-vigil-danger",
    "text-red-300": "text-vigil-danger",
    "text-red-200": "text-vigil-danger-text",
    # 提醒
    "bg-amber-500/20": "bg-vigil-warn-btn",
    "bg-amber-500/10": "bg-vigil-warn-soft",
    "text-amber-400": "text-vigil-warn",
    "text-amber-200": "text-vigil-warn-text",
    "text-amber-100": "text-vigil-warn-text",
}

# 裸 `rounded` 是**字面量 .25rem**（E5）⇒ 换成可主题化的 `rounded-md`。
# 用词边界，别把 `rounded-lg` / `rounded-r-full` 的前缀也吃掉。
BARE_ROUNDED = re.compile(r"(?<![\w-])rounded(?![\w-])")


def files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.ts*") if p.is_file())


def rewrite(text: str) -> str:
    for old in sorted(MAPPING, key=len, reverse=True):
        text = text.replace(old, MAPPING[old])
    return BARE_ROUNDED.sub("rounded-md", text)


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0
    for p in files():
        raw = p.read_bytes()
        text = raw.decode("utf-8")
        n = len(PALETTE.findall(text))
        total += n
        if n:
            print(f"{n:>4}  {p.relative_to(SRC.parent)}")
        if apply and n:
            out = rewrite(text)
            left = len(PALETTE.findall(out))
            if left:
                print(f"  ⛔ {p} 迁完还剩 {left} 处——映射表缺键，**没有写盘**")
                return 1
            p.write_bytes(out.encode("utf-8"))  # 按字节写：行尾原样保留（G5）
    print(f"总命中 {total}（应用前）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**4) 跑 `python tools/retheme_m7.py --apply`**：期望逐文件输出与红相位的 8 个数**逐字相同**，且没有"⛔ 还剩"。

**5) 手工收尾三处**（codemod 不碰的）：

- `src/App.tsx:46`：`className="min-h-screen bg-vigil-bg text-vigil-fg"` → `className="min-h-screen text-vigil-fg"`
  （页面底由 `body` 提供；留着 `bg-vigil-bg` 会让根 div 盖住 `--v-page-image` 的渐变——玻璃/粗野主义会看不见）。
- `src/App.tsx:47`：`... bg-vigil-header backdrop-blur` → `... bg-vigil-header backdrop-blur-vigil-header`
  （裸 `backdrop-blur` 是 8px 字面量；换成语义类后由 `--v-header-blur` 主题化，默认值 8px ⇒ 观感不变。T4 会重排这一行，本轮只改类名。）
- `src/index.css`：删掉 `@theme inline` 里的 `--color-vigil-bg`（它最后一个用户是 App 根 div，已删）。
  **保留** `--v-bg`（`body` 与 `theme.ts` 的 `theme-color` 同步要用）。
  ⚠️ T1 执行期把它**补回来过**（当时 App.tsx 还在用 `bg-vigil-bg`，删了顶栏底色会整条消失——
  见 T1 报告偏差 1）；只有在本任务删掉它的最后一个用户**之后**，删映射才是对的。

**6) 验证与提交**

```bash
cd web && npm test && npm run build
cd .. && git diff --stat    # ⚠️ 逐文件改动行数应与"该文件命中数"同量级——
                            # 整文件级别的 diff = 行尾被改了（G5）
```
- 目视：8787 上**默认主题观感与改动前相同**（唯一预期差异：7 处裸 `rounded` 的小按钮圆角 4px → 6px，已声明）。
- commit：`refactor(web): 227 处裸调色板类名收成语义 token（+ 零残留守卫）`

---

## Task 3: 五套主题的视觉（结构 + 调色 + 页面资产 + 面板站点）

**目标**：四套非默认主题各自成立——形状、字体、阴影、模糊、底色、可读性都不同，**不是只换颜色**。

**Interfaces**

- **Consumes**：T1 的 33 个 token 名与 `@theme inline` 映射；T2 之后的语义类名。
- **Produces**：四块完整的 `[data-theme='x']` 值；7 个面板站点上的 `shadow-vigil-card backdrop-blur-vigil-panel`。

**Steps**

**1) 先写两个失败测试**（此刻四套主题的值还等于默认 ⇒ 都红）。

`web/src/__tests__/themeTokens.test.ts` **追加**（`blocks` 从同文件导出，直接复用）：

```ts
test('结构维度每套主题各给一份，且与默认**不同**（否则"五套主题"只剩标签不同）', () => {
  const v = (theme: string, token: string) => {
    const b = blocks(CSS).find((x) => x.selector === `[data-theme='${theme}']`)
    expect(b, `缺 [data-theme='${theme}'] 块`).toBeTruthy()
    const m = b!.body.match(new RegExp(`${token}\\s*:\\s*([^;]+)`))
    expect(m, `${theme} 缺 ${token}`).toBeTruthy()
    return m![1].trim()
  }

  expect(v('brutalism', '--v-radius-xl')).toBe('0px') // 方角是粗野主义的判据
  expect(v('brutalism', '--v-font-sans')).toContain('monospace')
  expect(v('brutalism', '--v-shadow-card')).not.toBe('none') // 硬阴影承担"厚边框"（E5）
  expect(v('glass', '--v-panel-blur')).not.toBe('0px')
  expect(v('glass', '--v-page-image')).toContain('gradient')
  expect(v('vaporwave', '--v-page-image')).toContain('gradient')
  expect(v('material', '--v-shadow-card')).not.toBe('none') // 抬升
  expect(v('default', '--v-shadow-card')).toBe('none') // 默认主题保持今天的观感
  expect(v('default', '--v-page-image')).toBe('none')
})
```

`web/src/__tests__/themePalette.test.ts`（新文件，完整）：

```ts
import { expect, test } from 'vitest'
import { THEMES } from '../theme.ts'

// ⚠️ Node 内置模块的写法与理由见 `noRawPalette.test.ts` 顶部那段（M7 勘误 E9 的两条墙）
const NODE_FS = 'node:' + 'fs'
const HERE = import.meta.url
const { readFileSync } = (await import(/* @vite-ignore */ NODE_FS)) as {
  readFileSync: (p: URL, enc: string) => string
}

/**
 * ⭐ 调色板的**可读性守卫**。它回答两个肉眼会漏的问题：
 *   ① 浅色主题**真的**是浅色吗（出口判据 4 的反面：深色残留）
 *   ② 弱化文字 / 软底按钮上的文字**读得清**吗（主题化最容易在"某一套"上翻车）
 *
 * ⚠️ 期望值一律**逐字写死**，绝不写成"读 CSS 再比 CSS"（空守卫的经典形状）。
 * ⚠️ 已知近似：玻璃主题的真实底是**渐变**，而这里只能拿 `--v-bg`（不透明基色）算
 *    ⇒ 故 `--v-bg` 取渐变中位色。这条近似**写在这里**，不许被说成"渐变也验过了"。
 * ⚠️ 剥注释再解析（理由同 `themeTokens.test.ts`：注释里含示例 CSS）。
 */
const CSS = readFileSync(new URL('../index.css', HERE), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

type RGBA = [number, number, number, number]

function value(theme: string, token: string): string {
  const m = CSS.match(
    new RegExp(`\\[data-theme='${theme}'\\][^{]*\\{[^}]*${token}\\s*:\\s*([^;]+);`),
  )
  if (m === null) throw new Error(`找不到 ${theme} 的 ${token}`)
  return m[1].trim()
}

function parse(s: string): RGBA {
  const hex = s.match(/^#([0-9a-f]{6})$/i)
  if (hex !== null) {
    const n = parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1]
  }
  const rgba = s.match(/rgba?\(([^)]+)\)/)
  if (rgba !== null) {
    const p = rgba[1].split(',').map((x) => parseFloat(x.trim()))
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]
  }
  throw new Error(`不认识的色值：${s}`)
}

/** 半透明层叠在不透明底上（默认主题的面几乎都是 rgba，不算这步全错） */
function over(top: RGBA, bottom: RGBA): RGBA {
  const a = top[3]
  return [
    top[0] * a + bottom[0] * (1 - a),
    top[1] * a + bottom[1] * (1 - a),
    top[2] * a + bottom[2] * (1 - a),
    1,
  ]
}

function luminance([r, g, b]: RGBA): number {
  const f = (c: number) => {
    const x = c / 255
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

function contrast(a: RGBA, b: RGBA): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

test('四套非默认主题的两个"面"色都不等于默认主题（否则它没换过）', () => {
  for (const t of THEMES.filter((x) => x.id !== 'default')) {
    expect(value(t.id, '--v-surface'), `${t.id} 的 --v-surface`).not.toBe(
      value('default', '--v-surface'),
    )
    expect(value(t.id, '--v-bg'), `${t.id} 的 --v-bg`).not.toBe(value('default', '--v-bg'))
  }
})

test('浅色主题真的是浅色、深色主题真的是深色（出口判据 4 的静态形式）', () => {
  const light = ['material', 'brutalism']
  for (const t of THEMES) {
    const L = luminance(parse(value(t.id, '--v-bg')))
    if (light.includes(t.id)) {
      expect(L, `${t.id} 的 --v-bg 应该是浅色`).toBeGreaterThan(0.5)
    } else {
      expect(L, `${t.id} 的 --v-bg 应该是深色`).toBeLessThan(0.5)
    }
  }
})

test('正文与弱化文字在面板上都读得清（WCAG：正文 ≥4.5 / 弱化文字 ≥3）', () => {
  for (const t of THEMES) {
    const bg = parse(value(t.id, '--v-bg'))
    const card = over(parse(value(t.id, '--v-surface')), bg)
    expect(contrast(parse(value(t.id, '--v-fg')), card), `${t.id} 正文/卡片`).toBeGreaterThanOrEqual(4.5)
    expect(contrast(parse(value(t.id, '--v-fg-3')), card), `${t.id} 弱化文字/卡片`).toBeGreaterThanOrEqual(3)
    expect(
      contrast(parse(value(t.id, '--v-accent-text')), parse(value(t.id, '--v-accent-soft'))),
      `${t.id} 软底按钮文字`,
    ).toBeGreaterThanOrEqual(3)
    expect(
      contrast(parse(value(t.id, '--v-danger-text')), parse(value(t.id, '--v-danger-btn'))),
      `${t.id} 危险按钮文字`,
    ).toBeGreaterThanOrEqual(3)
  }
})
```

**2) 把四块主题**整块**替换成下面的完整文本**（每块 33 行一个不少；颜色/结构/页面资产都在这里定稿）：

```css
[data-theme='material'] {
  /* Material 3 浅色：tonal surface + elevation + 紫系 primary */
  --v-bg: #fdfbff;
  --v-header: rgba(253, 251, 255, 0.88);
  --v-page-image: none;
  --v-fg: #1c1b1f;
  --v-fg-2: #49454f;
  --v-fg-3: #5f5c66;
  --v-fg-4: #79747e;
  --v-surface: #f7f2fa;
  --v-surface-2: #e8def8;
  --v-surface-solid: #ffffff;
  --v-inset: #ece6f0;
  --v-border: #cac4d0;
  --v-border-soft: #e7e0ec;
  --v-accent: #6750a4;
  --v-accent-soft: #eaddff;
  --v-accent-text: #4f378b;
  --v-danger: #b3261e;
  --v-danger-soft: #f9dedc;
  --v-danger-btn: #f9dedc;
  --v-danger-btn-active: #f2b8b5;
  --v-danger-text: #8c1d18;
  --v-warn: #8b5000;
  --v-warn-soft: #ffdeaa;
  --v-warn-btn: #ffdeaa;
  --v-warn-text: #5c3c00;
  --v-radius-md: 0.5rem;
  --v-radius-lg: 0.75rem;
  --v-radius-xl: 0.75rem;
  --v-shadow-card: 0 1px 2px rgba(0, 0, 0, 0.3), 0 1px 3px 1px rgba(0, 0, 0, 0.15);
  --v-header-blur: 0px;
  --v-panel-blur: 0px;
  --v-font-sans: 'Roboto', system-ui, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  --v-tracking: normal;
}

[data-theme='brutalism'] {
  /* 高对比 + 硬阴影 + 方角 + 等宽：选中态纯黄，按钮纯黑底白字 */
  --v-bg: #f2f0eb;
  --v-header: rgba(242, 240, 235, 0.96);
  --v-page-image: repeating-linear-gradient(0deg, rgba(0, 0, 0, 0.05) 0 1px, transparent 1px 24px),
    repeating-linear-gradient(90deg, rgba(0, 0, 0, 0.05) 0 1px, transparent 1px 24px);
  --v-fg: #0a0a0a;
  --v-fg-2: #262626;
  --v-fg-3: #404040;
  --v-fg-4: #5c5c5c;
  --v-surface: #ffffff;
  --v-surface-2: #ffe600;
  --v-surface-solid: #ffffff;
  --v-inset: #ffffff;
  --v-border: #0a0a0a;
  --v-border-soft: #9a9a9a;
  --v-accent: #0a0a0a;
  --v-accent-soft: #0a0a0a;
  --v-accent-text: #ffffff;
  --v-danger: #d40000;
  --v-danger-soft: #ffd9d9;
  --v-danger-btn: #d40000;
  --v-danger-btn-active: #8f0000;
  --v-danger-text: #ffffff;
  --v-warn: #7a5c00;
  --v-warn-soft: #ffe600;
  --v-warn-btn: #ffe600;
  --v-warn-text: #4a3800;
  --v-radius-md: 0px;
  --v-radius-lg: 0px;
  --v-radius-xl: 0px;
  --v-shadow-card: 4px 4px 0 0 #0a0a0a;
  --v-header-blur: 0px;
  --v-panel-blur: 0px;
  --v-font-sans: ui-monospace, 'Cascadia Mono', Consolas, 'Microsoft YaHei', monospace;
  --v-tracking: 0.02em;
}

[data-theme='vaporwave'] {
  /* 深紫底 + 粉/青霓虹：软底低透明度，靠 --v-shadow-card 的辉光收边 */
  --v-bg: #1a0b2e;
  --v-header: rgba(26, 11, 46, 0.88);
  --v-page-image: radial-gradient(120% 70% at 50% 110%, rgba(0, 229, 255, 0.25), transparent 60%),
    linear-gradient(180deg, rgba(255, 52, 182, 0.22), transparent 45%),
    repeating-linear-gradient(0deg, rgba(0, 229, 255, 0.06) 0 1px, transparent 1px 26px);
  --v-fg: #f6e9ff;
  --v-fg-2: #dcc4ff;
  --v-fg-3: #b78fe0;
  --v-fg-4: #8f6cb5;
  --v-surface: rgba(255, 255, 255, 0.06);
  --v-surface-2: rgba(255, 52, 182, 0.22);
  --v-surface-solid: #241040;
  --v-inset: rgba(0, 0, 0, 0.35);
  --v-border: rgba(0, 229, 255, 0.45);
  --v-border-soft: rgba(0, 229, 255, 0.22);
  --v-accent: #00e5ff;
  --v-accent-soft: rgba(0, 229, 255, 0.18);
  --v-accent-text: #b3f7ff;
  --v-danger: #ff5c8a;
  --v-danger-soft: rgba(255, 92, 138, 0.16);
  --v-danger-btn: rgba(255, 92, 138, 0.22);
  --v-danger-btn-active: rgba(255, 92, 138, 0.34);
  --v-danger-text: #ffd0dd;
  --v-warn: #ffd166;
  --v-warn-soft: rgba(255, 209, 102, 0.16);
  --v-warn-btn: rgba(255, 209, 102, 0.24);
  --v-warn-text: #fff0c2;
  --v-radius-md: 0.5rem;
  --v-radius-lg: 0.75rem;
  --v-radius-xl: 1rem;
  --v-shadow-card: 0 0 0 1px rgba(0, 229, 255, 0.28), 0 0 20px rgba(255, 52, 182, 0.35);
  --v-header-blur: 12px;
  --v-panel-blur: 6px;
  --v-font-sans: system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  --v-tracking: 0.02em;
}

[data-theme='glass'] {
  /* 深色极光底 + 半透明白面板 + 大模糊：--v-bg 取渐变中位色（对比度测试要用） */
  --v-bg: #241447;
  --v-header: rgba(36, 20, 71, 0.55);
  --v-page-image: radial-gradient(90% 60% at 12% 0%, rgba(124, 58, 237, 0.55), transparent 62%),
    radial-gradient(80% 55% at 88% 8%, rgba(236, 72, 153, 0.42), transparent 58%),
    radial-gradient(120% 80% at 50% 105%, rgba(34, 211, 238, 0.38), transparent 62%),
    linear-gradient(160deg, #1b1035 0%, #241447 55%, #122140 100%);
  --v-fg: #ffffff;
  --v-fg-2: rgba(255, 255, 255, 0.82);
  --v-fg-3: rgba(255, 255, 255, 0.7);
  --v-fg-4: rgba(255, 255, 255, 0.55);
  --v-surface: rgba(255, 255, 255, 0.14);
  --v-surface-2: rgba(255, 255, 255, 0.26);
  --v-surface-solid: #3a2560;
  --v-inset: rgba(255, 255, 255, 0.1);
  --v-border: rgba(255, 255, 255, 0.3);
  --v-border-soft: rgba(255, 255, 255, 0.16);
  --v-accent: #a5f3fc;
  --v-accent-soft: rgba(165, 243, 252, 0.18);
  --v-accent-text: #cffafe;
  --v-danger: #ffa8b8;
  --v-danger-soft: rgba(255, 128, 149, 0.18);
  --v-danger-btn: rgba(255, 128, 149, 0.28);
  --v-danger-btn-active: rgba(255, 128, 149, 0.42);
  --v-danger-text: #ffffff;
  --v-warn: #ffe08a;
  --v-warn-soft: rgba(255, 224, 138, 0.18);
  --v-warn-btn: rgba(255, 224, 138, 0.26);
  --v-warn-text: #fff6da;
  --v-radius-md: 0.5rem;
  --v-radius-lg: 0.75rem;
  --v-radius-xl: 1rem;
  --v-shadow-card: 0 8px 32px rgba(12, 8, 32, 0.45);
  --v-header-blur: 18px;
  --v-panel-blur: 14px;
  --v-font-sans: system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  --v-tracking: normal;
}
```

> **不用网络字体**（含 CJK webfont）：离线 PWA + 体积 + 无 CDN 依赖三条理由；
> 美术资产靠渐变 / 网格 / 辉光 / 硬阴影 / 等宽，不靠字体文件。

**3) 7 个面板站点各加两个类**（机械规则：**元素上凡有 `rounded-xl` 的，追加 `shadow-vigil-card backdrop-blur-vigil-panel`**）：

| 文件:行（BASE 行号） | 元素 |
|---|---|
| `src/components/ItemCard.tsx:100` | `<li className="rounded-xl bg-vigil-surface p-3">` |
| `src/components/PersonPicker.tsx:92` | `mt-2 rounded-xl …` 面板 |
| `src/views/Digests.tsx:86` | `<article …>` 日报卡 |
| `src/views/Digests.tsx:197` | 日报列表项 |
| `src/views/Categories.tsx:79` | 类目列表项 |
| `src/views/Feed.tsx:262` | 搜索框 |
| `src/views/Feed.tsx:393` | 「加载更多」 |

> 规则是机械的（一律加），**不许按"我觉得它不像卡片"逐处判断**——判断会漂移，
> 而模糊/阴影是主题的资产；默认主题下这两个类的值是 `none` / `0px`，加了看不出来。
> T4 的浮层菜单会再加一处 `shadow-vigil-card`（第 8 处，已知且预期）。

**4) 验证与提交**

```bash
cd web && grep -rn "shadow-vigil-card" src --include=*.tsx | wc -l        # 期望 7（T4 之后 8）
cd web && grep -rn "backdrop-blur-vigil-panel" src --include=*.tsx | wc -l # 期望 7
cd web && npm test && npm run build
```
- 若某条对比度断言不过：**改值，不许改判据**；改不动就在报告里写清"哪一套的哪个 token 够不到 4.5、为什么接受"，交 reviewer 裁决。
- 目视（推荐）：8787 上逐套看一遍，把"第一眼觉得哪里丑"记进报告（用户验收要用）。
- commit：`feat(web): 五套主题的视觉——结构/调色/页面资产 + 面板站点`

---

## Task 4: 顶栏主题切换器 + 头部两行化

**目标**：顶栏一个 🎨 控件，点开五选一，立刻生效并落盘（出口判据 2 的交互半边）。

**Interfaces**

- **Consumes**：`THEMES` / `ThemeId` / `readTheme` / `applyTheme`（T1）。
- **Produces**：`ThemePicker`（`{ value: ThemeId; onChange: (id: ThemeId) => void }`）。

**为什么头部要改成两行**（**修前实测**，不是算术——我第一版写的"溢出被裁"是错的，见 §0 E8）：
375×667 下仪器量到「顶栏高 **77px**、5 个标签**全折成两行**、每个 tab 只剩 **48px 宽**」，
而**没有任何元素被裁**（右侧余 16px，`clippedCount=0`）——是**被挤扁**，不是被裁掉。
再加一个控件只会更扁 ⇒ 第一行放"品牌 + 动作"、第二行放 tab（必要时可横向滚动）。

**Steps**

**1) 写 `web/src/__tests__/ThemePicker.dom.test.tsx`**（先红：组件不存在）：

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import ThemePicker from '../components/ThemePicker.tsx'

afterEach(() => document.documentElement.removeAttribute('data-theme'))

test('默认关闭；点 🎨 展开五套，当前那套被标为选中', async () => {
  render(<ThemePicker value="material" onChange={() => {}} />)
  expect(screen.queryByRole('menu')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  expect(screen.getAllByRole('menuitemradio')).toHaveLength(5)
  expect(screen.getByRole('menuitemradio', { name: 'Material Design' })).toHaveAttribute(
    'aria-checked',
    'true',
  )
  expect(screen.getByRole('menuitemradio', { name: '毛玻璃' })).toHaveAttribute(
    'aria-checked',
    'false',
  )
})

test('选一套 ⇒ 回调收到它、菜单收起', async () => {
  const onChange = vi.fn()
  render(<ThemePicker value="default" onChange={onChange} />)
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: '蒸汽波' }))
  expect(onChange).toHaveBeenCalledWith('vaporwave')
  expect(screen.queryByRole('menu')).toBeNull()
})

test('点外面 / 按 Esc 都能关（没有这两条，手机上关不掉）', async () => {
  render(<ThemePicker value="default" onChange={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  await userEvent.click(document.body)
  expect(screen.queryByRole('menu')).toBeNull()

  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('menu')).toBeNull()
})
```

**2) 写 `web/src/components/ThemePicker.tsx`**：

```tsx
import { useEffect, useRef, useState } from 'react'
import { THEMES, type ThemeId } from '../theme.ts'

/**
 * 顶栏的紧凑切换器：一个 🎨 + 一个五项菜单。
 *
 * ⚠️ 它是**受控组件**（值在 App，不在自己手里）：主题是应用级状态，
 * 浮层只是它的一个视图——两处各持一份就会出现「菜单说材质、页面是蒸汽波」。
 */
export default function ThemePicker({
  value,
  onChange,
}: {
  value: ThemeId
  onChange: (id: ThemeId) => void
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointer(e: PointerEvent) {
      if (box.current !== null && !box.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        aria-label="切换主题"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="rounded-lg px-1.5 py-1 text-base active:bg-vigil-surface"
      >
        🎨
      </button>
      {open && (
        <ul
          role="menu"
          aria-label="主题"
          className="absolute right-0 z-30 mt-1 w-40 rounded-lg border border-vigil-border bg-vigil-surface-solid p-1 text-sm shadow-vigil-card"
        >
          {THEMES.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                role="menuitemradio"
                aria-checked={t.id === value}
                onClick={() => {
                  onChange(t.id)
                  setOpen(false)
                }}
                className={
                  'w-full rounded px-2 py-1.5 text-left ' +
                  (t.id === value
                    ? 'bg-vigil-accent-soft text-vigil-accent-text'
                    : 'text-vigil-fg-2 active:bg-vigil-surface')
                }
              >
                {t.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

**3) `web/src/App.tsx` 三处改动**：

```tsx
// ① import（加在现有 import 旁）
import ThemePicker from './components/ThemePicker.tsx'
import { applyTheme, readTheme, type ThemeId } from './theme.ts'

// ② state 与处理器（放在 tab 那几个 state 旁边）
const [theme, setTheme] = useState<ThemeId>(readTheme)
function pickTheme(id: ThemeId) {
  setTheme(id)
  applyTheme(id) // 落盘 + 挂属性 + 同步 theme-color，一处做完
}

// ③ header 换成两行（原 className="sticky top-0 …" 那个 <header> 的**整块**替换）
<header className="sticky top-0 z-10 border-b border-vigil-border bg-vigil-header backdrop-blur-vigil-header">
  <div className="mx-auto flex max-w-3xl items-center gap-1.5 px-4 pt-2">
    <span className="text-base font-semibold tracking-wide">🏮 VIGIL</span>
    {/* ⚠️ `ml-auto` 原来挂在 `nav` 上；撤销按钮插到它前面之后必须**挪过来**
        （同一行里只有一个 `ml-auto` 起作用，两个都在会变成两段式布局）。 */}
    <button
      onClick={undo}
      className="ml-auto rounded-lg px-2 py-1 text-xs text-vigil-fg-3 active:bg-vigil-surface"
    >
      ↶ 撤销
    </button>
    {undoMsg !== null && (
      <span className="max-w-[9rem] truncate text-xs text-vigil-fg-4">{undoMsg}</span>
    )}
    <ThemePicker value={theme} onChange={pickTheme} />
  </div>
  <nav className="mx-auto flex max-w-3xl gap-1 overflow-x-auto px-4 pb-2 pt-1 text-sm">
    {TABS.map((t) => (
      <button
        key={t.key}
        onClick={() => setTab(t.key)}
        className={
          'shrink-0 rounded-lg px-3 py-1.5 transition-colors ' +
          (tab === t.key
            ? 'bg-vigil-surface-2 text-vigil-fg'
            : 'text-vigil-fg-3 active:bg-vigil-surface')
        }
      >
        {t.label}
      </button>
    ))}
  </nav>
</header>
```
> ⚠️ **原有注释要保留**（`ml-auto` 为什么不挂在 nav 上）。`max-w-[9rem] truncate` 是给撤销
> 反馈的：它最长的一句是「没有可撤销的操作」，在 375px 上会与 🎨 抢位；截断而不是换行，
> 是为了让顶栏高度恒定。（T5 会把 `TABS`/`tab`/`setTab` 换成 `uiState` 的版本。）

**4) 验证与提交**

```bash
cd web && npm test && npm run build
```
- **375px 判据（⭐ 修前必红、修后必绿）**：在 375×667 下量**导航 tab 的盒子**——
  **每个 tab 按钮高 ≤ 40px**（= 标签只占一行）。**修前实测：按钮高 52px（两行）/ 宽 48px / 顶栏 77px**；
  修后应为 **32px 高（单行）**，宽度只会小幅回升（48 → 52）——**宽度只作参考，别用 56px 那条**（§0 E8-补：那是按错字号算的）。
  ⛔ **不许**用"没有控件被裁"当判据——修前就已满足，那是不会失败的判据。
  量法：`_smoke/m7-appearance-smoke.py`（页内探针已打 `minTabW`/`maxTabH`/`headerH`）。
- commit：`feat(web): 顶栏主题切换器 + 头部两行化（375px 下 tab 不再被挤成两行）`

---

## Task 5: 视图状态持久化（tab / kinds / persons）

**目标**：修掉 spec §1.5 点名的「刷新即重置」（`App.tsx:15-18`）。

**Interfaces**

- **Produces**（`web/src/uiState.ts`）：`type Tab`、`TABS`、`type View`、`DEFAULT_VIEW`、`VIEW_STORAGE_KEY = 'vigil.view'`、`readView()`、`writeView(v)`。
- **Consumes**：无（与主题**分两个 key**：清一个不该带上另一个）。

**Steps**

**1) 写两个失败测试**（先红）：

```ts
// web/src/__tests__/uiState.test.ts
import { afterEach, expect, test } from 'vitest'
import { DEFAULT_VIEW, VIEW_STORAGE_KEY, readView, writeView } from '../uiState.ts'

afterEach(() => localStorage.clear())

test('没存过 ⇒ 默认', () => {
  expect(readView()).toEqual(DEFAULT_VIEW)
})

test('存取一个完整视图', () => {
  writeView({ tab: 'digests', kinds: ['notice', 'life'], persons: [12345] })
  expect(readView()).toEqual({ tab: 'digests', kinds: ['notice', 'life'], persons: [12345] })
})

test('⚠️ 逐字段校验：坏的字段回落默认，好的字段保留', () => {
  // 一个坏字段（旧版本留下的 tab 名之类）不该毁掉整份记忆——
  // 那会让"记得我选的类目"这种小事变成"每次刷新都从头来"。
  localStorage.setItem(
    VIEW_STORAGE_KEY,
    JSON.stringify({ tab: 'gallery', kinds: ['notice', 42], persons: [1, -3, 'x'] }),
  )
  expect(readView()).toEqual({ tab: 'feed', kinds: ['notice'], persons: [1] })
})

test('垃圾 JSON / 非对象 ⇒ 默认，且不抛', () => {
  localStorage.setItem(VIEW_STORAGE_KEY, '{not json')
  expect(readView()).toEqual(DEFAULT_VIEW)
  localStorage.setItem(VIEW_STORAGE_KEY, '42')
  expect(readView()).toEqual(DEFAULT_VIEW)
})

test('kinds 去重、persons 去重', () => {
  localStorage.setItem(
    VIEW_STORAGE_KEY,
    JSON.stringify({ tab: 'feed', kinds: ['a', 'a'], persons: [7, 7, 8] }),
  )
  expect(readView().kinds).toEqual(['a'])
  expect(readView().persons).toEqual([7, 8])
})
```

```tsx
// web/src/__tests__/AppPersist.dom.test.tsx —— 端到端那一半：**重挂载**（= 刷新）后条件还在
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App.tsx'
import { VIEW_STORAGE_KEY } from '../uiState.ts'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

function installFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/items')) return ok({ items: [], total: 0, limit: 50, offset: 0 })
      return ok({})
    }),
  )
}

test('切到「日报」再重挂载 ⇒ 仍在日报（"刷新即重置"的守卫）', async () => {
  installFetch()
  const first = render(<App />)
  await userEvent.click(screen.getByRole('button', { name: '日报' }))
  // ⚠️ 变异反证：把初始化改回 `useState<Tab>('feed')` ⇒ 本条必红。
  expect(localStorage.getItem(VIEW_STORAGE_KEY)).toContain('digests')
  first.unmount()

  render(<App />)
  // ⚠️ 判据（"日报页首屏会渲染出哪一句话"）**按实测写**：实现者去看到底渲染了什么，
  // 不许猜；与计划不符就按实际改判据并在报告里说明（逃逸舱）。
  expect(await screen.findByText(/日报/)).toBeTruthy()
})

test('⚠️ 存了非法 tab ⇒ 回落 feed，不许白屏', async () => {
  installFetch()
  localStorage.setItem(
    VIEW_STORAGE_KEY,
    JSON.stringify({ tab: 'gallery', kinds: [], persons: [] }),
  )
  render(<App />)
  expect(await screen.findByText('还没有任何条目。', undefined, { timeout: 2000 })).toBeTruthy()
})
```

**2) 写 `web/src/uiState.ts`**：

```ts
/**
 * 视图状态（当前 tab + 类目/人物筛选）的持久化。
 *
 * 修掉 spec §1.5 点名的「刷新后 tab 与 kind 全部重置」。
 * ⚠️ 与主题分**两个 key**（`vigil.view` / `vigil.theme`）：清一个不该带上另一个。
 */
export type Tab = 'feed' | 'cats' | 'digests' | 'settings'

export const TABS: { key: Tab; label: string }[] = [
  { key: 'feed', label: '信息流' },
  { key: 'cats', label: '类目' },
  { key: 'digests', label: '日报' },
  { key: 'settings', label: '配置' },
]

export type View = { tab: Tab; kinds: string[]; persons: number[] }

export const VIEW_STORAGE_KEY = 'vigil.view'
export const DEFAULT_VIEW: View = { tab: 'feed', kinds: [], persons: [] }

const VALID_TABS = new Set<string>(TABS.map((t) => t.key))
const SLUG = /^[a-zA-Z0-9_-]{1,64}$/

/** 逐字段校验：坏字段回落默认，好字段保留（一个坏字段不该毁掉整份记忆）。 */
export function readView(): View {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(VIEW_STORAGE_KEY)
  } catch {
    return { ...DEFAULT_VIEW }
  }
  if (raw === null) return { ...DEFAULT_VIEW }
  let o: unknown
  try {
    o = JSON.parse(raw)
  } catch {
    return { ...DEFAULT_VIEW }
  }
  if (typeof o !== 'object' || o === null) return { ...DEFAULT_VIEW }
  const v = o as Record<string, unknown>
  const tab =
    typeof v.tab === 'string' && VALID_TABS.has(v.tab) ? (v.tab as Tab) : DEFAULT_VIEW.tab
  const kinds = Array.isArray(v.kinds)
    ? [...new Set(v.kinds.filter((k): k is string => typeof k === 'string' && SLUG.test(k)))]
    : []
  const persons = Array.isArray(v.persons)
    ? [
        ...new Set(
          v.persons.filter(
            (p): p is number => typeof p === 'number' && Number.isInteger(p) && p > 0,
          ),
        ),
      ]
    : []
  return { tab, kinds, persons }
}

export function writeView(v: View): void {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(v))
  } catch {
    // 存不下只影响"下次还记得"，不该让当前这次交互失败
  }
}
```

**3) `App.tsx` 改动**：`type Tab` 与 `TABS` 从 App **搬进** `uiState.ts`（App 改为 import）；三个 state 换成一份 `view`：

```tsx
import { readView, writeView, TABS, type Tab } from './uiState.ts'
// ...
const [view, setView] = useState(readView)
const [undoMsg, setUndoMsg] = useState<string | null>(null)
const [dataTick, setDataTick] = useState(0)

// 任何一处筛选变化都写回一次（一个 effect 收口，好过在每个 setter 里各写一遍）
useEffect(() => {
  writeView(view)
}, [view])

const { tab, kinds, persons } = view
const setTab = (t: Tab) => setView((v) => ({ ...v, tab: t }))
const setKinds = (k: string[]) => setView((v) => ({ ...v, kinds: k }))
const setPersons = (p: number[]) => setView((v) => ({ ...v, persons: p }))
```
> `Feed` 的 `kinds/onKinds/persons/onPersons` 与 `Categories` 的 `onPick` 契约**不变**
> （`setKinds([slug])` 的"替换而不是追加"语义要保留——见原注释）。

**4) 验证与提交**：`cd web && npm test && npm run build`；8787 上手动刷新一次，确认 tab 与筛选都还在。
commit：`fix(web): 视图状态落 localStorage——刷新不再重置 tab 与筛选`

---

## Task 6: PWA 更新链路（前端提示 + `/sw.js` no-cache）

**目标**：spec §4.3④ —— 补 `onNeedRefresh` 钩子 + 给 `/sw.js` 加 `Cache-Control: no-cache`。

**Interfaces**

- **Produces**（`web/src/swUpdate.ts`）：`markNeedRefresh(apply)`、`applyUpdate()`、`getNeedRefresh()`、`subscribe(fn)`、`_resetForTests()`。
- **Produces**（后端）：`spa()` 对 `sw.js` 发 `Cache-Control: no-cache`。
- **Consumes**：`virtual:pwa-register`（**只在 `main.tsx`**，见 E4）。

**Steps**

**1) 前端测试** `web/src/__tests__/swUpdate.test.tsx`（先红）：

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import SwUpdateToast from '../components/SwUpdateToast.tsx'
import { _resetForTests, markNeedRefresh } from '../swUpdate.ts'

afterEach(() => _resetForTests()) // ⚠️ 模块级状态必须逐用例清（M6 的 #27 就是漏了这个）

test('没有新版本 ⇒ 不出提示', () => {
  render(<SwUpdateToast />)
  expect(screen.queryByText(/有新版本/)).toBeNull()
})

test('先挂载后收到通知 ⇒ 提示出现（真实时序：页面开着，SW 才更新）', async () => {
  const apply = vi.fn()
  render(<SwUpdateToast />)
  markNeedRefresh(apply)
  expect(await screen.findByText(/有新版本/)).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: '立即刷新' }))
  expect(apply).toHaveBeenCalledTimes(1)
})

test('先收到通知后挂载 ⇒ 提示也在（顺序不该决定看不看得见）', () => {
  markNeedRefresh(() => {})
  render(<SwUpdateToast />)
  expect(screen.getByText(/有新版本/)).toBeTruthy()
})
```

**2) 写 `web/src/swUpdate.ts`**：

```ts
/**
 * 「有新版本」的信号源——**故意不 import `virtual:pwa-register`**。
 *
 * ⚠️ 实测（M7 计划期空针）：vitest 解析不了那个虚拟模块
 * （`TypeError: … file:///@vite-plugin-pwa/virtual:pwa-register/react`）。
 * ⇒ 能被测试的部分必须与它解耦：`main.tsx` 是**唯一**的接线点，
 * 而这个文件是可测的纯状态源。
 */
let needRefresh = false
let apply: (() => void) | null = null
const listeners = new Set<() => void>()

export function markNeedRefresh(fn: () => void): void {
  needRefresh = true
  apply = fn
  for (const l of listeners) l()
}

export function applyUpdate(): void {
  apply?.()
}

export function getNeedRefresh(): boolean {
  return needRefresh
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** 只有测试用：模块级状态会跨用例串（前一例标记过，后一例就看到提示）。 */
export function _resetForTests(): void {
  needRefresh = false
  apply = null
  listeners.clear()
}
```

**3) 写 `web/src/components/SwUpdateToast.tsx`**：

```tsx
import { useSyncExternalStore } from 'react'
import { applyUpdate, getNeedRefresh, subscribe } from '../swUpdate.ts'

/**
 * 「有新版本，立即刷新」提示条。
 *
 * ⚠️ 为什么不自动刷新：`registerType: 'autoUpdate'` 会让新 SW 立刻接管，
 * 但**正在跑的那份 bundle 不会换**——自动 reload 会在用户打字/勾选的中途
 * 把页面抽走（本应用有表单与多选框）。所以是"提示 + 一次点击"。
 */
export default function SwUpdateToast() {
  const need = useSyncExternalStore(subscribe, getNeedRefresh)
  if (!need) return null
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-4 z-40 mx-auto flex max-w-sm items-center gap-3 rounded-lg border border-vigil-border bg-vigil-surface-solid px-4 py-2 text-sm shadow-vigil-card"
    >
      <span className="text-vigil-fg-2">有新版本</span>
      <button
        onClick={applyUpdate}
        className="ml-auto rounded-lg bg-vigil-accent-soft px-3 py-1 text-vigil-accent-text"
      >
        立即刷新
      </button>
    </div>
  )
}
```

**4) `web/src/main.tsx`**（完整文件，替换 T1 那一版）：

```tsx
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
```

**5) 后端：`vigil/api.py` 的 `spa()`**（只动"返回真文件"那一支）：

```python
            if candidate.is_relative_to(dist_root) and candidate.is_file():
                # ⚠️ `/sw.js` 必须 `no-cache`（出口判据 3 的机械半边）：
                # Service Worker 脚本是「有新版本」唯一的发现入口，而浏览器对它走
                # **启发式缓存**（本仓此前 `Cache-Control` 零命中——计划期 grep 只命中
                # `.venv/` 里的 starlette）。被推迟的更新检查，在手机上表现为
                # 「我改了主题怎么没变」。
                #
                # ⛔ 其余静态资源**不许**跟着加：它们的正确语义是「内容哈希 + 长缓存」，
                # 顺手加 no-cache 是把一个文件的更新语义扩成全部资源的（阴性对照钉着）。
                return FileResponse(
                    candidate,
                    media_type=_MIME.get(candidate.suffix.lower()),
                    headers={"Cache-Control": "no-cache"} if candidate.name == "sw.js" else None,
                )
```

**6) 后端测试**（追加到 `tests/test_api.py` 里那三个静态托管用例旁边）：

```python
def test_sw_js_is_served_with_no_cache(client, tmp_path, monkeypatch):
    """⭐ 出口判据 3（新版本部署后无需手动清缓存）的机械半边。

    Service Worker 脚本是「有新版本」唯一的发现入口，而它此前**没有任何
    Cache-Control**（计划期实测：全仓 `grep -rn Cache-Control` 只命中 `.venv/`）
    ⇒ 浏览器走启发式缓存 ⇒ 更新检查被推迟 ⇒ 手机上表现为「我改了主题怎么没变」。

    阴性对照（本条一半的价值在这里）：别的静态资源**不许**被顺手加上 no-cache。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "sw.js").write_text("self.define = 1", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("1", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.text == "self.define = 1"  # 仍然发真文件（不是 index.html）
    assert r.headers["cache-control"] == "no-cache"

    r2 = client.get("/assets/index-abc123.js")
    assert r2.status_code == 200
    assert "no-cache" not in r2.headers.get("cache-control", "")
```

**7) 验证与提交**

```bash
cd web && npm test && npm run build
grep -c "vite-plugin-pwa:register-sw" web/dist/index.html   # 期望 0（不再二次注册）
cd .. && uv run pytest tests/test_api.py && uv run pytest
```
- commit：`feat(pwa,web): 补 onNeedRefresh 提示 + /sw.js no-cache（更新不必再清缓存）`

---

## 5. Spec 覆盖对照表

| spec 条目 | 落在哪个任务 |
|---|---|
| §4.3① 语义化（含「不在 CSS 里的 3 处」） | T1（token 层 + `theme-color` 同步）、T2（227 处）；`index.html` meta = T1；manifest `background_color`/`theme_color` = **明确不改**（静态文件只能有一个值；保留默认主题的 `#0b0f14`，理由写进 T1 的报告） |
| §4.3② 五套主题 | T1（机制）、T3（结构/调色/页面资产） |
| §4.3③ 持久化 + 顺路修「刷新即重置」 | T1（主题）+ T5（tab/筛选） |
| §4.3④ `onNeedRefresh` + `/sw.js` no-cache | T6 |
| §5 判据 1（人眼验收） | 冒烟 5 张截图 → 用户判定 → 可能的调色 fix 轮 |
| §5 判据 2 / 3 / 4 | T1+T5（判据 2）、T6 + 冒烟（判据 3）、T2+T3 的四条守卫（判据 4） |
| §1.5「浅色主题会打穿 `bg-black/30`」 | E6：那 12 处是**输入框底**（不是遮罩）⇒ `--v-inset` |

## 6. 逃逸舱（每个 implementer 都读这一段）

- 断言数字/顺序/措辞与实现不符 ⇒ **按实际修正并报告**（报告是审查输入），不必请示。
- **若需求自相矛盾或无法同时满足 ⇒ 停下报告，不许挑一半照做。**
- 计划里的**行号**按 BASE `8c3a0d3` 数；T2 的 codemod 改完之后行号会漂 ⇒ 以"文件 + 类名/函数"定位为准。
- 任何"我顺手也修了"的改动 ⇒ 先报告再动（M6 的边界纪律）。

## 7. 不做（明确排除，避免范围蔓延）

| 项 | 为什么不做 |
|---|---|
| 主题的自定义色板编辑器 | spec §7 已排除（五套预设够用） |
| 网络字体（含 CJK webfont） | 离线 PWA + 体积 + 无 CDN 依赖；美术靠渐变/辉光/网格/阴影 |
| 主题切换的过渡动画 | 低频动作；加了要处理 `prefers-reduced-motion`，收益不抵 |
| manifest 的 `background_color`/`theme_color` 跟随主题 | 静态文件只能有一个值；启动画面用默认主题色 |
| M6 的 F4–F7 / 5 条「留下一里程碑」/ 两条 ⚠️ 残余 | 用户 2026-09-22 裁定**不进 M7** |
| `docs/digests/*.md`、`data/`、`config/*.toml` | 08:00 管线与运行中的服务会改它们，与 M7 无关 |
| 行尾统一（19 个 `w/lf` + 3 个 `w/crlf`） | 见 G5：blob 全是 `i/lf`，git 侧无差异；顺手统一只会污染 diff |

## 8. 冒烟预案（阶段④，由 controller 执行）

1. `cd web && npm run build`（8787 上的自启服务**直接托管 dist** ⇒ 构建完线上就是新的，无发布步骤）。
2. Playwright 在 **1440×900 与 375×667** 两个尺寸下、对 `?theme=default|material|brutalism|vaporwave|glass` 各截图 → 10 张，交用户验收。
   ⚠️ **`?theme=` 覆盖当前还没实现**——它是 T4 的可选加项（约 5 行：URL 参数优先于 localStorage，且**不落盘**）。
   实现者按 Escape hatch 处理：**加了就在报告里说明并补一条用例；不加就报告"冒烟改用点击切换"**。
3. 机械检查（同一次会话里跑）：
   - ⚠️ **先记构建指纹**（仪器校准实测的缺口：dist 会在跑的过程中被外部重建，
     不记指纹的话两遍读数不是同一个构建，而报告看不出来）：`/index.html` 与 `/sw.js`
     的 sha256 + `/assets/*` 名单 + `git rev-parse HEAD` + `git status --porcelain` 条数，
     一起进 `report.json`；
   - 每套主题页面**非空白**（元素数 > 20、`document.body.innerText.length > 50`）；
   - 375px 下**不被挤扁**：导航每个 tab 宽 ≥ 56px、标签只占一行（修前 48px / 两行，见 §0 E8）。
     ⛔ 不用 `scrollWidth <= innerWidth`：`html{overflow-x:hidden}` 会把它夹到视口宽，**量不到**；
   - material 主题下**没有**亮度 < 0.15 的大面积背景（深色残留的像素级复核）；
   - 五套首屏截图**两两不同**（dHash 距离 > 4）——防"切了没变"。
4. PWA 更新：改一处可见文案 → `npm run build` → 已开着的标签页应在 ≤ 一轮内出现「有新版本」提示（真浏览器 + 真 SW）。
5. 用户人眼验收五套（判据 1）；某套不满意 ⇒ 一次**只改 `index.css`** 的 fix 轮 + 重截该套。
