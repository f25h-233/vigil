"""`strip_fake_header` 的原子性 —— M6 T1（U-4）。

⚠️ 本文件**不需要**真实 QQ 加密库：`strip_fake_header` 只做字节搬运，
不解析、不解密。造一个「带假头的文件」就能完整覆盖它。

⚠️ 也不能用 sqlcipher：那是 `open_encrypted` 的事，本文件不碰它。
"""

from __future__ import annotations

import os
import pathlib
import threading

import pytest

from vigil import qqdb


def _make_fake_header_src(path: pathlib.Path, body: bytes) -> pathlib.Path:
    """造一个「带 1024 字节假头」的源库。"""
    path.write_bytes(qqdb._FAKE_HEADER_MAGIC + b"\x00" * (
        qqdb.FAKE_HEADER_SIZE - len(qqdb._FAKE_HEADER_MAGIC)
    ) + body)
    return path


def test_strips_the_fake_header(tmp_path):
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"BODY" * 100)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst.read_bytes() == b"BODY" * 100


def test_plain_sqlite_is_copied_verbatim(tmp_path):
    """源文件已是明文 SQLite 结构 ⇒ 不偏移、原样复制。"""
    body = b"SQLite format 3\x00" + b"X" * 500
    src = tmp_path / "plain.db"
    src.write_bytes(body)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst.read_bytes() == body


def test_cache_hit_does_not_rewrite(tmp_path):
    """大小对且不比源旧 ⇒ 直接返回，**不重写**（identity 不变）。"""
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"BODY" * 100)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    before = dst.stat().st_ino
    dst2 = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst2 == dst
    assert dst.stat().st_ino == before, "缓存命中路径不该重写文件"


def test_rewrite_replaces_the_file_rather_than_truncating_it(tmp_path):
    """⭐ 本任务的核心断言（U-4 的机械判据）。

    **原子替换 ⇒ 文件身份变了**（新 inode 顶替旧的）。
    **截断重写 ⇒ 文件身份不变**（还是同一个文件，只是内容被从 0 字节重写）。

    所以 `st_ino` 的变化是原子性的**必要条件**，且它**确定、无计时依赖**——
    比「起两个线程赛跑」可靠得多（那种测试会 flaky，而 flaky 的守卫最终
    会被注释掉）。

    ⚠️ 变异反证：把 `os.replace(tmp, dst)` 换回
    `with open(dst, "wb") as out: ...` ⇒ 本条**必红**。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"OLD" * 200)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    # ⚠️ 先响亮地确认度量工具本身可用：FAT 之类的文件系统上 `st_ino` 恒为 0，
    # 那种环境下本条会**恒真**（0 != 0 不成立 ⇒ 其实恒红，但红的原因与 U-4 无关）。
    # 与其留一个「在别的机器上意义不明」的守卫，不如让它在测量工具不可用时
    # **明说**。NTFS 上 `st_ino` 是有效的（CPython 走 GetFileInformationByHandle）。
    assert dst.stat().st_ino != 0, "本机的 st_ino 不可用，本条判据失效——请改用别的度量"
    old_ino = dst.stat().st_ino

    # 让源变新 ⇒ 必然走重写分支（缓存判据是 size + mtime）
    _make_fake_header_src(tmp_path / "nt_msg.db", b"NEW" * 200)
    os.utime(src, (src.stat().st_atime + 10, src.stat().st_mtime + 10))

    qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst.read_bytes() == b"NEW" * 200
    assert dst.stat().st_ino != old_ino, (
        "重写必须走 os.replace（新文件顶替），不能就地截断重写——"
        "后者会让并发读者看到半个文件，而 SQLite 把它报成「坏页」"
    )


def test_a_reader_never_sees_a_partial_file(tmp_path, monkeypatch):
    """并发读者看到的内容，**要么全旧、要么全新**（没有第三种状态）。

    ⚠️ 这条与上一条是**两个不同的判据**：上一条看「文件身份换没换」，
    这一条看「读者实际看到了什么」。前者是机制，后者是后果——
    只钉机制的话，将来有人把 `os.replace` 换成「先删后建」仍会绿，
    而那同样会给读者一个「文件不存在」的窗口。

    做法：把 `shutil.copyfileobj` 换成一个**边拷边读**的版本，
    在拷贝**中途**去读 dst——此刻 dst 必须是**完整的旧内容**。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"OLD" * 200)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    _make_fake_header_src(tmp_path / "nt_msg.db", b"NEW" * 200)
    os.utime(src, (src.stat().st_atime + 10, src.stat().st_mtime + 10))

    seen: list[bytes] = []
    real_copyfileobj = qqdb.shutil.copyfileobj

    def spy(fsrc, fdst, length=0):
        real_copyfileobj(fsrc, fdst, length)
        # 拷完了才读一次 —— 此刻目标还没被 replace，读者应该看到**完整的旧内容**
        seen.append(dst.read_bytes())

    # ⚠️ **绝不要在这里写 `monkeypatch.undo()`**（M5 终审实测的坑）：pytest 的
    # `monkeypatch` 是**函数级单例**，`conftest.py` 那两个 autouse 隔离夹具用的是
    # **同一个实例** —— 一次 `undo()` 会把它们一起拆掉，于是本用例之后的代码
    # 会往**真实的** `data/overrides.db` 写字，而**没有任何断言变红**。
    # 补丁在测试结束时由 pytest 自动还原，本来就不需要手动 undo。
    monkeypatch.setattr(qqdb.shutil, "copyfileobj", spy)
    qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    assert seen == [b"OLD" * 200], (
        f"重写中途读到的必须是完整的旧文件，实际读到 {len(seen[0]) if seen else 0} 字节"
    )
    assert dst.read_bytes() == b"NEW" * 200


