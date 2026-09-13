# -*- coding: utf-8 -*-
"""按 owner/name 直接核验 GitHub 仓库（core API，与 search 配额独立）"""
import json, sys, time, urllib.request, os, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

REPOS = sys.argv[1:]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh_repo.jsonl")
f = open(OUT, "a", encoding="utf-8")

for rn in REPOS:
    url = f"https://api.github.com/repos/{rn}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            d = json.loads(r.read().decode("utf-8"))
        rec = {
            "full_name": d["full_name"],
            "stars": d.get("stargazers_count"),
            "lang": d.get("language"),
            "desc": (d.get("description") or "")[:300],
            "topics": d.get("topics", [])[:12],
            "pushed": (d.get("pushed_at") or "")[:10],
            "archived": d.get("archived"),
            "license": (d.get("license") or {}).get("spdx_id"),
            "url": d.get("html_url"),
            "homepage": d.get("homepage"),
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"OK  {rn:45s} {rec['stars']:>7} {rec['pushed']} {rec['lang']}")
    except Exception as e:
        print(f"ERR {rn:45s} {e}")
    f.flush()
    time.sleep(0.6)
f.close()
