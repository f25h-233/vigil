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