def test_failure_leaves_the_original_intact_and_no_temp_file(tmp_path, monkeypatch):
    """中途失败 ⇒ 原文件原样、且**不留临时文件**。

    ⚠️ 不留临时文件是承重的：`data/cache/` 会被 `strip_fake_header` 反复扫到，
    残留的 `.tmp<pid>` 会被后来的 cache 判据当成无关文件，越积越多。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"OLD" * 200)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    _make_fake_header_src(tmp_path / "nt_msg.db", b"NEW" * 200)
    os.utime(src, (src.stat().st_atime + 10, src.stat().st_mtime + 10))

    def boom(*a, **kw):
        raise OSError("磁盘满了")

    # ⚠️ 同样**不要** `monkeypatch.undo()`（理由见上一条用例）。
    monkeypatch.setattr(qqdb.shutil, "copyfileobj", boom)
    with pytest.raises(OSError):
        qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    assert dst.read_bytes() == b"OLD" * 200, "失败不该动到已存在的目标文件"
    leftovers = [p.name for p in dst.parent.iterdir() if ".tmp" in p.name]
    assert leftovers == [], f"失败路径必须清掉临时文件，残留：{leftovers}"


def test_temp_file_name_is_unique_per_process(tmp_path, monkeypatch):
    """临时文件名必须**带 pid**：两个进程同时剥同一个 dst 时用同一个临时名会互踩。

    ⚠️ 这条不是"防御性编程"：`vigil groups` 与 `vigil export` 确实会并发
    （前者是人工命令、后者由任务计划在 08:00 触发），而 T1 的锁只挡住
    **同一个 dst 的两次 strip 同时发生**——它挡不住「两个进程在**同一时刻**
    各自往 `dst.tmp` 里写」这个形状，因为锁是在 `cmd_groups` 里加的，
    而 `strip_fake_header` 是公共函数，将来可能被别处调用。

    ⚠️ 且不管有没有锁：**用同一个临时名是错的**，修法不该依赖调用方的纪律。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"BODY" * 100)
    dst = tmp_path / "cache" / "clear.db"

    names: list[str] = []
    real_replace = qqdb.os.replace

    def spy_replace(a, b):
        names.append(pathlib.Path(a).name)
        return real_replace(a, b)

    # ⚠️ 同样**不要** `monkeypatch.undo()`（理由见上文）。
    monkeypatch.setattr(qqdb.os, "replace", spy_replace)
    qqdb.strip_fake_header(src, dst)

    assert len(names) == 1
    assert str(os.getpid()) in names[0], (
        f"临时文件名 {names[0]!r} 里没有 pid——固定名 `dst.tmp` 在并发下会互踩"
    )
