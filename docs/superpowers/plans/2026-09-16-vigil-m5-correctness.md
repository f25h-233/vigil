# VIGIL M5「items 的正确性与可筛选性」实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `items` 表里的东西**是对的**（噪声判据落地、要素有闸门、批内不重复），并且**是可控的**（人工干预层：改分类 / 删条目 / 撤销；按人物与多类目筛选）。

**Architecture:** 三块互相咬合但边界清楚。① **抽取层**加判据（prompt v3 + 两道要素闸门 + 批内去重）；② **人工干预层**——新增 `data/overrides.db`，append-only 的编辑事件表，`data/vigil.db` **保持 `mode=ro` 不受任何影响**；③ **读取层**把 overlay 的 apply **收敛在 `store.py` 的查询函数里**（不在各消费方打补丁，理由见 spec §3.3），再往上加多值筛选与写端点。

**Tech Stack:** Python 3.13 / sqlite3（标准库）/ FastAPI / pytest；前端 React 19 + Vite 8 + Tailwind v4 + vitest。

**Spec:** `docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md`（**本计划按它写，执行者要读它**）

---

## Global Constraints

以下为项目级硬约束，**每个任务都隐含包含本节**。

1. **`data/vigil.db` 只读不变。** Web 侧（`vigil/api.py`）**绝不允许**写它——连接一律 `mode=ro`。
   人工干预只写 `data/overrides.db`（本计划新建）与 `config/*.toml`。**这是 D11 的机械保证，有测试守卫。**
2. **`data/vigil.db` 里 `items` 表的写入只允许来自 `refine.py` / `digest.py` 的既有路径**，
   以及本计划新增的**存量重判命令**（CLI，持单实例锁）。
3. **写 `config/*.toml` 必须原子**：写同目录临时文件 → `flush` + `os.fsync` → `os.replace`。
   **不许** `open(path, "w")` 直接截断（中途失败会留下半个文件）。
4. **行尾**：`core.autocrlf=true` + `* text=auto` ⇒ **工作区所有源码是 CRLF**。
   任何**文本替换式**操作（尤其是变异反证脚本）必须显式处理 CRLF——**M4 终审实测过
   「在 CRLF 文本里做替换 ⇒ 四条全『符合预期』」这个假绿形态**。
   纪律：隔离副本一律用 `git -c core.autocrlf=false -c core.eol=lf archive` 产出；
   变异脚本读文件用 `newline=""`，替换串里的换行写 `\r\n`，**且替换后必须先断言替换生效**
   （断言锚点命中数 ≥1），再跑测试。
5. **改 prompt 必须同步 `PROMPT_VERSION`**（`refine.py`），否则 `refine_runs` 里新老提示词的产出混在一起。
   **注意 `digest.py` 有另一个独立的 `PROMPT_VERSION`，两者不同源，别改错文件。**
6. **新增要素字段的硬判据**：语义归 prompt、格式/证据/时序归 code。
   **没有 code 层证据闸门的要素字段不算做完。**
7. **`items` 表的 item_id 不许翻新**（D16）。人工干预与重排**一律走 overlay 的 `set_kind` 事件**，
   不做 `DELETE` + `INSERT`。唯一的例外是存量重判里的「判为推广 → 删该 item」，且删之前
   必须确认它不被 `digest_items` 引用。
8. **测试不许碰真实全局资源**（`data/vigil.lock` 已有 autouse 夹具，**`data/overrides.db` 同样要有**）。
9. 测试环境：`uv run pytest`（仓库根目录）。前端：`cd web && npm test`。
10. **逃逸舱（两种形状，都必须遵守）**：
    - 若本计划描述与实际**代码**不符 → **按实际修正并在报告里写明偏差**，无需请示。
    - 若本计划**需求自相矛盾或无法同时满足** → **停下，报告，不许挑一半照做**。
      （把它当**高质量行为**上报，不是偏差——你是在替 controller 挡一个他自己看不见的洞。）

---

## File Structure

| 文件 | 状态 | 职责 |
|---|---|---|
| `vigil/refine.py` | 改 | prompt v3；两道要素闸门接进 `_to_item`；批内去重调用；读 overlay 跳过墓碑 |
| `vigil/deadline.py` | 改 | 加 `place_supported()`；加 `deadline_sane()`（时序闸门） |
| `vigil/store.py` | 改 | 批内去重；overlay 接入查询层（5 处读路径）；多值筛选 |
| `vigil/overrides.py` | **新** | 人工干预层：`data/overrides.db` 的建表、追加事件、折叠有效值、撤销 |
| `vigil/config.py` | 改 | `persons.toml` 的加载与原子保存；`Placeholder` → 见 Task 7 |
| `config/persons.toml` | **新** | 监视人物名单（`uin` 主键） |
| `vigil/api.py` | 改 | 多值 `kind`、`actor_uin`；三个写端点（改分类/删除/撤销） |
| `vigil/cli.py` | 改 | 新命令 `vigil repass`（存量重判）；`person` 子命令 |
| `vigil/repass.py` | **新** | 存量重判的编排（只删不换 + 降级闸门字段） |
| 前端 `web/src/**` | 改 | 多选筛选、人物筛选、改分类/删除/撤销 UI |
| `tests/test_overrides.py` | **新** | 人工干预层 |
| `tests/test_repass.py` | **新** | 存量重判 |
| `tests/test_config.py` | 改/新 | persons.toml |
| 其余 `tests/*.py` | 改 | 各任务自己的回归 |

---

## Task 1: prompt v3 —— 商业推广判据

**为什么**：spec §1.1 实测——328 条 items 里 46 条（**14.0%**）来自办卡号，spec §4.3 本就要求广告不入库。
预筛拦不住（保留关键词表里有「办理」，单条广告被"保送"），prompt 里也**一个字没提商业推广**。

**⚠️ 判据必须是"消息目的"而不是"出现了什么词"**——spec §1.2 实测：那 4 个号是真学生，
还贡献了 15 条好条目（早自习时间 / 住宿费 / 诈骗提醒 / 抢课通知）。**按 uid 或按关键词屏蔽误杀率 1:2。**

**Files:**
- Modify: `vigil/refine.py:30`（`PROMPT_VERSION`）、`vigil/refine.py:75-82`（丢弃规则）
- Test: `tests/test_refine.py`

**Interfaces:**
- Consumes: 无
- Produces: `refine.PROMPT_VERSION == "v3"`（Task 9 的存量重判按它筛 `refine_runs`）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_refine.py` 末尾：

```python
# ── Task 1：prompt v3 的商业推广判据 ──────────────────────────────


def test_prompt_version_is_v3():
    """版本号必须跟着提示词一起走。

    ⚠️ 这个断言是**回归锁**，不是行为测试——它只证明"文案改了、版本也改了"。
    真正的行为测试在 M5 出口判据 2（5 条已知好条目重抽后必须仍在），
    以及 `tests/test_repass.py` 的误杀守卫。**别把它当成"规则生效了"的证据。**
    """
    assert refine.PROMPT_VERSION == "v3"


def test_system_prompt_discards_commercial_promo():
    """prompt 里必须有商业推广的丢弃规则，且必须写明「看目的不看词」。"""
    from vigil.categories import load_categories

    prompt = refine.build_system_prompt(load_categories())
    assert "商业推广" in prompt
    # 反例必须出现在 prompt 里：它们正是 D13 判据的由来（实测误杀样本）
    assert "打电话办卡的都别信" in prompt
    assert "最早9.5" in prompt
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_refine.py -k "promo or version_is_v3" -v`
Expected: **2 failed** —— `assert 'v2' == 'v3'`、`AssertionError: '商业推广' not in prompt`

- [ ] **Step 3: 改 `PROMPT_VERSION`**

`vigil/refine.py:30`：

```python
PROMPT_VERSION = "v3"
```

- [ ] **Step 4: 在 prompt 的丢弃规则里加一条**

`vigil/refine.py` 的 `build_system_prompt`，在 `* 同学间的感慨、吐槽、附和` **之后**追加一段
（注意：它仍在那个 f-string 里，`{}` 需要转义成 `{{}}`——本段没有花括号，直接加）：

```
* **商业推广 / 代理招募 / 办卡广告**——流量卡、校园卡、宽带、电话卡的办理与
  代理招募、开卡返现、找人办卡、转让卡位等**以推销或拉客为目的**的消息。
  ⚠️ 判据看**这条消息想干什么**，不看它出现了哪个词。同样出现「校园卡」：
  「校园卡办理，需要的联系我」= 推广，丢掉；
  「打电话办卡的都别信哦所有人」= 提醒，「最早9.5」= 信息，
  「住宿费也统一扣1500」= 通知——**这三条都要照常产出**。
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_refine.py -k "promo or version_is_v3" -v`
Expected: **2 passed**

- [ ] **Step 6: 跑全量，确认没有别的东西被这条改动撞坏**

Run: `uv run pytest -q`
Expected: 全部通过。**若有别的测试钉了 `"v2"` 字面量，一并更新它**
（`grep -rn '"v2"' tests/ vigil/` 先查一遍）。

- [ ] **Step 7: Commit**

```bash
git add vigil/refine.py tests/test_refine.py
git commit -m "feat(refine): prompt v3 加商业推广判据——看消息目的不看词（D13）"
```

---

## Task 2: 两道要素闸门（`place` 证据 + `deadline` 时序）

**为什么**：spec §1.3 实测两处缺口。`deadline` 已有 `deadline_supported` 证据闸门，
但**不核时序**——item 83 的 `deadline_ts=2026-05-06` 早于 `event_ts=2026-08-05` 91 天，
一条已过期三个月的「⏰ 别忘」。`place` 则是**零校验**。

**⚠️ 闸门严格度是实测定的，不是拍的**（下表两条口径都真跑过）：

| `place` 口径 | 结果 |
|---|---|
| 整串逐字命中 / 片段命中 | 清掉 11/66，**其中 item 40 是误杀**（源文 `西太湖连隔板` 里有「西太湖」） |
| **任一 2 字子串命中源文**（采用） | 保留 58 / 清掉 8 |

清掉的 8 条逐条看过，**每一条都公道**：item 249 `立德楼1阶` ← 源文 `周六下午4.00-8.00`（真幻觉）、
item 271 `8号楼超市、2号楼超市` ← `常大方格纸在哪买`、item 283 `四号楼` ← `出护手霜`、
item 9/133/242 `西太湖(校区)` ← 源文里根本没有地点。

**⚠️ 但必须给「单字 place」留一条分支**：item 295 的 `place` 是 `湖`（1 字），
**bigram 对它不适用**（空集），按上面的规则会被误清。这是 M2 记过的
「多分支判据必须多分支守卫」。**规范化后短于 2 字的 place → 判据不适用 → 保留。**

**Files:**
- Modify: `vigil/deadline.py`（加两个纯函数）、`vigil/refine.py:296-309`（`_to_item`）
- Test: `tests/test_deadline.py`、`tests/test_refine.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `deadline.place_supported(place: str | None, sources: str) -> bool`
  - `deadline.deadline_sane(deadline_ts: int | None, event_ts: int) -> bool`

- [ ] **Step 1: 写失败测试（纯函数层）**

追加到 `tests/test_deadline.py`：

```python
# ── Task 2：place 证据闸门 ────────────────────────────────────────

import datetime as _dt

from vigil.deadline import deadline_sane, place_supported


def _ts(y, m, d, h=12):
    return int(_dt.datetime(y, m, d, h).timestamp())


def test_place_supported_by_literal_substring():
    assert place_supported("西太湖校区", "西太湖连隔板") is True


def test_place_supported_by_bigram_overlap():
    """源文只有「西太湖」，place 是「西太湖校区」——2 字子串命中即算有依据。"""
    assert place_supported("科教城宿舍", "科教城的同学宿舍没有校园网") is True


def test_place_without_evidence_is_unsupported():
    """item 249 的真实形状：源文只有时间，没有任何地点。"""
    assert place_supported("立德楼1阶", "周六下午4.00-8.00") is False


def test_place_shorter_than_2_chars_is_not_judged():
    """⚠️ 单字 place（真实数据 item 295 的 `湖`）判据**不适用**——bigram 是空集。

    这是「多分支判据必须多分支守卫」的落点：若把这条分支写成 return False，
    它就会把「湖」误清，而**没有任何测试会因此变红**。
    """
    assert place_supported("湖", "湖收磁吸灯或者小台灯") is True


def test_place_none_is_not_judged():
    """没有 place 就没有可核验的东西——返回 True（不构成"无依据"）。"""
    assert place_supported(None, "任意源文") is True
    assert place_supported("", "任意源文") is True


def test_place_ignores_separators_and_whitespace():
    """place 用了顿号/空格分隔（真实数据 item 271 的形状）。"""
    assert place_supported("8号楼超市、2号楼超市", "8号楼超市今天上新") is True


# ── Task 2：deadline 时序闸门 ─────────────────────────────────────


def test_deadline_before_message_day_is_insane():
    """item 83 的真实形状：死线比消息早 91 天。"""
    assert deadline_sane(_ts(2026, 5, 6), _ts(2026, 8, 5)) is False


def test_deadline_same_day_is_sane():
    """同一天不过夜——不判死（当天截止是常见的真实情况）。"""
    assert deadline_sane(_ts(2026, 9, 16, 8), _ts(2026, 9, 16, 23)) is True


def test_deadline_after_message_is_sane():
    assert deadline_sane(_ts(2026, 9, 20), _ts(2026, 9, 16)) is True


def test_deadline_none_is_sane():
    assert deadline_sane(None, _ts(2026, 9, 16)) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_deadline.py -v -k "place or sane"`
Expected: **ImportError: cannot import name 'place_supported'**（整文件 collection error 也算失败，
**但要确认失败原因就是它**——不是别的语法错）

- [ ] **Step 3: 实现两个纯函数**

追加到 `vigil/deadline.py` 末尾：

```python
def _bigrams(text: str) -> frozenset[str]:
    """去掉分隔符与空白后的全部 2 字子串。

    分隔符按实测数据里真出现过的集合取（item 271 用顿号、item 137 用全角竖线）。
    """
    cleaned = _PLACE_SEP.sub("", text)
    return frozenset(cleaned[i : i + 2] for i in range(len(cleaned) - 1))


_PLACE_SEP = re.compile(r"[\s、,，/｜|·]+")


def place_supported(place: str | None, sources: str) -> bool:
    """源文里能不能找到这个地点的依据。

    ⚠️ **判据刻意做得宽**（任一 2 字子串命中即算有依据），因为 place 与 deadline
    的性质不同：deadline 驱动「⏰ 别忘」，错了会让人误事；place 只是显示提示。
    实测：整串匹配太严会误杀「西太湖校区 ← 源文『西太湖连隔板』」这类。

    ⚠️ **短于 2 字的 place 判据不适用 ⇒ 返回 True**。真实数据里 item 295 的
    place 是单字「湖」，bigram 对它恒为空集——写成 False 会静默误清，
    且没有任何测试会因此变红（M2「多分支判据必须多分支守卫」）。
    """
    if not place:
        return True
    grams = _bigrams(place)
    if not grams:
        return True
    return bool(grams & _bigrams(sources))


def deadline_sane(deadline_ts: int | None, event_ts: int) -> bool:
    """截止日不早于消息当天——`deadline` 字段的语义是**需要行动的截止日**。

    ⚠️ 这不是"幻觉检测"（那由 `deadline_supported` 负责）。item 83 的
    `档案袋封口时间：5 月 6 日` 在源文里**找得到**、抽取也没错，它是**过去的既成事实**——
    但它不满足「需要行动」这个语义，所以不该占着「⏰ 别忘」那一节。

    判据按**本地日**比较（与 `_day_start` 的口径一致）：同一天不过夜 ⇒ 放行。
    """
    if deadline_ts is None:
        return True
    day_start = _day_start_of(event_ts)
    return deadline_ts >= day_start


def _day_start_of(ts: int) -> int:
    d = dt.datetime.fromtimestamp(ts)
    return int(dt.datetime.combine(d.date(), dt.time.min).timestamp())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_deadline.py -v -k "place or sane"`
Expected: **10 passed**

- [ ] **Step 5: 写失败测试（接线层）**

追加到 `tests/test_refine.py`：

```python
# ── Task 2：两道闸门接进 _to_item ─────────────────────────────────


def test_to_item_drops_place_without_evidence(msg_factory):
    """源文里没有地点 ⇒ place 降级为 None，**条目本身保留**（与 deadline 同一取舍）。"""
    batch = [
        msg_factory(
            1,
            "大概这周会有面试 到时候具体时间通知大家",
            uid="u_1",
        )
    ]
    it = refine._to_item(
        {"quote": "到时候具体时间通知大家", "kind": "notice",
         "title": "面试通知", "place": "立德楼1阶", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it is not None          # ⚠️ 条目必须还在
    assert it.place is None        # ⚠️ 只有 place 被降级


def test_to_item_keeps_place_with_evidence(msg_factory):
    batch = [msg_factory(1, "西太湖连隔板", uid="u_1")]
    it = refine._to_item(
        {"quote": "西太湖连隔板", "kind": "notice", "title": "澡堂隔板",
         "place": "西太湖校区", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it.place == "西太湖校区"


def test_to_item_drops_past_deadline(msg_factory):
    """item 83 的形状：死线早于消息日。"""
    batch = [msg_factory(1, "档案袋封口时间：5 月 6 日", ts=1_754_300_000, uid="u_1")]
    it = refine._to_item(
        {"quote": "档案袋封口时间：5 月 6 日", "kind": "notice",
         "title": "档案袋封口", "deadline": "2026-05-06", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it is not None
    assert it.deadline_ts is None


def test_to_item_keeps_future_deadline(msg_factory):
    batch = [msg_factory(1, "9月20日前交表", ts=1_757_900_000, uid="u_1")]
    it = refine._to_item(
        {"quote": "9月20日前交表", "kind": "notice", "title": "交表",
         "deadline": "2026-09-20", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it.deadline_ts is not None
```

> ⚠️ 执行者注意：上面两个 `ts` 字面量是**占位用的真实 epoch**。
> 跑之前先用 `uv run python -c "import datetime;print(int(datetime.datetime(2026,8,5,12).timestamp()))"`
> 核对一遍，**把实际算出来的值写进断言所在的测试**（本计划的值取自 2026-09-16 的本地时区）。
> 若你机器上算出来不同，**按实际值改测试，并在报告里写明**——这是逃逸舱第一种形状。

- [ ] **Step 6: 跑测试确认失败**

Run: `uv run pytest tests/test_refine.py -k "to_item_drops_place or to_item_keeps_place or to_item_drops_past or to_item_keeps_future" -v`
Expected: **4 failed**（`assert '立德楼1阶' is None` 一类）

- [ ] **Step 7: 在 `_to_item` 里接线**

