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

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        # ⚠️ 必须包成 ConfigError（M6 T2 修）。`TOMLDecodeError` 继承自
        # **ValueError** 而不是 RuntimeError，不包的话会绕过
        # `cli._load_config_only` 的 `except ConfigError`，用户看到的是
        # **裸 traceback** 而不是一行可读的配置错误。
        # ⚠️ `load_categories` 从 M5 起就是这么做的（那里有完整论证），
        # 而本函数一直没跟上——今天 `groups.toml` 只由人手编辑、撞上的概率低，
        # **M6 之后 Web 会写它** ⇒ 一次序列化缺陷就会以 traceback 收场。
        raise ConfigError(f"{path}: TOML 语法错误——{exc}") from exc

    return validate_config_raw(raw, path)


def validate_config_raw(raw: dict, path: pathlib.Path) -> Config:
    """把**已解析**的 TOML 校验成 `Config`。

    ⚠️ **读路径与写路径共用这一个函数**（M6 T2）。写路径若另写一套校验，
    两份会漂移——而漂移的后果在这里尤其重：`save_config` 能写出
    `load_config` 拒绝的文件 ⇒ 一份配置永久落盘（原子写、无回滚）
    ⇒ **整个程序起不来**（`config.py` 是所有入口的硬依赖）。

    ⚠️ 它**不是**段序的兜底（⚠️ 实测修正 M6 T2）：tomllib 下 `[settings]`
    写在 `[[groups]]` 之后仍落在顶层，本函数看不出顺序。它抓得住的是
    **结果**——「顶层根本没有 `settings`」（`raw.get("settings")` 得到 `None`
    ⇒ 报「缺少 [settings] 段」）。写路径因此在落盘前仍能挡住
    「上游把 settings 整个弄没了」那类缺陷。
    """
    # ↓↓↓ 以下为原 `load_config` 从 `settings = raw.get("settings")`
    #     到 `return Config(...)` 的**逐字搬移**，一行不改 ↓↓↓
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


# ── 写侧序列化（M6 T2）──────────────────────────────────────────────
#
# ⚠️ Python 标准库**只有 `tomllib`（读）**，没有写入器。本仓库的依赖表只有
# sqlcipher3，不为写 TOML 引第三方库。所以写侧是手写的，而手写序列化
# **唯一的正确性判据是「全函数」**：
#
#     任何合法的值进去，产出的文本都要能被 `tomllib` 读回**同一个值**。
#
# ⚠️ 光有「全函数」还不够：它只覆盖**值**，不覆盖**段序**（`[settings]` 掉到
# `[[groups]]` 后面）与**键名**。**键名**那半由各自的 `save_*` 用「先解析、再
# 喂给读路径的同一个校验函数」挡住（见 `save_config` / `save_categories`）；
# **段序**那半**挡不住**（⚠️ 实测修正 M6 T2：tomllib 下两种顺序解析出的顶层表
# 一模一样，见 `save_config` 的 docstring），只能靠代码里的书写顺序
# 与 `tests/test_config.py` 里那条行锚定断言钉着。


