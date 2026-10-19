"""QQ NT 本地库访问层。

只负责一件事：把 QQ 的加密库变成「可查询的数据源」。
定位库文件、剥假头、用 sqlcipher3 打开、读群清单。

失败策略（见 coding-creed §5）：
  - 配置错误 / 密钥错误 / 库文件缺失 → QQDBError 快速失败（这是我们自己的问题）
  - 坏页导致的单批查询失败        → 由调用方决定跳过（外部环境，不该拖垮整体）
"""

from __future__ import annotations

import os
import pathlib
import shutil

import sqlcipher3.dbapi2 as sqlcipher

# NTQQ 在真正的 SQLCipher 数据前插了 1024 字节假头，
# 头部魔数是 "SQLite header 3"（注意：不是真 SQLite 的 "SQLite format 3"）
FAKE_HEADER_SIZE = 1024
_FAKE_HEADER_MAGIC = b"SQLite header 3"
_REAL_HEADER_MAGIC = b"SQLite format 3\x00"

# 打开 NTQQ 加密库所需的 PRAGMA。顺序敏感：page_size 必须在 key 之前，
# 这是实测得出的（顺序错了会解密失败）。
def _cipher_pragmas(key: str) -> tuple[str, ...]:
    return (
        "PRAGMA cipher_page_size = 4096;",
        f"PRAGMA key = '{key}';",
        "PRAGMA kdf_iter = 4000;",
        "PRAGMA cipher_hmac_algorithm = HMAC_SHA1;",
        "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;",
    )


class QQDBError(RuntimeError):
    """配置或密钥层面的错误——应当快速失败，不要试图绕过。"""


def strip_fake_header(src: pathlib.Path, dst: pathlib.Path) -> pathlib.Path:
    """把 QQ 的加密库（带假头）复制成可被 SQLCipher 直接打开的形式。

    若源文件已是明文 SQLite 结构则原样复制。已存在且大小正确则跳过。

    ⚠️ **写 dst 必须原子**（U-4，M6 T1）。原实现是
    ``open(dst, "wb")`` —— 那是「**先截断、再拷**」，而 dst 与 `export`
    **共用同一个文件**（导出路径与 ``vigil groups`` 经 `cmd_groups` 指向
    **同一个路径**，它由 `export._clear_db_path` 定义）。并发时
    （用户手跑 ``vigil groups`` 而任务计划正在跑 ``vigil export``）：

      1. 后者把这个文件**从 0 字节重新写**；
      2. 正在读它的 export 于是读到**半个文件 / 空洞**；
      3. SQLite 报的是**坏页** —— 于是「消息静默消失」被报告成
         「QQ 库物理坏页」，一个**指向错误方向**的诊断（spec §1.6）。

    ⇒ 改成「同目录临时文件 → fsync → ``os.replace``」：读者要么看到
    完整的旧版、要么看到完整的新版，**没有第三种状态**。
    ``os.replace`` 在同一文件系统上是原子的，Windows 上也成立。

    ⚠️ 临时文件名带 **pid**。固定名 ``dst.tmp`` 只对「单写者」成立，
    而这里恰恰是并发场景；用同一个临时名会让两个进程互相写坏对方正在拷的
    临时文件 —— 而那只会在 replace 之后才现形，**长得像数据损坏**。
    ⚠️ 临时文件必须与目标**同目录**（``os.replace`` 不跨卷）。
    ⚠️ 失败路径要清掉临时文件：它的范围**只是"占盘"**，不是"被人扫到"——
    本函数从不列目录，全仓也没有东西扫 `data/cache/`（M6 终审 #1：从前的
    理由写的是「会被本函数反复扫到、越积越多」，**那是事实错误**，会让
    后来者按一个假前提去"清理"）。
    ⚠️ **代价如实记**：真正的失败路径有两个，本函数只覆盖**能跑完的那一个**。
    被 `SIGKILL`（任务计划强杀 / 蓝屏）打断时 `except BaseException` 也覆盖不到
    ——那会留下一个 `.tmp<pid>`，而它是**知情接受**的：峰值 **3.29 GB/次** 的
    残留只是白占盘，**没有任何自动清理**（glob 全删是错的：会误删并发写者的
    活临时文件，那条修法已撤销，见计划勘误 E3）。要清就人工确认没有
    `vigil export` 在跑之后手动删。
    """
    if not src.is_file():
        raise QQDBError(f"库文件不存在: {src}")

    with open(src, "rb") as f:
        head = f.read(len(_REAL_HEADER_MAGIC))

    has_fake_header = head.startswith(_FAKE_HEADER_MAGIC[: len(head)]) and not head.startswith(
        _REAL_HEADER_MAGIC
    )
    offset = FAKE_HEADER_SIZE if has_fake_header else 0
    expected_size = src.stat().st_size - offset

    # 缓存命中：大小对且不比源旧。比 mtime 是必须的——QQ 一旦写入新消息，
    # 源库就变新了，此时必须重新剥头，否则会读到过期快照。
    if dst.is_file() and dst.stat().st_size == expected_size:
        if dst.stat().st_mtime >= src.stat().st_mtime:
            return dst

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.tmp{os.getpid()}")
    try:
        with open(src, "rb") as f:
            f.seek(offset)
            with open(tmp, "wb") as out:
                shutil.copyfileobj(f, out, 64 << 20)
                # ⚠️ fsync 必须在 replace **之前**：否则断电时可能留下一个
                # 「名字已就位、内容还在页缓存里」的空文件——那比旧版本更糟，
                # 因为它**看起来是有效的**（大小对得上时连缓存判据都会放行）。
                out.flush()
                os.fsync(out.fileno())
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dst


