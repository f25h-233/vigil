"""日报合成的测试。**全部用构造样本，不联网、不碰 data/vigil.db。**"""

from __future__ import annotations

import json
import sqlite3

import pytest

from vigil import digest
from vigil.redact import Redactor
from vigil.store import WindowItem


def _item(
    item_id: int = 1,
    *,
    kind: str = "notice",
    title: str = "体检表",
    detail: str | None = "10月8日前交到辅导员处",
    event_ts: int = 1000,
    deadline_ts: int | None = None,
    group_id: int = 100,
    place: str | None = None,
    amount: str | None = None,
    confidence: float = 0.9,
) -> WindowItem:
    return WindowItem(
        item_id=item_id, kind=kind, title=title, detail=detail,
        event_ts=event_ts, deadline_ts=deadline_ts, group_id=group_id,
        place=place, amount=amount, confidence=confidence,
    )


# ── 载荷构造 ────────────────────────────────────────────────


def test_payload_sends_group_name_not_id():
    """⚠️ 探针第一版就是把 group_id 明文发了出去——这条测试守着它。"""
    payload = digest.build_items_payload(
        [_item(group_id=643375490)], {643375490: "新生群"}, Redactor()
    )

    assert payload[0]["group"] == "新生群"
    assert "643375490" not in json.dumps(payload, ensure_ascii=False)


def test_payload_sanitizes_fullwidth_quotes():
    payload = digest.build_items_payload(
        [_item(title="卖笔记", detail="昵称“风之海310”")], {}, Redactor()
    )

    assert "“" not in payload[0]["detail"]
    assert "「风之海310」" in payload[0]["detail"]


def test_payload_redacts_phone_numbers():
    """item 是模型从脱敏文本里抽的，但它会补出原文没有的实体——出网前再抹一遍。"""
    payload = digest.build_items_payload(
        [_item(detail="联系 13812345678 报名")], {}, Redactor()
    )

    assert "13812345678" not in payload[0]["detail"]


def test_payload_formats_time_and_deadline():
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 13, 14, 20).timestamp())
    dl = int(dt.datetime(2026, 10, 8).timestamp())
    payload = digest.build_items_payload([_item(event_ts=ts, deadline_ts=dl)], {}, Redactor())

    assert payload[0]["time"] == "14:20"
    assert payload[0]["deadline"] == "2026-10-08"


def test_payload_null_dashes_stay_null():
    payload = digest.build_items_payload(
        [_item(detail=None, place=None, amount=None, deadline_ts=None)], {}, Redactor()
    )

    assert payload[0]["detail"] is None
    assert payload[0]["deadline"] is None


def test_system_prompt_states_the_three_contracts():
    prompt = digest.build_system_prompt()

    assert "quotes" in prompt      # 逐字摘录
    assert "label" in prompt       # 短标签
    assert "不要编造" in prompt     # 不许补原文没有的实体


def test_user_prompt_carries_the_day():
    prompt = digest.build_user_prompt([], day="2026-09-13")

    assert "2026-09-13" in prompt


# ── 守卫补强（审查轮次 1：F1–F4）──────────────────────────────
#
# 上面 7 条是 brief 给的，覆盖的是「已经写好的那几条」。独立变异反证（22 个）
# 抓出它们的覆盖缺口：**载荷有无、提示词规则、别的文本字段、条数守恒**
# 这四类破坏全都 24 passed。下面每条都配了变异证据，见 task-2-report.md。


def test_payload_keeps_every_item():
    """⚠️ 窗口内**每一条** item 都必须出现在载荷里（设计判断第 1 条）。

    日报「不再筛第二遍」是这个工具最不能犯的错——静默漏掉正是它要防的事。
    变异反证：`for item in items:` 改成 `items[:1]`，原先 7 条测试全绿
    （因为它们全都只造 1 条 item，数量根本没被约束）。
    """
    items = [_item(i, title=f"条目{i}", event_ts=1000 + i) for i in range(1, 6)]

    payload = digest.build_items_payload(items, {}, Redactor())

    assert len(payload) == len(items)
    assert [p["title"] for p in payload] == [it.title for it in items]


