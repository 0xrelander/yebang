#!/usr/bin/env python3
"""野榜发现器：去「出生登记处」拉最近 N 天新出生的网站候选，不顺链接爬。

用法：python3 tools/discover.py <登记处> [<登记处>...] [--days 7]
登记处代号：github（新仓 homepage 字段）  hn（Show HN）  hf（Hugging Face Spaces 新建）  v2ex（分享创造，复用 collect.py 的产物）
输出：data/found/<登记处>-<日期>.json，每条 = 一个候选网站：
{ "src","src_name","name","url","source_url","author","author_url","author_type"(individual|organization|unknown),
  "desc","signals":{...公开数值},"created_at","found_at" }
零依赖，只用标准库。境外站可走代理：YEBANG_PROXY=http://host:port。GitHub 搜索建议带 GITHUB_TOKEN（`gh auth token`），匿名每分钟只给 10 次。
"""
import json, os, re, sys, time, html, datetime, urllib.request, urllib.error, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOUND = os.path.join(ROOT, "data", "found")
TODAY = datetime.date.today().isoformat()
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 yebang/0.2 (+https://github.com/0xrelander/yebang)",
      "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
PROXY = os.environ.get("YEBANG_PROXY", "")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DAYS = 7
if "--days" in sys.argv:
    DAYS = int(sys.argv[sys.argv.index("--days") + 1])
SINCE = datetime.date.today() - datetime.timedelta(days=DAYS)

def opener(proxy=False):
    handlers = [urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})] if (proxy and PROXY) else [urllib.request.ProxyHandler({})]
    return urllib.request.build_opener(*handlers)

def fetch(url, proxy=False, tries=3, sleep=2.0, headers=None, as_json=True):
    last = None
    for t in range(tries):
        try:
            h = dict(UA); h.update(headers or {})
            req = urllib.request.Request(url, headers=h)
            with opener(proxy).open(req, timeout=45) as resp:
                raw = resp.read()
            return json.loads(raw) if as_json else raw.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429):  # 搜索限速：等它说的秒数
                wait = int(e.headers.get("Retry-After") or 0) or 60
                print(f"  [rate] {e.code} 等 {wait}s", file=sys.stderr); time.sleep(wait); continue
            if e.code in (422, 404): raise
            time.sleep(sleep * (t + 1))
        except Exception as e:
            last = e; time.sleep(sleep * (t + 1))
    raise last

# 有人会把自己的 API token 写进仓库描述或 Space 标题里。落盘前抹掉，不替别人把秘密带出去（GitHub 推送保护也会拦）
SECRET_RE = re.compile(r"\b(hf_[A-Za-z0-9]{25,}|sk-(?:ant-|proj-)?[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|gh[ousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})\b")

def scrub(text):
    return SECRET_RE.sub(lambda m: m.group(0)[:4] + "[已抹去]", text)

def save(name, items, meta):
    os.makedirs(FOUND, exist_ok=True)
    p = os.path.join(FOUND, f"{name}-{TODAY}.json")
    text = scrub(json.dumps({"found_at": TODAY, "since": SINCE.isoformat(), **meta, "items": items}, ensure_ascii=False))
    open(p, "w", encoding="utf-8").write(text)
    print(f"{name}: {len(items)} 条 → {p}")

def clean(s, n=200):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()[:n]

def days_between(a, b):
    out, d = [], a
    while d <= b:
        out.append(d); d += datetime.timedelta(days=1)
    return out

# ---------------- GitHub：最近 N 天新建、填了 homepage 的仓（作者是个人账号） ----------------
GH_QUERIES = ["topic:ai", "topic:llm", "topic:ai-agent", "topic:chatgpt", "topic:openai", "topic:mcp", "topic:claude",
              "AI in:name,description", "智能 in:description", "大模型 in:description", "助手 in:description"]
# 搜索接口每次 5–6 秒、每个查询最多给 1000 条，所以按天切；--day 指定只拉某一天，几天并行跑（带 token 限 30 次/分，并行别超 3 个）