`vigil/refine.py` 顶部 import 改为（`deadline.py` 的导入行）：

```python
from .deadline import deadline_sane, deadline_supported, place_supported
```

`vigil/refine.py` 的 `_to_item`，把 `return store.ExtractedItem(...)` 那一段改成：

```python
    # ⚠️ 两道要素闸门都在**写入边界**上做，理由与 _drop_unsupported_deadlines
    # 的 docstring 完全一样：数据一旦入库就到处流，每个读取方各挡一次迟早有人忘。
    sources_text = "\n".join((m.content or "") for m in batch if m.msg_id in source_ids)
    raw_place = _text("place")
    place = raw_place if place_supported(raw_place, sources_text) else None

    deadline_ts = _parse_deadline(raw.get("deadline"))
    if deadline_ts is not None and not deadline_sane(deadline_ts, source.ts):
        deadline_ts = None

    return store.ExtractedItem(
        kind=kind,
        title=title,
        detail=_text("detail"),
        event_ts=source.ts,
        deadline_ts=deadline_ts,
        group_id=source.group_id,
        actor_uid=source.sender_uid or None,
        place=place,
        links=links,
        amount=_text("amount"),
        confidence=max(0.0, min(1.0, confidence)),
        src_msg_ids=(source.msg_id,),
    )
```

并在 `_to_item` 里、`source` 定下来之后（`if source is None: return None` 的下一行）加：

```python
    source_ids = frozenset({source.msg_id})
```

> ⚠️ **不要**把 `sources_text` 写成整个 batch 的正文拼接。`_to_item` 的 `src_msg_ids`
> 目前恒为 `(source.msg_id,)`，所以依据只应来自**那一条**消息。用整个 batch 会重演
> `deadline.py` 里 `_GAP` 注释记的那个坑——「跨消息拼接凭空造出证据」。

- [ ] **Step 8: 跑测试确认通过**

Run: `uv run pytest tests/test_refine.py tests/test_deadline.py -q`
Expected: 全部通过

- [ ] **Step 9: 跑全量**

Run: `uv run pytest -q`
Expected: 全部通过

- [ ] **Step 10: Commit**

```bash
git add vigil/deadline.py vigil/refine.py tests/test_deadline.py tests/test_refine.py
git commit -m "feat(deadline,refine): 两道要素闸门——place 证据(2字子串) + deadline 时序(不早于消息当天)"
```

---

## Task 3: `items` 批内去重

**为什么**：真库实测（M4 接力文件 §二.1）——`item 290` 与 `item 296` 同标题、同 `event_ts`、同群、
**`created_at` 同秒且来源是同一条消息**（`7685735400902931272`）⇒ 同一次 `save_items`。
**模型在一次响应里把同一条消息抽了两遍**，而 `save_items` 不去重。

**⚠️ 合并而不是丢弃**：两条重复项的 `src_msg_ids` 取**并集**。
`items` 表按设计没有唯一键，`item_sources` 是"这条 item 来自哪几条消息"的唯一记录——
直接丢掉一条会**静默丢掉它的来源行**（而"可回溯到原文"是 M1 的出口标准）。

**Files:**
- Modify: `vigil/store.py`（加 `_dedupe_batch`，在 `save_items` 里调用）
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `store.ExtractedItem`（已有）
- Produces: `store._dedupe_batch(items: list[ExtractedItem]) -> list[ExtractedItem]`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_store.py`：

```python
# ── Task 3：批内去重 ─────────────────────────────────────────────


def _item(title="标题", *, event_ts=1_700_000_000, group_id=100, src=(1,), kind="notice"):
    from vigil.store import ExtractedItem

    return ExtractedItem(
        kind=kind, title=title, detail=None, event_ts=event_ts,
        deadline_ts=None, group_id=group_id, actor_uid="u_x", place=None,
        links=(), amount=None, confidence=0.9, src_msg_ids=src,
    )


def test_dedupe_batch_collapses_identical_items():
    """item 290/296 的真实形状：同批同标题同 event_ts 同群。"""
    out = store._dedupe_batch([_item(src=(11,)), _item(src=(11,))])
    assert len(out) == 1


def test_dedupe_batch_merges_sources():
    """⚠️ 重复项的来源取并集，不是丢掉第二条——否则 item_sources 少一行且无声。"""
    out = store._dedupe_batch([_item(src=(11,)), _item(src=(22,))])
    assert len(out) == 1
    assert out[0].src_msg_ids == (11, 22)


def test_dedupe_batch_keeps_distinct_titles():
    out = store._dedupe_batch([_item("甲"), _item("乙")])
    assert [i.title for i in out] == ["甲", "乙"]


def test_dedupe_batch_keeps_same_title_in_other_group():
    out = store._dedupe_batch([_item(group_id=1), _item(group_id=2)])
    assert len(out) == 2


def test_dedupe_batch_keeps_same_title_at_other_time():
    out = store._dedupe_batch([_item(event_ts=1), _item(event_ts=2)])
    assert len(out) == 2