def test_payload_cleans_every_text_field():
    """⚠️ 三条硬规则要覆盖所有**会出网的文本字段**，不只 detail。

    ``clean()`` 管着 title / detail / place / amount 四个字段。title 尤其危险：
    它是模型被要求「逐字摘录」回连的字段（规则 3），全角引号出现在 title 时
    照旧触发退化。

    变异反证：让 title/place/amount 同时绕过 ``clean()``，原先全绿。
    """
    payload = digest.build_items_payload(
        [
            _item(
                title="昵称“风之海310”卖笔记",
                detail="联系 13812345678 报名",
                place="“三食堂”门口 13812345678",
                amount="“50 元” 13812345678",
            )
        ],
        {},
        Redactor(),
    )

    for field in ("title", "detail", "place", "amount"):
        assert "“" not in payload[0][field], field
        assert "13812345678" not in payload[0][field], field


def test_payload_unknown_group_id_does_not_leak_the_id():
    """⚠️ 群不在 ``names`` 里时，兜底也绝不能把群号发出去（spec §4.5）。

    真实触发场景：DB 里出现未配置进 ``config/groups.toml`` 的群。
    变异反证：兜底从 ``""`` 改成 ``str(item.group_id)``，原先全绿——
    而这是**群号明文出网**。
    """
    payload = digest.build_items_payload([_item(group_id=643375490)], {}, Redactor())

    assert payload[0]["group"] == ""
    assert "643375490" not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize(
    "rule_phrase",
    [
        "每一条 item 都必须出现在日报里",  # 规则 1：不许省略
        "合并成一行",                    # 规则 2：合并同类项，漏了日报退化成流水账
        "逐字摘录",                      # 规则 3：quote 回连契约
        "12 个字",                       # 规则 4：label 要短
        "一句话说清细节",                 # 规则 5：text 的职责
        "不要把它写进 label 或 text",     # 规则 6：群名不进输出（实测逼出来的）
        "不要编造",                      # 规则 7：不许补原文没有的实体
    ],
)
def test_system_prompt_carries_each_rule(rule_phrase):
    """7 条规则各有一个**只在该规则里出现**的特征短语。

    变异反证：原先只断言 ``"quotes"`` / ``"label"``，而这两个词在末尾的
    JSON 形状说明行里**也出现**——把规则 2（合并）、规则 4（label 短）、
    规则 6（不许写群名）整段删掉，原先全绿。而 docstring 明说规则 2 与 6
    是「实测逼出来的」：删了规则 6 模型会把群名当主语写进 text，与程序在
    行尾追加的群名重复。
    """
    prompt = digest.build_system_prompt()

    assert rule_phrase in prompt


def test_user_prompt_embeds_every_item():
    """⚠️ 载荷必须真的进到 user prompt 里，且一条不少。

    原先只断言 ``"2026-09-13" in prompt``，而日期出现在**前缀**里，
    与载荷无关。

    变异反证：①把 ``body`` 整个丢掉只留日期前缀 → 原先全绿，等于拿空
    items 列表去问模型；②``ensure_ascii=False`` 改成 ``True`` → 原先全绿，
    中文全变 ``\\uXXXX``（模型看不到原文，输出 token 暴涨）。
    """
    payload = digest.build_items_payload(
        [_item(1, title="体检表"), _item(2, title="讲座", event_ts=2000)], {}, Redactor()
    )

    prompt = digest.build_user_prompt(payload, day="2026-09-13")

    assert "体检表" in prompt
    assert "讲座" in prompt
    # ensure_ascii=True 会把中文写成 \uXXXX——见 docstring 变异反证 ②
    assert "\\u" not in prompt

# ── quote 匹配 ──────────────────────────────────────────────


