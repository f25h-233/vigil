"""配置与密钥读取。

失败策略：配置缺字段、群号格式不对、密钥为空 → ConfigError 快速失败。
不猜、不兜底——配置写错是我们自己的问题，越早暴露越好。
"""

from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "groups.toml"
DEFAULT_ENV = REPO_ROOT / ".env"


class ConfigError(RuntimeError):
    """配置层面的错误——快速失败。"""


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    enabled: bool = True


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
        groups.append(
            Group(id=gid, name=entry.get("name", ""), enabled=entry.get("enabled", True))
        )

    if not groups:
        raise ConfigError(f"{path}: 一个群都没配（[[groups]] 段为空）")

    return Config(qq_db_dir=qq_db_dir, output_db=output_db, groups=tuple(groups))


def load_key(env_path: pathlib.Path | None = None) -> str:
    """读取数据库密钥：优先环境变量，其次仓库根的 .env。"""
    key = os.environ.get("VIGIL_DB_KEY", "").strip()
    if key:
        return key

    env_path = env_path or DEFAULT_ENV
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "VIGIL_DB_KEY":
                return value.strip().strip("'\"")
    return ""
