# VIGIL 进度接力 — **M5 已完成并推送，M6 待规划**

> **钩子：新会话先读本文件。** 然后按需读下面两个（**顺序别反**）：
> 1. **spec**：`docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md`（M5–M7 设计，七条裁定 D10–D16）
>    —— **它的 §4.2 就是 M6 的范围**
> 2. **M5 计划**：`docs/superpowers/plans/2026-09-16-vigil-m5-correctness.md`
>    —— ⚠️ **它有 `## ⚠️ 执行期勘误` 一节（E1–E11），读计划正文前先读它**
>
> ⚠️ **第一版 spec（`2026-09-13-…-design.md`）只覆盖 M1–M4，已冻结。**
>
> 最后更新：2026-09-17 深夜　｜　仓库：`https://github.com/f25h-233/vigil`（private）
> **HEAD `6ce3941` 已推 origin/master**

---

## 一、一句话

**M5「items 的正确性与可筛选性」已完成并推送**（10 个任务 / 32 笔提交 / 后端 **605 passed** + 前端 **22 passed**）。
**下次会话要做的是 M6「配置从文件走到界面」的规划**——**不是重做 M5**。

---

## 二、当前工作区状态（**只放关系式，不放会漂的计数**）

> ⚠️ **每日管线每天 08:00 自己跑**，`messages`/`items`/`digests` **每天自己涨**。
> **本文件刻意不写计数**——M4 收尾踩过一次（写完 40 分钟就过期），**M5 期间又踩了一次**
> （T9 干跑跑到一半，08:00 管线把真库从 328 条变成 333 条，清单当场作废）。
> 要用就现查：`uv run vigil ...` 或 `sqlite3 file:data/vigil.db?mode=ro`。

```
HEAD          6ce3941（已推 origin/master）
测试          uv run pytest（**不加 -q**）→ 605 passed
              cd web && npm test → 22 passed；npm run build → 改前端必跑
任务计划       VIGIL每日管线 · 每日 08:00（`schtasks /query /tn "VIGIL每日管线" /v /fo LIST`）

不随时间漂的关系式：
  ① 归档不变量：docs/digests/ 的文件集合 == 库里 digests 的窗口日期集合，且**逐字节相等**
     （`.gitattributes` 给 docs/digests/*.md 定了 text eol=lf —— 对 git 免疫）
  ② Web 侧不写 data/vigil.db（D11）。**M5 已把它精确化**为「可写 config/ 与 data/overrides.db」
     **且有机械守卫**（三个写端点的主库指纹断言，含 -wal/-shm）
  ③ `items` 的可见集合 = 库里的行 − overlay 里软删的
  ④ **出口判据 3**：`deadline_ts < event_ts` 的条目 = **0**（M5 已清）
```

---

## 三、⏭ 现在该做什么

**M5 已经收口。下一步是 M6 的规划**（`/SDD` 从阶段① 写计划开始）。

M6 之前**先读** `docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md` 的 **§4.2**（M6 范围）
与 **§1.6**（**那个必须在计划期就处理的雷**）。

**M5 留下的、M6 必须接手的（按重要性）**：

1. ⭐ **U-4 与 `#3 加群` 同批解决**（spec §1.6 实测）：
   `vigil groups` 列群列表靠 `qqdb.strip_fake_header(...)`，它**就地截断重写 `data/cache/nt_msg_clear.db`**
   ——**与 `export` 共用同一个文件**。Web 端点直接复用 ⇒ ① 从后门打破「Web 不写 `data/`」
   ② 与正在跑的 `export` 抢文件，最坏后果是**部分消息静默消失、还被报告成「QQ 库物理坏页」**。
   **裁定：群列表必须走只读路径，且必须与 U-4 同批解决。**
2. **最终审查判「留下一里程碑」的 20 条 deferred**（清单在
   `.superpowers/sdd/2026-09-16-vigil-m5-correctness/deferred-minors.md`，**git-ignored 本地文件**）
3. ⚠️ **T10 的 DOM 测试缺口**：它在浏览器里抓到的两个缺陷（`onMutated={retry}` 导致删了还在、
   `undo()` 不通知重取）**修好了但零测试保护**。要钉住需新增 `@testing-library/react` + `jsdom`
   （已核实**确实不在依赖里**）。
4. ⚠️ **`refine.py` 的 F1**（冒烟发现）：整窗消息全被墓碑时，「跳过重抽（D15 墓碑）」那行排在
   `if not messages: return` **之后** ⇒ **日志与「窗口本来就空」同形**。
5. ⚠️ **`v3` 的生产误杀率从未测过**（归档文档 §5 有记）。

---

## 四、M5 交付了什么 / 出口判据现状（**如实标注，别粉饰**）

