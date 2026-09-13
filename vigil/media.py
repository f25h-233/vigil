"""消息里的图片引用 → 本地缓存文件。

QQ 的图片消息 BLOB 里存的是 `{32位hex}.{ext}` 形式的文件名，而这个 hex
**就是** `nt_data/Pic/` 下的缓存文件名（BLOB 里是大写，磁盘上是小写）。
所以拿图只需要两步：从 BLOB 里扫出名字 → 在缓存目录里找同名文件。

实测（2026-09-13，群 643375490）：
    含图片文件名的消息 7,142 条，其中图片**在本地**的只有 533 条 = 7%。

**这个 7% 不是"对不上号"，是"文件不在本地"。** 曾误判为
"BLOB 里是服务端 fileid、与缓存名不同源"——用对照样本推翻：命中与未命中
的两个 BLOB 结构完全相同，唯一差别是磁盘上有无该文件。全盘搜索确认
未命中样本确实不存在。QQ 并未把所有图都缓存下来（策略未明）。

所以本模块的产出天然分两类：**能取到的（path 有值）** 和 **没缓存的
（path 为 None）**。后者记录下来，是为了将来若要联网补全时知道缺哪些。
"""

from __future__ import annotations

import pathlib
import re

# BLOB 里的媒体文件名：32 位 hex + 扩展名。
# 限定扩展名是为了避免把其它 32-hex 标识误当文件名。
_MEDIA_NAME = re.compile(rb"([0-9A-Fa-f]{32})\.([A-Za-z0-9]{1,5})")
_MEDIA_EXTS = frozenset(
    {b"jpg", b"jpeg", b"png", b"gif", b"webp", b"bmp", b"heic"}
)

# 缓存文件名可能带尺寸后缀（缩略图形如 `{md5}_720.jpg`）
_SIZE_SUFFIX = re.compile(r"_\d+$")


def refs(blob: bytes | memoryview) -> list[tuple[str, str]]:
    """从消息 BLOB 里提取图片引用，返回 [(md5小写, 扩展名), ...]。

    一条消息可能引用多张图（转发/相册），所以返回列表；同图去重。
    """
    if not blob:
        return []
    seen: dict[str, str] = {}
    for m in _MEDIA_NAME.finditer(bytes(blob)):
        ext = m.group(2).lower()
        if ext not in _MEDIA_EXTS:
            continue
        seen.setdefault(m.group(1).decode().lower(), ext.decode())
    return list(seen.items())


def index_cache(root: pathlib.Path) -> dict[str, pathlib.Path]:
    """扫描本地图片缓存目录，建立 {md5: 文件路径} 索引。

    缩略图文件名带 `_720` 之类的尺寸后缀，统一剥掉后建索引——
    同一张图的原图与缩略图只保留先遇到的那个。
    """
    index: dict[str, pathlib.Path] = {}
    if not root.is_dir():
        return index
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stem = _SIZE_SUFFIX.sub("", path.stem.lower())
        index.setdefault(stem, path)
    return index
