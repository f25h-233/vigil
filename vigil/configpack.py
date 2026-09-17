"""配置包：把三份配置合成一份可携带的 TOML（M6 T7）。

**形态**：单个文件，`[settings]` + `[[groups]]` + `[[categories]]` + `[[persons]]`
+ `[[kind_aliases]]`。

**四条边界见计划 §T7 的表格。** 其中最容易漏的是第三条——
`kind_aliases` **必须**进包：它是「改过 slug 名」这件事的后果，
属于配置的语义；不含它的话，另一个机器导入后**条目会全部悬空**。

⚠️ **本模块不做任何写入之外的副作用**，也不碰 `data/vigil.db`。
"""

from __future__ import annotations

import pathlib
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass

from . import overrides
from .categories import Category, save_categories, validate_categories
from .config import (
    Config,
    ConfigError,
    Person,
    atomic_write_text,
    save_config,
    save_persons,
    toml_int,
    toml_path,
    toml_str,
    validate_config_raw,
)

PACK_SCHEMA = 1

_HEADER = """\
# VIGIL 配置包
#
# 这一个文件里装着三份配置：监听群 / 类目 / 监视人物，外加 slug 改名映射。
# 用 `vigil config import <这个文件>` 或网页「配置」页导入。
#
# ⛔ **不含任何密钥**：`.env` 里的 SILICONFLOW_API_KEY / VIGIL_DB_KEY 永远不在这里。
# ⛔ **不含人工干预数据**（改过的分类、软删的条目）——那是**本机**的数据，
#    不是配置（spec §7）。
"""


@dataclass(frozen=True)
class Pack:
    config: Config | None
    categories: tuple[Category, ...]
    persons: tuple[Person, ...]
    aliases: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Paths:
    """导入的落点。**显式传入**，不在模块里读 `REPO_ROOT`——

    ⚠️ 与 `api.persons_path()` / `api.config_path()` 同一条判据：
    路径若在模块级冻住，测试里 `monkeypatch.setattr` 就够不着它，
    于是一次导入会**写进真仓库**，而所有测试照样绿（那个夹具会变成空守卫）。
    """

    groups: pathlib.Path
    categories: pathlib.Path
    persons: pathlib.Path


@dataclass
class ImportReport:
    groups: int = 0
    categories: int = 0
    persons: int = 0
    aliases: int = 0
    settings_skipped: bool = False


def build(
    *,
    config: Config,
    cats: Sequence[Category],
    persons: Sequence[Person],
    aliases: Sequence[tuple[str, str]] | dict[str, str] = (),
) -> str:
    """渲染成配置包的文本。**不落盘**（`write_pack` 才落）。"""
    lines = [_HEADER, "", f"schema = {PACK_SCHEMA}", ""]

    # ⚠️ `[settings]` 写在所有 `[[…]]` 之前，与现有 `groups.toml` 的段序一致、
    # 便于人读与 diff（约定，不是不变量）。
    # ⚠️ **不许**在这里写「不改顺序会嵌套成 `groups[-1].settings`」那类理由
    # ——那是**实测不成立**的（计划勘误 E4 / M6 T2）：TOML 的 `[header]` 是
    # 从根算的**绝对路径**，`[settings]` 写在哪都在顶层；会嵌套的只有
    # `[groups.settings]` 那种显式带前缀的写法。本项目最贵的一课是**错的论证
    # 比没有论证更危险**：一个编出来的技术后果会让后来者以为自己理解了，
    # 于是不去验证。
    lines += [
        "[settings]",
        f"qq_db_dir = {toml_path(config.qq_db_dir)}",
        f"output_db = {toml_path(config.output_db)}",
        "",
    ]
    for g in config.groups:
        lines += [
            "[[groups]]",
            f"id = {toml_int(g.id, '群号')}",
            f"name = {toml_str(g.name)}",
            f"enabled = {'true' if g.enabled else 'false'}",
            f"tier = {toml_str(g.tier)}",
            "",
        ]
    for c in cats:
        lines += [
            "[[categories]]",
            f"slug = {toml_str(c.slug)}",
            f"label = {toml_str(c.label)}",
        ]
        if c.icon:
            lines.append(f"icon = {toml_str(c.icon)}")
        lines += [f"desc = {toml_str(c.desc)}", ""]
    for p in persons:
        lines += [
            "[[persons]]",
            f"uin = {toml_int(p.uin, 'uin')}",
            f"label = {toml_str(p.label)}",
        ]
        if p.note:
            lines.append(f"note = {toml_str(p.note)}")
        lines.append("")
    items = aliases.items() if isinstance(aliases, dict) else aliases
    for old, new in items:
        lines += [
            "[[kind_aliases]]",
            f"old_kind = {toml_str(old)}",
            f"new_kind = {toml_str(new)}",
            "",
        ]
    return "\n".join(lines)


