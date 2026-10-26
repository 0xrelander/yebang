#!/usr/bin/env python3
"""野榜采集器：把各公开来源拉成统一候选格式。

用法：python3 tools/collect.py <源> [<源>...]     源代号：xiaping skillhub clawhub skillssh coze v2ex
输出：data/raw/<源>-<日期>.json（原始回包，可核）  data/cands/<源>-<日期>.json（统一候选）

候选统一格式（一条 = 一个来源里的一个条目）：
{ "src","src_name","kind"(skill|app),"name","url","author","author_url","platforms":[...],"desc",
  "metric_label","metric", "extra":{...其它数值原样}, "created_at","updated_at" }
零依赖，只用标准库。境外站可走代理：设环境变量 YEBANG_PROXY=http://host:port；不设则直连。
"""
import json, os, re, sys, time, html, datetime, urllib.request, urllib.error, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
CANDS = os.path.join(ROOT, "data", "cands")
TODAY = datetime.date.today().isoformat()
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 yebang/0.1 (+https://github.com/0xrelander/yebang)",
      "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
PROXY = os.environ.get("YEBANG_PROXY", "")
CJK = re.compile(r"[一-鿿]")

def opener(proxy=False):
    handlers = [urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})] if (proxy and PROXY) else [urllib.request.ProxyHandler({})]
    return urllib.request.build_opener(*handlers)

def fetch(url, proxy=False, tries=3, sleep=1.5, as_json=True):
    last = None
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with opener(proxy).open(req, timeout=45) as resp:
                raw = resp.read()
            return json.loads(raw) if as_json else raw.decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(sleep * (t + 1))
    raise last

def save(dirname, name, obj):
    os.makedirs(dirname, exist_ok=True)
    p = os.path.join(dirname, f"{name}-{TODAY}.json")
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return p

def ms_day(ms):
    try:
        ms = int(ms)
        if ms > 10**12:
            ms //= 1000
        return datetime.datetime.utcfromtimestamp(ms).date().isoformat()
    except Exception:
        return ""

def day(s):
    return (s or "")[:10]

# ---------------- 虾评Skill（xiaping.coze.com，公开 JSON，国内直连） ----------------
def src_xiaping():
    allk, page, lim = [], 1, 50
    while True:
        d = fetch(f"https://xiaping.coze.com/api/skills?page={page}&limit={lim}&sort=downloads&order=desc")
        allk += d["skills"]
        if not d.get("hasMore") or page > 300:
            break
        page += 1; time.sleep(0.25)
    save(RAW, "xiaping", {"fetched_at": TODAY, "source": "https://xiaping.coze.com/api/skills", "total": d.get("total"), "skills": allk})
    seen, out = set(), []
    for s in allk:
        if s["id"] in seen: continue
        seen.add(s["id"])
        out.append({"src": "xiaping", "src_name": "虾评Skill", "kind": "skill",
            "name": s["name"].strip(), "url": f"https://xiaping.coze.com/skill/{s['id']}",
            "author": (s.get("owner_name") or "").strip(), "author_url": "", "platforms": ["OpenClaw"],
            "desc": (s.get("description") or "").strip(),
            "metric_label": "下载量", "metric": s.get("downloads") or 0,
            "extra": {"avg_stars_x100": s.get("avg_stars"), "star_count": s.get("star_count"), "comment_count": s.get("comment_count"), "category": s.get("category")},
            "created_at": day(s.get("created_at")), "updated_at": day(s.get("updated_at"))})
    return out