| # | 出口判据 | 状态 |
|---|---|---|
| 1 | 噪声：「生活」类目卡类 34% → <5% | 🛑 **用户裁定归档**（不再用 LLM 判据批量清噪声） |
| 2 | 误杀为零（5 条探针存活） | 🛑 **同上归档**（实测独立探针只 1/2 存活） |
| 3 | 无倒挂死线 | ✅ **0 条**（`vigil downgrade` 清掉了 item 83） |
| 4 | 人物筛选（并集 / 交集） | ✅ 冒烟 PASS（复选 2 人 = 35 = 并集；叠加类目收窄） |
| 5 | 幂等（重判跑两次不重复增长） | ⚪ **随 `--apply` 一起归档**——**既没通过也没失败，是没有对象** |
| 6 | 人工干预层 + `vigil.db` 全程 `mode=ro` | ✅ 冒烟 PASS（**真出网重跑日报**验「两处都变」；`--redo` 不复活；三次 Web 写的指纹逐字节相同） |

**十个任务**：T1 prompt v3｜T2 两道要素闸门｜T3 批内去重｜T4 人工干预层｜T5 overlay 接 5 处读路径｜
T6 refine 读墓碑｜T7 persons.toml｜T8 API 多值筛选 + 写端点｜T9 `vigil repass`｜T10 前端。

**🛑 噪声过滤线的完整归档**（为什么停 / 实测数字 / 留下了什么 / 未测缺口）：
**`docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md`** ← **涉及噪声/广告的任何问题先读它**。

---

## 五、M5 之后（M6 / M7 的范围，别再问用户）

用户 2026-09-16 已裁定拆三个里程碑：**M5 正确性 → M6 配置 → M7 外观**。

**M6「配置从文件走到界面」**：统一配置层 + 导入导出（#6）、LLM 配置（#5）、群号管理（#3）、
**类目编辑 + 撤销 + 重排**（用户追加）、U-4 遗留。详见 spec §4.2。

**M7「外观」**：五套主题（默认 / material design / 粗野主义 / 蒸汽波 / 毛玻璃）。

---

## 六、⭐ M5 实测推翻/确立的关键事实（**别再凭印象重来，也别重测**）

| # | 事实 |
|---|---|
| 1 | ⛔ **「屏蔽办卡号」实测否决**（D13）：那 4 个号是**真学生**，贡献 15 条好条目，**误杀率 1:2**。**在 QQ 里屏蔽 = 同一件事、同一筹码** |
| 2 | ⭐ **prompt v3 的探针有一半是受污染的**：item 86/111/143 的源文被**逐字写进了 prompt** ⇒ 它们存活**不构成证据**。真独立的是 **183（主）/ 182（次）** |
| 3 | ⭐ **「重判」可能根本不是重判**：`repass` 在稀疏集上建批（中位 **1** 条）而 `refine` 在密批（中位 **30**）⇒ 修上下文后删除量 **174 → 100**、探针复活两条 |
| 4 | ⭐ **「整批返回空」≠「逐条判死」**：39 个空批的**候选条数中位 8**，与非空批一样多 ⇒ **批次级失灵** |
| 5 | **判决有 10% 量级噪声**（无 seed、temperature 0.1）：同批逐字节重放 3 次，**10% 条目翻转** |
| 6 | **行尾唯一可信量具是 `git ls-files --eol`**。⛔ `grep -c $'\r$'` 是**静默假阴性**（对全 CRLF 文件返回 0）；⛔ `od -c \| grep -c '\r'` 也不可靠 |
| 7 | **`ATTACH 'file:…?mode=ro'` 只在连接带 `uri=True` 时被解析**；四条生产连接现已全带 |
| 8 | **`mode=ro` 连接无法把库转成 WAL** ⇒ **WAL 必须在建库时设** |

---

## 七、怎么跑 / 怎么重启

```bash
cd D:/github/VIGIL && uv run vigil serve --host 127.0.0.1 --port 8787   # 后端 + 前端静态托管
tailscale serve --bg 8787                                               # 手机 HTTPS 入口

uv run vigil daily          # 手动跑一次完整管线（任务计划跑的是 scripts/vigil-daily.cmd）
uv run vigil downgrade      # 字段降级（默认 --fields deadline；**加 --apply 才写**）
uv run vigil repass         # 存量重判（**只出清单**；⚠️ --apply 已被用户裁定永久不执行）
cd web && npm run build     # ⚠️ 前端改完**必须构建**，serve 托管的是 web/dist
```

**Tailscale 的坑**：`tailscale serve --bg 8787` 会**静默挂死 90 秒**（等证书）。
解法：<https://login.tailscale.com/admin/dns> → HTTPS Certificates → Enable（**已开启**）。

**⚠️ 任务计划的两个坑**：① `schtasks /change … /st` 会弹密码提示并挂死；
用 `Set-ScheduledTask -Trigger` 且 **`StartBoundary` 必须设未来时间**。
② **含中文的 `.ps1` 必须 UTF-8 BOM**（无 BOM 时任务名被**静默**注册成乱码）。

