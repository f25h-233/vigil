"""配置与密钥读取。

失败策略：配置缺字段、群号格式不对、密钥为空 → ConfigError 快速失败。
不猜、不兜底——配置写错是我们自己的问题，越早暴露越好。
"""

from __future__ import annotations

import os
import pathlib
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "groups.toml"
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_PERSONS = REPO_ROOT / "config" / "persons.toml"


class ConfigError(RuntimeError):
    """配置层面的错误——快速失败。"""


# 群分级：high = 不受关键词过滤（班级群/课程群/部门群里的
# 「闲聊」往往是真通知）；normal = 需要关键词或角色昵称命中。
TIER_HIGH = "high"
TIER_NORMAL = "normal"
VALID_TIERS = frozenset({TIER_HIGH, TIER_NORMAL})


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    enabled: bool = True
    tier: str = TIER_NORMAL


@dataclass(frozen=True)
class Config:
    qq_db_dir: pathlib.Path
    output_db: pathlib.Path
    groups: tuple[Group, ...]

    @property
    def enabled_groups(self) -> tuple[Group, ...]:
        return tuple(g for g in self.groups if g.enabled)

    def group_name(self, gid: int) -> str:
        for g in self.groups:
            if g.id == gid:
                return g.name
        return ""

    def tier_of(self, gid: int) -> str:
        """未知群的默认档位是 normal——保守，宁可多筛不可漏喂。"""
        for g in self.groups:
            if g.id == gid:
                return g.tier
        return TIER_NORMAL


def load_config(path: pathlib.Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG
    if not path.is_file():
        raise ConfigError(f"找不到配置文件: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    settings = raw.get("settings")
    if not isinstance(settings, dict):
        raise ConfigError(f"{path}: 缺少 [settings] 段")

    for field in ("qq_db_dir", "output_db"):
        if not settings.get(field):
            raise ConfigError(f"{path}: [settings] 缺少 {field}")

    qq_db_dir = pathlib.Path(settings["qq_db_dir"])
    if not qq_db_dir.is_dir():
        raise ConfigError(f"QQ 数据库目录不存在: {qq_db_dir}")

    output_db = pathlib.Path(settings["output_db"])
    if not output_db.is_absolute():
        output_db = REPO_ROOT / output_db

    groups: list[Group] = []
    for entry in raw.get("groups", []):
        gid = entry.get("id")
        if not isinstance(gid, int) or gid <= 0:
            raise ConfigError(f"{path}: 群号必须为正整数，实际是 {gid!r}")
        tier = str(entry.get("tier", TIER_NORMAL))
        if tier not in VALID_TIERS:
            raise ConfigError(
                f"{path}: 群 {gid} 的 tier 只能是 {sorted(VALID_TIERS)}，实际是 {tier!r}"
            )
        groups.append(
            Group(
                id=gid,
                name=entry.get("name", ""),
                enabled=entry.get("enabled", True),
                tier=tier,
            )
        )

    if not groups:
        raise ConfigError(f"{path}: 一个群都没配（[[groups]] 段为空）")

    return Config(qq_db_dir=qq_db_dir, output_db=output_db, groups=tuple(groups))


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


def _read_env(name: str, env_path: pathlib.Path | None = None) -> str:
    """先读同名环境变量，再读仓库根的 .env。找不到返回空串。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value

    path = env_path or DEFAULT_ENV
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        if key.strip() == name:
            return raw.strip().strip("'\"")
    return ""


def load_key(env_path: pathlib.Path | None = None) -> str:
    """读取数据库密钥：优先环境变量 VIGIL_DB_KEY，其次仓库根的 .env。"""
    return _read_env("VIGIL_DB_KEY", env_path)


def load_llm_key(env_path: pathlib.Path | None = None) -> str:
    """读取 LLM 密钥：优先环境变量 SILICONFLOW_API_KEY，其次 .env。

    与数据库密钥分开取名，是因为它们是完全不同的凭证——
    混用会让「换模型」变成一件危险的事。
    """
    return _read_env("SILICONFLOW_API_KEY", env_path)
