# -*- coding: utf-8 -*-
"""GitHub 仓库搜索：QQ群消息聚合 / 信息整理类方案"""
import json, sys, time, urllib.request, urllib.parse, os

QUERIES = sys.argv[1:]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh_raw.jsonl")

def gh(q, per_page=25, sort="stars"):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({
        "q": q, "sort": sort, "order": "desc", "per_page": per_page})
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/vnd.github+json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  [retry {attempt+1}] {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    return None

seen = set()
with open(OUT, "a", encoding="utf-8") as f:
    for q in QUERIES:
        print(f"== {q}", file=sys.stderr)
        d = gh(q)
        if not d:
            print(f"  FAILED: {q}", file=sys.stderr)
            time.sleep(8)
            continue
        items = d.get("items", [])
        print(f"  total={d.get('total_count')} got={len(items)}", file=sys.stderr)
        for it in items:
            fn = it["full_name"]
            if fn in seen:
                continue
            seen.add(fn)
            rec = {
                "query": q,
                "full_name": fn,
                "stars": it.get("stargazers_count"),
                "lang": it.get("language"),
                "desc": (it.get("description") or "")[:220],
                "topics": it.get("topics", [])[:10],
                "updated": (it.get("pushed_at") or "")[:10],
                "archived": it.get("archived"),
                "url": it.get("html_url"),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        time.sleep(8)  # 未认证搜索 API 限速 10/min
print("done", file=sys.stderr)