---

## 八、关键文件地图

| 路径 | 内容 |
|---|---|
| **`docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md`** | **噪声过滤线归档（实测数字 / 为什么停 / 未测缺口）** |
| `docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md` | M5–M7 设计（D10–D16）。**§4.2 = M6 范围，§1.6 = M6 的雷** |
| `docs/superpowers/plans/2026-09-16-vigil-m5-correctness.md` | M5 计划（**含 `## ⚠️ 执行期勘误` E1–E11**） |
| `.superpowers/sdd/2026-09-16-vigil-m5-correctness/` | M5 的 ledger / brief / 报告 / 终审 / 冒烟（**git-ignored 本地过程记忆**） |
| `vigil/overrides.py` | **人工干预层**（D14）：append-only 事件日志 + 物化 `item_state`；`attach_readonly` / `deleted_msg_ids` / `undo` / `delete_item` |
| `vigil/store.py` | **overlay 的 apply 收敛在这里**（5 处读路径 + `_ensure_overlay`）；批内去重 `dedupe_batch` |
| `vigil/refine.py` | prompt v3；两道要素闸门；**读 overlay 墓碑**（D15） |
| `vigil/repass.py` | 存量重判（**只出清单**）；`data/repass-audit-*.jsonl` 可**离线重建清单，零模型成本** |
| `vigil/deadline.py` | `deadline_supported` / `deadline_sane` / `place_supported` |
| `vigil/api.py` | 多值筛选（`?kind=` 多值、`?person=`）；三个写端点；**409/400 语义** |
| `tests/test_overlay_e2e.py` | **唯一能钉住 R13 的机械守卫**（Web 四端点 + 日报，含**阴性对照**） |
| `.gitattributes` | `docs/digests/*.md text eol=lf` —— 归档不变量的免疫层 |

---

## 九、未尽事项

- §三 的 5 条（U-4 / 20 条 deferred / DOM 测试缺口 / F1 / v3 生产误杀率未测）
- ⚠️ **延迟清单里的两条"环境陷阱"**（M5 终审报的）：
  - **`-shm` 不该进 D11 哈希断言**——读写连接开-关且为最后一条时 `-wal`/`-shm` 双双变 `<missing>` ⇒ **假红**
  - **`monkeypatch.undo()` 会静默拆掉 `tests/conftest.py` 的 autouse 隔离补丁**
    ⇒ 实测**往真 `data/overrides.db` 写了 9 条事件且无断言变红**
- `.superpowers/` 与 `_smoke/` 均**不入库**，是本地过程记忆
- `/tmp` 下累积了 M1–M5 的过程产物（数百 MB）；**C 盘紧张时值得清**，
  但**删之前先确认不是某个在跑的实验的输入**
- ⚠️ `data/` 下有一条 **80 MB 的 `vigil.db.bak-before-downgrade-20260917-181505`**
  与若干 M4 时期的备份；**M5 期间又新增 `bak-m5-smoke-*`**，值得清一清

---

## 十、方法论沉淀（**M5 新增，值得单独记**）

M1–M4 的完整教训在记忆 `vigil-sdd-lessons`。**M5 十个任务最值钱的一条**：

> ⭐ **「反着再问一句」十一战十一中。**
> 每个任务做完变异反证后，追问一句「**有没有哪条约束是变异全红但根本没被测到**的？」
> ——**每个任务都捞到了东西**（T2 抓 1 / T3 抓 3 / T4 抓 6 / T5 抓 3 / T6 抓 4 / T7 抓 4 / T8 抓 4 / T9 抓 2 / T10 抓 2…）。
>
> 最典型的三条：
> - **T9**：一个**专门验证「没写过主库」的守卫**，因为测试用了**只读连接**，**那条断言永远不可能被考验**
> - **T4**：`exists` 语义的测试**第一版没有牙齿**（兄弟条目没真引用那条 msg ⇒ 两种语义**答案相同**）
> - **T10**：brief 说「`tsc -b` 是 `types.ts` 的机械守卫」——**删掉字段后 `tsc -b` 仍 exit 0**

**另外两条 M5 才付学费学会的**：

1. **假红比假绿更难察觉**——一个写得不好的变异体会造出**假红**（实测：漏掉替换串里的 `ORDER BY`
   ⇒ 39 条红**全是 `no such column` 崩溃**，白追一轮）。**「变红了」看起来就是成功**，
   所以**变异体本身正确必须先被验证**；取函数原文要**程序化地从 git 取**。
2. **「可达性」有保质期**——T8 审查判过「非尾部 undo 今天不可达」，
   **T10 的前端一接上就可达了**。判「不可达」时，那个判断**只对当时那棵树成立**。