def test_match_lines_finds_item_by_quote():
    items = [_item(1, title="体检表"), _item(2, title="讲座", event_ts=2000)]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["讲座"], "label": "学术讲座", "text": "周五晚 7 点"}], items
    )

    assert unmatched == []
    assert len(lines) == 1
    assert lines[0].label == "学术讲座"
    assert lines[0].item_ids == (2,)


def test_match_lines_tolerates_inserted_spaces():
    """⚠️ 实测：模型会在数字两侧插空格（原文「风之海310」它写成「风之海 310」）。

    直接子串匹配会漏掉这种**格式**差异，但归一化后两侧都无空格、仍逐字对应。
    """
    items = [_item(1, detail="百度网盘搜索昵称“风之海310”")]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["风之海 310"], "label": "卖笔记", "text": ""}], items
    )

    assert unmatched == []
    assert lines[0].item_ids == (1,)


def test_match_lines_merges_multiple_quotes():
    items = [_item(1, title="面试地点变更"), _item(2, title="录取名单公布", event_ts=2000)]

    lines, _ = digest.match_lines(
        [{"quotes": ["面试地点变更", "录取名单公布"], "label": "新媒体", "text": "…"}],
        items,
    )

    assert lines[0].item_ids == (1, 2)


def test_match_lines_reports_unmatched_quotes():
    items = [_item(1, title="体检表")]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["根本不存在的标题"], "label": "x", "text": ""}], items
    )

    assert lines == []
    assert unmatched == ["根本不存在的标题"]


def test_match_lines_drops_too_short_quote():
    """太短的摘录容易误命中，宁可丢——沿用 refine._match_source 的判断。"""
    items = [_item(1, title="体检表")]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["表"], "label": "x", "text": ""}], items
    )

    assert lines == []
    assert unmatched == ["表"]


def test_match_lines_ignores_malformed_entries():
    """模型偶尔会返回字符串或 null 元素，不能让它们崩掉整轮。"""
    lines, unmatched = digest.match_lines(
        ["不是字典", None, {"quotes": "不是数组"}, {"quotes": ["体检表"], "label": "a"}],
        [_item(1, title="体检表")],
    )

    assert len(lines) == 1
    assert lines[0].label == "a"


def test_match_lines_falls_back_to_title_when_label_missing():
    lines, _ = digest.match_lines(
        [{"quotes": ["体检表"], "text": ""}], [_item(1, title="体检表")]
    )

    assert lines[0].label == "体检表"


def test_match_lines_one_quote_matching_two_items_marks_both():
    """标题重复的两条（实测全库有，如「校园卡办理」系列）必须都算覆盖。"""
    items = [_item(1, title="校园卡办理"), _item(2, title="校园卡办理", event_ts=2000)]

    lines, _ = digest.match_lines(
        [{"quotes": ["校园卡办理"], "label": "校园卡", "text": ""}], items
    )

    assert lines[0].item_ids == (1, 2)


# ── 机械补行 ────────────────────────────────────────────────


def test_build_rows_appends_mechanical_row_for_uncovered_item():
    items = [_item(1, title="体检表"), _item(2, title="讲座", event_ts=2000)]
    lines, _ = digest.match_lines(
        [{"quotes": ["体检表"], "label": "体检", "text": "10月8日前交"}], items
    )

    rows = digest.build_rows(lines, items)

    assert [r.mechanical for r in rows] == [False, True]
    assert rows[1].label == "讲座"


def test_build_rows_marks_low_confidence_only_when_all_items_low():
    items = [
        _item(1, title="存疑", confidence=0.1),
        _item(2, title="确定的", confidence=0.9, event_ts=2000),
    ]
    lines, _ = digest.match_lines(
        [
            {"quotes": ["存疑"], "label": "a", "text": ""},
            {"quotes": ["确定的"], "label": "b", "text": ""},
        ],
        items,
    )

    rows = digest.build_rows(lines, items)

    assert rows[0].low_confidence is True
    assert rows[1].low_confidence is False


