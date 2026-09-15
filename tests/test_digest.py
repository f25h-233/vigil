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
