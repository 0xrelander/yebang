#!/usr/bin/env python3
"""补查 Hugging Face 作者是不是个人：screen.py 并发查时镜像会回 429，把没查到的（author_type=unknown）慢速再查一遍。
用法：python3 tools/hf_authors.py <日期>     机构账号的条目从 screened 里拿掉并计入「非个人或大厂」
"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HF_API = os.environ.get("YEBANG_HF_API", "https://hf-mirror.com")
date = sys.argv[1]
p = os.path.join(ROOT, "data", "screened", f"{date}.json")
d = json.load(open(p, encoding="utf-8"))
todo = sorted({it["author"] for it in d["items"] if it["src"] == "hf" and it.get("author_type") == "unknown"})
print(f"待查 {len(todo)} 个作者")
res = {}
for i, a in enumerate(todo, 1):
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{HF_API}/api/users/{urllib.parse.quote(a)}/overview", headers={"User-Agent": "yebang/0.2"})
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read(); res[a] = "individual"; break
        except urllib.error.HTTPError as e:
            if e.code == 404: res[a] = "organization"; break
            if e.code == 429: time.sleep(3 * (attempt + 1)); continue
            res[a] = "unknown"; break
        except Exception:
            res[a] = "unknown"; break
    time.sleep(0.4)
    if i % 50 == 0: print(f"  {i}/{len(todo)}")
kept, dropped = [], 0
for it in d["items"]:
    if it["src"] == "hf" and it.get("author_type") == "unknown":
        it["author_type"] = res.get(it["author"], "unknown")
    if it.get("author_type") == "organization":
        dropped += 1; continue
    kept.append(it)
d["items"] = kept
st = d["stats"].get("Hugging Face Spaces")
if st:
    st["非个人或大厂"] += dropped; st["收录"] -= dropped
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
import collections
print("结果：", dict(collections.Counter(res.values())), "拿掉机构", dropped)