def test_save_items_writes_deduped_rows(memdb):
    store.ensure_schema(memdb)
    n = store.save_items(
        memdb, [_item(src=(11,)), _item(src=(11,))],
        model="m", prompt_ver="v3",
    )
    assert n == 1
    assert memdb.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_store.py -k dedupe -v`
Expected: **AttributeError: module 'vigil.store' has no attribute '_dedupe_batch'**（6 条里前 5 条红的
原因是这个；第 6 条红的可能是 `assert 2 == 1`）

- [ ] **Step 3: 实现**

`vigil/store.py` 顶部确认有 `from dataclasses import dataclass, replace`
（**没有 `replace` 就补上**），然后在 `save_items` **之前**插入：

```python
def _dedupe_batch(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """批内去重：``(title, event_ts, group_id)`` 相同的只留一条。

    ⚠️ 存在的理由是一个真实缺陷（M4 实测）：模型在**一次响应**里把同一条消息
    抽了两遍，而 `items` 表没有唯一键，于是库里出现两条一模一样的条目
    （真库 item 290 / 296，来源同为 msg 7685735400902931272）。
    `trans._run` 的记账防不住它——**同一次 `save_items` 内部**的重复，
    没有任何一层会拦。

    ⚠️ **来源取并集而不是丢弃**：两条重复项的 `src_msg_ids` 可能不同
    （同秒的两条不同消息），直接丢一条会让 `item_sources` 少一行。
    "可回溯到原文"是 M1 的出口标准，不能在这里静默失守。

    ⚠️ 键里**不带** `actor_uid` / `kind`：同标题同秒同群的条目，即便模型给了
    不同的类目，也是同一条信息被抽了两遍——按最早的那条留下。
    """
    seen: dict[tuple[str, int, int], int] = {}
    out: list[ExtractedItem] = []
    for it in items:
        key = (it.title, it.event_ts, it.group_id)
        idx = seen.get(key)
        if idx is None:
            seen[key] = len(out)
            out.append(it)
            continue
        merged = tuple(dict.fromkeys((*out[idx].src_msg_ids, *it.src_msg_ids)))
        out[idx] = replace(out[idx], src_msg_ids=merged)
    return out
```

并把 `save_items` 函数体第一行（`stamp = ...` 之前）改成：

```python
    items = _dedupe_batch(items)
    stamp = int(time.time()) if now is None else now
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_store.py -k dedupe -v`
Expected: **6 passed**

- [ ] **Step 5: 跑全量**

Run: `uv run pytest -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add vigil/store.py tests/test_store.py
git commit -m "fix(store): items 批内去重——(title,event_ts,group_id) 同键合并，来源取并集"
```

---

## Task 4: 人工干预层——存储与事件模型

**为什么**：用户要求「手动调整某条信息的分类」「删除某条信息」「撤销」。
这些是**写数据**，而 D11 规定 `data/vigil.db` 只读 ⇒ 落在独立的 append-only 事件表（D14）。

**设计要点（照抄 spec §3.3，别自己发挥）：**

- 存储 `data/overrides.db`，**独立可写 SQLite**。
- 两张表：`item_edits`（事件日志，append-only，撤销靠它）+ `item_state`（**物化的折叠结果**，
  由写入路径维护，读取路径只 JOIN 它——**这样读路径的 SQL 保持简单，不需要窗口函数**）。
- **两条键各司其职**：`item_id` 用于"改这一条"，`msg_id` 用于"永不被重抽复活"（D15）。

**Files:**
- Create: `vigil/overrides.py`、`tests/test_overrides.py`
- Modify: `vigil/store.py`（在 `ensure_schema` 里确保 overlay 文件存在——见 Step 5）

**Interfaces:**
- Consumes: 无
- Produces:
  - `overrides.OVERRIDES_DB: pathlib.Path`（默认 `REPO_ROOT / "data" / "overrides.db"`）
  - `overrides.ensure_schema(path: pathlib.Path | None = None) -> None`（建文件 + 建表，幂等）
  - `overrides.connect(path: pathlib.Path | None = None) -> sqlite3.Connection`（**可写**连接）
  - `overrides.attach_readonly(conn: sqlite3.Connection, path=None) -> None`（把 overlay 挂成 `ov`）
  - `overrides.set_kind(conn, *, item_id: int, kind: str, actor: str = "web", now: int | None = None) -> int`
  - `overrides.delete_item(conn, *, item_id: int, msg_id: int | None, actor: str = "web", now: int | None = None) -> int`
  - `overrides.undo(conn, *, edit_id: int) -> bool`
  - `overrides.last_edit(conn) -> tuple[int, int, str] | None`（`(edit_id, item_id, action)`）
  - `overrides.deleted_msg_ids(conn) -> frozenset[int]`（Task 6 的 refine 要用）
  - `overrides.rebuild_state(conn) -> None`（从事件日志重算 `item_state`）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_overrides.py`：

```python
"""人工干预层：append-only 的事件日志 + 物化状态。"""

import sqlite3

import pytest

from vigil import overrides


@pytest.fixture
def ov():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    overrides.ensure_tables(conn)
    yield conn
    conn.close()


def test_set_kind_writes_event_and_state(ov):
    edit_id = overrides.set_kind(ov, item_id=7, kind="academic")
    assert edit_id > 0
    row = ov.execute("SELECT kind, deleted FROM item_state WHERE item_id=7").fetchone()
    assert row["kind"] == "academic"
    assert row["deleted"] == 0
    ev = ov.execute("SELECT * FROM item_edits WHERE edit_id=?", (edit_id,)).fetchone()
    assert ev["action"] == "set_kind"
    assert ev["item_id"] == 7
    assert ev["new_value"] == "academic"


def test_set_kind_is_append_only_old_value_recorded(ov):
    overrides.set_kind(ov, item_id=7, kind="academic")
    overrides.set_kind(ov, item_id=7, kind="life")
    rows = ov.execute(
        "SELECT new_value FROM item_edits WHERE item_id=7 ORDER BY edit_id"
    ).fetchall()
    assert [r["new_value"] for r in rows] == ["academic", "life"]
    assert ov.execute("SELECT kind FROM item_state WHERE item_id=7").fetchone()["kind"] == "life"


def test_delete_marks_state_and_records_msg_id(ov):
    overrides.delete_item(ov, item_id=9, msg_id=555)
    assert ov.execute("SELECT deleted FROM item_state WHERE item_id=9").fetchone()["deleted"] == 1
    assert overrides.deleted_msg_ids(ov) == frozenset({555})


def test_delete_then_set_kind_last_wins(ov):
    """事件序决定状态——后发生的覆盖先发生的。"""
    overrides.delete_item(ov, item_id=9, msg_id=555)
    overrides.set_kind(ov, item_id=9, kind="life")
    row = ov.execute("SELECT kind, deleted FROM item_state WHERE item_id=9").fetchone()
    assert row["deleted"] == 0
    assert row["kind"] == "life"


def test_undo_removes_event_and_rebuilds_state(ov):
    overrides.set_kind(ov, item_id=7, kind="academic")
    eid = overrides.set_kind(ov, item_id=7, kind="life")
    assert overrides.undo(ov, edit_id=eid) is True
    assert ov.execute("SELECT kind FROM item_state WHERE item_id=7").fetchone()["kind"] == "academic"
    assert ov.execute("SELECT COUNT(*) FROM item_edits WHERE item_id=7").fetchone()[0] == 1


def test_undo_unknown_edit_returns_false(ov):
    assert overrides.undo(ov, edit_id=9999) is False


def test_undo_delete_restores_visibility(ov):
    eid = overrides.delete_item(ov, item_id=9, msg_id=555)
    assert overrides.undo(ov, edit_id=eid) is True
    assert ov.execute("SELECT COUNT(*) FROM item_state WHERE item_id=9").fetchone()[0] == 0


def test_last_edit(ov):
    assert overrides.last_edit(ov) is None
    overrides.set_kind(ov, item_id=7, kind="life")
    eid = overrides.delete_item(ov, item_id=8, msg_id=1)
    assert overrides.last_edit(ov) == (eid, 8, "delete")


def test_ensure_tables_is_idempotent(ov):
    overrides.ensure_tables(ov)
    overrides.ensure_tables(ov)
    assert ov.execute("SELECT COUNT(*) FROM item_edits").fetchone()[0] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_overrides.py -v`
Expected: **collection error: No module named 'vigil.overrides'**

- [ ] **Step 3: 实现 `vigil/overrides.py`**

```python
"""人工干预层：对**数据**的人工修改，不写 `data/vigil.db`。

为什么要单独一层（D14）：用户要「手动改分类 / 删除条目 / 撤销」，这三件事都要写数据，
而 M3 起 `data/vigil.db` 的只读是**机械保证**（`mode=ro`）。把它们写进主库，
那道保证就没了；而**一张 append-only 的事件表同时给出这三件事**——
撤销天然就有（事件可回溯），删除变成 tombstone，重排变成 `set_kind` 事件
（从而 `item_id` 永不翻新，见 D16）。

⚠️ **overlay 是视图层修正，不是"数据被改真了"**。直接 `sqlite3 data/vigil.db` 查，
被删的条目仍然在。这个性质是有意的，写在这里免得将来有人当成缺陷。

⚠️ **两张表的分工**：
* `item_edits` 是**唯一真相**（append-only，撤销就是对它做删除）
* `item_state` 是**物化的折叠结果**，由写入路径维护。
  读取路径 JOIN 它即可，不需要窗口函数——SQL 保持简单是刻意的。
  它可以在任何时候由 `rebuild_state()` 从 `item_edits` 完整重算。
"""

from __future__ import annotations

import pathlib
import sqlite3
import time

from .config import REPO_ROOT

OVERRIDES_DB = REPO_ROOT / "data" / "overrides.db"

ACTION_SET_KIND = "set_kind"
ACTION_SET_FIELD = "set_field"
ACTION_DELETE = "delete"

_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS item_edits (
    edit_id    INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL,
    msg_id     INTEGER,
    action     TEXT    NOT NULL,
    field      TEXT,
    old_value  TEXT,
    new_value  TEXT,
    actor      TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS item_edits_item ON item_edits(item_id);

CREATE TABLE IF NOT EXISTS item_state (
    item_id INTEGER PRIMARY KEY,
    kind    TEXT,
    deleted INTEGER NOT NULL DEFAULT 0
);
"""


class OverlayError(RuntimeError):
    """人工干预层的使用错误——快速失败。"""


def ensure_tables(conn: sqlite3.Connection) -> None:
    """建表。幂等。**不 commit**——调用方决定事务边界。"""
    conn.executescript(_TABLES_DDL)


def ensure_schema(path: pathlib.Path | None = None) -> None:
    """确保 overlay 文件存在且表齐全。幂等，供服务启动与写路径调用。

    ⚠️ 读取路径（`api.py`）**不能**在这里建库——它们是只读的。所以服务启动时
    先调这个函数（D11 允许 Web 写 overlay），之后每个请求才敢无条件 ATTACH。
    """
    target = path or OVERRIDES_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    try:
        ensure_tables(conn)
        conn.commit()
    finally:
        conn.close()


def connect(path: pathlib.Path | None = None) -> sqlite3.Connection:
    """**可写**连接（写端点专用）。"""
    conn = sqlite3.connect(str(path or OVERRIDES_DB))
    conn.row_factory = sqlite3.Row
    return conn


def attach_readonly(conn: sqlite3.Connection, path: pathlib.Path | None = None) -> None:
    """把 overlay 挂成 `ov`（只读）。读取路径专用。

    ⚠️ 用 `mode=ro` 挂——读取路径不该有写能力，哪怕只是"顺手"。
    ⚠️ 幂等：已挂过就什么都不做（`sqlite3` 重复 ATTACH 同名会报错）。
    """
    if any(r[1] == "ov" for r in conn.execute("PRAGMA database_list")):
        return
    target = (path or OVERRIDES_DB).as_posix()
    conn.execute(f"ATTACH DATABASE 'file:{target}?mode=ro' AS ov")


def _append(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    msg_id: int | None,
    action: str,
    field: str | None,
    old_value: str | None,
    new_value: str | None,
    actor: str,
    now: int | None,
) -> int:
    stamp = int(time.time()) if now is None else now
    cur = conn.execute(
        "INSERT INTO item_edits"
        " (item_id, msg_id, action, field, old_value, new_value, actor, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (item_id, msg_id, action, field, old_value, new_value, actor, stamp),
    )
    _apply_to_state(
        conn, item_id=item_id, action=action, new_value=new_value, edit_id=cur.lastrowid
    )
    conn.commit()
    return int(cur.lastrowid)


def set_kind(
    conn: sqlite3.Connection, *, item_id: int, kind: str, actor: str = "web",
    now: int | None = None,
) -> int:
    """把某条 item 的类目改掉（写一条事件，不改 `items` 表）。"""
    if not kind:
        raise OverlayError("kind 不能为空")
    return _append(
        conn, item_id=item_id, msg_id=None, action=ACTION_SET_KIND, field="kind",
        old_value=None, new_value=kind, actor=actor, now=now,
    )


def delete_item(
    conn: sqlite3.Connection, *, item_id: int, msg_id: int | None, actor: str = "web",
    now: int | None = None,
) -> int:
    """软删（D15）。`msg_id` 是「永不被重抽复活」的键——**能不传就一定要传**。

    ⚠️ 不知道 `msg_id` 时传 None 是允许的（界面仍然会隐藏它），
    但那条源消息将来 `--redo` 时**就会复活**。调用方有责任尽量带上。
    """
    return _append(
        conn, item_id=item_id, msg_id=msg_id, action=ACTION_DELETE, field=None,
        old_value=None, new_value=None, actor=actor, now=now,
    )


def undo(conn: sqlite3.Connection, *, edit_id: int) -> bool:
    """撤掉一条事件，然后重建状态。事件不存在返回 False。

    ⚠️ 这里是全模块**唯一**一处 DELETE——append-only 的例外。
    它的安全性来自「事件表的尾部没有外部引用」：没有任何东西按 edit_id 持有指针。
    """
    cur = conn.execute("DELETE FROM item_edits WHERE edit_id = ?", (edit_id,))
    if cur.rowcount == 0:
        conn.rollback()
        return False
    rebuild_state(conn)
    conn.commit()
    return True


def last_edit(conn: sqlite3.Connection) -> tuple[int, int, str] | None:
    row = conn.execute(
        "SELECT edit_id, item_id, action FROM item_edits ORDER BY edit_id DESC LIMIT 1"
    ).fetchone()
    return (int(row[0]), int(row[1]), str(row[2])) if row else None


def deleted_msg_ids(conn: sqlite3.Connection) -> frozenset[int]:
    """被软删条目对应的源消息 id——`refine` 靠它跳过重抽（D15）。"""
    return frozenset(
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT msg_id FROM item_edits"
            " WHERE action = ? AND msg_id IS NOT NULL",
            (ACTION_DELETE,),
        )
    )


def rebuild_state(conn: sqlite3.Connection) -> None:
    """从事件日志**完整重算** `item_state`。幂等，任何时刻调都得到同一结果。"""
    conn.execute("DELETE FROM item_state")
    rows = conn.execute(
        "SELECT item_id, action, new_value FROM item_edits ORDER BY edit_id ASC"
    ).fetchall()
    for item_id, action, new_value in rows:
        if action == ACTION_DELETE:
            conn.execute(
                "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, NULL, 1)"
                " ON CONFLICT(item_id) DO UPDATE SET deleted = 1",
                (item_id,),
            )
        elif action == ACTION_SET_KIND:
            conn.execute(
                "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, ?, 0)"
                " ON CONFLICT(item_id) DO UPDATE SET kind = excluded.kind, deleted = 0",
                (item_id, new_value),
            )


def _apply_to_state(
    conn: sqlite3.Connection, *, item_id: int, action: str, new_value: str | None,
    edit_id: int,
) -> None:
    """把一条新事件折叠进 `item_state`（增量，不重算全表）。

    ⚠️ 必须与 `rebuild_state` 的结果**恒等**——这是两者唯一的契约。
    `test_rebuild_state_matches_incremental` 守着它。
    """
    if action == ACTION_DELETE:
        conn.execute(
            "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, NULL, 1)"
            " ON CONFLICT(item_id) DO UPDATE SET deleted = 1",
            (item_id,),
        )
    elif action == ACTION_SET_KIND:
        conn.execute(
            "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, ?, 0)"
            " ON CONFLICT(item_id) DO UPDATE SET kind = excluded.kind, deleted = 0",
            (item_id, new_value),
        )
```

- [ ] **Step 4: 补两条测试（增量与重算必须恒等 + 软删的 msg_id 是并集）**

追加到 `tests/test_overrides.py`：

```python
def test_rebuild_state_matches_incremental(ov):
    """⚠️ 增量折叠与全量重算必须恒等——否则 undo 之后的 state 会与事件日志脱节。"""
    overrides.set_kind(ov, item_id=7, kind="academic")
    overrides.delete_item(ov, item_id=8, msg_id=1)
    overrides.set_kind(ov, item_id=8, kind="life")
    overrides.delete_item(ov, item_id=7, msg_id=2)

    before = [dict(r) for r in ov.execute("SELECT * FROM item_state ORDER BY item_id")]
    overrides.rebuild_state(ov)
    after = [dict(r) for r in ov.execute("SELECT * FROM item_state ORDER BY item_id")]
    assert before == after


def test_undo_then_rebuild_still_consistent(ov):
    overrides.set_kind(ov, item_id=7, kind="academic")
    eid = overrides.delete_item(ov, item_id=7, msg_id=2)
    overrides.undo(ov, edit_id=eid)
    overrides.rebuild_state(ov)
    row = ov.execute("SELECT kind, deleted FROM item_state WHERE item_id=7").fetchone()
    assert row["kind"] == "academic"
    assert row["deleted"] == 0
```

- [ ] **Step 5: 让 overlay 文件在写路径上自动就位**

`vigil/store.py` 的 `ensure_schema`（`store.py:181`）里，在 `conn.executescript(SCHEMA_DDL)` **之前**加：

```python
    # 人工干预层（D14）的文件也在这里就位：`refine` / `digest` 跑过之后，
    # 服务启动时就不必再建它。⚠️ **不能**放在 `api.py` 的 `connect()` 里——
    # 那是只读路径。
    from . import overrides

    overrides.ensure_schema()
```

> ⚠️ 局部 import 是刻意的：`store.py` 被 `overrides.py` 之外的很多模块导入，
> 而 `overrides.py` 反向 import 了 `config.py`。模块级 import 会形成环。
> **不要"顺手"提到文件顶部。**

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_overrides.py -v && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 7: Commit**

```bash
git add vigil/overrides.py tests/test_overrides.py vigil/store.py
git commit -m "feat(overrides): 人工干预层——append-only 事件日志 + 物化 item_state（D14/D15）"
```

---

## Task 5: overlay 接入 `store.py` 查询层（R13 的落点）

**为什么**：spec §3.3 实测——**真读路径只有 5 处**，而 `digest.py` **不直接读 `items`**（它走
`store.window_items`）。所以 apply 必须**收敛在 `store.py` 的查询函数里**。
若反过来在消费方（api / digest）各打一个补丁，漏掉的那一处**不会有任何测试变红**——
这就是 R13，M4「记下来了 ≠ 派下去了」的同族。

**⚠️ 本任务的核心设计决定：不许靠"调用方记得先 ATTACH"。**

若 SQL 里写 `ov.item_state` 而没人 ATTACH，SQLite 会报 `no such table: ov.item_state`——
一个**运行时**错误。任何一处漏了 attach 就是一个 500。
所以每个查询函数**入口自 attach**（`_ensure_overlay`），attach 本身幂等且便宜（一次 `PRAGMA`）。
**这样"忘记"在结构上不可能发生。**

**Files:**
- Modify: `vigil/overrides.py`（`attach_readonly` 支持文件缺失时自建）、`vigil/store.py`
- Modify: `tests/conftest.py`（autouse 夹具，**Global Constraint 8**）
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `overrides.attach_readonly`、`ov.item_state(item_id, kind, deleted)`
- Produces:
  - `store._ensure_overlay(conn) -> None`
  - 读路径的语义保证：**被软删的条目不出现在 `search_items` / `get_item` / `window_items` / `kind_counts` / `digest_items` 的任何结果里**；被 `set_kind` 过的条目在任何地方都显示**新类目**

- [ ] **Step 1: 写失败测试**

先加夹具。追加到 `tests/conftest.py` 末尾：

```python
@pytest.fixture(autouse=True)
def _isolate_overlay(tmp_path, monkeypatch):
    """把人工干预层的默认路径挪到 tmp。

    ⚠️ 与 `_isolate_lock_path` **同一条理由**（Global Constraint 8）：若不挪，
    任何调用 `store.search_items` 一类查询的测试都会去**建/读真实的
    `data/overrides.db`**——污染真库，且一旦真库里恰好有内容，测试结果
    变成**环境相关的**（M4 实测过这个形态：5 条用例莫名变红，红的还全是
    "退出码""密钥"这类看着像产品缺陷的名字）。
    """
    from vigil import overrides

    monkeypatch.setattr(overrides, "OVERRIDES_DB", tmp_path / "overrides.db")
```

追加到 `tests/test_store.py`：

```python
# ── Task 5：overlay 接入查询层 ────────────────────────────────────


def _seed(conn, *, title="标题", kind="notice", ts=1_700_000_000, group_id=100):
    from vigil.store import ExtractedItem

    conn.execute(
        "INSERT INTO items (kind, title, detail, event_ts, deadline_ts, group_id,"
        " actor_uid, place, links, amount, confidence, model, prompt_ver, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, title, None, ts, None, group_id, "u_x", None, "[]", None,
         0.9, "m", "v3", ts),
    )
    return conn.execute("SELECT MAX(item_id) FROM items").fetchone()[0]


def _ov_conn():
    from vigil import overrides

    overrides.ensure_schema()
    conn = overrides.connect()
    overrides.ensure_tables(conn)
    return conn


def test_soft_deleted_item_disappears_from_search(memdb):
    store.ensure_schema(memdb)
    iid = _seed(memdb)
    ov = _ov_conn()
    overrides.delete_item(ov, item_id=iid, msg_id=None)
    ov.close()

    items, total = store.search_items(memdb, limit=50, offset=0)
    assert total == 0, "⚠️ total 也必须跟着变——否则分页与『共 N 条』会说谎"
    assert items == []


def test_set_kind_overrides_kind_in_search(memdb):
    store.ensure_schema(memdb)
    iid = _seed(memdb, kind="notice")
    ov = _ov_conn()
    overrides.set_kind(ov, item_id=iid, kind="academic")
    ov.close()

    items, _ = store.search_items(memdb, limit=50, offset=0)
    assert items[0].kind == "academic"


def test_kind_filter_uses_effective_kind(memdb):
    """⚠️ 筛选必须按**覆盖后**的类目——否则改了分类却筛不出来。"""
    store.ensure_schema(memdb)
    iid = _seed(memdb, kind="notice")
    ov = _ov_conn()
    overrides.set_kind(ov, item_id=iid, kind="academic")
    ov.close()

    assert store.search_items(memdb, kind="academic", limit=50, offset=0)[1] == 1
    assert store.search_items(memdb, kind="notice", limit=50, offset=0)[1] == 0


def test_soft_deleted_item_disappears_from_window(memdb):
    """⚠️ R13 的典型形态：只改 API 不改 window_items ⇒「界面上删了、日报里还在」。"""
    store.ensure_schema(memdb)
    iid = _seed(memdb, ts=1_700_000_000)
    ov = _ov_conn()
    overrides.delete_item(ov, item_id=iid, msg_id=None)
    ov.close()

    got = store.window_items(memdb, since=1_699_000_000, until=1_701_000_000)
    assert got == []


def test_get_item_returns_none_for_deleted(memdb):
    store.ensure_schema(memdb)
    iid = _seed(memdb)
    ov = _ov_conn()
    overrides.delete_item(ov, item_id=iid, msg_id=None)
    ov.close()

    assert store.get_item(memdb, iid) is None


def test_kind_counts_uses_effective_kind_and_skips_deleted(memdb):
    store.ensure_schema(memdb)
    a = _seed(memdb, title="甲", kind="notice")
    _seed(memdb, title="乙", kind="notice")
    ov = _ov_conn()
    overrides.set_kind(ov, item_id=a, kind="academic")
    ov.close()

    counts = store.kind_counts(memdb)
    assert counts == {"academic": 1, "notice": 1}


def test_deleted_item_missing_from_digest_items(memdb):
    store.ensure_schema(memdb)
    iid = _seed(memdb)
    store.save_digest(
        memdb, window_from=1, window_to=2, body_md="x", model="m",
        prompt_ver="v1", item_ids=[iid],
    )
    ov = _ov_conn()
    overrides.delete_item(ov, item_id=iid, msg_id=None)
    ov.close()

    did = memdb.execute("SELECT MAX(digest_id) FROM digests").fetchone()[0]
    assert store.digest_items(memdb, did) == []
```

并在 `tests/test_store.py` 顶部 import 区加上：

```python
from vigil import overrides
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_store.py -k "soft_deleted or set_kind_overrides or kind_filter_uses or effective_kind or returns_none_for_deleted" -v`
Expected: 7 条**全部失败**。失败原因应当是 `sqlite3.OperationalError: no such table: ov.item_state`
（**不是你测试写错**——若报的是别的错，先查清楚再往下走）

- [ ] **Step 3: 让 `attach_readonly` 容忍文件缺失**

`vigil/overrides.py` 的 `attach_readonly` 改成：

```python
def attach_readonly(conn: sqlite3.Connection, path: pathlib.Path | None = None) -> None:
    """把 overlay 挂成 `ov`（只读）。**查询路径的每个入口都调它。**

    ⚠️ 用 `mode=ro` 挂——读取路径不该有写能力，哪怕只是"顺手"。
    ⚠️ 幂等：已挂过就什么都不做（重复 ATTACH 同名会报错）。
    ⚠️ 文件不存在时**先建一个空的**：读取路径必须能在"从没写过干预"的库上工作。
    这不违反 D11（overlay 本来就在 Web 的可写范围内），也比"读路径分支 SQL"干净得多
    ——分支 SQL 会让"忘了处理没 attach 的情况"重新变成一种可能。
    """
    if any(r[1] == "ov" for r in conn.execute("PRAGMA database_list")):
        return
    target = path or OVERRIDES_DB
    if not target.is_file():
        ensure_schema(target)
    conn.execute(f"ATTACH DATABASE 'file:{target.as_posix()}?mode=ro' AS ov")
```

- [ ] **Step 4: 在 `store.py` 加 `_ensure_overlay` 并改查询层**

`vigil/store.py`，在 `_ITEM_COLS` 定义**之前**插入：

```python
def _ensure_overlay(conn: sqlite3.Connection) -> None:
    """确保人工干预层已挂成 `ov`。**每个走 `_ITEM_COLS` 的查询入口都要调。**

    ⚠️ 做成"入口自 attach"而不是"调用方先 attach"，是**结构性**的防线：
    SQL 里写了 `ov.item_state` 而没人挂载时，报的是运行时的
    `no such table`——一个漏掉的调用方就是一个 500。
    自 attach 之后，「忘记」在结构上不可能发生（R13 的落点）。

    ⚠️ 局部 import 避免 `store` ↔ `overrides` 的模块级环（见 `ensure_schema` 里的说明）。
    """
    from . import overrides

    overrides.attach_readonly(conn)
```

把 `_ITEM_COLS` / `_ITEM_JOINS`（`store.py:682-693`）改成：

```python
_ITEM_COLS = (
    "i.item_id, COALESCE(ost.kind, i.kind) AS kind, i.title, i.detail, i.event_ts,"
    " i.deadline_ts, i.group_id,"
    " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS actor,"
    " i.place, i.amount, i.links,"
    " (SELECT COUNT(*) FROM item_sources src WHERE src.item_id = i.item_id)"
    "   AS source_count"
)

_ITEM_JOINS = (
    " FROM items i"
    " LEFT JOIN sender_names sn ON sn.group_id = i.group_id AND sn.uid = i.actor_uid"
    " LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id"
)

# ⚠️ 软删的条目在**所有**读取路径上都必须消失（D15）。拼进 `_ITEM_JOINS` 的
# `WHERE` 片段单独定义，是为了让"哪几处用了它"一眼可数——
# 漏掉任何一处的后果是「界面上删了、日报里还在」（R13）。
_NOT_DELETED = "IFNULL(ost.deleted, 0) = 0"
```

`_item_filters` 里，把 kind 那一段改成（**同时**加软删过滤）：

```python
    where: list[str] = [_NOT_DELETED]
    params: list[object] = []
    if kind:
        where.append("COALESCE(ost.kind, i.kind) = ?")
        params.append(kind)
```

`search_items` 的 COUNT 查询（`store.py:800-802`）改成：

```python
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM items i"
            f" LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id{clause}",
            params,
        ).fetchone()[0]
    )
```

并在 `search_items` 与 `get_item` 的函数体第一行加 `_ensure_overlay(conn)`。

`get_item` 的 SQL 改成（加软删过滤）：

```python
    row = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS} WHERE i.item_id = ? AND {_NOT_DELETED}",
        (item_id,),
    ).fetchone()
```

`window_items`（`store.py:352`）改成：

```python
def window_items(
    conn: sqlite3.Connection, *, since: int, until: int
) -> list[WindowItem]:
    """取时间窗内的条目，按 ``(event_ts, item_id)`` 升序。窗口是 ``[since, until)``。

    ⚠️ **人工干预层必须在这里生效**：被软删的条目不进日报，被改过类目的条目
    按新类目进日报。`digest.py` 不直接读 `items`——它走本函数，
    所以**这一处就是日报侧的全部接入点**（spec §3.3 实测）。
    """
    _ensure_overlay(conn)
    rows = conn.execute(
        "SELECT i.item_id, COALESCE(ost.kind, i.kind), i.title, i.detail, i.event_ts,"
        " i.deadline_ts, i.group_id, i.place, i.amount, i.confidence"
        " FROM items i"
        " LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id"
        f" WHERE i.event_ts >= ? AND i.event_ts < ? AND {_NOT_DELETED}"
        " ORDER BY i.event_ts ASC, i.item_id ASC",
        (since, until),
    ).fetchall()
    return [WindowItem(*row) for row in rows]
```

`kind_counts`（`store.py:842`）改成：

```python
def kind_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """每个类目有多少条（**按覆盖后的类目**，且不含软删）。类目视图的角标用它。"""
    _ensure_overlay(conn)
    return {
        str(k): int(n)
        for k, n in conn.execute(
            "SELECT COALESCE(ost.kind, i.kind), COUNT(*) FROM items i"
            " LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id"
            f" WHERE {_NOT_DELETED} GROUP BY COALESCE(ost.kind, i.kind)"
        )
    }
```

`digest_items`（`store.py:873`）在函数体第一行加 `_ensure_overlay(conn)`，
并在 WHERE 后补软删过滤：

```python
    rows = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS}"
        " JOIN digest_items di ON di.item_id = i.item_id"
        f" WHERE di.digest_id = ? AND {_NOT_DELETED}"
        " ORDER BY i.event_ts ASC, i.item_id ASC",
        (digest_id,),
    ).fetchall()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_store.py -v`
Expected: 全部通过

- [ ] **Step 6: 记录 `cli.py:518` 的**刻意不改**与理由**

`vigil/cli.py` 的 `cmd_deadline_audit` 里那句 `"SELECT title FROM items WHERE item_id = ?"`
**刻意不接 overlay**，在它上方加一行注释说明：

```python
                    # ⚠️ 这里**刻意不接 overlay**：`deadline-audit` 是对**底层数据**的
                    # 核验（"这条 item 的截止日在源文里有没有依据"），不是视图。
                    # 它就该看真实的 items——包括已软删的那些。
                    # 这是 spec §3.3 那张"5 处读路径"表里唯一一处「不需要 apply」的。
                    "SELECT title FROM items WHERE item_id = ?", (item_id,)
```

- [ ] **Step 7: 跑全量**

Run: `uv run pytest -q`
Expected: 全部通过

> ⚠️ **若这里出现大批失败**，先看是不是 `test_digest.py`——它有 108 条用例，
> 若其中有构造 `items` 后断言 `window_items` 的，现在会多一次 attach。
> 若失败原因是 `no such table: ov.item_state`，说明**有调用方在 attach 之前就渲染了 SQL**——
> 那是真缺陷，按逃逸舱第一种形状修正并报告。

- [ ] **Step 8: Commit**

```bash
git add vigil/store.py vigil/overrides.py vigil/cli.py tests/conftest.py tests/test_store.py
git commit -m "feat(store): overlay 接入 5 处读路径——查询入口自 attach，防 R13 漏接"
```

---

## Task 6: `refine` 读 overlay —— 墓碑阻复活（D15 的落地）

**为什么**：D15 说"软删且**永不被重抽复活**"。**`items` 的软删本身不会让它复活**
（行还在，只是被 overlay 挡住）；真正会让它复活的是 **`vigil refine --redo`**——
重抽时 `items` 会被重新写入。所以 `refine` 必须读 overlay 的 tombstone。

**⚠️ 本任务只影响 `--redo`（以及任何会重抽已处理消息的路径）。**
理由：非 `redo` 时 `pending_messages` 只返回 `refine_runs` 里没有 `ok` 记录的消息，
而被软删的条目**本来就抽过**（有 `ok` 记录）⇒ 根本不在待抽集合里。
**这也是为什么本任务不碰 `refine_runs`**——一旦把 tombstone 记成 `discarded`，
M1 出口标准「`refine_runs` 覆盖全部消息」的账目就被改写了，而那是**既有事实的记录**，不该被覆写。

**Files:**
- Modify: `vigil/refine.py`（`refine()` 里 `pending_messages` 之后）
- Test: `tests/test_refine.py`

**Interfaces:**
- Consumes: `overrides.deleted_msg_ids(conn) -> frozenset[int]`（Task 4）
- Produces: `refine.RefineStats.skipped_deleted: int`（新字段，报告里要看得见）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_refine.py`：

**⚠️ 本任务用 `tests/test_refine.py` 里**已经存在**的三个装置，不要另造一套**：
`FakeLLM`（`test_refine.py:14-25`，`__call__(cfg, *, system, user, sleep=None)`，记录 `self.calls`）、
`StubConfig`（`test_refine.py:60`）、`seeded` 夹具（`test_refine.py:28-57`，已建好
`messages` / `sender_names` 两张表并插了 3 条消息与 2 个发信人）。

```python
# ── Task 6：墓碑阻复活（D15） ─────────────────────────────────────


def test_refine_skips_tombstoned_messages_on_redo(seeded, monkeypatch):
    """被软删条目的源消息，`--redo` 时不得再被抽取（D15）。

    用 `seeded` 夹具里既有的 msg_id=3（"数学作业截止到9月7号"）。
    """
    from vigil import overrides

    overrides.ensure_schema()
    ov = overrides.connect()
    overrides.ensure_tables(ov)
    overrides.delete_item(ov, item_id=1, msg_id=3)
    ov.close()

    fake = FakeLLM(script=lambda _user: {"items": [
        {"quote": "数学作业截止到9月7号", "kind": "academic",
         "title": "数学作业截止", "deadline": "2026-09-07", "confidence": 0.9}
    ]})
    monkeypatch.setattr(refine, "chat_json", fake)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1, redo=True,
        on_progress=lambda *_: None,
    )
    assert stats.skipped_deleted == 1
    sent = " ".join(c["user"] for c in fake.calls)
    assert "数学作业" not in sent, "⚠️ 被墓碑挡下的消息**一步都不许出网**"