def test_build_rows_merged_row_is_confident_when_any_item_is():
    items = [_item(1, title="存疑", confidence=0.1), _item(2, title="确定的", confidence=0.9, event_ts=2000)]
    lines, _ = digest.match_lines(
        [{"quotes": ["存疑", "确定的"], "label": "a", "text": ""}], items
    )

    rows = digest.build_rows(lines, items)

    assert rows[0].low_confidence is False
    assert rows[0].deadline_ts is None


def test_build_rows_takes_earliest_deadline_of_merged_items():
    items = [
        _item(1, title="甲", deadline_ts=5000),
        _item(2, title="乙", deadline_ts=4000, event_ts=2000),
    ]
    lines, _ = digest.match_lines(
        [{"quotes": ["甲", "乙"], "label": "合并", "text": ""}], items
    )

    assert digest.build_rows(lines, items)[0].deadline_ts == 4000


def test_build_rows_mechanical_row_keeps_own_confidence():
    items = [_item(1, title="存疑的", confidence=0.1)]

    rows = digest.build_rows([], items)

    assert rows[0].mechanical is True
    assert rows[0].low_confidence is True


# ── 渲染 ────────────────────────────────────────────────────


@pytest.fixture
def cats():
    from vigil.categories import Category

    return (
        Category("notice", "通知公告", "正式通知", "📋"),
        Category("activity", "活动", "讲座与社团", "🎤"),
        Category("academic", "学业", "作业与考试", "📚"),
    )


def _render(rows, cats, *, window_from=0, names=None, groups=3, messages=412):
    return digest.render_markdown(
        day="2026-09-13",
        stat_line=digest.stat_line(groups=groups, messages=messages,
                                   items=sum(1 for _ in rows) or 0),
        rows=rows, cats=cats, names=names or {}, window_from=window_from,
    )


def test_render_header_and_stat_line(cats):
    out = _render([digest.Row("体检表", "10月8日前交", "notice", 100, None, False)], cats)

    assert out.startswith("# 守夜人日报 · 2026-09-13")
    assert "3 个群 412 条消息" in out
    assert "## 📋 通知公告" in out
    assert "- **体检表** 10月8日前交" in out


def test_render_appends_group_name(cats):
    out = _render(
        [digest.Row("体检表", "", "notice", 100, None, False)],
        cats, names={100: "储运263班级群"},
    )

    assert out.rstrip().endswith("· 储运263班级群")


def test_render_omits_tail_when_group_unknown(cats):
    """群名查不到时不要退回群号——那是本不该出现在成品里的数字。"""
    out = _render([digest.Row("体检表", "", "notice", 999, None, False)], cats)

    assert "999" not in out


def test_render_alerts_section_for_future_deadline(cats):
    rows = [digest.Row("体检表", "交到辅导员处", "notice", 100, 5000, False)]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" in out
    assert "截止 " in out
    # 进了「别忘」就不该在类目区块里再出现一次
    assert out.count("**体检表**") == 1


def test_render_excludes_already_past_deadline_from_alerts(cats):
    """⚠️ 实测数据里有 deadline 早于事件日的条目（8/5 的条目挂 5/6 的截止）。

    不过滤的话，八月日报里会冒出「别忘 5 月 6 日」这种不可能执行的事。
    """
    rows = [digest.Row("档案袋封口", "", "notice", 100, 500, False)]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" not in out
    assert "- **档案袋封口**" in out        # 仍然要出现在类目区块里，不丢


def test_render_sections_follow_category_order(cats):
    rows = [
        digest.Row("a", "", "academic", 100, None, False),
        digest.Row("b", "", "activity", 100, None, False),
        digest.Row("c", "", "notice", 100, None, False),
    ]

    out = _render(rows, cats)

    assert out.index("## 📋 通知公告") < out.index("## 🎤 活动") < out.index("## 📚 学业")


