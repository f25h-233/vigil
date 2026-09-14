"""从 siliconflow.cn/pricing 的 Next.js flight payload 里抽价格。一次性脚本。"""

import json
import re
import sys

s = open("sf_price.html", encoding="utf-8", errors="replace").read()

# flight payload 里每个模型是一段被转义的 JSON：\"modelId\":\"17885302826\",\"modelName\":\"Qwen/Qwen3-32B\"
MODEL = re.compile(r'\\"modelId\\":\\"(\d+)\\",\\"modelName\\":\\"([^\\]+)\\"')
FIELDS = [
    "contextLen",
    "price",
    "outputPrice",
    "inputPrice",
    "cachePrice",
    "currency",
    "unitOfGood",
    "billingType",
    "priceUnit",
    "outputUnit",
]

want = sys.argv[1:] or [
    "Qwen/Qwen3.5-35B-A3B",
    "Qwen/Qwen3.5-27B",
    "Qwen/Qwen3-32B",
    "Qwen/Qwen3-14B",
    "Qwen/Qwen3.5-4B",
    "Qwen/Qwen2.5-32B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
]

hits = {m.group(2): m.start() for m in MODEL.finditer(s)}
print(f"payload 共 {len(hits)} 个模型\n")

for mid in want:
    if mid not in hits:
        print(f"{mid:<32} ✗ 不在价格页 payload 里")
        continue
    seg = s[hits[mid] : hits[mid] + 3000]
    got = {}
    for k in FIELDS:
        m = re.search(r'\\"%s\\":\\"?([^,\\"]+)' % k, seg)
        if m:
            got[k] = m.group(1).lstrip('"')
    ctx = re.search(r"\\\"contextLen\\\":(\d+)", seg)
    print(f"{mid:<32} {json.dumps(got, ensure_ascii=False)}")