# ---------------- 腾讯 WorkBuddy SkillHub（api.skillhub.cn，公开 JSON，国内直连） ----------------
def src_skillhub(pages=int(os.environ.get("SKILLHUB_PAGES", "12"))):
    allk = []
    for sort in ("downloads", "stars"):
        for page in range(1, pages + 1):
            d = fetch(f"https://api.skillhub.cn/api/skills?page={page}&pageSize=50&sortBy={sort}&order=desc&source=community")
            items = d.get("data", {}).get("skills", [])
            allk += items
            if not items: break
            time.sleep(0.3)
    save(RAW, "skillhub", {"fetched_at": TODAY, "source": "https://api.skillhub.cn/api/skills?source=community", "total_reported": d.get("data", {}).get("total"), "skills": allk})
    seen, out = set(), []
    for s in allk:
        ns = s.get("namespace") or {}
        key = ns.get("canonicalName") or s.get("name")
        if key in seen: continue
        seen.add(key)
        canon = ns.get("canonicalName") or ""
        pub = (s.get("publisher") or {}).get("name") or ns.get("displayName") or s.get("ownerName") or ""
        out.append({"src": "skillhub", "src_name": "SkillHub", "kind": "skill",
            "name": (s.get("name") or "").strip(), "url": f"https://www.skillhub.cn/skills/{canon}" if canon else s.get("homepage", ""),
            "author": pub.strip(), "author_url": "", "platforms": ["WorkBuddy"],
            "desc": (s.get("description_zh") or s.get("description") or "").strip(),
            "metric_label": "下载量", "metric": s.get("downloads") or 0,
            "extra": {"stars": s.get("stars"), "installs": s.get("installs"), "score": s.get("score"), "category": s.get("category"), "upstream_url": s.get("upstream_url"), "canonical": ns.get("canonicalName"), "homepage": s.get("homepage")},
            "created_at": ms_day(s.get("created_at")), "updated_at": ms_day(s.get("updated_at"))})
    return out

# ---------------- ClawHub（clawhub.ai，公开 JSON，境外走代理） ----------------
def src_clawhub():
    allk, cursor, n = [], None, 0
    while True:
        u = "https://clawhub.ai/api/v1/skills?sort=downloads&limit=200" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        d = fetch(u, proxy=True)
        allk += d.get("items", [])
        cursor = d.get("nextCursor"); n += 1
        if not cursor or n > 40: break
        time.sleep(0.5)
    save(RAW, "clawhub", {"fetched_at": TODAY, "source": "https://clawhub.ai/api/v1/skills", "skills": allk})
    out = []
    for s in allk:
        st = s.get("stats") or {}
        out.append({"src": "clawhub", "src_name": "ClawHub", "kind": "skill",
            "name": (s.get("displayName") or s.get("slug") or "").strip(), "url": f"https://clawhub.ai/{s.get('ownerHandle')}/skills/{s.get('slug')}",
            "author": s.get("ownerHandle") or "", "author_url": f"https://clawhub.ai/u/{s.get('ownerHandle')}" if s.get("ownerHandle") else "",
            "platforms": ["OpenClaw"], "desc": (s.get("summary") or "").strip(),
            "metric_label": "下载量", "metric": st.get("downloads") or 0,
            "extra": {"installs": st.get("installs"), "stars": st.get("stars"), "comments": st.get("comments"), "versions": st.get("versions"), "slug": s.get("slug"), "topics": s.get("topics")},
            "created_at": ms_day(s.get("createdAt")), "updated_at": ms_day(s.get("updatedAt"))})
    return out

# ---------------- skills.sh（Vercel，首页榜 + 中文词搜索，境外走代理） ----------------
SKILLSSH_QUERIES = ["小红书", "微信", "抖音", "飞书", "公众号", "知乎", "B站", "淘宝", "钉钉", "百度", "中文", "翻译", "简历", "周报", "PPT"]
def src_skillssh():
    home = fetch("https://skills.sh/", proxy=True, as_json=False)
    os.makedirs(RAW, exist_ok=True)
    open(os.path.join(RAW, f"skillssh-home-{TODAY}.html"), "w", encoding="utf-8").write(home)
    rows = []
    # 行形状：<a href="/{owner}/{repo}/{skill}" ...> ... aria-label="Weekly installs: a, b, c"
    for m in re.finditer(r'href="/([^/"\s]+)/([^/"\s]+)/([^/"\s?#]+)"(.{0,4000}?)aria-label="Weekly installs: ([\d,\s]+)"', home, flags=re.S):
        owner, repo, skill, mid, weekly = m.groups()
        wk = [int(x.strip().replace(",", "")) for x in weekly.split(",") if x.strip()]
        rows.append({"source": f"{owner}/{repo}", "skill": skill, "weekly": wk})
    searched = {}
    for q in SKILLSSH_QUERIES:
        try:
            d = fetch(f"https://skills.sh/api/search?q={urllib.parse.quote(q)}", proxy=True)
            for s in d.get("skills", []):
                searched[s.get("id")] = s
            time.sleep(0.6)
        except Exception as e:
            print(f"  skills.sh search {q} failed: {e}", file=sys.stderr)
    save(RAW, "skillssh", {"fetched_at": TODAY, "home_rows": rows, "search": list(searched.values())})
    out, seen = [], set()
    for r in rows:
        key = f"{r['source']}/{r['skill']}"
        if key in seen: continue
        seen.add(key)
        total = None
        out.append({"src": "skillssh", "src_name": "skills.sh", "kind": "skill",
            "name": r["skill"], "url": f"https://skills.sh/{key}",
            "author": r["source"].split("/")[0], "author_url": f"https://github.com/{r['source'].split('/')[0]}",
            "platforms": ["Claude Code", "Codex", "Cursor"], "desc": f"来自 GitHub 仓 {r['source']}",
            "metric_label": "本周安装", "metric": r["weekly"][-1] if r["weekly"] else 0,
            "extra": {"weekly": r["weekly"], "github": f"https://github.com/{r['source']}"},
            "created_at": "", "updated_at": ""})
    for s in searched.values():
        src = s.get("source") or ""
        sid = s.get("id") or s.get("name") or ""
        key = f"{src}/{sid}"
        if key in seen or not src: continue
        seen.add(key)
        out.append({"src": "skillssh", "src_name": "skills.sh", "kind": "skill",
            "name": sid, "url": f"https://skills.sh/{key}",
            "author": src.split("/")[0], "author_url": f"https://github.com/{src.split('/')[0]}",
            "platforms": ["Claude Code", "Codex", "Cursor"], "desc": f"来自 GitHub 仓 {src}",
            "metric_label": "累计安装", "metric": s.get("installs") or 0,
            "extra": {"github": f"https://github.com/{src}", "found_by_search": True},
            "created_at": "", "updated_at": ""})
    return out