def test_render_unknown_kind_is_kept_not_dropped(cats):
    """类目表里没有的 kind（理论上不该有）排到最后，但**不能静默丢**。"""
    out = _render([digest.Row("x", "", "没见过的类目", 100, None, False)], cats)

    assert "- **x**" in out


def test_render_unsure_section_comes_last(cats):
    rows = [
        digest.Row("确定", "", "notice", 100, None, False),
        digest.Row("存疑", "", "academic", 100, None, True),
    ]

    out = _render(rows, cats)

    assert "## 🤔 拿不准的" in out
    assert out.index("## 🤔 拿不准的") > out.index("## 📋 通知公告")
    assert out.index("**存疑**") > out.index("## 🤔 拿不准的")


def test_render_low_confidence_beats_deadline(cats):
    """既低置信度又有截止日的行归「拿不准」——存疑的信息不该催人去办。"""
    rows = [digest.Row("存疑", "", "notice", 100, 5000, True)]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" not in out
    assert "## 🤔 拿不准的" in out


def test_render_empty_window_says_no_news(cats):
    out = digest.render_markdown(
        day="2026-08-08", stat_line=digest.stat_line(groups=2, messages=12, items=0),
        rows=[], cats=cats, names={},
    )

    assert "没有值得一提的信息" in out
    assert "# 守夜人日报 · 2026-08-08" in out


def test_stat_line_mentions_items_when_present(cats):
    assert "提炼出 7 条" in digest.stat_line(groups=3, messages=412, items=7)


def test_stat_line_omits_items_when_zero():
    line = digest.stat_line(groups=2, messages=12, items=0)

    assert "提炼出" not in line
    assert "12" in line


# ── 窗口换算 ────────────────────────────────────────────────


def test_day_window_covers_exactly_one_day():
    since, until = digest.day_window("2026-09-13")

    assert until - since == 86400
    import datetime as dt

    assert dt.datetime.fromtimestamp(since).strftime("%H:%M") == "00:00"


def test_day_window_rejects_garbage():
    with pytest.raises(ValueError):
        digest.day_window("昨天")


def test_yesterday_defaults_to_the_day_before_today():
    import datetime as dt

    assert digest.yesterday(dt.date(2026, 9, 15)) == "2026-09-14"


# ── 锚点不变量（审查轮次 1：I1）─────────────────────────────
#
# 锚点 = `hits.sort(key=(event_ts, item_id))` 之后的**第一个** item，它决定整行的
# 分区与署名群。审查实测：删掉那行 `hits.sort`、把 `picked[0]` 改成 `picked[-1]`、
# 或把排序键退化成只按 `item_id`，**当时的 200 条测试全绿**——三条都是静默错配。
# 根因是所有多命中夹具的「命中序」恰好等于「排序序」。下面两条刻意让两者**错开**。


def test_anchor_is_earliest_item_regardless_of_input_order():
    """items 逆序传入 + quotes 逆序列出，锚点仍须是 event_ts 最小的那条。

    红线：模型对 `quotes` 的顺序没有任何约束（prompt 也没规定），
    所以「按 quotes 命中序取锚点」= 让模型的书写顺序决定群名与分区。
    """
    items = [
        _item(9, title="晚的", event_ts=2000, kind="activity", group_id=200),
        _item(1, title="早的", event_ts=1000, kind="notice", group_id=100),
    ]

    lines, _ = digest.match_lines(
        [{"quotes": ["晚的", "早的"], "label": "L", "text": ""}], items
    )

    assert lines[0].item_ids == (1, 9)
    row = digest.build_rows(lines, items)[0]
    assert (row.kind, row.group_id) == ("notice", 100)


