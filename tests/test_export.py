"""`vigil.export.export()` 的异常契约。

⚠️ 本文件是 M4 scoped fix **新建**的：`vigil/export.py` 此前没有专属测试文件，
既有的 export 判据都在 `tests/test_cli.py` 里——但那些把 `vigil.export.export`
整个换成替身（`monkeypatch.setattr("vigil.export.export", ...)`），够不着函数
内部。本文件只钉 **`export()` 内部的异常形状**，不重复 CLI 那层的账。

为什么值得单独钉：`export()` 里有两个并排的「降级」，长得几乎一样，
但**只有一个是合法的**——

    try:   sender_map = senders.load_senders(...)   ← 增强项，取不到退化成空
    except Exception: sender_map = {}

    try:   cache = media.index_cache(...)          ← 增强项，取不到退化成空
    except Exception: cache = {}

差别在 `on_progress`（= `logs.emit`，计划 §8.5）**站在 try 的哪一边**：
报进度是「本次运行的记录」，它的失败必须冒出去，**不许**被当成
「增强项取不到」吞掉。旧形状把它挤进了 `try` —— 于是 `emit` 抛一次就把
`cache` 换成 `{}`，`stats.media_local` 变 0，汇总行报出
「图片引用：N 张，本地可取 0 张（0%）」这个**假数字**。

不碰真 QQ 库、不连网：源库是造出来的**明文** sqlite，`qqdb.open_encrypted`
被换成直连（真实现走 sqlcipher3，对明文库必然解密失败；本文件测的不是解密）。
"""

from __future__ import annotations

import sqlite3

import pytest

from vigil import export as export_mod
from vigil.config import Config, Group

GROUP_ID = 100
GROUP_NAME = "班级群"

# 源表 38 列，列名是纯数字——与真实 nt_msg.db 同形，列序只能靠位置取。
_NCOLS = 38
_COL_NAMES = tuple(f"400{i:02d}" for i in range(1, _NCOLS + 1))
_DDL_COLS = ", ".join(f'"{name}"' for name in _COL_NAMES)
_PLACEHOLDERS = ",".join("?" * _NCOLS)

# [40027] 群号在列序里的位置——从模块常量推出来，不写死数字。
_GROUP_COL_NAME = export_mod.GROUP_COL.strip('"')  # 模块常量带 SQL 引号
_GROUP_COL_INDEX = int(_GROUP_COL_NAME) - 40001
assert _COL_NAMES[_GROUP_COL_INDEX] == _GROUP_COL_NAME, "列序推错了"

# 两个 32 位 hex —— BLOB 里的图片文件名就是这个形状（media.refs 的输入）。
MD5_A = "a" * 32
MD5_B = "b" * 32
# 一条消息引用两张图（转发/相册），media_total 应为 2。
_TWO_REFS = f"{MD5_A.upper()}.JPG {MD5_B.upper()}.png".encode()


class _EmitBoom(RuntimeError):
    """模拟 `logs.emit` 在写日志时炸掉（§8.5 的 `OSError` 同族）。"""


def _row(msg_id: int, *, ts: int = 1_700_000_000, content: bytes | None = None) -> tuple:
    """造一行源表行：列序与 `export.py` 的 *_INDEX 常量对齐。"""
    cols: list = [None] * _NCOLS
    cols[export_mod.MSG_ID_INDEX] = msg_id
    cols[export_mod.UID_INDEX] = "u_1"  # [40020]，与 CONV_ID_INDEX 同列
    cols[export_mod.SENDER_NAME_INDEX] = "某同学"  # [40021]
    cols[export_mod.TS_INDEX] = ts
    cols[export_mod.CONTENT_INDEX] = content
    cols[_GROUP_COL_INDEX] = GROUP_ID
    return tuple(cols)