def test_refine_skips_deleted_counts_zero_without_tombstones(seeded, monkeypatch):
    """没有墓碑时该字段必须是 0——不能因为字段存在就恒为 1（否则判据是装饰）。"""
    fake = FakeLLM(script=lambda _user: {"items": []})
    monkeypatch.setattr(refine, "chat_json", fake)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1, redo=True,
        on_progress=lambda *_: None,
    )
    assert stats.skipped_deleted == 0
```

> ⚠️ **本任务与前几个任务的差别**：`refine()` 的其它参数（`prompt_ver`、`model` 等）
> 一律**照抄 `test_refine.py:237-300` 现有用例的写法**，本计划不重复列——
> 重复就会与既有夹具漂移。若现有的 `StubConfig` 缺 `tier_of`，按实际补。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_refine.py -k tombston or skipped_deleted -v`
Expected: `AttributeError: 'RefineStats' object has no attribute 'skipped_deleted'`

- [ ] **Step 3: 加字段与过滤**

`vigil/refine.py` 的 `RefineStats` 里，`discarded_local` 之后加：

```python
    skipped_deleted: int = 0     # 因软删墓碑而被跳过的消息数（D15）
```

`vigil/refine.py` 的 `refine()`，在 `stats.scanned = len(messages)` **之前**插入：

```python
        # D15：被软删条目的源消息**永不被重抽复活**。
        #
        # ⚠️ 只在重抽路径上起作用：非 redo 时 `pending_messages` 只返回没有 ok 记录的
        # 消息，而被软删的条目本来就抽过（有 ok 记录）⇒ 本来就不在集合里。
        # 会复活它们的**只有** `--redo`，以及将来任何重抽已处理消息的路径。
        #
        # ⚠️ **刻意不碰 `refine_runs`**：那些行的 ok 记录是**既有事实**，
        # 把它改写成 discarded 会篡改 M1 出口标准赖以成立的账目。
        tombstones = _tombstoned_msg_ids()
        if tombstones:
            kept = [m for m in messages if m.msg_id not in tombstones]
            stats.skipped_deleted = len(messages) - len(kept)
            messages = kept
```

`stats.scanned` 保持它在过滤**之后**的语义（"这轮真正要处理多少条"）——
把 `stats.scanned = len(messages)` 留在原处即可。

并把 `_tombstoned_msg_ids` 加在 `_record_error` 附近：

```python
def _tombstoned_msg_ids() -> frozenset[int]:
    """读人工干预层的墓碑（软删事件对应的源消息 id）。

    ⚠️ 读不到一律返回空集——overlay 缺失**不该**让 refine 跑不起来。
    最坏后果只是"这次重抽把某条复活了"，用户再删一次即可；
    而在这里抛异常会让整条每日管线停摆，代价大得多。
    """
    from . import overrides

    try:
        conn = overrides.connect()
        try:
            return overrides.deleted_msg_ids(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return frozenset()
```

- [ ] **Step 4: 在进度行里报告跳过数**

`refine()` 里那行 `on_progress(f"[refine] 扫描 ...")` 之后补一行：

```python
        if stats.skipped_deleted:
            on_progress(
                f"[refine] 其中 {stats.skipped_deleted:,} 条已软删，跳过重抽（D15 墓碑）"
            )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_refine.py -v && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 6: ⭐ 变异反证（本任务唯一的真判据）**

**照 Global Constraint 4 的 CRLF 纪律执行**。写一个脚本文件（**不要用命令行传中文锚点**——
Git Bash 会静默打空），内容：

```python
# _mutate_t6.py —— 变异反证：把墓碑过滤整段删掉，测试必须变红
import pathlib, subprocess, sys, os

ROOT = pathlib.Path(__file__).resolve().parent
src = ROOT / "vigil" / "refine.py"
backup = src.read_text(encoding="utf-8", newline="")

ANCHOR_START = "        tombstones = _tombstoned_msg_ids()"
ANCHOR_END = "            messages = kept\n"
assert ANCHOR_START in backup, "锚点未命中——替换会静默失效，停下"
assert backup.count(ANCHOR_START) == 1, "锚点不唯一——改错地方的风险，停下"

i = backup.index(ANCHOR_START)
j = backup.index(ANCHOR_END, i) + len(ANCHOR_END)
mutated = backup[:i] + backup[j:]

# ⚠️ 替换生效的锚点断言（M4 教训：光打印不够）
assert "tombstones = _tombstoned_msg_ids()" not in mutated, "替换没生效，停下"

src.write_text(mutated, encoding="utf-8", newline="")
try:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_refine.py", "-k",
         "tombstoned or skipped_deleted", "-q"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    print(r.stdout[-1500:])
    print("RETURNCODE", r.returncode)
finally:
    src.write_text(backup, encoding="utf-8", newline="")
    import subprocess as sp
    print("git diff 干净?", sp.run(["git", "diff", "--quiet", "vigil/refine.py"],
                                   cwd=ROOT).returncode == 0)
```

Run: `uv run python _mutate_t6.py`
Expected:
- 打印 `RETURNCODE 1`（测试**变红**）
- 红的必须是 `test_refine_skips_tombstoned_messages_on_redo` 的
  `assert stats.skipped_deleted == 1` / `assert calls == []` **本身**
- **若红在 import 错 / 语法错上，那是机械层面的失败，不构成有效反证**——重做
- `git diff 干净? True`

**做完删掉 `_mutate_t6.py`。**

- [ ] **Step 7: 阳性对照**

把变异**反过来**：把 `if tombstones:` 改成 `if False:`（即过滤永不执行），
测试**也必须变红**。若两次都红，说明判据真的在测那件事。

（理由：M2 第十节「变异反证必须加阳性对照」——单侧变异在**整段不存在**时也会"看起来有效"。）

- [ ] **Step 8: Commit**

```bash
git add vigil/refine.py tests/test_refine.py
git commit -m "feat(refine): 读 overlay 墓碑，软删条目永不被 --redo 复活（D15）"
```

---

## Task 7: 人物配置 `config/persons.toml`

**为什么**：用户要求「新增监视人物」+「按人物筛选」。

**⚠️ 两个实测事实决定了本任务的形状**（spec §1.4）：

1. **`uid ↔ uin` 是 1:1 可互查的**：4,772 个 uid / 4,681 个 uin，uid→uin 只有 6 个例外、
   uin→uid 只有 1 个例外。所以**配置里只存 `uin`（人类口径的 QQ 号）**，
   `uid` 在查询时经 `sender_names` 反查——**不落配置**，避免两者脱节。
2. **`uin = 0` 是匿名哨兵**（98 行），**必须拒绝录入**。
   另有 2.6% 的消息 `sender_uid` 为空（匿名），它们不该被任何人物筛选中。

**Files:**
- Create: `config/persons.toml`
- Modify: `vigil/config.py`
- Test: `tests/test_config.py`（若不存在则新建）

**Interfaces:**
- Consumes: 无
- Produces:
  - `config.Person(uin: int, label: str, note: str = "")`
  - `config.DEFAULT_PERSONS: pathlib.Path`
  - `config.load_persons(path=None) -> tuple[Person, ...]`（**文件不存在返回空元组**，不报错）
  - `config.save_persons(persons: Sequence[Person], path=None) -> None`（**原子写**）
  - `config.atomic_write_text(path: pathlib.Path, text: str) -> None`

- [ ] **Step 1: 写失败测试**

新建/追加 `tests/test_config.py`：

```python
"""配置层：persons.toml 的加载、校验与原子写。"""

import pathlib

import pytest

from vigil import config


def _write(tmp_path, text):
    p = tmp_path / "persons.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_persons_missing_file_is_empty(tmp_path):
    """没有这个文件是**合法状态**（一个人都没监视），不是错误。"""
    assert config.load_persons(tmp_path / "nope.toml") == ()


def test_load_persons_roundtrip(tmp_path):
    p = _write(tmp_path, '[[persons]]\nuin = 2874448217\nlabel = "卡王"\n')
    got = config.load_persons(p)
    assert got == (config.Person(uin=2874448217, label="卡王", note=""),)


def test_load_persons_rejects_zero_uin(tmp_path):
    """⚠️ uin=0 是匿名哨兵（实测真库 98 行），必须拒绝——否则"监视匿名者"是个无意义操作。"""
    p = _write(tmp_path, '[[persons]]\nuin = 0\nlabel = "匿名"\n')
    with pytest.raises(config.ConfigError, match="匿名"):
        config.load_persons(p)


def test_load_persons_rejects_duplicate_uin(tmp_path):
    p = _write(
        tmp_path,
        '[[persons]]\nuin = 1\nlabel = "甲"\n\n[[persons]]\nuin = 1\nlabel = "乙"\n',
    )
    with pytest.raises(config.ConfigError, match="重复"):
        config.load_persons(p)


def test_load_persons_rejects_empty_label(tmp_path):
    p = _write(tmp_path, '[[persons]]\nuin = 1\nlabel = ""\n')
    with pytest.raises(config.ConfigError, match="label"):
        config.load_persons(p)


def test_save_persons_is_roundtrippable(tmp_path):
    p = tmp_path / "persons.toml"
    people = (config.Person(uin=111, label="甲", note="备注"),)
    config.save_persons(people, p)
    assert config.load_persons(p) == people


def test_save_persons_replaces_not_appends(tmp_path):
    """⚠️ 保存是**整体替换**——追加语义会让"删掉一个人"永远做不到。"""
    p = tmp_path / "persons.toml"
    config.save_persons((config.Person(uin=1, label="甲"),), p)
    config.save_persons((config.Person(uin=2, label="乙"),), p)
    assert config.load_persons(p) == (config.Person(uin=2, label="乙"),)