def test_anchor_ranks_by_event_ts_before_item_id():
    """排序键是 ``(event_ts, item_id)``——**先比 event_ts**。

    这条夹具刻意让 `item_id` 的顺序与 `event_ts` 的顺序**相反**（早的那条
    item_id 更大）：只按 `item_id` 排的实现会挑错锚点，而 `item_ids` 集合、
    `label` / `text` 全都照旧——**唯独分区与署名群错**。
    """
    items = [
        _item(2, title="晚的", event_ts=2000, kind="activity", group_id=200),
        _item(9, title="早的", event_ts=1000, kind="notice", group_id=100),
    ]

    lines, _ = digest.match_lines(
        [{"quotes": ["晚的", "早的"], "label": "L", "text": ""}], items
    )

    assert lines[0].item_ids == (9, 2)
    row = digest.build_rows(lines, items)[0]
    assert (row.kind, row.group_id) == ("notice", 100)


# ── 编排 ────────────────────────────────────────────────────


class _FakeLLM:
    """假 LLM：记录调用次数，返回预设载荷。绝不联网。"""

    def __init__(self, lines):
        self.lines = lines
        self.calls = 0
        self.configs = []

    def __call__(self, cfg, *, system, user, sleep=None):
        from vigil.llm import LLMResult

        self.calls += 1
        self.configs.append(cfg)
        return LLMResult(payload={"lines": self.lines}, input_tokens=100,
                         output_tokens=50)


@pytest.fixture
def seeded(memdb):
    """两条 item + 一条窗口外 + 完整 messages。"""
    from vigil import store

    memdb.executescript(
        """
        CREATE TABLE messages (
            msg_id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
            ts INTEGER NOT NULL, sender_uid TEXT, content TEXT NOT NULL
        );
        """
    )
    since, until = digest.day_window("2026-09-13")
    memdb.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (1, 100, since + 60, "u_a", "通知：明天交体检表"),
            (2, 100, since + 120, "u_b", "收到"),
            (3, 200, since + 180, "u_c", "有讲座"),
        ],
    )
    store.ensure_schema(memdb)
    memdb.executemany(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "notice", "体检表", "10月8日前交", since + 60, None, 100, None,
             None, "[]", None, 0.9, "m", "v2", 1),
            (2, "activity", "讲座", None, since + 180, None, 200, None,
             None, "[]", None, 0.9, "m", "v2", 1),
        ],
    )
    memdb.commit()
    return memdb, since, until


class _Config:
    """最小 Config 替身——只用到 groups。"""

    def __init__(self, groups):
        from vigil.config import Group

        self.groups = tuple(Group(id=g, name=n) for g, n in groups.items())


def test_digest_writes_body_and_links_every_item(seeded, monkeypatch, tmp_path):
    from vigil import store

    conn, since, until = seeded
    fake = _FakeLLM([
        {"quotes": ["体检表"], "label": "体检", "text": "10月8日前交"},
        {"quotes": ["讲座"], "label": "讲座", "text": "周五晚"},
    ])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(
        _Config({100: "班级群", 200: "新生群"}), api_key="k", conn=conn,
        since=since, until=until, day_label="2026-09-13", output_dir=tmp_path,
    )

    assert fake.calls == 1
    assert stats.items == 2
    assert stats.mechanical == 0
    assert stats.errors == []
    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "- **体检** 10月8日前交 · 班级群" in body
    # 窗口内**每条** item 都必须挂上——这是「日报里的每一条都能在 Web 找到」的前提
    linked = conn.execute(
        "SELECT item_id FROM digest_items WHERE digest_id=? ORDER BY item_id",
        (stats.digest_id,),
    ).fetchall()
    assert [r[0] for r in linked] == [1, 2]


def test_digest_sends_max_tokens_and_thinking_off(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表"], "label": "a", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn, since=since,
                  until=until, day_label="2026-09-13", output_dir=tmp_path)

    assert fake.configs[0].max_tokens == digest.MAX_TOKENS
    assert fake.configs[0].enable_thinking is False