def open_encrypted(path: pathlib.Path, key: str) -> sqlcipher.Connection:
    """打开 NTQQ 加密库。key 无效时抛 QQDBError（快速失败）。"""
    if not key:
        raise QQDBError("数据库密钥为空。请检查 .env 里的 VIGIL_DB_KEY")

    conn = sqlcipher.connect(str(path), isolation_level=None)
    # QQ 昵称里可能存在非法 UTF-8 字节，默认 text_factory 会直接抛错。
    # 容忍式解码，坏字节替换成 U+FFFD 而不是让整个查询失败。
    conn.text_factory = lambda raw: raw.decode("utf-8", "replace")
    for pragma in _cipher_pragmas(key):
        conn.execute(pragma)
    try:
        # 真正触发解密的探针查询
        conn.execute("SELECT count(*) FROM sqlite_master;").fetchone()
    except Exception as exc:  # noqa: BLE001 — 统一转成我们自己的错误类型
        conn.close()
        raise QQDBError(f"无法解密，密钥可能不对: {exc}") from exc
    return conn


def list_group_message_counts(conn: sqlcipher.Connection) -> list[tuple[int, int, int]]:
    """返回 [(群号, 消息数, 最新时间戳)]，按消息数降序。

    走 idx40027_* 索引，不触发表扫描——实测坏页不影响此查询。

    ⚠️ **必须排除 "40027" 为 NULL 的行**（别名 group_id，两条理由都要成立才写这个
    WHERE）：
      · **正确性**：`GROUP BY` 会给 NULL 单建一组，于是 `int(g)` 拿到 None 直接抛
        `TypeError`，整个 `vigil groups` 崩掉（2026-10-19 实测：对方环境有这种行，
        本机 0 条——所以别用"我这儿没有"当判据）。即便不崩，群号为 NULL 的行
        **无法归属任何群**，本来也不该进群清单。
      · **性能**：`EXPLAIN QUERY PLAN` 实测——加了 `IS NOT NULL` 后由
        `SCAN group_msg_table USING COVERING INDEX idx40027_40058`
        变成 `SEARCH ... (40027>?)`，**仍走索引、且更快**。所以这不是"为了不崩
        而牺牲性能"的妥协。
    """
    rows = conn.execute(
        'SELECT "40027", count(*), max("40058") FROM group_msg_table '
        'WHERE "40027" IS NOT NULL '
        'GROUP BY "40027" ORDER BY count(*) DESC'
    ).fetchall()
    return [(int(g), int(n), int(t or 0)) for g, n, t in rows]


def open_group_info(clear_path: pathlib.Path, key: str) -> sqlcipher.Connection:
    """打开 group_info.db，用于取群号→群名映射。"""
    return open_encrypted(clear_path, key)


def group_names(conn: sqlcipher.Connection) -> dict[str, str]:
    """返回 {群号: 群名}。取不到名字的群不会出现在结果里。

    列号实测确认：60001 = 群号，60007 = 群名（见 docs/DATA-NOTES.md）。
    """
    try:
        rows = conn.execute('SELECT "60001", "60007" FROM group_list').fetchall()
    except Exception:  # noqa: BLE001 — 群名是锦上添花，拿不到不该中断主流程
        return {}
    return {str(gid): (name or "").strip() for gid, name in rows}