def src_github():
    hdr = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN: hdr["Authorization"] = f"Bearer {GH_TOKEN}"
    seen, out, nq = {}, [], 0
    stats = {"queries": 0, "repos_seen": 0, "with_homepage": 0}
    only = sys.argv[sys.argv.index("--day") + 1] if "--day" in sys.argv else ""
    days = [datetime.date.fromisoformat(only)] if only else days_between(SINCE, datetime.date.today())
    for d in days:
        for q in GH_QUERIES:
            page = 1
            while page <= 10:
                qs = urllib.parse.quote(f"created:{d.isoformat()} {q}")
                try:
                    data = fetch(f"https://api.github.com/search/repositories?q={qs}&per_page=100&page={page}", headers=hdr)
                except Exception as e:
                    print(f"  [github] {d} {q} p{page} 失败 {e}", file=sys.stderr); break
                stats["queries"] += 1
                items = data.get("items", [])
                for r in items:
                    if r["full_name"] in seen: continue
                    seen[r["full_name"]] = 1; stats["repos_seen"] += 1
                    hp = (r.get("homepage") or "").strip()
                    if not hp: continue
                    if not hp.startswith("http"): hp = "https://" + hp
                    stats["with_homepage"] += 1
                    out.append({"src": "github", "src_name": "GitHub 新仓", "name": r["name"], "url": hp, "source_url": r["html_url"],
                                "author": r["owner"]["login"], "author_url": r["owner"]["html_url"],
                                "author_type": "individual" if r["owner"]["type"] == "User" else "organization",
                                "desc": clean(r.get("description")), "signals": {"stars": r.get("stargazers_count", 0), "forks": r.get("forks_count", 0), "topics": r.get("topics", [])[:8], "language": r.get("language")},
                                "created_at": (r.get("created_at") or "")[:10], "found_at": TODAY, "query": q})
                if len(items) < 100 or data.get("total_count", 0) <= page * 100: break
                page += 1
                time.sleep(2.1)  # 带 token 的搜索限速 30 次/分
            time.sleep(2.1)
        print(f"  [github] {d} 累计仓 {stats['repos_seen']} 有 homepage {stats['with_homepage']}", file=sys.stderr)
    save(f"github-{only}" if only else "github", out, {"source": "https://api.github.com/search/repositories", "stats": stats, "queries": GH_QUERIES})

# ---------------- Show HN：最近 N 天的「我做了」帖（Algolia 公开接口） ----------------
def src_hn():
    ts = int(time.mktime(SINCE.timetuple()))
    out, page = [], 0
    while page < 10:
        d = fetch(f"https://hn.algolia.com/api/v1/search_by_date?tags=show_hn&numericFilters=created_at_i>{ts}&hitsPerPage=1000&page={page}")
        hits = d.get("hits", [])
        for h in hits:
            url = (h.get("url") or "").strip()
            if not url: continue  # 没链接的 Show HN（纯文字）不算网站
            title = re.sub(r"^\s*Show HN:\s*", "", h.get("title") or "", flags=re.I)
            name, _, rest = title.partition(" – ")
            if not rest: name, _, rest = title.partition(" - ")
            if not rest: name, _, rest = title.partition(": ")
            out.append({"src": "hn", "src_name": "Show HN", "name": clean(name, 60) or clean(title, 60), "url": url,
                        "source_url": f"https://news.ycombinator.com/item?id={h['objectID']}", "author": h.get("author"), "author_url": f"https://news.ycombinator.com/user?id={h.get('author')}",
                        "author_type": "individual", "desc": clean(rest or h.get("story_text") or "", 200),
                        "signals": {"points": h.get("points", 0), "comments": h.get("num_comments", 0)}, "created_at": (h.get("created_at") or "")[:10], "found_at": TODAY})
        if page + 1 >= d.get("nbPages", 1): break
        page += 1
    save("hn", out, {"source": "https://hn.algolia.com/api/v1/search_by_date?tags=show_hn"})

# ---------------- Hugging Face Spaces：最近 N 天新建的 Space（走国内镜像接口，正文链接仍指 huggingface.co） ----------------
HF_API = os.environ.get("YEBANG_HF_API", "https://hf-mirror.com")