def test_digest_never_sends_group_ids(seeded, monkeypatch, tmp_path):
    """⚠️ 守着「群号不出网」这条硬约束——探针第一版就是在这里翻车的。"""
    conn, since, until = seeded
    seen = {}

    def spy(cfg, *, system, user, sleep=None):
        from vigil.llm import LLMResult

        seen["user"] = user
        seen["system"] = system
        return LLMResult(payload={"lines": []}, input_tokens=1, output_tokens=1)

    monkeypatch.setattr("vigil.digest.chat_json", spy)

    digest.digest(_Config({100: "班级群", 200: "新生群"}), api_key="k", conn=conn,
                  since=since, until=until, day_label="2026-09-13", output_dir=tmp_path)

    assert "班级群" in seen["user"]
    assert "100" not in seen["user"].replace("2026-09-13", "").replace("10月8日", "")


def test_digest_uncovered_item_gets_mechanical_row(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表"], "label": "体检", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群", 200: "新生群"}), api_key="k",
                          conn=conn, since=since, until=until,
                          day_label="2026-09-13", output_dir=tmp_path)

    assert stats.mechanical == 1
    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "- **讲座**" in body


def test_digest_empty_window_does_not_call_model(seeded, monkeypatch, tmp_path):
    """空窗日：不花 token、不留空白文件，但**明确说没有信息**（spec §4.6）。"""
    conn, since, until = seeded
    conn.execute("DELETE FROM items")
    conn.commit()
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path)

    assert fake.calls == 0
    assert stats.items == 0
    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "没有值得一提的信息" in body


def test_digest_llm_failure_writes_nothing_and_reports(seeded, monkeypatch, tmp_path):
    """失败不许降级成「机械拼盘」——那种文件看起来和正常日报一样。"""
    from vigil.llm import LLMError

    conn, since, until = seeded

    def boom(cfg, *, system, user, sleep=None):
        raise LLMError("HTTP 503")

    monkeypatch.setattr("vigil.digest.chat_json", boom)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path)

    assert stats.errors and "503" in stats.errors[0]
    assert stats.digest_id is None
    assert not (tmp_path / "2026-09-13.md").exists()
    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0


def test_digest_rerun_replaces_instead_of_stacking(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表", "讲座"], "label": "全部", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)
    cfg = _Config({100: "班级群", 200: "新生群"})

    digest.digest(cfg, api_key="k", conn=conn, since=since, until=until,
                  day_label="2026-09-13", output_dir=tmp_path)
    digest.digest(cfg, api_key="k", conn=conn, since=since, until=until,
                  day_label="2026-09-13", output_dir=tmp_path)

    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 1
    assert fake.calls == 2


def test_digest_dry_run_does_not_call_model_or_write(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path, dry_run=True)

    assert fake.calls == 0
    assert stats.items == 2
    assert not (tmp_path / "2026-09-13.md").exists()


def test_digest_dry_run_on_empty_window_still_writes_nothing(seeded, monkeypatch, tmp_path):
    """⚠️ 空窗 + dry-run 的组合——端到端实测抓到过：当时空窗分支排在 dry_run
    检查前面且无条件落库，于是 `--dry-run` 照样写了库、落了文件。
    单测原本用的样本有 item，走的是另一条分支，所以没守住这个组合。"""
    conn, since, until = seeded
    conn.execute("DELETE FROM items")
    conn.commit()
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path, dry_run=True)

    assert fake.calls == 0
    assert stats.digest_id is None
    assert not (tmp_path / "2026-09-13.md").exists()
    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0


def test_digest_no_write_skips_file_but_still_saves(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表", "讲座"], "label": "全部", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群", 200: "新生群"}), api_key="k",
                          conn=conn, since=since, until=until,
                          day_label="2026-09-13", output_dir=tmp_path,
                          write_file=False)

    assert stats.digest_id is not None
    assert stats.output_path == ""
    assert not (tmp_path / "2026-09-13.md").exists()


def test_digest_rejects_reversed_window(seeded):
    conn, _, _ = seeded

    with pytest.raises(ValueError):
        digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                      since=5000, until=1000, day_label="2026-09-13")