def toml_str(value: str) -> str:
    """TOML 基本字符串——**全函数**：任何字符串进去，`save` 的产物都 `load` 得回来。

    ⚠️ 只转义反斜杠与双引号是**不够**的：一个带换行的 label 会写出**解析不了**的 toml，
    而原子写会让它**永久落盘**——`save` 成功返回、`load` 从此抛 `TOMLDecodeError`，
    整份文件连读都读不出来（M5 T7 实测，见 task-7-report.md）。

    ⚠️ 这里只是**转义**那一半；「名字里不许有换行」的**拒绝**在 API 层——
    `config/*.toml` 是人手输的，把一个换行静默存进"名字"里、再在界面上错乱显示，
    比直接报错更不诚实。

    ⚠️ 原名为 `_toml_str`，M6 T2 去掉下划线：`categories.py` 的写侧要用它，
    而跨模块 import 一个下划线名字是在制造「这是私有的、但谁都在用」的假象。
    """
    out: list[str] = []
    for ch in value:
        esc = TOML_ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ch < " " or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def toml_int(value: object, field: str) -> int:
    """把值当整数写出——**拒绝 bool，也拒绝「能转成整数的字符串」**。

    ⚠️ `bool` 是 `int` 的子类（`True == 1`），所以裸的 `isinstance(x, int)`
    会放行 `True` ⇒ 写出 `uin = true`，读回来是 `uin = 1`（M5 遗留 #22，已复现）。

    ⚠️ 也不接受 `"100000001"` 这类字符串：给「静默转一下」留口子，就等于把
    `api._edit_id_of` 那个 `int("abc")` → 500、`1.9` → 静默截断成 1 的缺陷
    换个形状请回来（那里已有完整论证）。**契约是「整数」而不是「能转成整数的东西」。**

    ⚠️ 它同时是 M5 遗留 #19 的落点：旧代码是裸 f-string `f"uin = {p.uin}"`，
    一个非 int 的值可以**注入 TOML**（已复现：写出第二个 `[[persons]]` 段头，
    并让整份文件 `TOMLDecodeError` 报废）。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"{field} 必须是整数（**拒绝 bool**：True 是 int 的子类，会静默变成 1；"
            f"也拒绝字符串：静默转换会把「1.9 截断」那类缺陷请回来），"
            f"实际是 {value!r}（{type(value).__name__}）"
        )
    return value


def _toml_path(value: pathlib.Path) -> str:
    """把路径写成 TOML 字符串：**能在仓库内相对表达就相对**，否则写绝对。

    ⚠️ 不统一成绝对、也不统一成相对——两个方向各有一个具体的坏法：

      · **全写绝对** ⇒ 配置文件搬到别的目录时仍指回原仓库。T8 的「配置包
        在另一个目录导入并生效」会因此**静默指向旧库**（判据 4 直接失败）。
      · **全写相对** ⇒ `REPO_ROOT` 之外的路径（QQ 库在 `C:/Users/...`）
        根本没法相对表达；而**相对路径的解析基准是 cwd、不是 `REPO_ROOT`**
        （⚠️ 实测修正 M6 T2：`validate_config_raw` 只对 `output_db` 做
        `REPO_ROOT / ...`，`qq_db_dir` 是裸 `Path(...)`。实测：
        `qq_db_dir = "qqdb"` 在 cwd=那个目录时读得通，cwd=仓库根时抛
        「QQ 数据库目录不存在: qqdb」）。⇒ 全写相对等于把「从哪个目录启动」
        冻进配置，换个 cwd 就报一句**指向根本没错的路径**的错误。
    """
    try:
        return toml_str(value.relative_to(REPO_ROOT).as_posix())
    except ValueError:
        return toml_str(value.as_posix())


def _check_persons_shape(path: pathlib.Path, raw: dict) -> None:
    """名单文件的**形状**不对就响亮报错（M5 终审 Minor-4 实测）。

    ⚠️ 原实现是 `raw.get("persons", [])`：键名拼错时**静默返回空名单**。
    而 `save_persons` 是**整体覆盖**写（「整体替换不是追加」是它刻意的语义，
    否则删不掉人）⇒ 一次手误的后果是：

        写 `[[person]]`（少个 s） → load 得到 () → 界面上「加一个人」时
        load → append → save ⇒ **原有名单被整体覆盖掉，全程零报错**。

    而 `config/persons.toml` 的文件头**自己邀请手工编辑**（「或手工往下面追加
    一段 `[[persons]]`」），也就是说这条路径一定会被走到。

    ⚠️ 与本模块的立场一致：「配置写错是我们自己的问题，**越早暴露越好**。
    不猜、不兜底」。所以这里不"宽容地多认几个键名"，直接抛 `ConfigError`——
    并且把最常见的那个形状（`[[person]]`）在消息里点名。
    """
    unknown = sorted(k for k in raw if k != "persons")
    if unknown:
        raise ConfigError(
            f"{path}: 只认 `[[persons]]` 段，却发现了这些顶层键：{unknown}。"
            "最常见的形状是 `[[person]]`（少写一个 s）——写错的段落会被**整体忽略**："
            "读出来是一份空名单，而下一次保存是**整体覆盖**写，"
            "手工加的人会无声消失（M5 终审实测）。请改成 `[[persons]]`。"
        )
    section = raw.get("persons", [])
    if not isinstance(section, list):
        raise ConfigError(
            f"{path}: `persons` 必须是**数组表**（`[[persons]]`，两层方括号），"
            f"实际是 {type(section).__name__}——写成 `[persons]` 时读出来的是"
            "一张表而不是一串人，后面的逐条校验会以一个看不懂的异常收场。"
        )


def load_persons(path: pathlib.Path | None = None) -> tuple[Person, ...]:
    """读监视人物名单。

    ⚠️ **文件不存在返回空元组**（与 `load_config` 的快速失败不同）：
    "一个人都没监视"是完全合法的状态，而 `load_config` 面对的是一份**必需**的配置。

    ⚠️ **但文件存在、形状却不对时必须响亮**（`_check_persons_shape`）：键名拼错
    （`[[person]]`）在旧实现里静默读成空名单，而 `save_persons` 是整体覆盖写
    ⇒ 一次手误会让手工加的人无声消失。

    ⚠️ `uin = 0` 是匿名哨兵（实测真库 98 行），**必须拒绝**——
    匿名者没有身份，把它加进监视名单是个不会生效的操作，越早暴露越好。
    """
    target = path or DEFAULT_PERSONS
    if not target.is_file():
        return ()

    with open(target, "rb") as f:
        raw = tomllib.load(f)

    _check_persons_shape(target, raw)

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


_GROUPS_HEADER = """\
# VIGIL 监听群配置
#
# ── 怎么加群 ───────────────────────────────────────────────
#   1. 跑 `vigil groups`，它会列出 QQ 本地库里所有群
#      （含群号、群名、消息数，以及「是否已纳入」）
#   2. 把新群的 id 按下面格式加一段 [[groups]]
#   3. 重跑 `vigil export`。**每次都是全量重读所有已纳群**（不做增量记账，
#      实测 4.7 万条几秒），写入用 INSERT OR REPLACE，所以重跑不会产生重复行。
#      新群加进来后第一次 export 就会拉到它的全部历史。
#
# ── 怎么退群 ───────────────────────────────────────────────
#   把 enabled 改成 false（保留配置便于回看），或整段删掉。
#   已导出的历史数据留在库里不动——那是你的记录。
#
# ⚠️ **本文件由程序整体重写**（网页「配置」页保存时会覆盖它）：
#    手工改也行，但**手工加的注释会在下一次网页保存时消失**。
#
# 注意：刚加入的新群，QQ 需要先把它同步到本地库
#      （group_info.db 出现群名、nt_msg.db 开始落消息），
#      之后 `vigil groups` 才看得见。刚加完立刻查可能是空的。
"""


def save_config(config: Config, path: pathlib.Path | None = None) -> None:
    """整体替换写出群配置（原子）。

    ⚠️ 是**整体替换**不是追加：追加语义下「删掉一个群」永远做不到
    （与 `save_persons` 同一条理由）。

    ⚠️ **`[settings]` 必须写在 `[[groups]]` 之前**。⚠️ 实测修正（M6 T2）：
    原稿给的理由是「否则会被解析成最后一个数组元素下的子表
    （`groups[-1].settings`）⇒ `raw.get("settings")` 变成 `None` ⇒ 程序起不来」
    ——**这条实测不成立**：tomllib（TOML 1.0）里 `[settings]` 是**根相对**路径，
    写在 `[[groups]]` 之后**仍落在顶层**（实测 `raw.get("settings")` 拿到的正是
    那张表）；只有 `[groups.settings]` 这种**穿过数组**的写法才会嵌套。
    所以段序**只有这一处在保证**：代码里这个顺序 +
    `tests/test_config.py::test_save_config_writes_settings_before_groups`
    的行锚定断言（把它挪到 `[[groups]]` 之后 ⇒ 那条测试实测变红）。
    末尾那次落盘前自校验能挡住的是「最终文本里顶层根本没有 `settings`」
    （⇒「缺少 [settings] 段」），**挡不住段序本身**——tomllib 认为那是合法的。

    ⚠️ 路径走 `_toml_path`（仓库内相对、仓库外绝对），不要图省事写绝对。
    """
    target = path or DEFAULT_CONFIG

    # ⚠️ 拒绝零个群**不是洁癖**：`validate_config_raw` 把「一个群都没配」
    # 当成配置错误，所以写出一份零群的配置 = **把程序改成起不来**——
    # 而且下一次启动才现形，那时用户已经在网页上点过保存、拿到了「成功」。
    # ⚠️ 这同时**否掉了一个看起来更自然的设计**：网页上「删掉最后一个群」。
    # 正确动作是 `enabled = false`（保留配置、保留历史）。
    if not config.groups:
        raise ConfigError(
            "拒绝写出零个群的配置：读回来会被判成「一个群都没配」的配置错误，"
            "整个程序起不来。要退掉最后一个群，请改成 `enabled = false`"
            "（保留配置、保留已导出的历史）。"
        )

    lines = [
        _GROUPS_HEADER,
        "",
        "[settings]",
        f"qq_db_dir = {_toml_path(config.qq_db_dir)}",
        f"output_db = {_toml_path(config.output_db)}",
        "",
    ]
    for g in config.groups:
        lines.append("[[groups]]")
        lines.append(f"id = {toml_int(g.id, '群号')}")
        lines.append(f"name = {toml_str(g.name)}")
        lines.append(f"enabled = {'true' if g.enabled else 'false'}")
        lines.append(f"tier = {toml_str(g.tier)}")
        lines.append("")

    text = "\n".join(lines)

    # ⚠️ **顺序是承重的：先自己解析+校验，再落盘**。反过来的话，一份不合法的
    # 配置已经落盘了才发现不对——而 `atomic_write_text` 是原子写，
    # **没有任何自动回滚**，那份坏配置会一直躺在那里直到有人手动修。
    # ⚠️ 校验的是**最终文本**（而不是内存里的 `Config`）：只有这样才能抓到
    # 序列化本身的缺陷（漏转义的引号、写反的段序），而不只是数据的问题。
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"内部错误：为 {target} 生成的 TOML 解析不了——{exc}") from exc
    validate_config_raw(raw, target)

    atomic_write_text(target, text)


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
        # ⚠️ 走 `toml_int` 而不是裸 f-string（M5 遗留 #19/#22）：
        # 裸 f-string 让一个非 int 的值**可注入 TOML**（已复现：能写出第二个
        # `[[persons]]` 段头，并让整份文件 `TOMLDecodeError` 报废），
        # 而 `uin = true` 会被接受（bool ⊂ int）⇒ 建出一个 uin=1 的人。
        # `Person` 是 frozen dataclass 但**不强制类型**，所以产品路径今天
        # 够不到它——T8 的批量导入会让它够到，故必须在此之前收掉。
        lines.append(f"uin = {toml_int(p.uin, 'uin')}")
        lines.append(f"label = {toml_str(p.label)}")
        if p.note:
            lines.append(f"note = {toml_str(p.note)}")
        lines.append("")
    atomic_write_text(target, "\n".join(lines))


# TOML 基本字符串里**必须转义**的字符。实测坏字符集是
# **U+0000–U+0008、U+000A–U+001F（`\t` 除外）、U+007F**——原样落进引号里会让 tomllib 解析失败；
# 而 `]` / `#` / `=` / `"""` / U+2028 / C1 / NBSP / BOM 都实测 round-trip 一致，**不必动**
# （别凭直觉扩大转义集：多转义不会更安全，只会改变正文）。
TOML_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


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
