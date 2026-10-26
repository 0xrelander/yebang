#!/usr/bin/env python3
"""野榜排名：data/cands/*-<日期>.json → data/issues/<日期>.json（第 N 期）

用法：python3 tools/rank.py <日期> <期数> [--no-alive]
排法（与 data/method.md 一致，改公式先改那边再改这里）：
 1. 过滤：大厂/平台官方出品不排；中转/代理/倒卖额度不排；境外技能市场只收名字或描述含中文、或按中文平台词搜到的；人工排除名单 data/exclude.txt
 2. 合并：同一技能在多个来源出现按名字归一后合并（去空格/标点/大小写/.skill 后缀），也按 slug 合并
 3. 打分：每个来源内 归一分 = log10(1+该条数值) / log10(1+该来源候选中的最大数值)，野榜分 = 各来源归一分最高值 + 每多出现一个来源加 0.1（最多加 0.3）
 4. 应用榜发布当天逐条打开一次，打不开不排
 5. 创刊号按累计数值排；从第 2 期起主排本周增量（本期数据已留快照）
"""
import json, os, re, sys, math, glob, datetime, urllib.request, urllib.error, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CJK = re.compile(r"[一-鿿]")
PROXY = os.environ.get("YEBANG_PROXY", "")  # 境外站代理，形如 http://host:port；不设则直连

BIG_CO = {"vercel-labs", "vercel", "anthropics", "anthropic", "openai", "google", "googleapis", "microsoft", "larksuite", "lark", "bytedance", "tencent",
          "alibaba", "aliyun", "alibabacloud", "baidu", "huawei", "coze", "workbuddy", "codebuddy", "openclaw", "clawhub", "official", "meta", "aws", "amazon",
          "supabase", "stripe", "cloudflare", "github", "heygen-com", "expo", "n8n-io", "remotion-dev", "mattpocock", "obra", "anthropic-ai", "modelcontextprotocol"}
BIG_CO_RE = re.compile(r"(feishu|lark|tencent|alibaba|aliyun|bytedance|baidu|huawei|apache|microsoft|google|openai|anthropic|vercel|xiaomi|jd\.com|meituan|netease|kuaishou|bilibili-official)", re.I)
MEDIA_RE = re.compile(r"(bilibili\.com|youtube\.com|youtu\.be|mp\.weixin\.qq\.com|zhihu\.com|xiaohongshu\.com|weibo\.com|juejin\.cn|csdn\.net|twitter\.com|x\.com/|douyin\.com|t\.me/|discord\.gg|qq\.com/.*group|\.md$|\.(png|jpe?g|gif|webp|svg)(\?|$))", re.I)
RELAY_RE = re.compile(r"(中转|代理|api\s*key\s*池|免费额度|免费\s*api|白嫖|镜像站|翻墙|vpn|机场|key\s*池|额度共享|低价\s*api|倒卖)", re.I)
TOP_N = 20

def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"\.skill$|\s*skill$", "", s)
    s = re.sub(r"[\s\-_·•.。,，:：()（）\[\]【】/\\'\"“”‘’!！?？]+", "", s)
    return s

def load_cands(date):
    items = []
    for p in sorted(glob.glob(os.path.join(DATA, "cands", f"*-{date}.json"))):
        d = json.load(open(p, encoding="utf-8"))
        items += d["items"]
    return items

def tidy(it):
    if it["src"] == "skillssh" and "/" in it["name"]:
        parts = it["name"].split("/")
        it["name"], it["author"] = parts[-1], parts[0]
        it["author_url"] = f"https://github.com/{parts[0]}"
    if it["src"] == "clawhub" and (it["name"].lower().startswith(("description:", "name:")) or len(it["name"]) > 40):
        it["name"] = (it.get("extra") or {}).get("slug") or it["name"][:40]
    return it

def load_exclude():
    ex = {}
    p = os.path.join(DATA, "exclude.txt")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"): continue
            k, _, why = line.partition("\t")
            ex[k.strip()] = why.strip()
    return ex

