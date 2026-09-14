"""类目配置：从 config/categories.toml 读，校验后供预筛与提示词共用。

为什么不硬编码成常量：类目是产品决策，用户已经改过一次
（把「二手」「失物招领」从「生活」里拆出来）。写死在代码里，
每次调整都要改代码、改测试、重发版。
"""

from __future__ import annotations

import pathlib
import re
import tomllib
from dataclasses import dataclass

from .config import REPO_ROOT

DEFAULT_CATEGORIES = REPO_ROOT / "config" / "categories.toml"

# 保留字：被丢弃的消息在 refine_runs 里记这个值，所以不能用作类目名
DISCARD = "discard"

# slug 会被写进 items.kind 列、渲染进提示词、当作 CLI 与前端的筛选键，
# 所以必须是小写英文标识符。
# ⚠️ 只查 str.isidentifier() 不够——它放行 'Notice' 和 '通知'，
# 而两者都会在下游造成麻烦（W1 审查实测）。用正则收紧。
# ⚠️ 用 \Z 而不是 $：Python 里 $ 允许结尾有一个换行，
# 于是 "notice\n" 会被放行（fix 审查实测）。
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*\Z")


class CategoryError(RuntimeError):
    """类目配置有问题——快速失败。"""


@dataclass(frozen=True)
class Category:
    slug: str
    label: str
    desc: str
    icon: str = ""


def load_categories(path: pathlib.Path | None = None) -> tuple[Category, ...]:
    path = path or DEFAULT_CATEGORIES
    if not path.is_file():
        raise CategoryError(f"找不到类目配置: {path}")

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        # 必须包成 CategoryError：TOMLDecodeError 继承自 ValueError 而不是
        # RuntimeError，不包的话会绕过 cli 的错误处理契约，用户看到的是
        # 原始 traceback 而不是一行可读的配置错误。
        raise CategoryError(f"{path}: TOML 语法错误——{exc}") from exc

    entries = raw.get("categories")
    if not entries:
        raise CategoryError(f"{path}: [[categories]] 段为空")

    out: list[Category] = []
    seen: set[str] = set()

    for entry in entries:
        slug = str(entry.get("slug", ""))
        if not _SLUG_RE.match(slug):
            raise CategoryError(
                f"{path}: slug 必须匹配 {_SLUG_RE.pattern}，实际是 {slug!r}"
            )
        if slug in seen:
            raise CategoryError(f"{path}: slug 重复: {slug}")
        if slug == DISCARD:
            raise CategoryError(f"{path}: {DISCARD!r} 是保留字，不能作类目")
        seen.add(slug)

        desc = str(entry.get("desc", "")).strip()
        if not desc:
            raise CategoryError(f"{path}: 类目 {slug} 缺少 desc（提示词要用它）")

        out.append(
            Category(
                slug=slug,
                label=str(entry.get("label", slug)),
                desc=desc,
                icon=str(entry.get("icon", "")),
            )
        )

    return tuple(out)


def prompt_block(cats: tuple[Category, ...]) -> str:
    """渲染成提示词里的类目表——改 categories.toml 即改提示词。"""
    width = max(len(c.slug) for c in cats)
    return "\n".join(f"{c.slug.ljust(width)}  {c.label}：{c.desc}" for c in cats)
