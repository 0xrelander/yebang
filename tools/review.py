#!/usr/bin/env python3
"""编辑复核用：把过了四道门的网站按行业打印成紧凑行，供人挑精选。
用法：python3 tools/review.py <日期> [行业] [--zh] [--top N]
"""
import json, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
date = sys.argv[1]
d = json.load(open(os.path.join(ROOT, "data", "screened", f"{date}.json"), encoding="utf-8"))
only = [a for a in sys.argv[2:] if not a.startswith("--")]
top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 0
zh = "--zh" in sys.argv
groups = collections.OrderedDict()
for it in d["items"]:
    if only and it["industry"] not in only: continue
    if zh and it["lang"] != "zh": continue
    groups.setdefault(it["industry"], []).append(it)
for ind, its in groups.items():
    its.sort(key=lambda x: (0 if x["lang"] == "zh" else 1, -x["score"]))
    print(f"\n## {ind} ({len(its)})")
    for i, it in enumerate(its[:top] if top else its):
        s = it["signals"]; sig = s.get("stars") or s.get("points") or s.get("likes") or s.get("replies") or 0
        print(f"{it['lang']} {it['src'][:2]} {sig:>4} | {it['name'][:34]:34} | {it['url'][:48]:48} | {(it['desc'] or '')[:110]}")
