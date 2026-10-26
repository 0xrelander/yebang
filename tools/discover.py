#!/usr/bin/env python3
"""野榜发现器：去「出生登记处」拉最近 N 天新出生的网站候选，不顺链接爬。

用法：python3 tools/discover.py <登记处> [<登记处>...] [--days 7]
登记处代号：github（新仓 homepage 字段）  hn（Show HN）  hf（Hugging Face Spaces 新建）  v2ex（分享创造，复用 collect.py 的产物）
          devto（#showdev）  juejin（掘金「我做了一个」类帖）  betalist / uneed / indiehackers / microlaunch（海外发布台，走代理）
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

def fetch_raw(url, proxy=False, tries=3, sleep=2.0, headers=None, timeout=45, data=None):
    """返回 (字节, 响应头)。读到一半断线（IncompleteRead）、回包截断也算失败重试。data 给了就是 POST。"""
    last = None
    for t in range(tries):
        try:
            h = dict(UA); h.update(headers or {})
            req = urllib.request.Request(url, headers=h, data=data)
            with opener(proxy).open(req, timeout=timeout) as resp:
                raw = resp.read(); hdrs = resp.headers
            return raw, hdrs
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

def fetch(url, proxy=False, tries=3, sleep=2.0, headers=None, as_json=True, timeout=45, data=None):
    last = None
    for t in range(tries):
        try:
            raw, _ = fetch_raw(url, proxy=proxy, tries=1, sleep=sleep, headers=headers, timeout=timeout, data=data)
            return json.loads(raw) if as_json else raw.decode("utf-8", "ignore")
        except Exception as e:  # 含读一半断线、回包截断的 JSON；限速已在 fetch_raw 里等过
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
              "topic:gemini", "topic:rag", "topic:machine-learning", "topic:generative-ai", "topic:artificial-intelligence",
              "AI in:name,description", "GPT in:name,description", "LLM in:name,description", "chatbot in:name,description",
              "智能 in:description", "大模型 in:description", "助手 in:description", "智能体 in:description"]
# 搜索接口每次 5–6 秒、每个查询最多给 1000 条（10 页 × 100）。一天里光「AI in:name,description」就新建一万八千多个仓，
# 只拿前 1000 等于只看了 5%——所以凡是总数超过 1000 的时段都按创建时刻再切细（created:起..止 支持到秒），切到每段不足 1000 为止。
# --day 指定只拉某一天，几天并行跑（带 token 限 30 次/分，并行别超 3 个）
GH_SLICE_MAX = 900  # 每个时间段最多这么多条才不翻页翻丢；超过就切

def _gh_ts(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")

# 走 GraphQL 而不是 REST 搜索：只要几个字段，一页 100 个仓约 40KB（REST 是 700KB，国内直连老读一半断线），
# 而且不占 REST 搜索那 30 次/分的额度（GraphQL 是每小时 5000 点，一次搜索 1 点）
GH_GQL = """query($q:String!,$after:String){ search(query:$q,type:REPOSITORY,first:100,after:$after){ repositoryCount pageInfo{hasNextPage endCursor}
  nodes{ ... on Repository { name url homepageUrl description createdAt isFork stargazerCount forkCount primaryLanguage{name} owner{login url __typename} repositoryTopics(first:8){nodes{topic{name}}} } } } }"""

def _gh_slice(q, start, end, hdr, seen, out, stats, depth=0):
    """拉 [start, end] 这段时间里匹配 q 的仓；总数超过上限就等分成若干段递归。"""
    rng = f"created:{_gh_ts(start)}..{_gh_ts(end)}"
    page, total, after = 1, None, None
    while page <= 10:
        body = json.dumps({"query": GH_GQL, "variables": {"q": f"{rng} {q}", "after": after}}).encode()
        try:
            data = fetch("https://api.github.com/graphql", headers=hdr, data=body, tries=5, sleep=3.0, timeout=60)
            s = data["data"]["search"]
        except Exception as e:
            stats["lost_pages"] += 1
            print(f"  [github] {rng} {q} p{page} 失败 {str(e)[:120]}（这页丢了）", file=sys.stderr)
            if page == 1 or total is None: return  # 第一页都拿不到，这段没法分页，整段记为丢失
            break  # 游标断了接不上，后面的页只能放弃
        stats["queries"] += 1
        total = s.get("repositoryCount", 0)
        if page == 1 and total > GH_SLICE_MAX and (end - start) >= datetime.timedelta(minutes=10):
            k = min(24, -(-total // (GH_SLICE_MAX * 2 // 3)))  # 按每段约 600 条估分几段，留余量
            step = (end - start) / k
            stats["slices"] += k
            for i in range(k):
                a = start + step * i
                b = end if i == k - 1 else start + step * (i + 1) - datetime.timedelta(seconds=1)
                time.sleep(0.5)
                _gh_slice(q, a, b, hdr, seen, out, stats, depth + 1)
            return
        nodes = [n for n in (s.get("nodes") or []) if n]
        for r in nodes:
            if r["url"] in seen: continue
            seen[r["url"]] = 1; stats["repos_seen"] += 1
            if r.get("isFork"): continue  # fork 来的仓，homepage 多半是原作者的站，不算这人新出生的
            hp = (r.get("homepageUrl") or "").strip()
            if not hp: continue
            if not hp.startswith("http"): hp = "https://" + hp
            stats["with_homepage"] += 1
            ow = r.get("owner") or {}
            out.append({"src": "github", "src_name": "GitHub 新仓", "name": r["name"], "url": hp, "source_url": r["url"],
                        "author": ow.get("login"), "author_url": ow.get("url"),
                        "author_type": "individual" if ow.get("__typename") == "User" else "organization",
                        "desc": clean(r.get("description")), "signals": {"stars": r.get("stargazerCount", 0), "forks": r.get("forkCount", 0),
                                                                        "topics": [t["topic"]["name"] for t in ((r.get("repositoryTopics") or {}).get("nodes") or []) if t.get("topic")][:8],
                                                                        "language": (r.get("primaryLanguage") or {}).get("name")},
                        "created_at": (r.get("createdAt") or "")[:10], "found_at": TODAY, "query": q})
        pi = s.get("pageInfo") or {}
        if not pi.get("hasNextPage") or len(nodes) < 100: break
        after = pi.get("endCursor"); page += 1
        time.sleep(0.5)

def src_github():
    if not GH_TOKEN: sys.exit("GraphQL 搜索必须带 token：export GITHUB_TOKEN=$(gh auth token)")
    hdr = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {GH_TOKEN}"}
    seen, out = {}, []
    stats = {"queries": 0, "slices": 0, "lost_pages": 0, "repos_seen": 0, "with_homepage": 0}
    only = sys.argv[sys.argv.index("--day") + 1] if "--day" in sys.argv else ""
    days = [datetime.date.fromisoformat(only)] if only else days_between(SINCE, datetime.date.today())
    for d in days:
        day0 = datetime.datetime(d.year, d.month, d.day)
        for q in GH_QUERIES:
            _gh_slice(q, day0, day0 + datetime.timedelta(hours=23, minutes=59, seconds=59), hdr, seen, out, stats)
            time.sleep(0.5)
            print(f"  [github] {d} {q}: 累计仓 {stats['repos_seen']} 有 homepage {stats['with_homepage']} 请求 {stats['queries']} 切段 {stats['slices']}", file=sys.stderr)
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
        data = None
        for t in range(4):  # 镜像偶尔回半截 JSON，整页重拉
            try:
                raw, hdrs = fetch_raw(url, proxy=False, tries=2, sleep=3.0, timeout=60)
                data = json.loads(raw); link = hdrs.get("Link", ""); break
            except Exception as e:
                print(f"  [hf] 第 {n + 1} 页失败 {e}，重试", file=sys.stderr); time.sleep(3 * (t + 1))
        if data is None:
            # 半途断了：比盘上已有的那份多才落盘，否则别拿残缺的盖掉完整的
            p = os.path.join(FOUND, f"hf-{TODAY}.json")
            have = len(json.load(open(p, encoding="utf-8")).get("items", [])) if os.path.exists(p) else 0
            print(f"  [hf] 第 {n + 1} 页连续失败，到此为止（已拉 {len(out)} 条，盘上 {have} 条）", file=sys.stderr)
            if len(out) <= have: raise RuntimeError(f"HF 只拉到 {len(out)} 条，不如盘上的 {have} 条，不覆盖")
            break
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

# ---------------- 共用：从一段帖子正文里挑出「像作品网站」的第一个链接 ----------------
# 不算作品本体的链接：代码托管、社区、视频、商店、打赏、文档、图片……（筛选阶段 screen.py 还会再按 JUNK_HOST 过一遍）
NOT_SITE = re.compile(r"(github\.com|gitlab\.com|gitee\.com|dev\.to|juejin\.cn|youtube|youtu\.be|vimeo\.com|bilibili\.com|twitter\.com|x\.com/|linkedin\.com|medium\.com|reddit\.com|producthunt\.com|news\.ycombinator|discord\.(gg|com)|t\.me/|npmjs\.com|pypi\.org|crates\.io|huggingface\.co|hf\.co|apps\.apple\.com|play\.google\.com|chromewebstore|chrome\.google\.com|microsoft\.com|marketplace\.visualstudio|buymeacoffee|ko-fi|patreon|gumroad|substack|notion\.(site|so)|docs\.google|forms\.gle|bit\.ly|mp\.weixin|zhihu\.com|csdn\.net|xiaohongshu|weibo\.com|douyin|wikipedia|stackoverflow|unsplash|imgur|giphy|shields\.io|img\.shields|badge|vercel\.com|netlify\.com|cloudflare\.com|openai\.com|anthropic\.com|google\.com|amazon\.|apple\.com|meta\.com|facebook\.com|instagram\.com|tiktok\.com|threads\.net|mastodon|bsky\.app|loom\.com|figma\.com|canva\.com|calendly|typeform|tally\.so|airtable|\.(png|jpe?g|gif|webp|svg|mp4|mov|pdf|zip)(\?|$))", re.I)

def first_site_link(text):
    for u in re.findall(r"https?://[^\s<>\"'()\[\]（）]+", text or ""):
        u = u.rstrip(".,;:!?。，、")
        if NOT_SITE.search(u) or len(u) > 200: continue
        return u
    return None

def _location(url, proxy=True):
    """只看这个地址把人跳去哪（发布台的「访问网站」按钮都是跳转链）。"""
    class NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    hs = [urllib.request.ProxyHandler({"http": PROXY, "https": PROXY} if (proxy and PROXY) else {}), NoRedir()]
    try:
        urllib.request.build_opener(*hs).open(urllib.request.Request(url, headers=UA), timeout=30)
    except urllib.error.HTTPError as e:
        return e.headers.get("Location")
    except Exception:
        return None
    return None

def _title(h):
    m = re.search(r"<title[^>]*>(.*?)</title>", h or "", re.S)
    return clean(re.split(r"\s[|–\-—]\s", html.unescape(m.group(1)))[0], 80) if m else ""

def _meta_desc(h):
    m = re.search(r'<meta\s+(?:name|property)="(?:description|og:description)"\s+content="([^"]*)"', h or "", re.I) or \
        re.search(r'<meta\s+content="([^"]*)"\s+(?:name|property)="(?:description|og:description)"', h or "", re.I)
    return clean(html.unescape(m.group(1)), 200) if m else ""

# ---------------- dev.to #showdev：最近 N 天「我做了」帖（公开接口，直连） ----------------
def src_devto():
    out, page, n_art = [], 1, 0
    while page <= 15:
        arts = fetch(f"https://dev.to/api/articles?tag=showdev&per_page=100&page={page}")
        if not arts: break
        stop = False
        for a in arts:
            day = (a.get("published_at") or "")[:10]
            if day < SINCE.isoformat(): stop = True; break
            n_art += 1
            try:
                full = fetch(f"https://dev.to/api/articles/{a['id']}")
            except Exception:
                continue
            url = first_site_link(full.get("body_markdown") or "")
            if not url:
                cu = a.get("canonical_url") or ""
                url = cu if cu and "dev.to" not in cu and not NOT_SITE.search(cu) else None
            if not url: continue
            u = a.get("user") or {}
            out.append({"src": "devto", "src_name": "dev.to #showdev", "name": clean(a.get("title"), 80), "url": url, "source_url": a.get("url"),
                        "author": u.get("username"), "author_url": f"https://dev.to/{u.get('username')}",
                        "author_type": "organization" if a.get("organization") else "individual", "desc": clean(a.get("description"), 200),
                        "signals": {"reactions": a.get("public_reactions_count", 0), "comments": a.get("comments_count", 0)}, "created_at": day, "found_at": TODAY})
            time.sleep(0.3)
        if stop: break
        page += 1
    print(f"  [devto] 近 {DAYS} 天 showdev 帖 {n_art}，带作品链接 {len(out)}", file=sys.stderr)
    save("devto", out, {"source": "https://dev.to/api/articles?tag=showdev", "articles": n_art})

# ---------------- 掘金：搜「我做了一个 / 上线了 / 独立开发」这类帖，按最新排，取正文里的作品链接（公开接口，直连） ----------------
JJ_QUERIES = ["我做了一个", "我做了个", "做了个工具", "做了个网站", "上线了", "独立开发", "开源了一个", "AI 工具 上线", "vibe coding", "一个人做了"]

def src_juejin():
    base, common = "https://api.juejin.cn", "aid=2608&uuid=7000000000000000000&spider=0"
    since = int(time.mktime(SINCE.timetuple()))
    seen, out, n_art = {}, [], 0
    for q in JJ_QUERIES:
        cursor = "0"
        for _ in range(5):
            try:
                d = fetch(f"{base}/search_api/v1/search?{common}&query={urllib.parse.quote(q)}&id_type=0&cursor={cursor}&limit=20&search_type=2&sort_type=1")
            except Exception as e:
                print(f"  [juejin] {q} 失败 {e}", file=sys.stderr); break
            rows, fresh = d.get("data") or [], 0
            for r in rows:
                rm = r.get("result_model") or {}
                ai, au = rm.get("article_info") or {}, rm.get("author_user_info") or {}
                aid = ai.get("article_id")
                if not aid or aid in seen or int(ai.get("ctime") or 0) < since: continue
                seen[aid] = 1; fresh += 1; n_art += 1
                try:
                    det = fetch(f"{base}/content_api/v1/article/detail?{common}", headers={"Content-Type": "application/json"},
                                data=json.dumps({"article_id": aid, "client_type": 2608, "forbid_cache_time": 0, "need_theme": False}).encode())
                    mc = ((det.get("data") or {}).get("article_info") or {}).get("mark_content") or ""
                except Exception:
                    mc = ""
                url = first_site_link(mc) or first_site_link(ai.get("brief_content"))
                if not url: continue
                out.append({"src": "juejin", "src_name": "掘金", "name": clean(ai.get("title"), 80), "url": url, "source_url": f"https://juejin.cn/post/{aid}",
                            "author": au.get("user_name"), "author_url": f"https://juejin.cn/user/{au.get('user_id')}", "author_type": "individual",
                            "desc": clean(ai.get("brief_content"), 200), "signals": {"views": ai.get("view_count", 0), "diggs": ai.get("digg_count", 0)},
                            "created_at": datetime.date.fromtimestamp(int(ai["ctime"])).isoformat(), "found_at": TODAY, "query": q})
                time.sleep(0.5)
            if not d.get("has_more") or fresh == 0: break
            cursor = str(d.get("cursor") or int(cursor) + 20)
            time.sleep(1)
    print(f"  [juejin] 近 {DAYS} 天命中帖 {n_art}，带作品链接 {len(out)}", file=sys.stderr)
    save("juejin", out, {"source": "https://api.juejin.cn/search_api/v1/search", "queries": JJ_QUERIES, "articles": n_art})

# ---------------- 海外发布台：BetaList / Uneed / Indie Hackers / Microlaunch（公开页，走代理） ----------------
# 这些台子本身就是「个人把新站登记出来」的地方；台子不标作者是不是个人，作者这道门只剩大厂名单能拦，方法页写明了
def _launch_item(src, src_name, name, url, source_url, desc, created=None, author=None):
    name = re.split(r":\s|\s[|–—]\s", name or "")[0]  # 发布台标题多是「名字: 一句话」，只留名字
    return {"src": src, "src_name": src_name, "name": clean(name, 80) or url, "url": url, "source_url": source_url, "author": author, "author_url": None,
            "author_type": "unknown", "desc": clean(desc, 200), "signals": {}, "created_at": created or TODAY, "found_at": TODAY}

def src_betalist():
    out, seen = [], {}
    for page in (1, 2):
        h = fetch(f"https://betalist.com/?page={page}", proxy=True, as_json=False)
        for slug in dict.fromkeys(re.findall(r'href="/startups/([^"/]+)"', h)):
            if slug in seen: continue
            seen[slug] = 1
            loc = _location(f"https://betalist.com/startups/{slug}/visit")
            if not loc or not loc.startswith("http"): continue
            url = re.sub(r"([?&])ref=betalist(&|$)", lambda m: m.group(1) if m.group(2) else "", loc).rstrip("?&")
            try:
                sp = fetch(f"https://betalist.com/startups/{slug}", proxy=True, as_json=False)
            except Exception:
                sp = ""
            m = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', sp)
            out.append(_launch_item("betalist", "BetaList", _title(sp) or slug, url, f"https://betalist.com/startups/{slug}", _meta_desc(sp), m.group(1) if m else None))
            time.sleep(1)
    save("betalist", out, {"source": "https://betalist.com/"})

def src_uneed():
    out = []
    h = fetch("https://www.uneed.best/", proxy=True, as_json=False)
    for slug in dict.fromkeys(re.findall(r'href="/tool/([^"/]+)"', h)):
        try:
            sp = fetch(f"https://www.uneed.best/tool/{slug}", proxy=True, as_json=False)
        except Exception:
            continue
        # 「访问网站」按钮带 ref=uneed.best；没有就退回页面里第一个像作品的外链
        m = re.search(r'(https?://[^"\'\s\\&?]+)[^"\'\s\\]*ref=uneed', sp)
        urls = [m.group(1)] if m else [u for u in dict.fromkeys(re.findall(r'https?://[^\s"\'<>\\]+', sp))
                if not re.search(r"uneed|klibon|creem\.io|stripe|lemonsqueezy|cloudflareinsights|fonts|cdn|w3\.org|schema\.org|gstatic|nuxt|unpkg|jsdelivr|supabase|googleapis|googleusercontent|cloudfront|\.(js|css|png|jpe?g|svg|webp|ico)(\?|$)", u) and not NOT_SITE.search(u)]
        if not urls: continue
        out.append(_launch_item("uneed", "Uneed", _title(sp) or slug, urls[0].rstrip("/") + "/", f"https://www.uneed.best/tool/{slug}", _meta_desc(sp)))
        time.sleep(1)
    save("uneed", out, {"source": "https://www.uneed.best/"})

def src_indiehackers():
    out = []
    h = fetch("https://www.indiehackers.com/products?sorting=newest", proxy=True, as_json=False)
    for slug in dict.fromkeys(re.findall(r'href="/product/([^"?#/]+)', h)):
        try:
            sp = fetch(f"https://www.indiehackers.com/product/{slug}", proxy=True, as_json=False)
        except Exception:
            continue
        urls = [u for u in dict.fromkeys(re.findall(r'href="(https?://[^"]+)"', sp)) if not re.search(r"indiehackers", u) and not NOT_SITE.search(u)]
        if not urls: continue
        out.append(_launch_item("indiehackers", "Indie Hackers", _title(sp) or slug, urls[0], f"https://www.indiehackers.com/product/{slug}", _meta_desc(sp)))
        time.sleep(1)
    save("indiehackers", out, {"source": "https://www.indiehackers.com/products?sorting=newest"})

def src_microlaunch():
    out, seen = [], {}
    for page in (1, 2, 3):
        try:
            h = fetch(f"https://microlaunch.net/?page={page}", proxy=True, as_json=False)
        except Exception:
            break
        sites = [s.replace("\\u0026", "&").split("&")[0] for s in re.findall(r'url=(https?://[^&"\\\s]+)', h)]
        new = [s for s in dict.fromkeys(sites) if s not in seen]
        if not new: break
        for s in new:
            seen[s] = 1
            host = urllib.parse.urlparse(s).netloc
            out.append(_launch_item("microlaunch", "Microlaunch", host, s.rstrip("/") + "/", "https://microlaunch.net/", ""))
        time.sleep(1)
    save("microlaunch", out, {"source": "https://microlaunch.net/", "note": "页面只给站点域名（favicon 参数），名字和简介靠筛选阶段打开网站取"})

SRC = {"github": src_github, "hn": src_hn, "hf": src_hf, "v2ex": src_v2ex, "devto": src_devto, "juejin": src_juejin,
       "betalist": src_betalist, "uneed": src_uneed, "indiehackers": src_indiehackers, "microlaunch": src_microlaunch}

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
