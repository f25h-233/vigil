"""探针：blob 里的本地图片路径，能覆盖多少、文件是否真实存在。

结论若成立，图片通知就能 OCR——不需要联网、不需要映射表。
"""

import pathlib
import re
import sqlite3
from collections import Counter

PAT = re.compile(rb"[A-Za-z]:\\[\x20-\x7e]{8,}")  # 单反斜杠

conn = sqlite3.connect("data/vigil.db")
rows = conn.execute(
    """SELECT g.[40001], g.[40800] FROM group_msg_table g
       WHERE g.[40001] IN (SELECT msg_id FROM messages WHERE content='[非文本]')"""
).fetchall()
conn.close()

found: dict[int, str] = {}
for mid, blob in rows:
    if not blob:
        continue
    m = PAT.search(blob)
    if m:
        found[mid] = m.group().decode("utf-8", "replace")

print(f"[非文本] {len(rows):,} 条中，blob 含本地路径: {len(found):,} ({len(found)/len(rows)*100:.1f}%)")

ok: list[tuple[int, str, int]] = []
stale = 0
for mid, p in found.items():
    fp = pathlib.Path(p)
    if fp.is_file():
        ok.append((mid, p, fp.stat().st_size))
    else:
        stale += 1

print(f"  文件真实存在: {len(ok):,}   路径陈旧/已被清理: {stale:,}")
print()
print("=== 存在的样例（可直接 OCR）===")
for mid, p, size in ok[:6]:
    print(f"  {size/1024:>7.0f} KB  ...{p[-64:]}")

print()
print("=== 目录分布 ===")
dirs = Counter(str(pathlib.Path(p).parent).split("nt_data")[-1] for _, p, _ in ok)
for d, n in dirs.most_common(6):
    print(f"  {n:>6}  {d}")

if ok:
    print()
    print("=== 后缀分布 ===")
    exts = Counter(pathlib.Path(p).suffix.lower() for _, p, _ in ok)
    for e, n in exts.most_common():
        print(f"  {n:>6}  {e}")