def passes(it, ex):
    a = (it.get("author") or "").lower()
    if a in BIG_CO or a.startswith("lark-") or a.endswith("-official") or BIG_CO_RE.search(a): return False
    m = re.match(r"https?://github\.com/([^/]+)/", it.get("url") or "")
    if m and (m.group(1).lower() in BIG_CO or BIG_CO_RE.search(m.group(1))): return False
    if it["src"] == "coze" and (it.get("extra") or {}).get("category") in ("角色", "游戏"): return False
    if it["src"] == "v2ex":
        links = [l for l in (it.get("extra") or {}).get("links", []) if not MEDIA_RE.search(l)]
        if not links: return False
        it["url"] = links[0]
    text = f"{it.get('name','')} {it.get('desc','')}"
    if RELAY_RE.search(text): return False
    if it["src"] in ("clawhub", "skillssh"):
        if not (CJK.search(text) or it.get("extra", {}).get("found_by_search")): return False
    if it["src"] == "coze":
        if it["extra"].get("is_official") or it["extra"].get("enterprise_label"): return False
    if it["src"] == "skillssh" and a in BIG_CO: return False
    if it["url"] in ex or norm_name(it["name"]) in ex: return False
    if not it.get("name"): return False
    if (it.get("metric") or 0) <= 0: return False
    return True

def merge(items):
    """按名字归一 / slug 合并；一条同时命中两个组时把两组并成一组（避免顺序造成的分裂）。"""
    groups, key2g = [], {}
    for it in items:
        keys = {norm_name(it["name"])}
        slug = (it.get("extra") or {}).get("slug") or ((it.get("extra") or {}).get("canonical") or "").split("/")[-1]
        if slug: keys.add("slug:" + norm_name(slug))
        hits = sorted({key2g[k] for k in keys if k in key2g})
        if not hits:
            gi = len(groups); groups.append([])
        else:
            gi = hits[0]
            for other in hits[1:]:
                groups[gi] += groups[other]; groups[other] = []
                for k, v in list(key2g.items()):
                    if v == other: key2g[k] = gi
        groups[gi].append(it)
        for k in keys: key2g[k] = gi
    return [g for g in groups if g]

def best_desc(g, lead):
    """skills.sh 只有仓名没有描述，优先用同组里其它来源的真描述（中文优先）。"""
    cands = [it.get("desc", "") for it in [lead] + g if it.get("desc") and not it["desc"].startswith("来自 GitHub 仓")]
    cands.sort(key=lambda d: (0 if CJK.search(d) else 1))
    return cands[0] if cands else lead.get("desc", "")

def score(groups, kind):
    maxes = {}
    for g in groups:
        for it in g:
            maxes[it["src"]] = max(maxes.get(it["src"], 0), it["metric"])
    out = []
    for g in groups:
        best, n_src = None, len({it["src"] for it in g})
        for it in g:
            nrm = math.log10(1 + it["metric"]) / math.log10(1 + maxes[it["src"]])
            if best is None or nrm > best[0]: best = (nrm, it)
        sc = best[0] + min(0.3, 0.1 * (n_src - 1))
        lead = best[1]
        plats = []
        for it in g:
            for p in it.get("platforms", []):
                if p not in plats: plats.append(p)
        srcs = [{"src_name": it["src_name"], "url": it["url"], "metric_label": it["metric_label"], "metric": it["metric"], "author": it["author"]} for it in g]
        out.append({"score": round(sc, 4), "name": lead["name"], "url": lead["url"], "author": lead["author"], "author_url": lead.get("author_url", ""),
                    "platforms": plats, "desc": re.sub(r"\s+", " ", best_desc(g, lead))[:90], "source": lead["src_name"], "source_url": lead["url"],
                    "metric_label": lead["metric_label"], "metric": lead["metric"], "sources": srcs, "created_at": lead.get("created_at", ""),
                    "extra": lead.get("extra", {})})
    out.sort(key=lambda x: (-x["score"], -len(x["sources"]), -x["metric"]))
    return out

