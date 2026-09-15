"""截止日核验：源文里能不能逐字找到这个日期。

⚠️ 本文件的用例是**从 tests/test_digest.py 的既有覆盖里长出来的**：
核验函数原在 digest.py，M3 平移到 deadline.py。平移的正确性由
「test_digest.py 的 105 条既有测试全绿」证明，本文件补的是**新增的那部分**：
「哪些该清掉」这个集合计算。

⚠️ 数字是**实测值**（`pytest tests/test_digest.py --co -q`，2026-09-15），不是
计划里的 72——那个数是更早的计数快照，已经过期（审查裁决：本项目对「没人能
验证的数字」有纪律，写小的不如写准的）。
"""

from __future__ import annotations

import datetime as dt

from vigil import deadline


def _ts(y: int, m: int, d: int) -> int:
    return int(dt.datetime(y, m, d, 12, 0).timestamp())


def test_supported_when_source_has_the_date_literally():
    assert deadline.deadline_supported(_ts(2026, 9, 16), "9月16日12:00开始报名缴费")


def test_unsupported_when_source_only_has_relative_words():
    # 四条都是真实库里出现过的原文（见计划「发现 6」）
    assert not deadline.deadline_supported(_ts(2026, 9, 14), "请于今天下午16点之前改备注")
    assert not deadline.deadline_supported(_ts(2026, 9, 15), "明早7：20各班在宿舍楼下集合")
    assert not deadline.deadline_supported(_ts(2026, 9, 19), "周六下午4.00-8.00")
    assert not deadline.deadline_supported(_ts(2026, 8, 31), "八月要出六级成绩了")


def test_no_deadline_is_never_supported():
    assert not deadline.deadline_supported(None, "随便什么 9月16日")


def test_unverified_ids_picks_only_the_unsupported():
    items = [(1, _ts(2026, 9, 16)), (2, _ts(2026, 9, 14)), (3, None)]
    sources = {1: "9月16日截止", 2: "今天下午截止", 3: "无关"}
    assert deadline.unverified_item_ids(items, sources) == frozenset({2})


def test_unverified_ids_treats_missing_source_row_as_unsupported():
    """没有来源行 = 证不出来 = 没有依据。**口径必须与 M2 一致。**"""
    assert deadline.unverified_item_ids([(7, _ts(2026, 9, 16))], {}) == frozenset({7})


def test_unverified_ids_ignores_items_without_deadline():
    assert deadline.unverified_item_ids([(1, None), (2, None)], {}) == frozenset()