def write_pack(
    path: pathlib.Path,
    *,
    config: Config,
    cats: Sequence[Category],
    persons: Sequence[Person],
    aliases: Sequence[tuple[str, str]] | dict[str, str] = (),
) -> pathlib.Path:
    text = build(config=config, cats=cats, persons=persons, aliases=aliases)
    atomic_write_text(path, text)
    return path


def parse(text: str, path: pathlib.Path) -> Pack:
    """解析并**完整校验**一个配置包。任何问题都抛 `ConfigError`。

    ⚠️ 校验的是**整包**，而且是**在任何写入之前**——`import_pack` 靠这一点
    才能做到「全有或全无」。半新半旧的配置是最坏的结果：用户看到「导入失败」，
    以为什么都没发生，实际已经写进去了一半。
    """
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: TOML 语法错误——{exc}") from exc

    if raw.get("schema") != PACK_SCHEMA:
        raise ConfigError(
            f"{path}: 配置包版本不符（读到 {raw.get('schema')!r}，"
            f"本程序认 {PACK_SCHEMA}）。这份包可能是更新版的 VIGIL 导出的——"
            "形状变了就必须拒绝，静默错读会让导入的配置**看起来对了、其实错了**。"
        )

    # ⚠️ 群清单可以为空（"这份包只带类目"是合法的），但**真导入时**会撞
    # `validate_config_raw` 的「一个群都没配」——那是 `save_config` 的判据，
    # 与"包里有没有群"是两回事。这里用一份**宽容的**校验拿到分组数据。
    groups_raw = raw.get("groups", [])
    cfg: Config | None = None
    if raw.get("settings") is not None:
        try:
            cfg = validate_config_raw(raw, path)
        except ConfigError as exc:
            # 包里的 qq_db_dir 多半指向**导出那台机器**的路径。这是**预期内**的，
            # 所以把话说明白：要么在本机建好那个目录，要么用 `--keep-settings`。
            raise ConfigError(
                f"{path}: [settings] 段校验不过——{exc}\n"
                "  ⚠️ 若这份包来自另一台机器，它的 qq_db_dir 是**那边**的路径。"
                "用 `--keep-settings`（网页上勾「保留本机路径」）只导入群/类目/人物。"
            ) from exc
    elif groups_raw:
        raise ConfigError(
            f"{path}: 有 [[groups]] 却没有 [settings]——群配置没法独立存在"
            "（它需要 qq_db_dir 才知道去哪儿读消息）"
        )

    cats = validate_categories(raw.get("categories"), path)

    persons: list[Person] = []
    seen: set[int] = set()
    for entry in raw.get("persons", []):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: 每个 [[persons]] 段都必须是键值表")
        uin = entry.get("uin")
        if isinstance(uin, bool) or not isinstance(uin, int) or uin <= 0:
            raise ConfigError(f"{path}: 人物 uin 必须为正整数，实际是 {uin!r}")
        if uin in seen:
            raise ConfigError(f"{path}: uin {uin} 重复出现")
        label = str(entry.get("label", "")).strip()
        if not label:
            raise ConfigError(f"{path}: uin {uin} 缺 label")
        seen.add(uin)
        persons.append(
            Person(uin=uin, label=label, note=str(entry.get("note", "")).strip())
        )

    aliases: list[tuple[str, str]] = []
    seen_old: set[str] = set()
    for entry in raw.get("kind_aliases", []):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: 每个 [[kind_aliases]] 段都必须是键值表")
        old = str(entry.get("old_kind", "")).strip()
        new = str(entry.get("new_kind", "")).strip()
        if not old or not new:
            raise ConfigError(f"{path}: kind_aliases 的两端都不能为空")
        if old == new:
            raise ConfigError(f"{path}: kind_aliases 的两端相同（{old}）")
        if old in seen_old:
            raise ConfigError(f"{path}: 旧类目 {old} 出现了两次")
        seen_old.add(old)
        aliases.append((old, new))

    return Pack(
        config=cfg,
        categories=cats,
        persons=tuple(persons),
        aliases=tuple(aliases),
    )


def _read_local_config(path: pathlib.Path) -> Config | None:
    """读本机那份 `groups.toml`；**读不出来返回 `None`**（不是异常）。

    ⚠️ 两件各不相同的事在这里被归成同一支，理由都是"此刻没法保留本机设置"：
      · **文件不在** —— 第一次导入，没有任何"本机设置"可保留；
      · **文件坏了**（语法错 / 校验不过）—— 里面的 qq_db_dir 取不出来。
        ⚠️ `TOMLDecodeError` 必须一并接住：它继承自 **ValueError** 而不是
        RuntimeError，只捕 `ConfigError` 的话一次手改笔误会让导入以
        **裸 traceback** 收场（这正是 `load_config` 从 M6 T2 起要包它的同一条理由）。
    """
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            return validate_config_raw(tomllib.load(f), path)
    except (ConfigError, tomllib.TOMLDecodeError):
        return None


