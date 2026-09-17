"""配置层：persons.toml 的加载、校验与原子写。"""

import pathlib

import pytest

from vigil import config


def _write(tmp_path, text):
    p = tmp_path / "persons.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_persons_missing_file_is_empty(tmp_path):
    """没有这个文件是**合法状态**（一个人都没监视），不是错误。"""
    assert config.load_persons(tmp_path / "nope.toml") == ()


def test_load_persons_roundtrip(tmp_path):
    p = _write(tmp_path, '[[persons]]\nuin = 2874448217\nlabel = "卡王"\n')
    got = config.load_persons(p)
    assert got == (config.Person(uin=2874448217, label="卡王", note=""),)


def test_load_persons_rejects_zero_uin(tmp_path):
    """⚠️ uin=0 是匿名哨兵（实测真库 98 行），必须拒绝——否则"监视匿名者"是个无意义操作。"""
    p = _write(tmp_path, '[[persons]]\nuin = 0\nlabel = "匿名"\n')
    with pytest.raises(config.ConfigError, match="匿名"):
        config.load_persons(p)


def test_load_persons_rejects_duplicate_uin(tmp_path):
    p = _write(
        tmp_path,
        '[[persons]]\nuin = 1\nlabel = "甲"\n\n[[persons]]\nuin = 1\nlabel = "乙"\n',
    )
    with pytest.raises(config.ConfigError, match="重复"):
        config.load_persons(p)


def test_load_persons_rejects_empty_label(tmp_path):
    p = _write(tmp_path, '[[persons]]\nuin = 1\nlabel = ""\n')
    with pytest.raises(config.ConfigError, match="label"):
        config.load_persons(p)


def test_save_persons_is_roundtrippable(tmp_path):
    p = tmp_path / "persons.toml"
    people = (config.Person(uin=111, label="甲", note="备注"),)
    config.save_persons(people, p)
    assert config.load_persons(p) == people


def test_save_persons_replaces_not_appends(tmp_path):
    """⚠️ 保存是**整体替换**——追加语义会让"删掉一个人"永远做不到。"""
    p = tmp_path / "persons.toml"
    config.save_persons((config.Person(uin=1, label="甲"),), p)
    config.save_persons((config.Person(uin=2, label="乙"),), p)
    assert config.load_persons(p) == (config.Person(uin=2, label="乙"),)


