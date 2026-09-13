"""QQ NT 本地库访问层。

只负责一件事：把 QQ 的加密库变成「可查询的数据源」。
定位库文件、剥假头、用 sqlcipher3 打开、读群清单。

失败策略（见 coding-creed §5）：
  - 配置错误 / 密钥错误 / 库文件缺失 → QQDBError 快速失败（这是我们自己的问题）
  - 坏页导致的单批查询失败        → 由调用方决定跳过（外部环境，不该拖垮整体）
"""

from __future__ import annotations

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
    with open(src, "rb") as f:
        f.seek(offset)
        with open(dst, "wb") as out:
            shutil.copyfileobj(f, out, 64 << 20)
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
    """
    rows = conn.execute(
        'SELECT "40027", count(*), max("40058") FROM group_msg_table '
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
