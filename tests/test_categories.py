"""类目配置的测试。重点是校验失败路径——配置错要快速失败。"""

from __future__ import annotations

import pytest

from vigil import categories
from vigil.categories import Category, CategoryError


def _write(tmp_path, body: str):
    p = tmp_path / "categories.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_real_project_config():
    """真实配置文件必须能加载，且正是用户裁定的七类。"""
    cats = categories.load_categories()
    assert [c.slug for c in cats] == [
        "notice",
        "academic",
        "activity",
        "life",
        "secondhand",
        "lostfound",
        "job",
    ]
    assert all(c.label and c.desc for c in cats)


def test_rejects_duplicate_slug(tmp_path):
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "notice"
label = "通知"
desc = "正式通知"

[[categories]]
slug = "notice"
label = "重复"
desc = "重复了"
""",
    )
    with pytest.raises(CategoryError, match="重复"):
        categories.load_categories(p)


def test_rejects_discard_as_slug(tmp_path):
    """discard 是保留字（表示「丢弃」），不能当类目名。"""
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "discard"
label = "丢弃"
desc = "假装是个类目"
""",
    )
    with pytest.raises(CategoryError, match="保留字"):
        categories.load_categories(p)


def test_rejects_missing_desc(tmp_path):
    """desc 不是可选的——提示词靠它告诉模型这一类收什么。"""
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "notice"
label = "通知"
""",
    )
    with pytest.raises(CategoryError, match="desc"):
        categories.load_categories(p)


def test_rejects_empty_config(tmp_path):
    p = _write(tmp_path, "[settings]\n")
    with pytest.raises(CategoryError, match="空"):
        categories.load_categories(p)


def test_prompt_block_lists_every_slug():
    cats = categories.load_categories()
    block = categories.prompt_block(cats)
    for c in cats:
        assert c.slug in block
        assert c.desc in block
    # 一行一个类目
    assert len(block.splitlines()) == len(cats)


def test_category_is_frozen():
    c = Category(slug="a", label="b", desc="c")
    with pytest.raises(Exception):
        c.slug = "x"  # type: ignore[misc]