def test_atomic_write_leaves_no_temp_file(tmp_path):
    p = tmp_path / "x.txt"
    config.atomic_write_text(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"
    assert [f.name for f in tmp_path.iterdir()] == ["x.txt"]


def test_atomic_write_failure_leaves_original_intact(tmp_path, monkeypatch):
    """⚠️ 写失败时**原文件必须一个字都没变**——这是原子写的全部意义。"""
    p = tmp_path / "x.txt"
    config.atomic_write_text(p, "原始内容")

    import os as _os

    def boom(*a, **k):
        raise OSError("模拟磁盘满")

    monkeypatch.setattr(_os, "replace", boom)
    with pytest.raises(OSError):
        config.atomic_write_text(p, "新内容")
    assert p.read_text(encoding="utf-8") == "原始内容"


def test_atomic_write_flushes_before_fsync(tmp_path, monkeypatch):
    """⚠️ fsync **不是**「原理上不可观测」——在 `os.fsync` 回调里读同目录的临时文件即可。

    两条变异实测（都是删一行，见 task-7-report.md「Fix loop 第 1 轮」）：
    - 删掉 `os.fsync` ⇒ 回调一次都不触发 ⇒ 本用例红（持久性保证整个消失）；
    - 删掉 `f.flush()` ⇒ fsync 落在**空文件**上 ⇒ 本用例红
      （这是**真 bug** 不是仪式：崩电窗口里重开出来的是一份空配置）。

    ⚠️ 断言的是「fsync 那一刻正文已经在文件里」，不是「某行代码存在」——
    顺序反了（先 fsync 再 flush）同样红。
    """
    import os as _os

    at_fsync = []
    real_fsync = _os.fsync

    def spy(fd):
        at_fsync.append(
            [(t.name, t.read_text(encoding="utf-8")) for t in sorted(tmp_path.glob("*.tmp"))]
        )
        real_fsync(fd)

    monkeypatch.setattr(_os, "fsync", spy)
    p = tmp_path / "fsynced.txt"
    config.atomic_write_text(p, "正文")

    bodies = [[body for _, body in snapshot] for snapshot in at_fsync]
    assert bodies == [["正文"]], (
        f"fsync 必须恰好调用一次、且那一刻正文已经在同目录临时文件里"
        f"（fsync 被删/flush 被删/顺序反了都会红）；实测={at_fsync!r}"
    )
    assert p.read_text(encoding="utf-8") == "正文"


def test_atomic_write_replaces_within_same_directory(tmp_path, monkeypatch):
    """⚠️ `os.replace` **不跨卷**（实测 C:→D: 报 `WinError 17`）⇒ 临时文件必须与目标同目录。

    ⚠️ 只测行为是**盲的**：本机 pytest 的 `tmp_path` 与系统 temp **同卷**，把临时文件
    放到系统 temp 也照样能替换成功。所以本用例直接断言 `os.replace` 的实参
    `src.parent == dst.parent` —— 换写法后**本机即红**。
    """
    import os as _os

    calls = []
    real_replace = _os.replace

    def spy(src, dst, *a, **k):
        calls.append((pathlib.Path(src), pathlib.Path(dst)))
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(_os, "replace", spy)
    p = tmp_path / "same_dir.txt"
    config.atomic_write_text(p, "x")

    assert len(calls) == 1, f"os.replace 应当恰好调用一次；实测={calls!r}"
    src, dst = calls[0]
    assert dst == p
    assert src.parent == dst.parent, f"临时文件必须与目标同目录（不跨卷）：src={src}"


def test_atomic_write_cleans_temp_on_failure(tmp_path, monkeypatch):
    """⚠️ 失败路径必须清掉临时文件——`config/` 是要进 git 的目录，`.tmp` 垃圾会一直躺着。"""
    import os as _os

    def boom(*a, **k):
        raise OSError("模拟磁盘满")

    monkeypatch.setattr(_os, "replace", boom)
    p = tmp_path / "boom.txt"
    with pytest.raises(OSError):
        config.atomic_write_text(p, "新内容")

    assert [f.name for f in tmp_path.iterdir()] == [], "失败路径留下了临时文件"


def test_toml_str_is_total(tmp_path):
    """⚠️ `toml_str` 必须是**全函数**：任何字符串进去，`save` 的产物都 `load` 得回来。

    实测坏字符集（原样落进引号里会让 tomllib 解析失败）：
    **U+0000–U+0008、U+000A–U+001F（`\\t` 除外）、U+007F**。
    `\\t` / `]` / `#` / `=` / `\"\"\"` / U+2028 / C1 / NBSP / BOM 实测 round-trip 一致，不在此列。
    """
    bad = "".join(chr(c) for c in range(0x00, 0x20)) + "\x7f"
    people = (config.Person(uin=1, label="甲" + bad + "乙", note="备" + bad),)
    p = tmp_path / "persons.toml"
    config.save_persons(people, p)
    assert config.load_persons(p) == people


# --- M5 终审修复轮：拼错的段落不许静默吞掉（Minor-4）----------------


def test_load_persons_rejects_a_misspelled_section_name(tmp_path):
    """⭐ M5 终审 Minor-4：`[[person]]`（少个 s）**必须响亮**，不许静默读成空名单。

    实测的伤害链：`raw.get("persons", [])` 键名拼错时返回 `()`；而
    `save_persons` 是**整体覆盖**写（「删掉一个人」只能这么做）⇒
    下一次在界面上「加一个人」时 load → append → save，
    **手工加的人无声消失**，全程零报错。

    而文件头**自己邀请手工编辑**（「或手工往下面追加一段 `[[persons]]`」），
    也就是说这条路径一定会被走到——与「越早暴露越好」的模块立场相反。

    变异「把 `load_persons` 里的 `_check_persons_shape(...)` 那行去掉」⇒ 本条红。
    """
    p = _write(tmp_path, '[[person]]\nuin = 2874448217\nlabel = "辅导员"\n')
    with pytest.raises(config.ConfigError, match="persons"):
        config.load_persons(p)
    # 反向：改正之后就正常（不许把整类文件都拒掉）
    p.write_text('[[persons]]\nuin = 2874448217\nlabel = "辅导员"\n', encoding="utf-8")
    assert config.load_persons(p) == (
        config.Person(uin=2874448217, label="辅导员", note=""),
    )


def test_load_persons_rejects_a_wrong_bracket_shape(tmp_path):
    """`[persons]`（一层方括号）也要响亮：那是一张**表**，不是一串人。

    不拦的话 `for entry in raw["persons"]` 会去迭代字典的**键**（字符串），
    后面 `entry.get("uin")` 以一个看不懂的 `AttributeError` 收场——
    而"看不懂的异常"正是"这个文件写错了"最不该有的表现。
    """
    p = _write(tmp_path, '[persons]\nuin = 2874448217\nlabel = "辅导员"\n')
    with pytest.raises(config.ConfigError, match="数组表"):
        config.load_persons(p)


def test_load_persons_empty_file_is_still_legal(tmp_path):
    """阳性对照：**空文件**是合法的（一个人都没监视），不许被上面两条顺带拒掉。"""
    assert config.load_persons(_write(tmp_path, "")) == ()
    assert config.load_persons(_write(tmp_path, "# 只有注释\n")) == ()


# ── M6 T2：写侧序列化层 ──────────────────────────────────────────────


def test_save_config_roundtrips(tmp_path):
    """`save_config` 的产物必须被 `load_config` 原样读回来。

    ⚠️ 这条钉的是「**全函数**」那一半：任何 `Config` 进去，产物都读得回来。
    但它**钉不住段序**——见下一条。
    """
    p = tmp_path / "groups.toml"
    cfg = config.Config(
        qq_db_dir=tmp_path / "qqdb",
        output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(
            config.Group(id=111, name="甲群", enabled=True, tier="high"),
            config.Group(id=222, name="乙群", enabled=False),
        ),
    )
    (tmp_path / "qqdb").mkdir()
    config.save_config(cfg, p)
    back = config.load_config(p)
    assert back.groups == cfg.groups
    assert back.output_db == cfg.output_db


def test_save_config_writes_settings_before_groups(tmp_path):
    """⭐ `[settings]` 必须在 `[[groups]]` **之前**（布局约定，见下）。

    ⚠️ 实测修正（M6 T2）：原稿给的理由是「`[table]` 出现在
    `[[array_of_tables]]` 之后会被解析成最后一个数组元素下的子表
    （`groups[-1].settings`）⇒ `raw.get("settings")` 变成 `None` ⇒
    下一次 `load_config` 报「缺少 [settings] 段」，整个程序起不来」。
    这条**实测不成立**：tomllib 里 `[settings]` 是**根相对**路径，写在
    `[[groups]]` 之后**仍落在顶层**（`raw.get("settings")` 拿到的正是那张表）；
    只有 `[groups.settings]` 这种**穿过数组**的写法才嵌套。
    所以段序**不是**靠 load 报错兜住的——就靠下面这条断言钉着。

    ⚠️ 变异反证：把 `save_config` 里的 `lines = [HEADER, "", "[settings]"]`
    挪到 `for g in config.groups` 之后 ⇒ 本条**必红**（实测 `assert 28 < 0`：
    红的原因就是行锚定断言，**不是** `load_config` 抛 `ConfigError`）。

    ⚠️ 实施修正（M6 T2）：原稿用的是 `text.index("[[groups]]")`，而
    `_GROUPS_HEADER` 的**正文里**有一句「按下面格式加一段 `[[groups]]`」
    ⇒ 子串搜索命中的是**注释里那个**（实测 643 vs 168），段序完全正确也红。
    改成**行锚定**比较，钉的仍是段头本身的先后。
    """
    p = tmp_path / "groups.toml"
    (tmp_path / "qqdb").mkdir()
    cfg = config.Config(
        qq_db_dir=tmp_path / "qqdb",
        output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(config.Group(id=111, name="甲群"),),
    )
    config.save_config(cfg, p)
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines.index("[settings]") < lines.index("[[groups]]")
    # 再机械确认一次：解析出来的顶层键就是那两个
    import tomllib
    assert set(tomllib.loads(text)) == {"settings", "groups"}


def test_save_config_refuses_zero_groups(tmp_path):
    """⚠️ 拒绝写出零个群。

    不是洁癖：`load_config` 把「一个群都没配」当成配置错误（`[[]] 段为空`），
    所以写出一份零群的配置 = **把程序改成起不来**——而且下一次启动才现形，
    那时用户已经在网页上点过保存、拿到了「成功」。

    ⚠️ 这同时**否掉了一个看起来更自然的设计**：「删掉最后一个群」。
    要退掉最后一个群，正确动作是 `enabled = false`（保留配置、保留历史）。
    """
    p = tmp_path / "groups.toml"
    (tmp_path / "qqdb").mkdir()
    cfg = config.Config(
        qq_db_dir=tmp_path / "qqdb", output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(),
    )
    with pytest.raises(config.ConfigError, match="零个群"):
        config.save_config(cfg, p)
    assert not p.exists(), "拒绝之后不许留下文件"


def test_save_config_keeps_repo_relative_paths_relative(tmp_path):
    """仓库内的路径写**相对**、仓库外的写**绝对**（`_toml_path` 的契约）。

    两个方向各有一个具体的坏法：
      · 全写绝对 ⇒ 配置搬到别的目录时仍指回原仓库（T8 的导入导出就废了）；
      · 全写相对 ⇒ `C:/Users/...` 的 QQ 库路径会被 `load_config` 拼成
        `REPO_ROOT / "C:/Users/..."`，一个不存在的路径。

    ⚠️ 实施修正（M6 T2）：原稿写的是 `qq_db_dir=pathlib.Path("C:/somewhere/nt_db")`
    ——一个**不存在**的路径，而 `save_config` 落盘前要把最终文本喂给
    `validate_config_raw`，那里有「QQ 数据库目录不存在」这条检查
    ⇒ 原稿在本平台**必红**（实测 `ConfigError: QQ 数据库目录不存在: C:\\somewhere\\nt_db`）。
    换成一个真实存在、且仍在 `REPO_ROOT` **之外**的绝对路径（本平台的 pytest
    `tmp_path` 就是 `C:/Users/...`，与 docstring 里那个坏法同形）：契约不变。
    """
    p = tmp_path / "groups.toml"
    outside = tmp_path / "nt_db"
    outside.mkdir()
    cfg = config.Config(
        qq_db_dir=outside,
        output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(config.Group(id=111, name="甲群"),),
    )
    config.save_config(cfg, p)
    text = p.read_text(encoding="utf-8")
    assert 'output_db = "data/vigil.db"' in text
    assert f'qq_db_dir = "{outside.as_posix()}"' in text


def test_save_persons_rejects_a_non_int_uin(tmp_path):
    """⭐ M5 遗留 #19 + #22：`uin` 必须是**真正的整数**，且**拒绝 bool**。

    ⚠️ 旧实现是裸 f-string `f"uin = {p.uin}"`，两个坏法：
      · `uin="1\\n[[persons]]\\nlabel=\\"注入\\""` ⇒ 写出**第二个段头**，
        整份文件结构被改写（已复现）；
      · `uin=True` ⇒ 写出 `uin = true`，读回来是 `uin = 1`（`bool` ⊂ `int`）。

    ⚠️ `Person` 是 frozen dataclass，**不强制类型** ⇒ 产品路径今天够不到它。
    但 T8 的批量导入会让它够到，所以必须在此之前收掉（终审原话）。

    ⚠️ 变异反证：把 `save_persons` 里那行换回 `f"uin = {p.uin}"`
    ⇒ 本条**必红**。
    """
    for bad in ("1\n[[persons]]\nlabel=\"注入\"", True, 1.5, "100000001"):
        with pytest.raises(config.ConfigError, match="uin"):
            config.save_persons(
                [config.Person(uin=bad, label="甲")], tmp_path / "persons.toml"  # type: ignore[arg-type]
            )
    assert not (tmp_path / "persons.toml").exists()


def test_saved_persons_never_contain_a_uid_key(tmp_path):
    """M5 遗留 #20：`uid` **不落配置**——`config/*.toml` 里不许出现它。

    ⚠️ 为什么要有这条：`Person` 的键是 `uin`，`uid` 只在**查询时**由
    `sender_names` 反查（spec §3.1：uid 与 uin 会脱节，落盘就等于把一份
    会过期的映射冻进配置）。今天靠「代码里没写 uid」保证，而
    **没有任何测试挡着后来者顺手加一列**。
    """
    p = tmp_path / "persons.toml"
    config.save_persons([config.Person(uin=100000001, label="甲")], p)
    assert "uid" not in p.read_text(encoding="utf-8")


def test_load_config_wraps_a_toml_syntax_error(tmp_path):
    """⚠️ 本任务修掉的既有缺陷：语法错误必须包成 `ConfigError`。

    不包的话 `tomllib.TOMLDecodeError`（继承自 **ValueError**，不是
    RuntimeError）会**绕过 `cli._load_config_only` 的 `except ConfigError`**，
    用户看到的是**裸 traceback** 而不是一行可读的配置错误。
    `load_categories` 早就这么做了（`categories.py:51-55` 有完整论证），
    `load_config` 没有——M6 之后 Web 会写这份文件，撞上的概率从
    「人手打错字」升到「一次序列化缺陷」。

    ⚠️ 变异反证：去掉 `load_config` 里那个 `try/except tomllib.TOMLDecodeError`
    ⇒ 本条**必红**（抛的是 TOMLDecodeError）。
    """
    p = tmp_path / "groups.toml"
    p.write_text("[settings\nqq_db_dir = 1\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="TOML"):
        config.load_config(p)


def test_toml_str_is_reachable_under_its_public_name():
    """`_toml_str` → `toml_str` 的改名必须真的发生（`categories.py` 要 import 它）。

    ⚠️ 这条看着像废话，但它挡的是一个具体的形状：改名改了一半——
    留个 `_toml_str = toml_str` 的兼容别名。别名会让两处引用**看起来都在用
    `toml_str`**，而实际上 `save_persons` 走的是别名那条路，于是
    「谁在调用它」这个问题永远数不清（本项目反复吃「看起来有、其实没人看」
    那个形状的亏，见 `daily.RunReport.counters` 的墓碑）。
    """
    assert hasattr(config, "toml_str")
    assert not hasattr(config, "_toml_str"), "别留兼容别名"
