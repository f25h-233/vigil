"""脱敏的测试。

**样本来源要说清楚**（早期版本的本文件曾声称"全部取自真实数据"，那是错的）：
群昵称样本确实取自本机真实数据（`2600090309张韩18368500707` 一类），
但**正文样本多是构造的**——真实语料里没有恰好可用的例子。
比如 `13812345678` 这个手机号在全库 0 命中，它只是形态正确。
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


# ── URL 豁免 ──────────────────────────────────────────────────────
# W1 审查实测：不豁免时全库 34 条链接有 2 条被打烂，
# 都是 B 站分享链的 32 位 hex vd_source。


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.bilibili.com/video/BV1GH4y1H75S/?vd_source=1a2b3c4d5e6f7a8b",
        "报名 https://www.wjx.cn/vm/1788234567890.aspx",
        "https://docs.qq.com/sheet/DR0p1b2M3d4567890123",
        "https://qr.qq.com/q/1234567890123",
        "https://example.com/activity?id=1788234567890&t=1",
    ],
)
def test_urls_are_left_intact(raw):
    """链接必须原样保留——`links` 是 item schema 的一等字段。

    链接里的文档 ID / 分享 token 是结构化标识符，不是手机号或学号；
    抹掉会产出**残废 URL 且是静默的**——没有报错，只是数据错了。
    """
    assert redact_text(raw) == raw


def test_url_exemption_is_scoped():
    """豁免只针对 URL 段——同一行里 URL 之外的号码仍要抹掉。"""
    text = "联系13812345678 报名 https://www.wjx.cn/vm/1788234567890.aspx"
    out = redact_text(text)
    assert "13812345678" not in out
    assert "https://www.wjx.cn/vm/1788234567890.aspx" in out


# ── 身份短号 ──────────────────────────────────────────────────────
# W1 审查实测：QQ 号常见 8 位、群号 9 位，而 LONGNUM 阈值是 10 位
# → 81464214 / 421632774 会原样出网。阈值又不能下调（8 位会打死 20261008），
# 所以只能靠上下文标签。


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("QQ：81464214", f"QQ：{PLACEHOLDER}"),
        ("加我qq 81464214", f"加我qq {PLACEHOLDER}"),
        ("群号 421632774", f"群号 {PLACEHOLDER}"),
        ("微信号：abc123456", "微信号：abc123456"),  # 非纯数字，不该动
    ],
)
def test_redacts_identity_numbers_after_label(raw, expected):
    assert redact_text(raw) == expected


@pytest.mark.parametrize("raw", ["第 3 教学楼", "下午 4 点 30 分", "2026 级", "共 12345 人"])
def test_identity_rule_does_not_eat_ordinary_numbers(raw):
    """没有身份标签的普通数字不能被误伤——否则日期地点全毁。"""
    assert redact_text(raw) == raw


def test_phone_does_not_leave_residue_in_long_digits():
    """缺数字边界时，13 位数字会被咬掉前 11 位、留下 `90` 的残渣。"""
    out = redact_text("订单号6217001381234567890")
    assert "567890" not in out, "不该留下残渣"
    assert out == f"订单号{PLACEHOLDER}"


# ── 匿名者 ────────────────────────────────────────────────────────


def test_actor_rejects_empty_uid():
    """匿名者没有身份——静默返回共享代号会让模型把不同人当成同一人。"""
    with pytest.raises(ValueError, match="匿名"):
        Redactor().actor("")


def test_actor_rejection_does_not_shift_real_codes():
    """一次误调用不该影响真实 uid 的代号分配（W1 审查实测的隐患）。"""
    r = Redactor()
    with pytest.raises(ValueError):
        r.actor("")
    assert r.actor("u_a") == "U1"
    assert r.actor("u_b") == "U2"


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