def _make_source_db(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {export_mod.TABLE} ({_DDL_COLS})")
    # QQCLI_COMPAT_TABLE：源库里本来就有（列结构相同），导出时写一份过去；
    # 输出库的 schema 是照抄源库的，缺了它 export() 会在写兼容层时炸。
    conn.execute(f"CREATE TABLE {export_mod.QQCLI_COMPAT_TABLE} ({_DDL_COLS})")
    # qqcli 打开库时会校验 c2c_msg_table 是否存在（见 _open_output_db 的 docstring）
    conn.execute("CREATE TABLE c2c_msg_table (x)")
    conn.execute(
        f"INSERT INTO {export_mod.TABLE} VALUES ({_PLACEHOLDERS})",
        _row(1, content=_TWO_REFS),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """明文假源库 + 直连替身 + 一份配置。返回这个 tmp_path。"""
    _make_source_db(tmp_path / "qq" / "nt_msg.db")

    # 只换「打开」这一步：真 open_encrypted 走 sqlcipher3，明文库必然解密失败。
    monkeypatch.setattr(
        export_mod.qqdb, "open_encrypted", lambda path, key: sqlite3.connect(str(path))
    )
    return tmp_path


def _config(tmp_path) -> Config:
    return Config(
        qq_db_dir=tmp_path / "qq",
        output_db=tmp_path / "export.db",
        groups=(Group(id=GROUP_ID, name=GROUP_NAME),),
    )


def test_media_index_progress_failure_is_not_swallowed(env, monkeypatch):
    """⭐ 报进度失败**不许**被当成「图片增强项取不到」吞掉。

    旧形状把 `on_progress` 和 `index_cache` 挤在同一个 try 里 ⇒ `emit` 抛一次
    就把 `cache` 变成 `{}` ⇒ `stats.media_local` 变 0 ⇒ 汇总行报出
    「本地可取 0 张（0%）」——**一个假数字**（计划 §8.5：能吞的只有打扫类失败）。

    变异 M1（把 `on_progress` 挪回 `try` 里）→ 第一条断言红。
    变异 M2（删掉 `index_cache` 的 `except`，不让它降级）→ 第二条断言红。
    """
    cfg = _config(env)
    seen: list[str] = []

    # ── 第一条：报进度抛 → 必须冒出来 ────────────────────────────
    # ⚠️ 只在那**一行**上抛：若在所有进度上都抛，旧形状照样会红——
    # 但不是因为「被吞」，而是因为群进度那行的异常本来就会冒出去（它在
    # 循环里，不受这个 try 覆盖）。那样这条判据就**钉错了东西**。
    def boom(msg: str) -> None:
        seen.append(msg)
        if "本地图片缓存" in msg:
            raise _EmitBoom("日志写不进去")

    with pytest.raises(_EmitBoom):
        export_mod.export(cfg, "k-db", on_progress=boom)
    assert any("本地图片缓存" in m for m in seen), (
        "★ 得先确认异常真的来自「本地图片缓存」那行，否则本条判据什么都没钉"
    )

    # ── 第二条（阳性对照）：index_cache 抛 → 照样降级，不拖垮导出 ──
    lines: list[str] = []

    def bad_index(_root):
        raise OSError("缓存目录读不动了")

    monkeypatch.setattr(export_mod.media, "index_cache", bad_index)
    stats = export_mod.export(cfg, "k-db", on_progress=lines.append)

    assert stats.per_group == [(GROUP_ID, GROUP_NAME, 1)], "导出本身必须照常跑完"
    assert stats.media_total == 2, "图片引用照数——引用来自 BLOB，与缓存无关"
    assert stats.media_local == 0, "缓存索引取不到 ⇒ 本地可取就是 0（这是**真的** 0）"
    assert any("本地图片缓存：0 个" in m for m in lines)


def test_media_local_counts_really_present_files(env):
    """阳性对照：缓存目录里真有文件时，`media_local` 必须数得出来。

    没有这一条，「`media_local` 恒为 0」也能让上面第二条断言全绿——
    那意味着上面那个 0 是废话，而不是「降级降出来的 0」。
    """
    pic_dir = env / "nt_data" / "Pic"
    pic_dir.mkdir(parents=True)
    (pic_dir / f"{MD5_A}.jpg").write_bytes(b"x")
    (pic_dir / f"{MD5_B}.png").write_bytes(b"x")

    stats = export_mod.export(_config(env), "k-db", on_progress=lambda _m: None)

    assert stats.media_total == 2
    assert stats.media_local == 2, "两张图都在缓存里，本地可取就该是 2 而不是 0"
