"""消息正文提取：把 [40800] 的 protobuf BLOB 变成人话。

移植自 qqcli-rs 的 `extract_text`（src/db.rs），算法本身是启发式的：

    1. 在 BLOB 里找 [0x82][0x16] 标记
    2. 标记后是 varint 长度，再往后是文本字节
    3. 用「含中文字符」或「纯可打印 ASCII」校验，防止把二进制噪声当文本
    4. 都不成 → 退回 GBK 解码整个 BLOB

本机实测（抽样 3000 条）：约 76% 的消息能取出可读文本，
16% 是图片类（本模块暂标 [非文本]），8% 无法解析。

TODO: 富消息（图片/文件/表情/合并转发）需要完整的段解析器——
      qqcli 的 segment.rs + normalize.rs 做了这件事，见 docs/DATA-NOTES.md。
"""

from __future__ import annotations

import re

NON_TEXT = "[非文本]"

# 兜底路径：直接在字节里找连续的中文串。
# 为什么需要：有一类消息的文本**不在 0x82 0x16 标记里**，而是散落在其他
# protobuf 字段中——实测包括撤回提示（"你猜猜撤回了什么"）、表情描述
# （"动画表情""并坏笑了一下"）等。只认标记会整类漏掉。
# 实测这批占非文本消息的 70%，漏掉它们会严重低估覆盖率。
_ZH_RUN = re.compile(r"[一-鿿　-〿！-～]{2,}")

_MARKER = b"\x82\x16"
_MAX_TEXT_LEN = 4096  # 与 qqcli 保持一致


def _blen(s: str) -> int:
    """UTF-8 字节长度。

    移植时的坑：Rust 的 `str::len()` 返回**字节数**，Python 的 `len()` 返回**字符数**。
    原文里的 `len() > 3` 等判据全是字节语义——直接照抄会丢掉所有两字短消息
    （"行吧""好的""收到"），而这类消息在群聊里恰恰最密集。
    """
    return len(s.encode("utf-8", "replace"))


def _is_chinese(cp: int) -> bool:
    return 0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF


# C0 控制字符（制表/换行/回车除外）
_CONTROL_CHARS = frozenset(chr(i) for i in range(0x20)) - {"\t", "\n", "\r"}


def _plausible(s: str) -> bool:
    """挡住「二进制噪声被解码成假文本」。

    真实聊天文本不会含 C0 控制字符，而 protobuf 的字段标记
    （0x13/0x15/0x16/0x17）恰好落在该区间；出现替换字符（U+FFFD）同理。
    没有这道闸，一条二维码/富消息会被解成一串看似中文的乱码。
    """
    return not (set(s) & _CONTROL_CHARS) and "�" not in s


def _looks_like_text(s: str) -> bool:
    """照着 qqcli 的判据：有中文就算，或者全是可打印 ASCII 且够长。"""
    if _blen(s) < 2:
        return False
    if any(_is_chinese(ord(c)) for c in s):
        return True
    return _blen(s) >= 3 and all(0x21 <= ord(c) <= 0x7E or ord(c) > 0x9FFF for c in s)


def _read_at(data: bytes) -> str:
    """data 以 [0x82][0x16] 开头：读 varint 长度，再取文本。"""
    if len(data) < 4:
        return ""

    length = 0
    shift = 0
    j = 2
    while j < len(data) and shift < 64:
        byte = data[j]
        j += 1
        length |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    else:
        return ""

    if not 0 < length < _MAX_TEXT_LEN or j + length > len(data):
        return ""

    text = data[j : j + length].decode("utf-8", "replace").strip()
    return text if _looks_like_text(text) and _plausible(text) else ""


def _scan(data: bytes) -> str:
    """在整块 BLOB 里找第一个能解出文本的标记。"""
    start = 0
    while True:
        idx = data.find(_MARKER, start)
        if idx < 0:
            return ""
        found = _read_at(data[idx:])
        if found:
            return found
        start = idx + 1


def _scan_cjk_run(raw: bytes) -> str:
    """兜底：找最长的连续中文串（文本可能不在 0x82 标记里）。"""
    text = raw.decode("utf-8", "replace")
    runs = [r for r in _ZH_RUN.findall(text) if _plausible(r)]
    if not runs:
        return ""
    return max(runs, key=len).strip()


def extract_text(raw: bytes | None) -> str:
    """从消息 BLOB 提取可读文本；取不到返回空串。

    三条路径依次尝试：
      1. 0x82 0x16 标记（多数普通消息）
      2. 连续中文串兜底（撤回提示、表情描述等散落的文本）
      3. GBK 解码（旧式编码消息）
    """
    if not raw:
        return ""

    if b"\x82" in raw:
        found = _scan(raw)
        if _blen(found) > 3:
            return found

    # 路径 2：标记法失败时，直接找中文串
    found = _scan_cjk_run(raw)
    if _blen(found) > 3:
        return found

    try:
        decoded = raw.decode("gbk", "replace").strip()
    except Exception:  # noqa: BLE001 — 解码失败不算异常路径
        return ""
    return decoded if _blen(decoded) > 3 and _plausible(decoded) else ""


def readable(raw: bytes | None) -> str:
    """给人看的形式：取不到文本时给一个占位标记，而不是空白。"""
    return extract_text(raw) or NON_TEXT
