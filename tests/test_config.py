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
    """⚠️ `_toml_str` 必须是**全函数**：任何字符串进去，`save` 的产物都 `load` 得回来。

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