def import_pack(
    pack: Pack,
    *,
    keep_settings: bool,
    paths: Paths,
    on_progress=print,
) -> ImportReport:
    """把包写进 `paths`。**全有或全无**：校验在 `parse` 里已经跑完。

    ⚠️ **写入顺序有意义**：先写 `kind_aliases`，再写配置。
    反过来的话，中间崩溃会留下「配置里已经没有 `life` 了、但别名还没建」
    ⇒ 条目永久悬空。这与 `api.api_update_category` 的顺序是**同一条理由**。

    ⚠️ **整段取 `overrides.ALIAS_LOCK`**（T5 的不变量）：别名写完、类目文件
    还没写的那一瞬间，若 `reconcile_if_stale`（挂在**每一次查询**上）跑进来，
    它会拿**磁盘上那份还是旧的**类目表去剪枝 ⇒ 刚写进去的别名被判成
    "目标不存在"剪掉 ⇒ 条目永久悬空。写端点取这把锁覆盖
    `set_kind_alias → 写文件` 整段，与 `api_update_category` 完全同形。
    """
    report = ImportReport(settings_skipped=keep_settings)

    # ① 别名 → ② 类目 → ③ 剪枝：三段在同一把锁里（见 docstring）。
    with overrides.ALIAS_LOCK:
        if pack.aliases:
            # ⚠️ `ensure_schema()` 不能省：`overrides.connect()` **不建表**，
            # 而 `vigil config import` 可能是这台机器上第一条碰 overlay 的命令
            # （没有它就是一个 `no such table: kind_alias` 的裸 traceback）。
            overrides.ensure_schema()
            ov = overrides.connect()
            try:
                for old, new in pack.aliases:
                    overrides.set_kind_alias(ov, old_kind=old, new_kind=new)
            finally:
                ov.close()
            report.aliases = len(pack.aliases)

        # ② 类目
        save_categories(pack.categories, paths.categories)
        report.categories = len(pack.categories)

        # ③ 剪枝：维持 T5 的不变量「表里不许有 `old_kind ∈ 现存 slug` 的行」。
        # ⚠️ **不能只在"包里有别名"时才剪**：导入会把**某个 slug 带回来**
        # （本机把 `life` 改名成 `life_v2` 之后，导入一份含 `life` 的包）——
        # 那一刻表里那条 `life→life_v2` 就变成"顶着现存 slug"的毒行，
        # `store._EFFECTIVE_KIND` 里无条件的 `ka2` 会把用户手工选的合法类目顶掉
        # （`prune_kind_aliases` 的 docstring 里有实测反例）。
        overrides.ensure_schema()
        ov = overrides.connect()
        try:
            overrides.prune_kind_aliases(
                ov, live_slugs=[c.slug for c in pack.categories]
            )
        finally:
            ov.close()

    # ④ 人物
    save_persons(pack.persons, paths.persons)
    report.persons = len(pack.persons)

    # ⑤ 群（+ settings）
    if pack.config is not None and not keep_settings:
        save_config(pack.config, paths.groups)
        report.groups = len(pack.config.groups)
    elif pack.config is not None:
        # ⚠️ `keep_settings` 只保留 **[settings] 段**，群清单仍然来自包。
        # 「保留本机路径」被理解成「整个 groups.toml 都不动」是一个很自然的误读，
        # 而那样导入一份包就什么都不发生了——用户会以为导入坏了。
        #
        # ⚠️ 本机那份可能还不存在（第一次导入），那时**没法保留**，
        # 只能整份用包里的——但那又需要包的 qq_db_dir 在本机存在。
        # 所以这一支要么成功、要么由 `validate_config_raw` 响亮报错。
        local = paths.groups
        current = _read_local_config(local)
        if current is not None:
            merged = Config(
                qq_db_dir=current.qq_db_dir,
                output_db=current.output_db,
                groups=pack.config.groups,
            )
            save_config(merged, local)
            report.groups = len(merged.groups)
        if report.groups == 0:
            save_config(pack.config, local)
            report.groups = len(pack.config.groups)
            on_progress(
                "[导入] 本机还没有 groups.toml，无法保留本机路径——"
                "整份用了包里的（包括 qq_db_dir）"
            )

    on_progress(
        f"[导入] 群 {report.groups} / 类目 {report.categories} / "
        f"人物 {report.persons} / 改名 {report.aliases}"
        + ("（保留本机 [settings]）" if keep_settings else "")
    )
    return report
