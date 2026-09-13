"""独立验证：被判为「非文本」的消息里，到底还有没有文字？

方法刻意绕开我自己的提取器（它用的是 0x82 0x16 标记启发式），
改为直接在原始字节里搜合法的 UTF-8 中文序列——两段连续中文才算数，
避免把偶合的三字节串误判成文字。

若结果接近 0，说明 71.7% 没有"漏捞"，只是那些消息本来就没文字。
"""

import re
import sqlite3

# 合法的 UTF-8 中文（3 字节序列，E4~E9 开头且续字节合法），至少 2 个字
ZH = re.compile(rb"(?:[\xe4-\xe9][\x80-\xbf]{2}){2,}")

conn = sqlite3.connect("data/vigil.db")
rows = conn.execute(
    """SELECT g.[40001], g.[40800] FROM group_msg_table g
       WHERE g.[40001] IN (SELECT msg_id FROM messages WHERE content='[非文本]')"""
).fetchall()
conn.close()

with_text = []
no_text = 0
for mid, blob in rows:
    if not blob:
        no_text += 1
        continue
    hits = ZH.findall(blob)
    if hits:
        with_text.append((mid, [h.decode("utf-8", "replace") for h in hits[:3]]))
    else:
        no_text += 1

total = len(rows)
print(f"被判为 [非文本] 的消息: {total:,}")
print(f"  独立扫描后确实没有中文的: {no_text:,}  ({no_text/total*100:.1f}%)")
print(f"  独立扫描后发现含中文的:   {len(with_text):,}  ({len(with_text)/total*100:.1f}%)")
print()
if with_text:
    print("=== 被漏捞的样例（提取器的召回损失）===")
    for mid, texts in with_text[:12]:
        print(f"  msgid={mid}  {texts}")
else:
    print("结论：没有漏捞——被判非文本的消息里确实一个字都没有。")
