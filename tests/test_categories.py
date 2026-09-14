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


@pytest.mark.parametrize(
    "bad", ["Notice", "NOTICE", "通知", "2notice", "no-tice", "no.tice", "", "notice "]
)
def test_rejects_non_lowercase_ascii_slug(tmp_path, bad):
    """slug 会进 items.kind 列、提示词、前端筛选键——必须是小写英文标识符。

    `str.isidentifier()` 不够：它放行 `Notice` 与 `通知`（W1 审查实测）。
    """
    p = _write(
        tmp_path,
        f"""
[[categories]]
slug = "{bad}"
label = "x"
desc = "y"
""",
    )
    with pytest.raises(CategoryError):
        categories.load_categories(p)


def test_accepts_underscore_and_digits_after_first_letter(tmp_path):
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "part_time_job2"
label = "x"
desc = "y"
""",
    )
    assert categories.load_categories(p)[0].slug == "part_time_job2"


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


def test_rejects_slug_with_trailing_newline(tmp_path):
    """`^[a-z][a-z0-9_]*$` 的 `$` 允许结尾一个换行，所以 `"notice\\n"` 会被旧正则放行。

    ⚠️ 这里**必须用 TOML 多行字符串**把真换行喂进去：写成单行基本串里的
    `\\n` 转义会被 tomllib 判为非法字符（单行串不允许裸换行），
    测试就会绕过正则、在 TOML 解析层失败——**假绿**。
    所以本用例与下面的 `test_rejects_malformed_toml` 必须分开，
    各自只测一件事。
    """
    p = _write(
        tmp_path,
        '[[categories]]\nslug = """notice\n"""\nlabel = "x"\ndesc = "y"\n',
    )
    with pytest.raises(CategoryError, match="slug 必须匹配"):
        categories.load_categories(p)


def test_rejects_malformed_toml(tmp_path):
    """TOML 语法错也必须走 CategoryError，而不是甩原始 traceback。

    `tomllib.TOMLDecodeError` 继承自 ValueError 而非 RuntimeError——
    不包的话会绕过 cli 的错误处理契约（cli 只捕 CategoryError）。
    这条是 fix 审查实测抓出来的。
    """
    p = _write(tmp_path, '[[categories]]\nslug = "unclosed\n')
    with pytest.raises(CategoryError, match="TOML"):
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