TITLE_JUNK = re.compile(r"\s*(?:[-–—|·:：]\s*)?(GitHub|on the App Store|App Store|TestFlight|Join the .* beta|在 App Store 上|TapTap|官网|首页|Home)\s*$", re.I)
def alive(url, proxy):
    """返回 (活着吗, 页面标题)。401/403/405/429 算活着（有防护）。"""
    handlers = [urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})] if (proxy and PROXY) else [urllib.request.ProxyHandler({})]
    op = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36 yebang-alive-check/0.1"})
    try:
        with op.open(req, timeout=25) as r:
            ok = 200 <= r.status < 400
            body = r.read(200000).decode("utf-8", "ignore") if ok else ""
    except urllib.error.HTTPError as e:
        return e.code in (401, 403, 405, 429), ""
    except Exception:
        return False, ""
    m = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.S | re.I)
    title = re.sub(r"\s+", " ", html_unescape(m.group(1))).strip() if m else ""
    g = re.match(r"GitHub - ([^:]+?)(?::.*)?$", title)
    if g: title = g.group(1).strip()
    title = re.sub(r"^[\u200e\u200f\s]*(?:App Store 上的|Mac App Store 上的|(?:iPhone|iPad|Mac)\s*版)\s*[“\"]?(.+?)[”\"]?\s*$", r"\1", title)
    title = re.split(r"\s+[-–—|·]\s+", title)[0].strip()
    title = TITLE_JUNK.sub("", title).strip().strip("“”\"'\u200e\u200f ")
    return ok, title[:40]

def html_unescape(s):
    import html as _h
    return _h.unescape(s)

def clean_post_title(t):
    t = re.sub(r"^\s*[\[【（(][^\]】）)]{1,12}[\]】）)]\s*", "", t)
    t = re.sub(r"^(我|自己|顺手|最近|分享一?个?|做了一?个?|用\s*\S+\s*做了一?个?|开源了?一?个?|上线了?一?个?)+", "", t)
    t = re.split(r"[，,。：:；;（(]|\s+-\s+|\s*[—–]\s*|想听听|求反馈|帮忙看看|欢迎", t)[0]
    return t.strip()[:32] or t[:32]

def main():
    date = sys.argv[1]; issue = int(sys.argv[2]); do_alive = "--no-alive" not in sys.argv
    ex = load_exclude()
    items = [tidy(it) for it in load_cands(date) if passes(it, ex)]
    skills = [it for it in items if it["kind"] == "skill"]
    apps = [it for it in items if it["kind"] == "app"]
    for it in apps:  # V2EX 用浏览数当主数值，回复数留 extra
        if it["src"] == "v2ex" and it["extra"].get("views"):
            it["metric_label"], it["metric"] = "浏览", it["extra"]["views"]
    sk = score(merge(skills), "skill")
    ap = score(merge(apps), "app")
    # 应用榜：发布当天打开一次
    final_apps, checked = [], datetime.date.today().strftime("%m-%d")
    for it in ap:
        if len(final_apps) >= TOP_N: break
        if do_alive:
            ok, title = alive(it["url"], proxy=not re.search(r"coze\.cn|\.cn/|\.cn$", it["url"]))
            if not ok:
                print(f"  [dead] {it['name'][:30]} {it['url']}", file=sys.stderr); continue
            it["alive"], it["checked"] = True, checked
            if it["source"].startswith("V2EX"):
                post_title = it["name"]
                it["name"] = title if (title and 2 <= len(title) <= 40 and not re.search(r"(404|not found|error|登录|login)", title, re.I)) else clean_post_title(post_title)
                it["desc"] = ("帖：" + post_title)[:90]
                it["source_url"] = it["extra"].get("post") or it["url"]
        final_apps.append(it)
        time.sleep(0.3)
    final_skills = sk[:TOP_N]
    for i, it in enumerate(final_skills, 1): it["rank"] = i
    for i, it in enumerate(final_apps, 1): it["rank"] = i
    out = {"issue": issue, "date": date, "period": "", "cutoff": "", "title": "", "note": "", "skills": final_skills, "apps": final_apps,
           "pool": {"skills_candidates": len(skills), "skills_groups": len(sk), "apps_candidates": len(apps), "apps_groups": len(ap),
                    "sources": sorted({it["src_name"] for it in items})}}
    p = os.path.join(DATA, "issues", f"{date}.json")
    existing = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    for k in ("period", "cutoff", "title", "note", "poster_note", "skills_sub", "apps_sub"):
        if existing.get(k): out[k] = existing[k]
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"skills pool {len(skills)} → groups {len(sk)} → top {len(final_skills)}; apps pool {len(apps)} → groups {len(ap)} → top {len(final_apps)}")
    print(p)

if __name__ == "__main__":
    main()