# ---------------- 扣子商店（coze.cn，公开 JSON，国内直连）：智能体 entity_type=1，应用 entity_type=6 ----------------
def src_coze(pages=int(os.environ.get("COZE_PAGES", "10"))):
    allp = []
    for et in (1, 6):
        for page in range(1, pages + 1):
            d = fetch(f"https://www.coze.cn/api/marketplace/product/list?entity_type={et}&sort_type=1&page_num={page}&page_size=50")
            prods = d.get("data", {}).get("products", [])
            allp += prods
            if not prods or not d.get("data", {}).get("has_more"): break
            time.sleep(0.4)
    save(RAW, "coze", {"fetched_at": TODAY, "source": "https://www.coze.cn/api/marketplace/product/list", "products": allp})
    out, seen = [], set()
    for p in allp:
        mi = p.get("meta_info") or {}
        eid = str(mi.get("entity_id") or p.get("id") or "")
        if not eid or eid in seen: continue
        seen.add(eid)
        et = mi.get("entity_type")
        be, pe = p.get("bot_extra") or {}, p.get("project_extra") or {}
        users = be.get("user_count") if et == 1 else pe.get("user_count")
        convs = be.get("chat_conversation_count") if et == 1 else None
        ui = p.get("user_info") or {}
        out.append({"src": "coze", "src_name": "扣子商店", "kind": "app",
            "name": (mi.get("name") or "").strip(),
            "url": f"https://www.coze.cn/store/{'agent' if et == 1 else 'project'}/{eid}",
            "author": (ui.get("name") or (p.get("seller") or {}).get("name") or "").strip(), "author_url": "",
            "platforms": ["扣子 " + ("智能体" if et == 1 else "应用")],
            "desc": (mi.get("description") or "").strip().split("\n")[0][:80],
            "metric_label": "用户数", "metric": users or 0,
            "extra": {"heat": mi.get("heat"), "favorite_count": mi.get("favorite_count"), "conversations": convs, "is_official": mi.get("is_official"),
                      "enterprise_label": bool((ui.get("enterprise_label") or {}).get("icon_url")), "category": (mi.get("category") or {}).get("name"), "entity_type": et},
            "created_at": ms_day(mi.get("listed_at")), "updated_at": ""})
    return out

