#!/usr/bin/env python3
"""后置剔除：规则更新后不用重跑 30 分钟的存活检查，直接从 screened 里拿掉命中的条目并计入对应那道门。
用法：python3 tools/prune.py <日期>
规则：rank.py 的 RELAY_RE（中转/代理/代充…）+ data/exclude.txt（网址<TAB>原因）
"""
import json, os, sys, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rank import RELAY_RE, load_exclude

date = sys.argv[1]
p = os.path.join(ROOT, "data", "screened", f"{date}.json")
d = json.load(open(p, encoding="utf-8"))
ex = load_exclude()
kept, n_relay, n_ex = [], 0, 0
for it in d["items"]:
    text = " ".join([it.get("name", ""), it.get("desc", ""), it.get("title", ""), it.get("meta", "")])
    st = d["stats"].setdefault(it["src_name"], {})
    if RELAY_RE.search(text):
        n_relay += 1; st["中转代理"] = st.get("中转代理", 0) + 1; st["收录"] = st.get("收录", 0) - 1; continue
    if it["url"] in ex:
        n_ex += 1; st["网址不算网站"] = st.get("网址不算网站", 0) + 1; st["收录"] = st.get("收录", 0) - 1; continue
    kept.append(it)
d["items"] = kept
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"剔除 中转代理 {n_relay} · 人工名单 {n_ex} · 剩 {len(kept)}")