def test_atomic_write_leaves_no_temp_file(tmp_path):
    p = tmp_path / "x.txt"
    config.atomic_write_text(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"
    assert [f.name for f in tmp_path.iterdir()] == ["x.txt"]


def test_atomic_write_failure_leaves_original_intact(tmp_path, monkeypatch):
    """⚠️ 写失败时**原文件必须一个字都没变**——这是原子写的全部意义。"""
    p = tmp_path / "x.txt"
    config.atomic_write_text(p, "原始内容")

    import os as _os

    def boom(*a, **k):
        raise OSError("模拟磁盘满")

    monkeypatch.setattr(_os, "replace", boom)
    with pytest.raises(OSError):
        config.atomic_write_text(p, "新内容")
    assert p.read_text(encoding="utf-8") == "原始内容"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: `AttributeError: module 'vigil.config' has no attribute 'load_persons'`

- [ ] **Step 3: 实现**

`vigil/config.py`：把顶部 import 改成

```python
import os
import pathlib
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
```

并在 `DEFAULT_ENV` 之后加：

```python
DEFAULT_PERSONS = REPO_ROOT / "config" / "persons.toml"
```

在 `load_config` **之后**追加：

```python
@dataclass(frozen=True)
class Person:
    """一个被监视的人物。**键是 uin（QQ 号）**——uid 在查询时反查（见模块 docstring）。"""

    uin: int
    label: str
    note: str = ""


def atomic_write_text(path: pathlib.Path, text: str) -> None:
    """原子写文本：同目录临时文件 → fsync → ``os.replace``。

    ⚠️ **不许**写成 ``path.write_text(...)``：那是"截断 + 写"，
    中途失败（磁盘满、进程被杀）会留下**半个文件**——配置直接废掉。
    ``os.replace`` 在同一文件系统上是原子替换，Windows 上也成立。

    ⚠️ 临时文件必须与目标**同目录**（``os.replace`` 不跨卷）。
    ⚠️ 失败路径要清掉临时文件：留下一堆 ``.tmp`` 会污染 `config/`，
    而 `config/` 是要进 git 的。
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_persons(path: pathlib.Path | None = None) -> tuple[Person, ...]:
    """读监视人物名单。

    ⚠️ **文件不存在返回空元组**（与 `load_config` 的快速失败不同）：
    "一个人都没监视"是完全合法的状态，而 `load_config` 面对的是一份**必需**的配置。

    ⚠️ `uin = 0` 是匿名哨兵（实测真库 98 行），**必须拒绝**——
    匿名者没有身份，把它加进监视名单是个不会生效的操作，越早暴露越好。
    """
    target = path or DEFAULT_PERSONS
    if not target.is_file():
        return ()

    with open(target, "rb") as f:
        raw = tomllib.load(f)

    out: list[Person] = []
    seen: set[int] = set()
    for entry in raw.get("persons", []):
        uin = entry.get("uin")
        if not isinstance(uin, int) or uin <= 0:
            raise ConfigError(
                f"{target}: 人物 uin 必须为正整数；0 是匿名哨兵，不能监视。实际是 {uin!r}"
            )
        if uin in seen:
            raise ConfigError(f"{target}: uin {uin} 重复出现")
        label = str(entry.get("label", "")).strip()
        if not label:
            raise ConfigError(f"{target}: uin {uin} 缺 label（label 是给人看的名字）")
        seen.add(uin)
        out.append(Person(uin=uin, label=label, note=str(entry.get("note", "")).strip()))
    return tuple(out)


def save_persons(persons: Sequence[Person], path: pathlib.Path | None = None) -> None:
    """整体替换写出人物名单（原子）。

    ⚠️ 是**整体替换**不是追加：追加语义下"删掉一个人"永远做不到。
    """
    target = path or DEFAULT_PERSONS
    lines = [
        "# VIGIL 监视人物名单",
        "#",
        "# ── 怎么加人 ─────────────────────────────────────────────",
        "#   1. 在前端「按人物筛选」里添加，或手工往下面追加一段 [[persons]]",
        "#   2. uin 是 QQ 号。不要填 0（那是匿名哨兵）。",
        "#   3. 本文件由程序原子写出；手工改也行，下次保存会整体覆盖。",
        "#",
        "# label 是你自己起的名字（不是群昵称快照）——群昵称会变，label 不会。",
        "",
    ]
    for p in persons:
        lines.append("[[persons]]")
        lines.append(f"uin = {p.uin}")
        lines.append(f"label = {_toml_str(p.label)}")
        if p.note:
            lines.append(f"note = {_toml_str(p.note)}")
        lines.append("")
    atomic_write_text(target, "\n".join(lines))


def _toml_str(value: str) -> str:
    """TOML 基本字符串。只转义反斜杠与双引号——够用且不会引入意外转义。"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
```

- [ ] **Step 4: 建初始文件**

```bash
cat > config/persons.toml <<'EOF'
# VIGIL 监视人物名单
#
# ── 怎么加人 ─────────────────────────────────────────────
#   1. 在前端「按人物筛选」里添加，或手工往下面追加一段 [[persons]]
#   2. uin 是 QQ 号。不要填 0（那是匿名哨兵）。
#   3. 本文件由程序原子写出；手工改也行，下次保存会整体覆盖。
#
# label 是你自己起的名字（不是群昵称快照）——群昵称会变，label 不会。
EOF
git add config/persons.toml
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_config.py -v && uv run pytest -q`
Expected: 全部通过

> ⚠️ 若 `tests/test_config.py` 原本不存在，`git add` 时别漏了它。
> 若它原本存在（例如测 `load_config`），**追加而不是覆盖**。

- [ ] **Step 6: Commit**

```bash
git add vigil/config.py config/persons.toml tests/test_config.py
git commit -m "feat(config): persons.toml——uin 主键、拒绝匿名哨兵、原子写"
```

---

## Task 8: API —— 多值筛选 + 人物维度 + 三个写端点

**为什么**：spec §四 的 `#3`（类目多选，`kind IN (...)`）与 `#4`（人物维度，
维度内并集 × 维度间交集），以及 `#4/⑪/⑫` 的写端点（改分类 / 删除 / 撤销）。

**⚠️ 写端点只写 overlay，绝不写 `vigil.db`**（D11）。这是本任务最容易被破坏的约束。

**⚠️ `_ITEM_COLS` 加一列 ⇒ `_to_api_item` 的解包元组与 `ApiItem` dataclass 必须同时改**。
三处不同步 = `ValueError: too many values to unpack`，而且**只会在真跑起来时暴露**。

**Files:**
- Modify: `vigil/store.py`（`_ITEM_COLS`、`_to_api_item`、`ApiItem`、`_item_filters`、`search_items`）
- Modify: `vigil/api.py`（三个新端点 + 改现有查询参数）
- Test: `tests/test_api.py`、`tests/test_store.py`

**Interfaces:**
- Consumes: `config.load_persons/save_persons/Person`（Task 7）、`overrides.*`（Task 4）
- Produces:
  - `store.ApiItem.actor_uin: int | None`（新字段）
  - `store.search_items(..., kinds: Sequence[str] | None = None, actor_uins: Sequence[int] | None = None)`
    —— **`kind=` 单值参数被 `kinds=` 取代**；**保留 `kind=` 作为兼容别名会掩盖漏改的调用方，故不保留**
  - `GET /api/items?kind=a&kind=b&person=1&person=2`
  - `GET /api/persons` → `{"persons": [{"uin","label","note","count"}]}`
  - `POST /api/persons` body `{"uin","label","note"}` → 201
  - `DELETE /api/persons/{uin}` → 204
  - `POST /api/items/{item_id}/kind` body `{"kind": "..."}` → `{"edit_id": N}`
  - `DELETE /api/items/{item_id}` → `{"edit_id": N}`
  - `POST /api/undo` body `{"edit_id": N | null}` → `{"undone": bool}`

- [ ] **Step 1: 写失败测试（store 层）**

追加到 `tests/test_store.py`：

```python
# ── Task 8：多值与人物维度 ────────────────────────────────────────


def _seed_with_sender(conn, *, title, kind, ts, group_id=100, uid="u_1", uin=111):
    from vigil.store import ExtractedItem

    conn.execute(
        "INSERT OR REPLACE INTO sender_names (group_id, uid, group_nick, qq_nick, uin)"
        " VALUES (?,?,?,?,?)",
        (group_id, uid, "昵称", "QQ昵称", uin),
    )
    conn.execute(
        "INSERT INTO items (kind, title, detail, event_ts, deadline_ts, group_id,"
        " actor_uid, place, links, amount, confidence, model, prompt_ver, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, title, None, ts, None, group_id, uid, None, "[]", None, 0.9, "m", "v3", ts),
    )
    return conn.execute("SELECT MAX(item_id) FROM items").fetchone()[0]


def test_search_items_accepts_multiple_kinds(memdb):
    store.ensure_schema(memdb)
    _seed_with_sender(memdb, title="甲", kind="notice", ts=1)
    _seed_with_sender(memdb, title="乙", kind="academic", ts=2)
    _seed_with_sender(memdb, title="丙", kind="life", ts=3)

    _, total = store.search_items(memdb, kinds=["notice", "academic"], limit=50, offset=0)
    assert total == 2


def test_search_items_multiple_persons_is_union(memdb):
    """维度内是**并集**。"""
    store.ensure_schema(memdb)
    _seed_with_sender(memdb, title="甲", kind="notice", ts=1, uid="u_a", uin=111)
    _seed_with_sender(memdb, title="乙", kind="notice", ts=2, uid="u_b", uin=222)
    _seed_with_sender(memdb, title="丙", kind="notice", ts=3, uid="u_c", uin=333)

    _, total = store.search_items(memdb, actor_uins=[111, 222], limit=50, offset=0)
    assert total == 2


def test_kinds_and_persons_are_intersection(memdb):
    """⭐ 维度**间**是**交集**——这是 spec §四 #4 的原始要求，别写成并集。"""
    store.ensure_schema(memdb)
    _seed_with_sender(memdb, title="甲", kind="notice", ts=1, uid="u_a", uin=111)
    _seed_with_sender(memdb, title="乙", kind="academic", ts=2, uid="u_a", uin=111)
    _seed_with_sender(memdb, title="丙", kind="notice", ts=3, uid="u_b", uin=222)

    _, total = store.search_items(
        memdb, kinds=["notice"], actor_uins=[111], limit=50, offset=0
    )
    assert total == 1


def test_actor_uin_exposed_on_api_item(memdb):
    store.ensure_schema(memdb)
    _seed_with_sender(memdb, title="甲", kind="notice", ts=1, uid="u_a", uin=111)
    items, _ = store.search_items(memdb, limit=50, offset=0)
    assert items[0].actor_uin == 111


def test_actor_uin_is_none_for_anonymous(memdb):
    """匿名消息（sender_uid 为空）不该匹配任何人物筛选。"""
    store.ensure_schema(memdb)
    _seed_with_sender(memdb, title="甲", kind="notice", ts=1, uid="", uin=None)
    items, _ = store.search_items(memdb, limit=50, offset=0)
    assert items[0].actor_uin is None
    assert store.search_items(memdb, actor_uins=[111], limit=50, offset=0)[1] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_store.py -k "multiple_kinds or multiple_persons or intersection or actor_uin" -v`
Expected: `TypeError: search_items() got an unexpected keyword argument 'kinds'`

- [ ] **Step 3: 实现 store 层**

`vigil/store.py` 的 `ApiItem` dataclass 里，`actor` 之后加：

```python
    actor_uin: int | None
```

`_ITEM_COLS` 的 `actor` 那一列之后加 `sn.uin AS actor_uin`：

```python
_ITEM_COLS = (
    "i.item_id, COALESCE(ost.kind, i.kind) AS kind, i.title, i.detail, i.event_ts,"
    " i.deadline_ts, i.group_id,"
    " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS actor,"
    " sn.uin AS actor_uin,"
    " i.place, i.amount, i.links,"
    " (SELECT COUNT(*) FROM item_sources src WHERE src.item_id = i.item_id)"
    "   AS source_count"
)
```

`_to_api_item` 的解包与构造改成：

```python
def _to_api_item(row: tuple) -> ApiItem:
    (item_id, kind, title, detail, event_ts, deadline_ts, group_id,
     actor, actor_uin, place, amount, links, source_count) = row
    return ApiItem(
        item_id=item_id,
        kind=kind,
        title=title,
        detail=detail,
        event_ts=event_ts,
        deadline_ts=deadline_ts,
        group_id=group_id,
        actor=actor or None,
        actor_uin=int(actor_uin) if actor_uin is not None else None,
        place=place,
        amount=amount,
        links=_parse_links(links),
        source_count=int(source_count),
    )
```

`_item_filters` 整体替换为：

```python
def _item_filters(
    *,
    kinds: Sequence[str] | None,
    actor_uins: Sequence[int] | None,
    since: int | None,
    until: int | None,
    group: int | None,
    q: str | None,
) -> tuple[list[str], list[object]]:
    """拼 WHERE 片段。

    ⚠️ **维度内并集、维度间交集**（spec §四 #4）：
    `kinds` 之间是 OR、`actor_uins` 之间是 OR，而两组之间是 AND。
    写成"全部 OR 到一起"是最容易犯的错，也是这个函数唯一的语义要点。
    """
    where: list[str] = [_NOT_DELETED]
    params: list[object] = []

    if kinds:
        marks = ",".join("?" * len(kinds))
        where.append(f"COALESCE(ost.kind, i.kind) IN ({marks})")
        params.extend(kinds)
    if actor_uins:
        marks = ",".join("?" * len(actor_uins))
        where.append(f"sn.uin IN ({marks})")
        params.extend(actor_uins)
    if since is not None:
        where.append("i.event_ts >= ?")
        params.append(since)
    if until is not None:
        where.append("i.event_ts < ?")
        params.append(until)
    if group is not None:
        where.append("i.group_id = ?")
        params.append(group)
    if q is not None:
        q = _strip_controls(q)
    if q:
        if len(q) >= MIN_TRIGRAM:
            where.append(
                "i.item_id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)"
            )
            params.append(_fts_phrase(q))
        else:
            like = f"%{_escape_like(q)}%"
            where.append(
                "(i.title LIKE ? ESCAPE '\\'"
                " OR IFNULL(i.detail, '') LIKE ? ESCAPE '\\')"
            )
            params += [like, like]
    return where, params
```

`search_items` 的签名与调用改成：

```python
def search_items(
    conn: sqlite3.Connection,
    *,
    kinds: Sequence[str] | None = None,
    actor_uins: Sequence[int] | None = None,
    since: int | None = None,
    until: int | None = None,
    group: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ApiItem], int]:
    """查条目，返回 ``(当页, 符合条件的总数)``。

    排序是 ``event_ts DESC, item_id DESC``（新的在前）——信息流的默认读法。
    ⚠️ 与 ``window_items`` 的 ASC 不同是**故意的**：日报按时间顺着读，
    信息流按时间倒着看。两处都不许「顺手改成一致」。
    """
    _ensure_overlay(conn)
    where, params = _item_filters(
        kinds=kinds, actor_uins=actor_uins,
        since=since, until=until, group=group, q=q,
    )
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = int(
        conn.execute(
            "SELECT COUNT(*) FROM items i"
            " LEFT JOIN sender_names sn"
            "   ON sn.group_id = i.group_id AND sn.uid = i.actor_uid"
            " LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id"
            f"{clause}",
            params,
        ).fetchone()[0]
    )
    rows = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS}{clause}"
        " ORDER BY i.event_ts DESC, i.item_id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_to_api_item(r) for r in rows], total
```

> ⚠️ COUNT 的 FROM 必须**与 `_ITEM_JOINS` 一致**（多值人物筛选用到了 `sn.uin`），
> 否则会 `no such column: sn.uin`。这里刻意把 JOIN 展开写，就是要让两处并排可见。

并在 `vigil/store.py` 顶部确认有 `from collections.abc import Sequence`（没有就补）。

- [ ] **Step 4: 修 `api.py` 的调用点（`kinds` 改名）**

`vigil/api.py` 的 `api_items` 改成：

```python
    @app.get("/api/items")
    def api_items(
        kind: list[str] = Query(default=[]),
        person: list[int] = Query(default=[]),
        since: str | None = None,
        until: str | None = None,
        group: int | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=MAX_LIMIT),
        offset: int = Query(0, ge=0),
    ) -> dict:
        # since/until 都按**包含该日**理解：内部窗口右端取次日 00:00（左闭右开）。
        q = (q or "").strip()
        con = connect()
        try:
            items, total = store.search_items(
                con,
                kinds=kind or None,
                actor_uins=person or None,
                since=_day_start(since) if since else None,
                until=_day_start(until, plus_days=1) if until else None,
                group=group,
                q=q or None,
                limit=limit,
                offset=offset,
            )
        finally:
            con.close()
        return {
            "items": [item_out(it) for it in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
```

`item_out` 里加一列：

```python
            "actor_uin": it.actor_uin,
```

- [ ] **Step 5: 修被 `kinds` 改名撞坏的调用点**

已实测，**生产代码只有 1 处、测试只有 1 处**（不是"到处都是"）：

| 位置 | 现状 | 改成 |
|---|---|---|
| `vigil/api.py:170` | `kind=kind or None,` | Step 4 已改 |
| `tests/test_store.py:842` | `store.search_items(conn, kind="job")[1] == 1` | `store.search_items(conn, kinds=["job"])[1] == 1` |

`_item_filters` 也只有 `store.py:796` 一个调用点（`search_items` 内），一并改。

Run:
```bash
grep -rn "kind=" vigil/ tests/ --include=*.py | grep -i "search_items"
uv run pytest -q
```
Expected: grep 只剩新写法；测试全绿

> ⚠️ **不要**给 `search_items` 保留 `kind=` 兼容别名。留了的话，漏改的调用点
> 会静默退化成"单值筛选"而**测试照样绿**——那正是要防的形态。

- [ ] **Step 6: 写失败测试（API 层：写端点）**

追加到 `tests/test_api.py`：

**⚠️ 本任务直接用 `tests/test_api.py` 里**已经存在**的两个夹具**：
`db_path`（`test_api.py:58-82`，临时库里已有 item 1「选课通知」+ 源消息 11）与
`client`（`test_api.py:84-87`，`TestClient(create_app(_config_for(db_path)))`）。
**不要另造一套建库装置。**

```python
# ── Task 8：写端点（只写 overlay，绝不写 vigil.db） ──────────────


def test_write_kind_does_not_touch_vigil_db(client, db_path):
    """⭐ D11 的机械守卫：写端点跑完，`data/vigil.db` 的字节必须**一点没变**。

    ⚠️ 这不是"检查没报错"——是把**整个文件的哈希**前后比。
    任何绕过 overlay 直接写主库的实现，都会在这里变红。
    """
    import hashlib

    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    r = client.post("/api/items/1/kind", json={"kind": "life"})
    assert r.status_code == 200
    assert r.json()["edit_id"] > 0

    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before, (
        "⚠️ 写端点动了 data/vigil.db——D11 的机械保证被打破"
    )


def test_set_kind_is_visible_in_the_list(client):
    assert client.get("/api/items").json()["items"][0]["kind"] == "academic"
    client.post("/api/items/1/kind", json={"kind": "life"})
    assert client.get("/api/items").json()["items"][0]["kind"] == "life"


def test_deleted_item_is_hidden_from_list(client):
    assert client.get("/api/items").json()["total"] == 1
    assert client.delete("/api/items/1").status_code == 200
    assert client.get("/api/items").json()["total"] == 0
    assert client.get("/api/items/1").status_code == 404


def test_delete_also_hides_it_from_the_digest(client, db_path):
    """⚠️ R13 的典型形态：只改列表不改日报 ⇒「界面上删了、日报里还在」。"""
    import sqlite3 as _sq

    from vigil import store as _store

    con = _sq.connect(str(db_path))
    _store.save_digest(
        con, window_from=1, window_to=2, body_md="x", model="m",
        prompt_ver="v1", item_ids=[1],
    )
    con.close()

    did = client.get("/api/digests").json()["digests"][0]["digest_id"]
    assert len(client.get(f"/api/digests/{did}").json()["items"]) == 1

    client.delete("/api/items/1")
    assert client.get(f"/api/digests/{did}").json()["items"] == []


def test_undo_restores_item(client):
    client.delete("/api/items/1")
    assert client.get("/api/items").json()["total"] == 0
    assert client.post("/api/undo", json={"edit_id": None}).json()["undone"] is True
    assert client.get("/api/items").json()["total"] == 1


def test_undo_with_nothing_to_undo(client):
    assert client.post("/api/undo", json={"edit_id": None}).json()["undone"] is False


def test_person_crud_round_trip(client, tmp_path, monkeypatch):
    """⚠️ `load_persons` 走的是 `REPO_ROOT / "config" / "persons.toml"`，
    必须把它挪开——否则这个测试会**写进仓库里真实的配置文件**。"""
    import pathlib

    from vigil import api as _api

    monkeypatch.setattr(
        _api, "REPO_ROOT", tmp_path / "fake_root"
    )
    (tmp_path / "fake_root" / "config").mkdir(parents=True)

    assert client.get("/api/persons").json()["persons"] == []
    r = client.post("/api/persons", json={"uin": 111, "label": "甲", "note": ""})
    assert r.status_code == 201
    body = client.get("/api/persons").json()["persons"]
    assert body[0]["label"] == "甲"
    assert client.delete("/api/persons/111").status_code == 204
    assert client.get("/api/persons").json()["persons"] == []


def test_person_rejects_anon_sentinel(client, tmp_path, monkeypatch):
    from vigil import api as _api

    monkeypatch.setattr(_api, "REPO_ROOT", tmp_path / "fake_root")
    r = client.post("/api/persons", json={"uin": 0, "label": "匿名", "note": ""})
    assert r.status_code == 400
```

> ⚠️ 上面 `test_person_crud_round_trip` 用 `monkeypatch.setattr(_api, "REPO_ROOT", ...)`
> ——**它成立的前提是 `api.py` 里写的是 `REPO_ROOT / "config" / "persons.toml"`，
> 而不是把路径在 `create_app` 时就冻进闭包**。这与 `WEB_DIST` 的既有教训是同一个
> （`api.py:289-292` 的 docstring 专门记过这件事）。**Step 8 实现时必须照此办理。**

- [ ] **Step 7: 跑测试确认失败**

Run: `uv run pytest tests/test_api.py -k "kind_does_not_touch or hidden_from_list or undo_restores or person_crud or rejects_anon" -v`
Expected: **失败**（端点 404 或 `NotImplementedError`——后者说明占位还没按既有夹具替换掉）

- [ ] **Step 8: 实现 `api.py` 的写端点**

`vigil/api.py` 顶部 import 补：

```python
from fastapi import Body
from pydantic import BaseModel

from . import overrides
from .categories import load_categories, Category
from .config import REPO_ROOT, Config, Person, load_persons, save_persons
```

> ⚠️ `load_categories` 已有，别重复 import；`Category` 只有在类型注解里用到才加。

在 `create_app` 里，`cat_by_slug = ...` 之后加：

```python
    # ⚠️ overlay 的**文件**在这里就位（D11 允许 Web 写 overlay）。之后每个
    # 请求的 `store._ensure_overlay(conn)` 才能无条件 ATTACH。
    # ⚠️ **不能**在这里调 `store.ensure_schema`——那是写 `vigil.db`，
    # 而本文件的连接是 `mode=ro`（见 connect() 的 docstring）。
    overrides.ensure_schema()

    def persons_path() -> pathlib.Path:
        """⚠️ 路径**每次现读** `REPO_ROOT` 全局，不许在 `create_app` 时算好冻进闭包。

        这与 `WEB_DIST` 的既有教训是同一件事（`api.py:289-292` 的 docstring 专门记过）：
        冻住的话，测试里 `monkeypatch.setattr(api, "REPO_ROOT", tmp_path)` 就够不着它，
        于是那些测试**测的还是仓库里真实的 `config/persons.toml`**——
        **会往真仓库里写人**，而且因为它们总能读到点什么、于是全都变成「怎么改都绿」的空守卫。
        """
        return REPO_ROOT / "config" / "persons.toml"
```

并在 `create_app` 顶部 import 补 `import pathlib`。

在 `api_item` **之后**加四个端点：

```python
    @app.post("/api/items/{item_id}/kind")
    def api_set_kind(item_id: int, body: dict = Body(...)) -> dict:
        """改一条条目的类目。**只写 overlay**（D11）。"""
        kind = str(body.get("kind", "")).strip()
        if not kind:
            raise HTTPException(status_code=400, detail="kind 不能为空")
        con = connect()
        try:
            if store.get_item(con, item_id) is None:
                raise HTTPException(status_code=404, detail=f"没有这条条目：{item_id}")
        finally:
            con.close()
        ov = overrides.connect()
        try:
            return {"edit_id": overrides.set_kind(ov, item_id=item_id, kind=kind)}
        finally:
            ov.close()

    @app.delete("/api/items/{item_id}")
    def api_delete_item(item_id: int) -> dict:
        """软删一条条目（D15）。`msg_id` 从**源消息**取，用于"永不被重抽复活"。"""
        con = connect()
        try:
            if store.get_item(con, item_id) is None:
                raise HTTPException(status_code=404, detail=f"没有这条条目：{item_id}")
            srcs = store.source_messages(con, item_id)
        finally:
            con.close()
        ov = overrides.connect()
        try:
            return {
                "edit_id": overrides.delete_item(
                    ov, item_id=item_id, msg_id=srcs[0].msg_id if srcs else None
                )
            }
        finally:
            ov.close()

    @app.post("/api/undo")
    def api_undo(body: dict = Body(default={})) -> dict:
        """撤销一条编辑。`edit_id` 缺省 = 撤最近一条。"""
        target = body.get("edit_id") if isinstance(body, dict) else None
        ov = overrides.connect()
        try:
            if target is None:
                last = overrides.last_edit(ov)
                if last is None:
                    return {"undone": False}
                target = last[0]
            return {"undone": overrides.undo(ov, edit_id=int(target))}
        finally:
            ov.close()

    @app.get("/api/persons")
    def api_persons() -> dict:
        people = load_persons(persons_path())
        con = connect()
        try:
            counts: dict[int, int] = {}
            for p in people:
                _, n = store.search_items(
                    con, actor_uins=[p.uin], limit=1, offset=0
                )
                counts[p.uin] = n
        finally:
            con.close()
        return {
            "persons": [
                {"uin": p.uin, "label": p.label, "note": p.note,
                 "count": counts.get(p.uin, 0)}
                for p in people
            ]
        }

    @app.post("/api/persons", status_code=201)
    def api_add_person(body: dict = Body(...)) -> dict:
        uin = body.get("uin")
        if not isinstance(uin, int) or uin <= 0:
            raise HTTPException(
                status_code=400,
                detail="uin 必须是正整数（0 是匿名哨兵，不能监视）",
            )
        label = str(body.get("label", "")).strip()
        if not label:
            raise HTTPException(status_code=400, detail="label 不能为空")
        path = persons_path()
        people = [p for p in load_persons(path) if p.uin != uin]
        people.append(Person(uin=uin, label=label, note=str(body.get("note", ""))))
        save_persons(people, path)
        return {"uin": uin, "label": label}

    @app.delete("/api/persons/{uin}", status_code=204)
    def api_del_person(uin: int) -> None:
        path = persons_path()
        people = tuple(p for p in load_persons(path) if p.uin != uin)
        save_persons(people, path)
        return None
```

- [ ] **Step 9: 跑测试确认通过 + 全量**

Run: `uv run pytest tests/test_api.py -v && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 10: ⭐ 反向验证 D11 守卫（Global Constraint，M4 §二十六的形态）**

把 `api_set_kind` 里的 `overrides.connect()` **临时**改成 `sqlite3.connect(db_uri.replace("mode=ro", "mode=rwc"))`
（即故意让它写主库），跑 `test_write_kind_does_not_touch_vigil_db`。
Expected: **必须变红**。若它仍然绿，说明那个守卫是**空守卫**——先修守卫再往下走。

**做完把改动还原，并 `git diff` 确认干净。**

- [ ] **Step 11: Commit**

```bash
git add vigil/store.py vigil/api.py tests/test_store.py tests/test_api.py
git commit -m "feat(api): 多值筛选(维度内并集×维度间交集) + 人物维度 + 三个写端点(只写 overlay)"
```

---

## Task 9: 存量重判命令 `vigil repass`（D10）

**为什么**：prompt v3 与两道新闸门**只对未来的抽取生效**。真库里已有的 46 条广告 item
（占 14.0%，7/8 月高达 26%/28%）不会自己消失。

**⚠️ 语义是「只删不换」，不是「整批替换」**——实测（spec R9）：`digest_items` 66 行指向 66 条，
其中**那 46 条广告被引用的 = 0 条**，但另外 66 条**是**被引用的。
整批替换（删旧插新）会让这 66 条悬空，**同时把 item_id 全部翻新**。

**⚠️ 例外是字段降级**：spec 说"保留旧 item 不动"，指的是**不重建**（避免 item_id 翻新）。
`UPDATE items SET place=NULL` 不翻新 id，所以**存量条目上未经新闸门的 `place`/`deadline_ts`
要在这里降级同步**——否则 M5 出口判据 3（不再有 `deadline_ts < event_ts`）无法达成。

**Files:**
- Create: `vigil/repass.py`、`tests/test_repass.py`
- Modify: `vigil/store.py`（加 `items_used_in_digests`、`existing_items_for_messages`、`delete_items`、`downgrade_fields`）
- Modify: `vigil/cli.py`（新子命令）

**Interfaces:**
- Consumes: `refine.PROMPT_VERSION`、`refine.build_system_prompt`、`refine._to_item`（**复用，不重写**）、
  `deadline.place_supported`、`deadline.deadline_sane`
- Produces:
  - `repass.RepassStats(deleted, kept, skipped_referenced, downgraded, errors, input_tokens, output_tokens)`
  - `repass.repass(config, *, api_key, conn=None, model=..., budget_tokens=None, on_progress=print) -> RepassStats`
  - `store.items_used_in_digests(conn, item_ids: Sequence[int]) -> frozenset[int]`
  - `store.delete_items(conn, item_ids: Sequence[int]) -> int`
  - `store.downgrade_item_fields(conn, updates: Sequence[tuple[int, str | None, int | None]]) -> int`
    （`(item_id, place, deadline_ts)`）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_repass.py`：

```python
"""存量重判：只删不换 + 字段降级同步。"""

import sqlite3

import pytest

from vigil import overrides, repass, store


@pytest.fixture
def con():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    yield conn
    conn.close()


def _msg(conn, msg_id, content, *, group_id=100, ts=1_700_000_000, uid="u_1"):
    conn.execute(
        "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
        " VALUES (?,?,?,?,?)",
        (msg_id, group_id, ts, uid, content),
    )
    conn.commit()


def _item(conn, msg_id, *, title="标题", kind="notice", event_ts=1_700_000_000,
          group_id=100, place=None, deadline_ts=None):
    cur = conn.execute(
        "INSERT INTO items (kind, title, detail, event_ts, deadline_ts, group_id,"
        " actor_uid, place, links, amount, confidence, model, prompt_ver, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, title, None, event_ts, deadline_ts, group_id, "u_1", place,
         "[]", None, 0.9, "m", "v2", event_ts),
    )
    conn.execute(
        "INSERT INTO item_sources (item_id, msg_id) VALUES (?,?)",
        (cur.lastrowid, msg_id),
    )
    conn.commit()
    return cur.lastrowid


def test_plan_deletes_item_whose_message_no_longer_produces(con):
    """v3 判为推广 ⇒ 对应旧 item 该删。"""
    _msg(con, 1, "校园卡办理，需要的联系我")
    iid = _item(con, 1, title="校园卡办理")
    plan = repass.build_plan(con, verdicts={1: 0})
    assert plan.to_delete == [iid]


def test_plan_keeps_item_whose_message_still_produces(con):
    _msg(con, 1, "最早9.5")
    iid = _item(con, 1, title="宿舍最早入住时间")
    plan = repass.build_plan(con, verdicts={1: 1})
    assert plan.to_delete == []
    assert iid in plan.to_keep


def test_plan_deletes_duplicate_extras(con):
    """⭐ 真库 item 290/296 的形状：同一条消息产出了两条，v3 只产出 1 条。

    只留第一条，多余的删掉——**这是批内去重之外的第二道防线**。
    """
    _msg(con, 1, "征集一起去恐龙园活动")
    first = _item(con, 1, title="征集一起去恐龙园活动")
    second = _item(con, 1, title="征集一起去恐龙园活动")
    plan = repass.build_plan(con, verdicts={1: 1})
    assert plan.to_delete == [second]
    assert plan.to_keep == [first]


def test_plan_skips_items_referenced_by_digests(con):
    """⭐ 被日报引用的**不删**，进 `skipped_referenced` 并报告——不静默处理。"""
    _msg(con, 1, "校园卡办理，需要的联系我")
    iid = _item(con, 1, title="校园卡办理")
    store.save_digest(
        con, window_from=1, window_to=2, body_md="x", model="m",
        prompt_ver="v1", item_ids=[iid],
    )
    plan = repass.build_plan(con, verdicts={1: 0})
    assert plan.to_delete == []
    assert plan.skipped_referenced == [iid]


def test_apply_plan_actually_deletes(con):
    _msg(con, 1, "校园卡办理，需要的联系我")
    iid = _item(con, 1, title="校园卡办理")
    plan = repass.build_plan(con, verdicts={1: 0})
    repass.apply_plan(con, plan)
    assert con.execute("SELECT COUNT(*) FROM items WHERE item_id=?", (iid,)).fetchone()[0] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM item_sources WHERE item_id=?", (iid,)
    ).fetchone()[0] == 0, "⚠️ 来源行必须一起删——否则留下悬空的 item_sources"


def test_apply_plan_downgrades_place(con):
    """存量条目上未经新闸门的 place 要降级（否则出口判据 3 达不到）。"""
    _msg(con, 1, "大概这周会有面试 到时候具体时间通知大家")
    iid = _item(con, 1, title="面试通知", place="立德楼1阶")
    plan = repass.build_plan(con, verdicts={1: 1})
    repass.apply_plan(con, plan)
    assert con.execute("SELECT place FROM items WHERE item_id=?", (iid,)).fetchone()[0] is None


def test_upsert_fts_after_delete(con):
    """⚠️ 删了 items 之后 FTS 索引必须跟着走——否则搜索会返回不存在的条目。

    实测过这个形态：`items_fts` 是 external-content 表 + 三个触发器，
    `DELETE FROM items` 会触发 `items_fts_ad`。但**触发器只在 SQLite 自己
    执行 DELETE 时才触发**——用 `DROP`/重建绕过就不会。
    这条测试钉的是"我们走的是那条会触发触发器的主路径"。
    """
    _msg(con, 1, "校园卡办理，需要的联系我")
    iid = _item(con, 1, title="校园卡办理")
    got, _ = store.search_items(con, q="校园卡", limit=50, offset=0)
    assert len(got) == 1

    plan = repass.build_plan(con, verdicts={1: 0})
    repass.apply_plan(con, plan)

    got, _ = store.search_items(con, q="校园卡", limit=50, offset=0)
    assert got == [], "⚠️ 删了条目但 FTS 还能搜到 ⇒ 触发器没跑"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_repass.py -v`
Expected: `ModuleNotFoundError: No module named 'vigil.repass'`

- [ ] **Step 3: 加 store 的四个函数**

在 `vigil/store.py` 的 `kind_counts` 附近加：

```python
def items_used_in_digests(
    conn: sqlite3.Connection, item_ids: Sequence[int]
) -> frozenset[int]:
    """这些 item 里，哪些被**任何**一篇日报引用过。

    ⚠️ 存量重判靠它决定"哪些不能删"——删掉被引用的条目会让
    `digest_items` 留下悬空行，而日报正文里那句话还印着（spec R9）。
    """
    if not item_ids:
        return frozenset()
    marks = ",".join("?" * len(item_ids))
    return frozenset(
        int(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT item_id FROM digest_items WHERE item_id IN ({marks})",
            list(item_ids),
        )
    )


def existing_items_for_messages(
    conn: sqlite3.Connection, msg_ids: Sequence[int]
) -> dict[int, list[int]]:
    """源消息 → 它产出过的 item_id 列表（按 item_id 升序）。

    存量重判的第一步：找出"已产出条目的那批源消息"及其产物。
    """
    if not msg_ids:
        return {}
    marks = ",".join("?" * len(msg_ids))
    out: dict[int, list[int]] = {}
    for mid, iid in conn.execute(
        f"SELECT msg_id, item_id FROM item_sources WHERE msg_id IN ({marks})"
        " ORDER BY msg_id, item_id",
        list(msg_ids),
    ):
        out.setdefault(int(mid), []).append(int(iid))
    return out


def delete_items(conn: sqlite3.Connection, item_ids: Sequence[int]) -> int:
    """删条目及其来源行。返回删除条数。

    ⚠️ 必须先删 `item_sources`：`items` 的 FTS 触发器（`items_fts_ad`）挂在
    `items` 的 DELETE 上，删主行会顺带清索引；而 `item_sources` 没有触发器，
    不显式删就会留下**指向不存在条目的来源行**。

    ⚠️ **不 commit**——调用方决定事务边界（存量重判要整批要么全成要么全废）。
    """
    if not item_ids:
        return 0
    marks = ",".join("?" * len(item_ids))
    conn.execute(f"DELETE FROM item_sources WHERE item_id IN ({marks})", list(item_ids))
    cur = conn.execute(f"DELETE FROM items WHERE item_id IN ({marks})", list(item_ids))
    return int(cur.rowcount)


def downgrade_item_fields(
    conn: sqlite3.Connection,
    updates: Sequence[tuple[int, str | None, int | None]],
) -> int:
    """把存量条目的 `place` / `deadline_ts` 改成给定值（通常是把不合格的降为 NULL）。

    `updates` 是 ``(item_id, place, deadline_ts)`` 三元组。

    ⚠️ 这是 UPDATE 不是重建 ⇒ `item_id` 不变 ⇒ 不打断 `digest_items`（D16 的同一条理由）。
    ⚠️ **不 commit**，理由同 `delete_items`。
    """
    n = 0
    for item_id, place, deadline_ts in updates:
        cur = conn.execute(
            "UPDATE items SET place = ?, deadline_ts = ? WHERE item_id = ?",
            (place, deadline_ts, item_id),
        )
        n += int(cur.rowcount)
    return n
```

- [ ] **Step 4: 实现 `vigil/repass.py`**

```python
"""存量重判：让**已有的** items 跟上新的判据（prompt v3 + 两道要素闸门）。

⚠️ **语义是「只删不换」**（spec D10 / R9 实测）：

* 源消息在新判据下**不再产出**条目 → 删掉它的旧 item
* 源消息在新判据下**仍然产出** → **保留旧 item**（不重建、不翻新 `item_id`）
* **被 `digest_items` 引用的**条目一律不删，进 `skipped_referenced` 并报告

不这样做的代价已经量过：`digest_items` 66 行指向 66 条，
整批替换会让它们全部悬空，而**日报正文里那些话还印着**。

⚠️ 例外是**字段降级**：`place`/`deadline_ts` 用 UPDATE 同步到新闸门的结果。
UPDATE 不翻新 id，所以与"保留旧 item"不矛盾——而少了这一步，
M5 出口判据 3（不再有 `deadline_ts < event_ts`）根本达不到。
"""

from __future__ import annotations

import dataclasses
import sqlite3
from dataclasses import dataclass, field

from . import prefilter, store
from .categories import load_categories
from .config import Config
from .deadline import deadline_sane, place_supported
from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json
from .refine import (
    PROMPT_VERSION,
    RefineStats,
    _match_source,
    _parse_deadline,
    _to_item,
    build_system_prompt,
    build_user_prompt,
)
from .redact import Redactor
from . import refine as refine_mod


@dataclass
class RepassPlan:
    """一次重判的**可核对清单**。做事之前先把它打出来给人看。"""

    to_delete: list[int] = field(default_factory=list)
    to_keep: list[int] = field(default_factory=list)
    skipped_referenced: list[int] = field(default_factory=list)
    # (item_id, place, deadline_ts) —— 保留但需要降级的条目
    downgrades: list[tuple[int, str | None, int | None]] = field(default_factory=list)
    verdicts: dict[int, int] = field(default_factory=dict)   # msg_id -> 新产出条数


@dataclass
class RepassStats:
    scanned_msgs: int = 0
    deleted: int = 0
    kept: int = 0
    skipped_referenced: int = 0
    downgraded: int = 0
    batches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    budget_hit: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def build_plan(
    conn: sqlite3.Connection,
    *,
    verdicts: dict[int, int],
    item_ids_by_msg: dict[int, list[int]] | None = None,
    judged: dict[int, store.ExtractedItem] | None = None,
) -> RepassPlan:
    """把「每条源消息在新判据下产出几条」折叠成一张执行计划。

    ⚠️ 本函数是**纯的**（只读 conn，不写）——这样才能在真库上先跑一遍看清单，
    确认无误再 `apply_plan`。存量重判是不可逆操作，事前可见比事后回滚值钱。

    `verdicts`: `msg_id -> 新判据下产出的条目数`（0 = 判为不该入库）。
    `item_ids_by_msg`: 该消息**曾经**产出过的 item_id（缺省时现查）。
    `judged`: `msg_id -> 新判据下的条目`，用于算出字段降级值。
    """
    plan = RepassPlan(verdicts=dict(verdicts))
    if item_ids_by_msg is None:
        item_ids_by_msg = store.existing_items_for_messages(conn, list(verdicts))

    all_existing = [iid for ids in item_ids_by_msg.values() for iid in ids]
    referenced = store.items_used_in_digests(conn, all_existing)

    for msg_id, n_new in verdicts.items():
        olds = item_ids_by_msg.get(msg_id, [])
        # 保留前 n_new 条（n_new 为 0 时一条都不留），其余是"多余的"。
        keep_n = min(len(olds), n_new)
        for iid in olds[:keep_n]:
            if iid in referenced:
                plan.skipped_referenced.append(iid)
            else:
                plan.to_keep.append(iid)
        for iid in olds[keep_n:]:
            if iid in referenced:
                plan.skipped_referenced.append(iid)
            else:
                plan.to_delete.append(iid)

    if judged:
        plan.downgrades = _plan_downgrades(conn, plan.to_keep, judged, item_ids_by_msg)
    return plan


def _plan_downgrades(
    conn: sqlite3.Connection,
    keep_ids: list[int],
    judged: dict[int, store.ExtractedItem],
    item_ids_by_msg: dict[int, list[int]],
) -> list[tuple[int, str | None, int | None]]:
    """算出保留条目里需要降级的 `(item_id, place, deadline_ts)`。

    ⚠️ 现有条目的 `place`/`deadline_ts` 是**旧判据**下写的——新闸门没管过它们。
    这里按新判据重算一遍，只降级、不升级（新判据下"该有值"而旧条目没有的，不动它：
    那属于"抽取质量"问题，不是本次要修的）。
    """
    by_item = {iid: mid for mid, ids in item_ids_by_msg.items() for iid in ids}
    rows = conn.execute(
        "SELECT item_id, place, deadline_ts, event_ts FROM items WHERE item_id IN"
        f" ({','.join('?' * len(keep_ids))})",
        keep_ids,
    ).fetchall() if keep_ids else []

    out: list[tuple[int, str | None, int | None]] = []
    for item_id, place, deadline_ts, event_ts in rows:
        src = judged.get(by_item.get(item_id))
        if src is None:
            continue
        sources_text = ""
        if src.src_msg_ids:
            row = conn.execute(
                "SELECT content FROM messages WHERE msg_id = ?", (src.src_msg_ids[0],)
            ).fetchone()
            sources_text = (row[0] or "") if row else ""
        new_place = place if place_supported(place, sources_text) else None
        new_dl = deadline_ts
        if deadline_ts is not None and not deadline_sane(deadline_ts, event_ts):
            new_dl = None
        if (new_place, new_dl) != (place, deadline_ts):
            out.append((int(item_id), new_place, new_dl))
    return out


def apply_plan(conn: sqlite3.Connection, plan: RepassPlan) -> RepassStats:
    """执行计划。**整批一个事务**——要么全成要么全废，不留半个状态。"""
    stats = RepassStats()
    with store.transaction(conn):
        stats.deleted = store.delete_items(conn, plan.to_delete)
        stats.downgraded = store.downgrade_item_fields(conn, plan.downgrades)
    stats.kept = len(plan.to_keep)
    stats.skipped_referenced = len(plan.skipped_referenced)
    return stats


def collect_source_messages(conn: sqlite3.Connection) -> list[store.PendingMessage]:
    """所有**已产出条目**的源消息（去重），按 (ts, msg_id) 升序。

    ⚠️ 这是 D10 划定的重判范围——不碰 4.7 万条全量，只碰产出过条目的那批。
    实测真库规模：328 条 item ⇒ 约 328 条源消息 ⇒ 约 11 批。
    """
    rows = conn.execute(
        "SELECT DISTINCT m.msg_id, m.group_id, m.ts,"
        " COALESCE(m.sender_uid, '') AS uid,"
        " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS sender,"
        " m.content"
        " FROM item_sources src"
        " JOIN messages m ON m.msg_id = src.msg_id"
        " LEFT JOIN sender_names sn"
        "        ON sn.group_id = m.group_id AND sn.uid = m.sender_uid"
        " ORDER BY m.ts ASC, m.msg_id ASC"
    ).fetchall()
    return [store.PendingMessage(*row) for row in rows]


def repass(
    config: Config,
    *,
    api_key: str,
    conn: sqlite3.Connection | None = None,
    db_path=None,
    batch_size: int = 30,
    budget_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    enable_thinking: bool | None = False,
    apply: bool = False,
    on_progress=print,
) -> tuple[RepassPlan, RepassStats]:
    """跑一轮存量重判。`apply=False` 时**只出清单不写库**。

    ⚠️ 返回 `(plan, stats)`：即使 apply，调用方也拿得到清单去写报告。
    """
    cats = load_categories()
    known_kinds = frozenset(c.slug for c in cats)
    system = build_system_prompt(cats)
    redactor = Redactor(config)
    today = __import__("datetime").date.today().isoformat()

    owns = conn is None
    if conn is None:
        conn = sqlite3.connect(str(db_path))
    stats = RepassStats()
    try:
        msgs = collect_source_messages(conn)
        stats.scanned_msgs = len(msgs)
        if not msgs:
            on_progress("[repass] 没有需要重判的源消息")
            return RepassPlan(), stats

        batches = prefilter.make_batches(msgs, max_batch=batch_size)
        llm_cfg = LLMConfig(
            api_key=api_key, model=model, enable_thinking=enable_thinking
        )

        verdicts: dict[int, int] = {}
        judged: dict[int, store.ExtractedItem] = {}
        for batch in batches:
            if budget_tokens is not None and stats.total_tokens >= budget_tokens:
                stats.budget_hit = True
                break
            try:
                result = chat_json(
                    llm_cfg,
                    system=system,
                    user=build_user_prompt(batch, redactor, today=today),
                )
            except LLMError as exc:
                stats.errors.append(f"批次失败: {exc}")
                for m in batch:
                    verdicts.setdefault(m.msg_id, 0)
                continue
            stats.batches += 1
            stats.input_tokens += result.input_tokens
            stats.output_tokens += result.output_tokens

            produced = _produce(result.payload, batch, known_kinds=known_kinds)
            counts: dict[int, int] = {m.msg_id: 0 for m in batch}
            for it in produced:
                for mid in it.src_msg_ids:
                    counts[mid] = counts.get(mid, 0) + 1
                    judged.setdefault(mid, it)
            verdicts.update(counts)

        plan = build_plan(conn, verdicts=verdicts, judged=judged)
        if apply:
            applied = apply_plan(conn, plan)
            stats.deleted = applied.deleted
            stats.kept = applied.kept
            stats.skipped_referenced = applied.skipped_referenced
            stats.downgraded = applied.downgraded
        else:
            stats.kept = len(plan.to_keep)
            stats.skipped_referenced = len(plan.skipped_referenced)
            stats.downgraded = len(plan.downgrades)
        return plan, stats
    finally:
        if owns:
            conn.close()


def _produce(payload: object, batch, *, known_kinds) -> list[store.ExtractedItem]:
    """复用 refine 的 `_to_item`——**不重写一遍**。

    ⚠️ 重写会让两条路径的判据漂移：存量重判说"该删"，而新抽取说"该留"，
    同一个消息在两次运行里得到相反结论，而**没有任何测试会发现**。
    """
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []
    out: list[store.ExtractedItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            it = _to_item(raw, batch, known_kinds=known_kinds)
        except Exception:  # noqa: BLE001 —— 单条脏数据不该掀掉整轮
            continue
        if it is not None:
            out.append(it)
    return out
```

- [ ] **Step 5: 跑测试确认失败→通过**

Run: `uv run pytest tests/test_repass.py -v`
Expected: 先红后绿。**若 `_match_source` / `_to_item` / `_parse_deadline` 是私有名不可导入**，
按逃逸舱第一种形状处理：在 `refine.py` 里给它们加公开别名（如 `match_source = _match_source`），
**不要**把实现复制一份到 `repass.py`。

- [ ] **Step 6: 注册 CLI 子命令**

`vigil/cli.py` 的 `main()` 里，`p_refine` 那一段**之后**加：

```python
    p_repass = sub.add_parser(
        "repass",
        help="存量重判：让已有条目的来源消息按当前提示词重跑一遍（只删不换）",
    )
    p_repass.add_argument(
        "--apply", action="store_true",
        help="真的写库；**不给就只出清单**——存量重判不可逆，默认先看清单",
    )
    p_repass.add_argument("--batch", type=int, default=30, help="每批消息数")
    p_repass.add_argument("--budget", type=int, help="token 预算上限")
    p_repass.add_argument("--model", default=None, help="覆盖默认模型")
    p_repass.add_argument("--think", action="store_true", help="打开模型思考模式")
    p_repass.set_defaults(func=cmd_repass)
```

并在 `cmd_refine` 附近加处理函数（**照抄 `cmd_refine` 的持锁与退出码写法**）：

```python
def cmd_repass(args) -> int:
    """存量重判。⚠️ 写库 ⇒ **必须持锁**（与 refine/digest 同一套退出码契约）。"""
    config, key = _load_or_die()
    api_key = load_llm_key()
    if not api_key:
        print("[repass] 缺少 SILICONFLOW_API_KEY（在 .env 或环境变量里）",
              file=sys.stderr)
        return 1

    if not args.apply:
        # 只读清单不上锁——与 `deadline-audit` 的 dry-run 同一理由：
        # 给只读检查上锁会造出假拒绝。
        plan, stats = repass_mod.repass(
            config, api_key=api_key, batch_size=args.batch,
            budget_tokens=args.budget,
            model=args.model or refine_mod.DEFAULT_MODEL,
            enable_thinking=args.think, apply=False,
        )
        _print_repass_plan(plan, stats)
        return 0

    try:
        with lock.SingleInstance():
            plan, stats = repass_mod.repass(
                config, api_key=api_key, batch_size=args.batch,
                budget_tokens=args.budget,
                model=args.model or refine_mod.DEFAULT_MODEL,
                enable_thinking=args.think, apply=True,
            )
    except lock.AlreadyRunning as exc:
        logs.emit(f"[跳过] {exc}")
        return 2
    _print_repass_plan(plan, stats)
    return 0


def _print_repass_plan(plan, stats) -> None:
    """把清单打出来——**这是本命令存在的意义之一**：不可逆操作事前可见。"""
    print(f"[repass] 重判源消息 {stats.scanned_msgs} 条，跑 {stats.batches} 批，"
          f"token {stats.total_tokens:,}")
    print(f"  将删除 {len(plan.to_delete)} 条：")
    for iid in plan.to_delete:
        print(f"    - item {iid}")
    print(f"  保留 {len(plan.to_keep)} 条；字段降级 {len(plan.downgrades)} 条")
    if plan.skipped_referenced:
        print(f"  ⚠️ 跳过 {len(plan.skipped_referenced)} 条（被日报引用，删了会让归档悬空）：")
        for iid in plan.skipped_referenced:
            print(f"    - item {iid}")
    if stats.errors:
        for e in stats.errors:
            print(f"  [错误] {e}", file=sys.stderr)
```

`vigil/cli.py` 顶部 import 补 `from . import repass as repass_mod`（**照抄现有 `refine_mod` 的别名风格**）。

- [ ] **Step 7: 跑测试 + 在真库上**干跑一次

Run:
```bash
uv run pytest -q
uv run vigil repass            # ⚠️ 不带 --apply：只出清单，不写库
```

✅ **这一步是本任务真正的验收**：清单里**必须**包含那些已知的广告条目
（校园卡相关的 item 24–162 那一批），**并且**必须**不**包含
item 14 / 84 / 86 / 111 / 143（§1.2 的 5 条误杀反例）。

**若那 5 条出现在 `to_delete` 里 → 立即停下报告**：说明 prompt v3 的判据没吃住 D13，
这是 M5 出口判据 2 要守的东西，**不许用"再调一下 prompt"的方式私下消化**。

- [ ] **Step 8: 备份真库后 apply**

```bash
cp data/vigil.db "data/vigil.db.bak-m5-repass-$(date +%Y%m%d-%H%M%S)"
uv run vigil repass --apply
```

- [ ] **Step 9: 复算 M5 出口判据 1 与 3**

```bash
uv run python -c "
import sqlite3, datetime
con = sqlite3.connect('file:data/vigil.db?mode=ro', uri=True)
tot = con.execute(\"select count(*) from items where kind='life'\").fetchone()[0]
n = con.execute(\"select count(*) from items where kind='life' and (title like '%卡%' or title like '%套餐%' or title like '%流量%')\").fetchone()[0]
print(f'判据1: life 类目 {tot} 条，卡类 {n} 条 = {n*100//max(tot,1)}%   (基线 34%)')
bad = con.execute('select count(*) from items where deadline_ts is not null and deadline_ts < event_ts').fetchone()[0]
print(f'判据3: deadline_ts < event_ts 的条目 = {bad} 条   (基线 1)')
"
```

Expected: 判据 1 **< 5%**；判据 3 **0 条**。

- [ ] **Step 10: Commit**

```bash
git add vigil/repass.py vigil/store.py vigil/cli.py tests/test_repass.py
git commit -m "feat(repass): 存量重判命令——只删不换 + 字段降级，默认只出清单"
```

---

## Task 10: 前端 —— 多选筛选 / 人物维度 / 改分类 / 删除 / 撤销

**为什么**：用户要求的 `#4`（按人物筛选）与 `⑪⑫`（手动改分类、删除）在界面上没有入口。

**⚠️ 三条既有约定不许破**（`types.ts` 文件头自己写着）：

1. **`types.ts` 是 `vigil/api.py` 的逐字影子**——改一边必须同时改另一边。
2. **`Shown` 类型把「数据 / 总数 / 筛选条件」绑成一体**（`Feed.tsx:12-17` 的注释解释了为什么）。
   筛选条件变成数组后，**必须仍然保持"同生同死"**——`kind: string` → `kinds: string[]` 之后，
   `switching` 的比较不能再用 `!==`（数组恒不等，会让"读取中…"永远亮着）。
3. **空结果与未知必须分开说**（`Feed.tsx:29-31` 的 `Shown | null` 三态）。
   多选之后这条不变。

**Files:**
- Modify: `web/src/types.ts`、`web/src/api.ts`、`web/src/App.tsx`、`web/src/views/Feed.tsx`、`web/src/components/ItemCard.tsx`
- Create: `web/src/components/PersonPicker.tsx`
- Test: `web/src/__tests__/api.test.ts`

**Interfaces:**
- Consumes: Task 8 的六个端点
- Produces: 无（终端用户界面）

- [ ] **Step 1: 写失败测试（API 客户端的查询串）**

追加到 `web/src/__tests__/api.test.ts`：

```ts
// ── Task 10：多值查询串 ──────────────────────────────────────────

it('多值 kind 用重复参数而不是逗号拼接', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
  })
  vi.stubGlobal('fetch', spy)

  await fetchItems({ kinds: ['notice', 'academic'], limit: 50 })
  expect(spy.mock.calls[0][0]).toBe(
    '/api/items?kind=notice&kind=academic&limit=50',
  )
})

it('多值 person 同理', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
  })
  vi.stubGlobal('fetch', spy)

  await fetchItems({ persons: [111, 222], limit: 50 })
  expect(spy.mock.calls[0][0]).toBe('/api/items?person=111&person=222&limit=50')
})

it('空数组等于不筛选', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
  })
  vi.stubGlobal('fetch', spy)

  await fetchItems({ kinds: [], persons: [], limit: 50 })
  expect(spy.mock.calls[0][0]).toBe('/api/items?limit=50')
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm test`
Expected: 三条新用例失败（`fetchItems` 仍拼 `kind=` 单值 / 不认识 `kinds`）

- [ ] **Step 3: 改 `web/src/api.ts`**

把 `ItemQuery` 与 `fetchItems` 换成：

```ts
export type ItemQuery = {
  /** ⚠️ 多值。**空数组与不传同义**（= 不筛选），别把 [] 拼成空参数。 */
  kinds?: string[]
  /** 人物维度，值是 uin（QQ 号）。 */
  persons?: number[]
  since?: string
  until?: string
  group?: number
  q?: string
  limit?: number
  offset?: number
}

export function fetchItems(query: ItemQuery): Promise<ItemPage> {
  const p = new URLSearchParams()
  // ⚠️ 必须用 append 而不是 set：set 会让后一个值覆盖前一个，
  // 于是"选了三个类目"发出去变成"只筛最后一个"，而**页面不会报错**。
  for (const k of query.kinds ?? []) {
    if (k) p.append('kind', k)
  }
  for (const u of query.persons ?? []) {
    p.append('person', String(u))
  }
  if (query.since) p.set('since', query.since)
  if (query.until) p.set('until', query.until)
  if (query.group !== undefined && query.group !== null) {
    p.set('group', String(query.group))
  }
  if (query.q) p.set('q', query.q)
  if (query.limit !== undefined) p.set('limit', String(query.limit))
  if (query.offset !== undefined) p.set('offset', String(query.offset))
  return getJSON<ItemPage>(`/api/items?${p.toString()}`)
}
```

> ⚠️ 上面假设 `getJSON` 已存在（`api.ts:9-24`）。若它的签名与这里不符，**按实际的改**并报告。

在 `fetchItems` 之后追加写操作的封装（**照抄 `getJSON` 的错误处理形状**）：

```ts
async function sendJSON<T>(url: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const b = (await r.json()) as { detail?: unknown }
      if (typeof b.detail === 'string') msg = b.detail
    } catch {
      /* 非 JSON 响应（比如未构建时的 503 HTML）就用状态码 */
    }
    throw new Error(msg)
  }
  // 204 没有 body——`r.json()` 会抛，必须显式短路
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

// ⚠️ `Person` 类型**定义在 `types.ts`**（Step 4），这里只 import 再转出去。
// 两个文件各定义一份的话，TS 会以其中一份为准、另一份悄悄失效——
// 而 `types.ts` 是「与后端契约逐字对应」的那一份，它必须是唯一的真相源。
import type { Person } from './types.ts'
export type { Person }

export const fetchPersons = () =>
  getJSON<{ persons: Person[] }>('/api/persons')

export const addPerson = (uin: number, label: string, note = '') =>
  sendJSON<{ uin: number; label: string }>('/api/persons', 'POST', {
    uin,
    label,
    note,
  })

export const removePerson = (uin: number) =>
  sendJSON<void>(`/api/persons/${uin}`, 'DELETE')

export const setItemKind = (itemId: number, kind: string) =>
  sendJSON<{ edit_id: number }>(`/api/items/${itemId}/kind`, 'POST', { kind })

export const deleteItem = (itemId: number) =>
  sendJSON<{ edit_id: number }>(`/api/items/${itemId}`, 'DELETE')

export const undoLast = (editId?: number) =>
  sendJSON<{ undone: boolean }>('/api/undo', 'POST', {
    edit_id: editId ?? null,
  })
```

- [ ] **Step 4: 改 `web/src/types.ts`**

`Item` 类型里，`actor` 之后加一行：

```ts
  /** QQ 号（uin）。实名消息才有；匿名消息为 null，且不该被人物筛选中。 */
  actor_uin: number | null
```

**文件末尾**追加：

```ts
/**
 * 一个被监视的人物。
 *
 * ⚠️ `count` 是"这个 uin 发过的条目数"，由后端算好——前端不要在拿到
 * 全部条目后自己数：那需要把整个库拉下来，而且计数会随筛选条件漂移。
 */
export type Person = {
  uin: number
  label: string
  note: string
  count: number
}
```

- [ ] **Step 5: 改 `web/src/App.tsx`**

`kind` 单项改成数组，并加人物筛选与撤销：

```tsx
export default function App() {
  const [tab, setTab] = useState<Tab>('feed')
  // 类目筛选状态**提到 App**：这样「类目」页点一个类目跳回信息流时，
  // 筛选条件能带过去，而 Feed 卸载重挂也不会丢。
  //
  // ⚠️ 多选：维度**内**是并集（选中多个类目 = 它们的合集），
  // 维度**间**是交集（类目 ∧ 人物）——spec §四 #4。
  const [kinds, setKinds] = useState<string[]>([])
  const [persons, setPersons] = useState<number[]>([])
  // 撤销的可见反馈：点完要说一句，否则不知道到底生效没有
  const [undoMsg, setUndoMsg] = useState<string | null>(null)

  async function undo() {
    setUndoMsg(null)
    try {
      const r = await undoLast()
      setUndoMsg(r.undone ? '已撤销上一步' : '没有可撤销的操作')
    } catch (e: unknown) {
      setUndoMsg(e instanceof Error ? e.message : String(e))
    }
  }
  ...
```

`<header>` 的 `<nav>` 之前插入：

```tsx
          <button
            onClick={undo}
            className="ml-auto rounded-lg px-2 py-1 text-xs text-white/55 active:bg-white/5"
          >
            ↶ 撤销
          </button>
          {undoMsg !== null && (
            <span className="text-xs text-white/40">{undoMsg}</span>
          )}
```

> ⚠️ `nav` 上原本有 `ml-auto`。撤销按钮插在它前面时，`ml-auto` 要**从 nav 挪到撤销按钮上**
> （同一行里只能有一个 `ml-auto` 起作用，否则布局会变成两段式）。

`<main>` 里的三行改成：

```tsx
        {tab === 'feed' && (
          <Feed
            kinds={kinds}
            onKinds={setKinds}
            persons={persons}
            onPersons={setPersons}
          />
        )}
        {tab === 'cats' && (
          <Categories
            onPick={(slug) => {
              setKinds([slug])
              setTab('feed')
            }}
          />
        )}
```

> ⚠️ `onPick` 用 `setKinds([slug])`（**替换**而不是追加）：从类目页点进来是"我要看这一类"，
> 追加会得到「上一次的筛选 ∧ 这一次的」这种没人要的结果。

- [ ] **Step 6: 改 `web/src/views/Feed.tsx`**

`Shown` 与 props 改成：

```tsx
type Shown = {
  items: Item[]
  total: number
  /** ⚠️ 存成 join 后的字符串：数组恒不等于自身，`switching` 的比较会永远为真。 */
  kindsKey: string
  personsKey: string
  q: string
}

export default function Feed({
  kinds,
  onKinds,
  persons,
  onPersons,
}: {
  kinds: string[]
  onKinds: (k: string[]) => void
  persons: number[]
  onPersons: (p: number[]) => void
}) {
```

在 `const seq = useRef(0)` 之后加：

```tsx
  const kindsKey = [...kinds].sort().join(',')
  const personsKey = [...persons].sort().join(',')
```

查询 effect（`Feed.tsx:53-73`）里的两处 `fetchItems` 与 `setShown` 改为：

```tsx
    fetchItems({
      kinds,
      persons,
      q: q || undefined,
      limit: PAGE,
    })
      .then((page) => {
        if (mine !== seq.current) return
        setShown({ items: page.items, total: page.total, kindsKey, personsKey, q })
      })
```

（`loadMore` 里的同理，用 `shown.kindsKey.split(',').filter(Boolean)` 与
`shown.personsKey.split(',').filter(Boolean).map(Number)` 还原，**续的是屏幕上那批数据**。）

依赖数组改成 `[kindsKey, personsKey, q, reloadTick]`。

`switching` 改成：

```tsx
  const switching =
    loading &&
    shown !== null &&
    (shown.kindsKey !== kindsKey || shown.personsKey !== personsKey || shown.q !== q)
```

`picked` 改成：

```tsx
  const pickedKinds =
    shown !== null
      ? cats.filter((c) => shown.kindsKey.split(',').includes(c.slug))
      : []
```

`countLine` 的类目那一段改成：

```tsx
      : `共 ${shown.total} 条` +
        (pickedKinds.length > 0
          ? ` · ${pickedKinds.map((c) => c.label).join('、')}`
          : '') +
        (shown.personsKey ? ` · ${shown.personsKey.split(',').length} 个人物` : '') +
        (shown.q ? ` · 关键词「${shown.q}」` : '') +
        (switching ? ' · 读取中…' : '')
```

Chip 那一栏改成多选（**点一下切换，不是替换**）：

```tsx
      <div className="mt-3 -mx-1 flex flex-wrap gap-1.5">
        <Chip active={kinds.length === 0} onClick={() => onKinds([])}>
          全部
        </Chip>
        {cats.map((c) => (
          <Chip
            key={c.slug}
            active={kinds.includes(c.slug)}
            onClick={() =>
              onKinds(
                kinds.includes(c.slug)
                  ? kinds.filter((k) => k !== c.slug)
                  : [...kinds, c.slug],
              )
            }
          >
            {c.icon} {c.label}
          </Chip>
        ))}
      </div>

      <PersonPicker selected={persons} onChange={onPersons} />
```

`ItemCard` 的渲染改成（**把改分类与删除的回调交下去**）：

```tsx
        {shown !== null &&
          shown.items.map((it) => (
            <ItemCard key={it.item_id} item={it} onMutated={retry} />
          ))}
```

> ⚠️ `onMutated={retry}` 而不是 `setReloadTick`：`retry` 已经处理了
> 「有数据时续页 / 无数据时重跑首屏」两种情况，复用它是既有语义。

- [ ] **Step 7: 新建 `web/src/components/PersonPicker.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { addPerson, fetchPersons, removePerson } from '../api.ts'
import type { Person } from '../types.ts'

/**
 * 「按人物筛选」——一个**与类目体系并列的第二维度**。
 *
 * ⚠️ 与类目的关系是：**维度内并集、维度间交集**（spec §四 #4）。
 * 这个组件只管"选了哪些人"，拼 WHERE 是后端的事——前端不要试图
 * 把两个维度揉成一个 `q` 或一个 `kind`，那会让交集变成并集。
 *
 * ⚠️ 三态必须分开（与 Feed 同一条规矩）：还没读到 / 读到了 0 个人 / 读取失败。
 * 把「读失败」画成「一个人都没有」会让用户以为名单被清空了。
 */
export default function PersonPicker({
  selected,
  onChange,
}: {
  selected: number[]
  onChange: (uins: number[]) => void
}) {
  const [people, setPeople] = useState<Person[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [uin, setUin] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)

  function reload() {
    setErr(null)
    fetchPersons()
      .then((r) => setPeople(r.persons))
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : String(e))
        setPeople(null)
      })
  }

  useEffect(reload, [])

  async function add() {
    const n = Number(uin.trim())
    if (!Number.isInteger(n) || n <= 0) {
      setErr('QQ 号必须是正整数（0 不是有效账号）')
      return
    }
    if (!label.trim()) {
      setErr('给它起个名字——群昵称会变，这个名字不会')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await addPerson(n, label.trim())
      setUin('')
      setLabel('')
      reload()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function drop(n: number) {
    setBusy(true)
    setErr(null)
    try {
      await removePerson(n)
      // 从当前筛选里也摘掉——否则筛选项还留着一个已经不存在的人，
      // 列表会一直空着，而用户不知道是为什么
      onChange(selected.filter((u) => u !== n))
      reload()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="rounded-full bg-white/5 px-3 py-1 text-xs text-white/55"
      >
        👤 按人物筛选
        {selected.length > 0 ? `（已选 ${selected.length}）` : ''}
      </button>

      {open && (
        <div className="mt-2 rounded-xl bg-white/5 p-3">
          {err !== null && (
            <p className="mb-2 text-xs text-red-400">{err}</p>
          )}
          {people === null && err === null && (
            <p className="text-xs text-white/40">读取中…</p>
          )}
          {people !== null && people.length === 0 && (
            <p className="text-xs text-white/40">
              还没有监视任何人。在下面加一个 QQ 号。
            </p>
          )}
          {people !== null && people.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {people.map((p) => {
                const on = selected.includes(p.uin)
                return (
                  <span key={p.uin} className="inline-flex items-center">
                    <button
                      onClick={() =>
                        onChange(
                          on
                            ? selected.filter((u) => u !== p.uin)
                            : [...selected, p.uin],
                        )
                      }
                      className={
                        'rounded-l-full px-3 py-1 text-xs ' +
                        (on
                          ? 'bg-sky-500/20 text-sky-300'
                          : 'bg-white/5 text-white/55')
                      }
                    >
                      {p.label}（{p.count}）
                    </button>
                    <button
                      onClick={() => drop(p.uin)}
                      disabled={busy}
                      title={`不再监视 ${p.uin}`}
                      className="rounded-r-full bg-white/5 px-2 py-1 text-xs text-white/35 active:bg-white/10"
                    >
                      ×
                    </button>
                  </span>
                )
              })}
            </div>
          )}

          <div className="mt-3 flex flex-wrap gap-1.5">
            <input
              value={uin}
              onChange={(e) => setUin(e.target.value)}
              inputMode="numeric"
              placeholder="QQ 号"
              className="w-28 rounded-lg bg-black/30 px-2 py-1 text-xs outline-none placeholder:text-white/30"
            />
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="名字（辅导员张老师）"
              className="flex-1 rounded-lg bg-black/30 px-2 py-1 text-xs outline-none placeholder:text-white/30"
            />
            <button
              onClick={add}
              disabled={busy}
              className="rounded-lg bg-sky-500/20 px-3 py-1 text-xs text-sky-300 disabled:opacity-40"
            >
              新增
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 8: 改 `web/src/components/ItemCard.tsx`**

props 改成：

```tsx
export default function ItemCard({
  item,
  onMutated,
}: {
  item: Item
  /** 改动成功后通知父级重取列表。不传则只读（日报页就是这样用的）。 */
  onMutated?: () => void
}) {
```

在 `const [loading, setLoading] = useState(false)` 之后加：

```tsx
  const [busy, setBusy] = useState(false)
  const [actErr, setActErr] = useState<string | null>(null)
  const [cats, setCats] = useState<Category[]>([])

  useEffect(() => {
    if (!onMutated) return
    fetchCategories()
      .then((r) => setCats(r.categories))
      .catch(() => setCats([]))
  }, [onMutated])

  async function changeKind(slug: string) {
    setBusy(true)
    setActErr(null)
    try {
      await setItemKind(item.item_id, slug)
      onMutated?.()
    } catch (e: unknown) {
      setActErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setActErr(null)
    try {
      await deleteItem(item.item_id)
      onMutated?.()
    } catch (e: unknown) {
      setActErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
```

import 补：`import { useEffect } from 'react'`（与既有 `useState` 合并）、
`import { fetchCategories, fetchItem, setItemKind, deleteItem } from '../api.ts'`、
`import type { Category, Item, Source } from '../types.ts'`。

在 `<li>` 的**最外层 button 之后**（`{open && (...)}` 之前）插入操作条：

```tsx
      {onMutated && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-white/5 pt-2 text-xs">
          <select
            value={item.kind}
            disabled={busy}
            onChange={(e) => changeKind(e.target.value)}
            className="rounded-lg bg-black/30 px-2 py-1 text-xs text-white/70 outline-none"
          >
            {cats.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.icon} {c.label}
              </option>
            ))}
          </select>
          <button
            onClick={remove}
            disabled={busy}
            className="rounded-lg bg-red-500/10 px-2 py-1 text-red-300 disabled:opacity-40"
          >
            删除
          </button>
          {actErr !== null && <span className="text-red-400">{actErr}</span>}
        </div>
      )}
```

> ⚠️ 操作条**只在外层按钮之外**（`<button>` 里不能再放 `<select>`/`<button>`——
> HTML 不允许嵌套交互元素，浏览器会把内层踢出去，点击行为变得不可预测）。

- [ ] **Step 9: 跑前端测试与构建**

Run:
```bash
cd web && npm test
cd web && npm run build
```
Expected: 测试全绿；构建成功（`tsc -b` 会抓到任何类型不同步——
**这是 `types.ts` 影子契约的机械守卫**）

- [ ] **Step 10: 真跑一次（真实进程 + 真实数据）**

```bash
cd D:/github/VIGIL && uv run vigil serve --host 127.0.0.1 --port 8787
```
浏览器打开 `http://127.0.0.1:8787`，逐条验：
1. 点两个类目 → 计数行显示两个类目名 → 列表是**并集**
2. 再选一个人物 → 列表变窄（**交集**）
3. 改一条的分类 → 刷新后仍是新分类；`data/vigil.db` 的 mtime **没变**
4. 删一条 → 从列表消失；**日报页里也不见了**（R13 的两处都验）
5. 点「↶ 撤销」 → 条目回来

- [ ] **Step 11: Commit**

```bash
git add web/src
git commit -m "feat(web): 多选类目 + 人物维度筛选 + 改分类/删除/撤销"
```

---

## 阶段① 自审三件套

### 1. Spec 覆盖对照表

| spec 章节 / 要求 | 归属任务 |
|---|---|
| §4.1 ① 噪声：prompt v3 | **Task 1** |
| §4.1 ① 噪声：存量重判（D10） | **Task 9** |
| §4.1 ② `place` 证据闸门 | **Task 2** |
| §4.1 ② `deadline` 时序闸门 | **Task 2** |
| §4.1 ③ 人物配置 `persons.toml` | **Task 7** |
| §4.1 ③ store 加 `uin` + 人物筛选 | **Task 8** |
| §4.1 ③ API 多值 `kind` | **Task 8** |
| §4.1 ③ 前端「按人物筛选」 | **Task 10** |
| §4.1 ④ 人工干预层存储（D14） | **Task 4** |
| §4.1 ④ 手动改分类 / 软删 / 撤销 | **Task 4**（层）+ **Task 8**（端点）+ **Task 10**（界面） |
| §4.1 ④ **overlay 接入 5 处读路径** | **Task 5** |
| §4.1 ④ `refine` 读墓碑（D15） | **Task 6** |
| §4.1 ⑤ `items` 批内去重 | **Task 3** |
| §5 M5 出口判据 1（噪声 <5%） | **Task 9 Step 9** |
| §5 M5 出口判据 2（误杀为零） | **Task 9 Step 7** |
| §5 M5 出口判据 3（无倒挂死线） | **Task 2** + **Task 9 Step 9** |
| §5 M5 出口判据 4（人物筛选） | **Task 10 Step 10** |
| §5 M5 出口判据 5（幂等） | **Task 9**（重判跑两次清单应为空） |
| §5 M5 出口判据 6（干预层 + `mode=ro`） | **Task 5** + **Task 8 Step 10**（反向验证） |
| §3.4 要素归属判据 | **Task 2**（本条判据的首次落地） |
| §2 D11（Web 写边界） | **Task 5** + **Task 8** |
| §2 D16（item_id 不翻新） | **Task 3** + **Task 9** |
| §6 R13（overlay 覆盖不全） | **Task 5**（结构性缓解）+ **Task 10 Step 10 第 4 条** |

**未覆盖项（显式标"本里程碑不做"）：**

| 项 | 为什么不做 |
|---|---|
| M6 的 #3 群号管理 / #5 LLM 配置 / #6 导入导出 / 类目编辑与重排 | **属于 M6**，spec §4.2 |
| M7 的五套主题 | **属于 M7**，spec §4.3 |
| U-4（`groups` 与 `export` 共用缓存库） | **属于 M6**（与 #3 同批，spec §1.6） |
| 类目 slug 重命名/删除的级联 | **属于 M6**（类目编辑才需要它） |
| 「撤销」的历史列表 UI（只做"撤最近一步"） | 用户要的是"回滚到过去"，**单步撤销先落地**；多步历史进 M6 的类目编辑一起做 |
| `vigil person` CLI 子命令 | Web 已覆盖；加 CLI 无新消费者 |

### 2. 占位符扫描

已扫描：本计划**没有** `TBD` / `TODO` / "实现细节待定" / "类似 Task N"。

**两处刻意留给执行者的**，都标了 ⚠️ 与逃逸舱指引，**不是占位符**：
- Task 6 / Task 8 / Task 9 的测试辅助（`_cfg()` / `_client()` / `_stub_llm_conf()`）——
  要求**照抄既有测试文件的写法**，理由是重复给一份会与既有夹具漂移。
- Task 2 Step 5 的两处 epoch 字面量——要求**实际算一遍再写进去**。

### 3. 跨任务类型/签名一致性

| 名字 | 定义处 | 使用处 | 一致？ |
|---|---|---|---|
| `overrides.attach_readonly(conn, path=None)` | Task 4 Step 3 | Task 5 Step 4 | ✅ |
| `overrides.deleted_msg_ids(conn)` | Task 4 Step 3 | Task 6 Step 3 | ✅ |
| `store._ensure_overlay(conn)` | Task 5 Step 4 | Task 5 各查询 | ✅ |
| `store.search_items(kinds=, actor_uins=)` | Task 8 Step 3 | Task 8 Step 4（api.py）、Task 8 测试 | ✅ |
| `store.ApiItem.actor_uin` | Task 8 Step 3 | Task 8 Step 4（`item_out`）、Task 10 `types.ts` | ✅ |
| `store.delete_items` / `downgrade_item_fields` / `items_used_in_digests` / `existing_items_for_messages` | Task 9 Step 3 | Task 9 Step 4（`repass.py`） | ✅ |
| `config.Person` / `load_persons` / `save_persons` / `atomic_write_text` | Task 7 Step 3 | Task 8 Step 8（api.py） | ✅ |
| `repass.build_plan` / `apply_plan` / `RepassPlan` | Task 9 Step 4 | Task 9 Step 1 测试、Step 6 CLI | ✅ |
| `refine.RefineStats.skipped_deleted` | Task 6 Step 3 | Task 6 测试、Step 4 进度行 | ✅ |
| 前端 `Item.actor_uin` | Task 10 Step 4 | Task 10 Step 8（ItemCard 未直接用，但契约完整） | ✅ |
| 前端 `Person` 类型 | Task 10 Step 4（**唯一真相源：`types.ts`**） | Step 3（api.ts 只 `import type` 再转出）、Step 7 `PersonPicker` | ✅（自审已修正） |

> ⚠️ 上面最后一行是**自审抓到的真缺陷并已就地修掉**：初稿在 `api.ts` 与 `types.ts`
> 各定义了一份 `Person`，TS 会以其中一份为准、另一份悄悄失效。
> 已改为 `api.ts` 只 `import type { Person } from './types.ts'`。
> 这正是 writing-plans 自审三件套里「跨任务类型一致性」那条要抓的东西。

---

## 执行方式

- **模式：pipeline**（`/SDD pipeline`）——理由见 spec §6 与接力文件「M5 若只有 Python 一条链或有共享文件，就回 pipeline」：
  Task 8 的多值筛选、人物维度、写端点在 `store.py` 同一批函数上咬合；
  Task 5 的 overlay 接入也在同一批函数上。**写者表过不去。**
- 每个任务：`task-brief` → implementer → `review-package` → reviewer 双裁决 → 裁决 → fix → scoped re-review。
- **别跳过的三个变异反证点**：Task 6 Step 6-7（墓碑）、Task 8 Step 10（D11 守卫反向验证）、
  Task 2 的四条闸门分支（尤其「短于 2 字 → 不判定」那条——它是**空守卫风险最高的一处**）。
- **Task 9 Step 7 是全程最危险的一步**：清单里若出现 item 14/84/86/111/143，
  **停下报告，不许自行调 prompt 消化**。