HF_PAGES = int(os.environ.get("YEBANG_HF_PAGES", "30"))  # 每页 100；HF 一天新建上千个 Space，绝大多数是练手，先只探最新 30 页

def src_hf():
    out, url, n = [], f"{HF_API}/api/spaces?sort=createdAt&direction=-1&limit=100&full=true", 0
    while url and n < HF_PAGES:
        url = re.sub(r"^https://huggingface\.co", HF_API, url)  # 翻页链接指回官方域，改走镜像
        req = urllib.request.Request(url, headers=UA)
        with opener(False).open(req, timeout=60) as resp:
            data = json.loads(resp.read()); link = resp.headers.get("Link", "")
        n += 1
        stop = False
        for s in data:
            created = (s.get("createdAt") or s.get("lastModified") or "")[:10]
            if created and created < SINCE.isoformat(): stop = True; break
            card = s.get("cardData") or {}
            author, sid, sub = s.get("author"), s.get("id"), s.get("subdomain")
            # 网站本体在 <subdomain>.hf.space（Space 没在跑会回 503，正好当「打不开」）；huggingface.co 的页面只当出处
            out.append({"src": "hf", "src_name": "Hugging Face Spaces", "name": clean(card.get("title") or sid.split("/")[-1], 60),
                        "url": f"https://{sub}.hf.space/" if sub else f"https://huggingface.co/spaces/{sid}", "source_url": f"https://huggingface.co/spaces/{sid}",
                        "author": author, "author_url": f"https://huggingface.co/{author}", "author_type": "unknown",
                        "desc": clean(card.get("short_description") or "", 200),
                        "signals": {"likes": s.get("likes", 0), "sdk": card.get("sdk") or s.get("sdk")},
                        "created_at": created, "found_at": TODAY})
        if stop: break
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
        time.sleep(1)
    save("hf", out, {"source": f"{HF_API}/api/spaces?sort=createdAt", "note": "author_type 在 screen 阶段按 /api/organizations 判"})

# ---------------- V2EX 分享创造：复用 collect.py 已拉的候选 ----------------
def src_v2ex():
    p = os.path.join(ROOT, "data", "cands", f"v2ex-{TODAY}.json")
    if not os.path.exists(p):
        sys.exit("先跑 python3 tools/collect.py v2ex")
    media = re.compile(r"(bilibili\.com|youtube\.com|youtu\.be|mp\.weixin\.qq\.com|zhihu\.com|xiaohongshu\.com|weibo\.com|juejin\.cn|csdn\.net|twitter\.com|x\.com/|douyin\.com|t\.me/|discord\.gg|v2ex\.com|imgur|\.(png|jpe?g|gif|webp|svg)(\?|$))", re.I)
    out = []
    for it in json.load(open(p, encoding="utf-8"))["items"]:
        links = [l for l in (it.get("extra") or {}).get("links", []) if not media.search(l)]
        if not links: continue
        out.append({"src": "v2ex", "src_name": "V2EX 分享创造", "name": clean(it["name"], 80), "url": links[0], "source_url": (it.get("extra") or {}).get("post") or it["url"],
                    "author": it.get("author"), "author_url": it.get("author_url"), "author_type": "individual", "desc": clean(it.get("desc"), 200),
                    "signals": {"views": (it.get("extra") or {}).get("views", 0), "replies": (it.get("extra") or {}).get("replies", it.get("metric", 0))},
                    "created_at": it.get("created_at", ""), "found_at": TODAY})
    save("v2ex", out, {"source": "https://www.v2ex.com/go/create"})

SRC = {"github": src_github, "hn": src_hn, "hf": src_hf, "v2ex": src_v2ex}

if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if a in SRC]
    if not names: sys.exit(__doc__)
    for n in names:
        t0 = time.time()
        try:
            SRC[n]()
        except Exception as e:
            print(f"{n}: 失败 {e!r}", file=sys.stderr)
        print(f"  ({n} 用时 {time.time()-t0:.0f}s)", file=sys.stderr)
