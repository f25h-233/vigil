"""脱敏的测试。

样本全部取自本机真实群昵称与真实消息——用真数据测才有意义。
"""

from __future__ import annotations

import pytest

from vigil.redact import PLACEHOLDER, Redactor, redact_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        # 真实群昵称：学号 + 姓名 + 手机号（实测样本）
        ("2600090309张韩18368500707", f"{PLACEHOLDER}张韩{PLACEHOLDER}"),
        ("2600090304杜欣格19850212122", f"{PLACEHOLDER}杜欣格{PLACEHOLDER}"),
        # 姓名保留是关键：它是判断「谁发的」的信号
        ("西太湖新媒体杨馨雅", "西太湖新媒体杨馨雅"),
        # 带角色的昵称，号码抹掉、角色留下
        (
            "储运263班主任助理卞雨琦19551968610",
            f"储运263班主任助理卞雨琦{PLACEHOLDER}",
        ),
        # 只带学号
        ("2600090319储运263林子哲", f"{PLACEHOLDER}储运263林子哲"),
        # 正文里的手机号
        ("有问题打我电话13812345678", f"有问题打我电话{PLACEHOLDER}"),
    ],
)
def test_redacts_numbers_keeps_names(raw, expected):
    assert redact_text(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "截止日期是2026-10-08",
        "9月15日24:00截止",
        "作业截止9月7号",
        "学费4800元",
        "明天下午3点到4点",
        "2026级新生",
    ],
)
def test_does_not_touch_dates_or_amounts(raw):
    """日期与金额必须毫发无伤——打坏了 prompt 就抽不出 deadline。

    连字符与中文让它们不命中 \\d{10,}，这是设计如此，不是巧合。
    """
    assert redact_text(raw) == raw


def test_redactor_is_stable_within_run():
    """同一 uid 必须一直拿到同一个代号，否则模型看不出「同一人说了两次」。"""
    r = Redactor()
    assert r.actor("u_a") == r.actor("u_a")
    assert r.actor("u_a") != r.actor("u_b")
    assert r.group(100) == r.group(100)
    assert r.group(100) != r.group(200)


def test_redactor_codes_are_short():
    """代号要短——它们会出现在每一条发给模型的记录里。"""
    r = Redactor()
    assert r.actor("u_first") == "U1"
    assert r.actor("u_second") == "U2"
    assert r.group(999) == "G1"


def test_redactor_text_delegates():
    r = Redactor()
    assert r.text("电话13812345678") == f"电话{PLACEHOLDER}"


def test_handles_empty_and_none_like():
    assert redact_text("") == ""
    assert redact_text("无号码") == "无号码"