# ---------------- V2EX 分享创造（节点页 + 帖页，境外走代理）：近 30 天带 AI 关键词的「我做了一个」 ----------------
AI_RE = re.compile(r"(AI|人工智能|大模型|GPT|Claude|LLM|Agent|智能体|Gemini|DeepSeek|豆包|通义|千问|Kimi|MCP|Skill|OpenClaw|Codex|Cursor|生成式|AIGC|语音识别|OCR|总结|翻译|Copilot|chatbot|机器人)", re.I)
def src_v2ex(pages=int(os.environ.get("V2EX_PAGES", "12")), days=30):
    since = datetime.date.today() - datetime.timedelta(days=days)
    topics = []
    for p in range(1, pages + 1):
        h = fetch(f"https://www.v2ex.com/go/create?p={p}", proxy=True, as_json=False)
        cells = re.split(r'<div class="cell from_', h)[1:]
        oldest = None
        for c in cells:
            m = re.search(r'<span class="item_title"><a href="/t/(\d+)[^"]*"[^>]*>(.*?)</a>', c, flags=re.S)
            if not m: continue
            tid, title = m.group(1), html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            rep = re.search(r'class="count_livid">(\d+)<', c)
            au = re.search(r'<strong><a href="/member/([^"]+)"', c)
            tm = re.search(r'<span title="([\d-]+ [\d:]+)', c)
            d = tm.group(1)[:10] if tm else ""
            oldest = d if d else oldest
            topics.append({"id": tid, "title": title, "replies": int(rep.group(1)) if rep else 0, "author": au.group(1) if au else "", "date": d})
        time.sleep(0.8)
        if oldest and oldest < since.isoformat(): break
    recent = [t for t in topics if t["date"] >= since.isoformat()]
    picked = []
    for t in recent:
        if not AI_RE.search(t["title"]): continue
        try:
            api = fetch(f"https://www.v2ex.com/api/topics/show.json?id={t['id']}", proxy=True)
            page = fetch(f"https://www.v2ex.com/t/{t['id']}", proxy=True, as_json=False)
        except Exception as e:
            print(f"  v2ex topic {t['id']} failed: {e}", file=sys.stderr); continue
        a = api[0] if isinstance(api, list) and api else {}
        rendered = a.get("content_rendered") or ""
        body = html.unescape(re.sub(r"<[^>]+>", " ", rendered)) or (a.get("content") or "")
        created = datetime.datetime.fromtimestamp(a.get("created", 0), datetime.timezone(datetime.timedelta(hours=8))).date().isoformat() if a.get("created") else t["date"]
        views = re.search(r"(\d+)\s*(?:views|次点击)", page)
        links = re.findall(r'href="(https?://[^"]+)"', rendered)
        links += re.findall(r"(https?://[^\s<>\"']+)", a.get("content") or "")
        ext, seen_l = [], set()
        for l in links:
            l = l.rstrip(").,，。")
            if re.search(r"v2ex\.com|imgur|imgse|sm\.ms|jsdelivr|github\.com/[^/]+/[^/]+/(?:issues|blob)", l) or l in seen_l: continue
            seen_l.add(l); ext.append(l)
        picked.append({**t, "created": created, "replies": a.get("replies", t["replies"]), "views": int(views.group(1)) if views else None, "body": body[:400], "links": ext[:5]})
        time.sleep(0.8)
    save(RAW, "v2ex", {"fetched_at": TODAY, "node": "create", "scanned": len(topics), "recent": len(recent), "picked": picked})
    out = []
    for t in picked:
        out.append({"src": "v2ex", "src_name": "V2EX 分享创造", "kind": "app",
            "name": t["title"][:60], "url": (t["links"][0] if t["links"] else f"https://www.v2ex.com/t/{t['id']}"),
            "author": t["author"], "author_url": f"https://www.v2ex.com/member/{t['author']}",
            "platforms": ["网页 / 独立应用"], "desc": re.sub(r"\s+", " ", t["body"])[:80],
            "metric_label": "回复数", "metric": t["replies"],
            "extra": {"views": t["views"], "post": f"https://www.v2ex.com/t/{t['id']}", "links": t["links"]},
            "created_at": t.get("created") or t["date"], "updated_at": t["date"]})
    return out

SOURCES = {"xiaping": src_xiaping, "skillhub": src_skillhub, "clawhub": src_clawhub, "skillssh": src_skillssh, "coze": src_coze, "v2ex": src_v2ex}

def main():
    want = sys.argv[1:] or list(SOURCES)
    for k in want:
        t0 = time.time()
        try:
            items = SOURCES[k]()
            p = save(CANDS, k, {"date": TODAY, "src": k, "count": len(items), "items": items})
            print(f"[ok] {k}: {len(items)} → {p} ({time.time()-t0:.0f}s)")
        except Exception as e:
            print(f"[fail] {k}: {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
