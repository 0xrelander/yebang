#!/usr/bin/env python3
"""野榜筛选器：data/found/*-<日期>.json → data/screened/<日期>.json

用法：python3 tools/screen.py <日期> [--threads 16] [--limit N]
做四件事（和 data/method.md 一致，改规则先改那边再改这里）：
 1. 去重与去杂：同一网址只留一条（多个登记处都见到的合并）；网址指向仓库页、文档页、应用商店、社交帖、打赏页、大厂域名的，不算「网站」
 2. 野生门：作者必须是个人账号（GitHub owner type=User；Hugging Face /api/users 查得到；HN、V2EX 发帖人天然是个人）；大厂与官方账号不收；中转/代理/倒卖额度不收
 3. 当天逐条打开：打不开不收；记页面标题、描述、有没有可操作的界面（输入框/按钮/表单/单页应用壳）
 4. 归行业、归语言，算一个「初筛分」只用来排搜索结果和给编辑挑样本，不是榜
零依赖。境外站先直连，失败再走 YEBANG_PROXY。
"""
import json, os, re, sys, glob, html, time, datetime, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PROXY = os.environ.get("YEBANG_PROXY", "")
HF_API = os.environ.get("YEBANG_HF_API", "https://hf-mirror.com")
CJK = re.compile(r"[一-鿿]")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 yebang-alive-check/0.2 (+https://github.com/0xrelander/yebang)"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rank import BIG_CO, BIG_CO_RE, RELAY_RE, TITLE_JUNK  # 复用创刊号的名单与规则

# 这些网址不是「一个能打开用的网站」：仓库页 / 包管理页 / 文档 / 商店 / 社交帖 / 打赏页 / 大厂产品
JUNK_HOST = re.compile(r"(^|\.)(github\.com|gitlab\.com|bitbucket\.org|gitee\.com|codeberg\.org|sourceforge\.net|npmjs\.com|pypi\.org|crates\.io|pkg\.go\.dev|rubygems\.org|nuget\.org|"
                       r"marketplace\.visualstudio\.com|open-vsx\.org|chrome\.google\.com|chromewebstore\.google\.com|addons\.mozilla\.org|apps\.apple\.com|play\.google\.com|testflight\.apple\.com|"
                       r"t\.me|discord\.(gg|com)|twitter\.com|x\.com|youtube\.com|youtu\.be|bilibili\.com|weibo\.com|zhihu\.com|xiaohongshu\.com|douyin\.com|tiktok\.com|instagram\.com|facebook\.com|linkedin\.com|reddit\.com|"
                       r"medium\.com|substack\.com|mp\.weixin\.qq\.com|juejin\.cn|csdn\.net|cnblogs\.com|dev\.to|hashnode\.dev|news\.ycombinator\.com|producthunt\.com|v2ex\.com|"
                       r"ko-fi\.com|patreon\.com|buymeacoffee\.com|afdian\.(com|net)|mbd\.pub|opencollective\.com|"
                       r"readthedocs\.io|readthedocs\.org|notion\.site|notion\.so|docs\.google\.com|forms\.gle|arxiv\.org|doi\.org|wikipedia\.org|"
                       r"openai\.com|chatgpt\.com|anthropic\.com|claude\.ai|perplexity\.ai|google\.com|microsoft\.com|apple\.com|amazon\.com|aws\.amazon\.com|vercel\.com|netlify\.com|cloudflare\.com|"
                       r"huggingface\.co/(datasets|models|papers|blog)|modelscope\.cn/(models|datasets)|coze\.(cn|com)|deepseek\.com|moonshot\.cn|aliyun\.com|tencent\.com|baidu\.com|bytedance\.com|feishu\.cn|larksuite\.com|dingtalk\.com|"
                       r"localhost|127\.0\.0\.1|example\.com)(/|$|:)", re.I)
JUNK_PATH = re.compile(r"(^/docs?(/|$)|/wiki(/|$)|/blog/|\.(pdf|md|zip|tar\.gz|dmg|exe|apk|ipa)(\?|$))", re.I)
DOC_SITE = re.compile(r"(docusaurus|mkdocs|vitepress|docsify|sphinx|gitbook|mintlify|readme\.io|\bdocs?\b.*\|)", re.I)
UI_RE = re.compile(r"<(input|textarea|select|form|button)\b|id=[\"'](root|app|__next|__nuxt|q-app|svelte|__layout)[\"']|<(canvas|video|audio)\b|data-reactroot|ng-version|<streamlit|gradio", re.I)
LOGIN_RE = re.compile(r"(sign in|log ?in|登录|登陆|注册后|wechat login|请先登录)", re.I)
PLACEHOLDER_RE = re.compile(r"(coming soon|under construction|site not found|deployment not found|project not found|this site can.t be reached|domain (is )?for sale|parked|敬请期待|正在建设|建设中|域名出售|site is under)", re.I)

INDUSTRIES = [  # 顺序即优先级：前面的行业词先命中
    ("金融投研", r"(stock|股票|股市|a股|美股|港股|trading|trader|交易|投研|基金|fund|crypto|比特币|bitcoin|defi|web3|量化|quant|finance|financ|投资|invest|portfolio|财报|earnings|期权|options|forex|外汇|券商|k线|candlestick|估值|valuation|税|tax|记账|budget|理财|wealth|保险|insurance|贷款|loan|mortgage|房贷|会计|accounting|发票|invoice)"),
    ("医疗健康", r"(health|医疗|医生|医院|诊断|diagnos|病历|clinic|患者|patient|药|pharma|drug|健康|fitness|健身|workout|睡眠|sleep|饮食|diet|营养|nutrition|calorie|卡路里|therapy|心理|mental|meditation|冥想|焦虑|anxiety|symptom|症状|体检|血压|glucose|血糖|怀孕|pregnan|经期|period tracker)"),
    ("法律合规", r"(legal|law\b|lawyer|律师|法律|法规|合同|contract|compliance|合规|judg|判决|诉讼|litigation|专利|patent|商标|trademark|隐私政策|privacy policy|terms of service|gdpr)"),
    ("教育学习", r"(education|edu\b|学习|learn|学生|student|teacher|老师|课程|course|考研|考试|exam|quiz|高考|雅思|托福|ielts|toefl|英语|english learn|vocabulary|单词|flashcard|anki|tutor|家教|作业|homework|题库|讲解|lecture|k12|幼儿|kids learn|儿童|数学|math\b|physics|chemistry|language learning|日语|韩语|法语|西班牙语)"),
    ("电商营销", r"(e-?commerce|电商|淘宝|天猫|京东|拼多多|shopify|amazon seller|亚马逊|跨境|dropship|marketing|营销|seo\b|广告|ads\b|投放|文案|copywrit|landing page|落地页|crm|客户|lead gen|线索|小红书运营|直播|带货|选品|listing|product description|商品描述|email campaign|newsletter|投标|招标|标书|采购|tender|procurement|b2b|销售|sales|获客|商机)"),
    ("内容创作", r"(writing|写作|小说|novel|fiction|剧本|script|storytell|故事|博客|blog|公众号|文章|article|video|视频|剪辑|edit video|播客|podcast|字幕|subtitle|配音|voice|tts|text.to.speech|语音合成|图片生成|image gen|text.to.image|绘画|drawing|漫画|comic|manga|meme|表情包|thumbnail|封面|youtube|tiktok|短视频|音乐|music|歌|song|lyrics|作曲|beat|photo|照片|修图|retouch|壁纸|wallpaper|头像|avatar|音效|sound|audio|音频|录音|transcri|转写)"),
    ("设计创意", r"(design|设计|figma|ui\b|ux\b|logo|icon|图标|配色|color palette|palette|字体|font|typograph|海报|poster|排版|layout|mockup|原型|prototype|3d|three\.js|blender|渲染|render|建筑|architect|室内|interior|家装|svg|illustrat|插画)"),
    ("开发工具", r"(developer|开发者|程序员|coding|代码|code review|codegen|api\b|sdk|cli\b|terminal|shell|git\b|github|debug|deploy|devops|docker|kubernetes|k8s|database|sql|数据库|regex|json|yaml|cron|log\b|logging|monitor|监控|测试|testing|playwright|selenium|爬虫|scrap|crawler|浏览器插件|extension|vscode|ide\b|mcp server|mcp\b|prompt|提示词|rag\b|embedding|vector|向量|llm ops|fine-?tun|微调|agent framework|workflow|自动化|automation|n8n|zapier|webhook|open ?source|开源|self-?host|自部署|本地部署|local model|ollama)"),
    ("办公效率", r"(productivity|效率|note|笔记|todo|to-do|task|任务|calendar|日程|日历|schedule|meeting|会议|纪要|minutes|邮件|email|gmail|outlook|pdf|excel|spreadsheet|表格|ppt|slides|演示|文档|document|summar|总结|摘要|翻译|translat|简历|resume|cv\b|面试|interview|求职|job|招聘|hiring|recruit|okr|kanban|看板|知识库|knowledge base|second brain|读书|reading|rss|信息流|聊天记录|wechat|微信|飞书|钉钉|slack|notion)"),
    ("生活服务", r"(travel|旅行|旅游|行程|itinerary|酒店|hotel|flight|机票|recipe|菜谱|食谱|cooking|做饭|餐厅|restaurant|外卖|pet|宠物|猫|狗|vet\b|veterinar|home|家居|装修|购物|shopping|比价|price|优惠|coupon|占星|astrolog|塔罗|tarot|星座|horoscope|八字|命理|风水|恋爱|dating|相亲|育儿|parent|宝宝|baby|婚礼|wedding|礼物|gift|天气|weather|地图|map|交通|出行|租房|rent|买房|real estate|房产|车|car\b|驾考|驾照|穿搭|outfit|fashion|美妆|skincare|护肤|园艺|garden|植物|plant)"),
    ("游戏娱乐", r"(game|游戏|play\b|puzzle|解谜|wordle|猜|chess|象棋|围棋|go\b.*game|扑克|poker|麻将|桌游|board game|trivia|roleplay|角色扮演|rpg|dnd|companion|陪伴|陪聊|虚拟男友|虚拟女友|waifu|anime|二次元|cosplay|小说推|剧|drama|电影|movie|film|追番|番剧|娱乐|entertain|趣味|fun\b|quiz game|tarot game|模拟器|simulat)"),
    ("科研学术", r"(research|科研|paper|论文|arxiv|文献|literature|citation|引用|academic|学术|scholar|实验|experiment|dataset|数据集|benchmark|统计|statistic|生物|bio|基因|gene|protein|蛋白|化学|chem|物理|physics|天文|astro|气候|climate|地理|gis|遥感|材料|material|数学证明|theorem|latex|overleaf|conference|期刊|journal|peer review|审稿)"),
]
def _compile(pattern):
    """英文词加词边界（script 不再命中 TypeScript），中文词原样；命中按个数计。"""
    terms = pattern[1:-1].split("|")
    parts = []
    for t in terms:
        if CJK.search(t) or "\\." in t or ".*" in t: parts.append(t); continue
        exact = t.endswith("\\b")  # 写了 \b 的词只认整词（ui、api、go），没写的允许后缀（translat → translator/translation）
        core = t.replace("\\b", "")
        parts.append(r"\b" + core + ("" if exact else r"\w*") + r"\b")
    return re.compile("|".join(parts), re.I)
INDUSTRY_RE = [(n, _compile(p)) for n, p in INDUSTRIES]

def norm_url(u):
    u = (u or "").strip()
    if not u: return ""
    if not re.match(r"^https?://", u): u = "https://" + u
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return ""
    host = p.netloc.lower()
    if host.startswith("www."): host = host[4:]
    q = [kv for kv in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not kv[0].lower().startswith(("utm_", "ref", "source", "fbclid", "gclid"))]
    path = re.sub(r"/+$", "", p.path) or ""
    return urllib.parse.urlunsplit((p.scheme.lower() or "https", host, path, urllib.parse.urlencode(q), ""))

GENERIC_NAME = re.compile(r"^(my[\s_-]*(model|app|space|site|project|website|portfolio|test)|test\d*|testing|demo\d*|sample|example|untitled|new[\s_-]*(space|app|project)|webapp|web[\s_-]*app|app\d*|space\d*|project\d*|hello[\s_-]*world|first[\s_-]*(space|app)|template|starter|playground|练习|测试|demo|示例|我的\S{0,4})$", re.I)

def is_generic_name(name):
    n = re.sub(r"[\s_\-]+", " ", (name or "").strip().lower())
    return bool(GENERIC_NAME.match(n)) or len(n) < 2

def is_junk_url(u, src_url=""):
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return "坏网址"
    host, path = p.netloc.lower(), p.path or "/"
    if not host or "." not in host: return "坏网址"
    if JUNK_HOST.search(host + path): return "不是独立网站（仓库/文档/商店/社交/大厂域）"
    if JUNK_PATH.search(path): return "文档/下载页"
    if src_url and norm_url(src_url) == norm_url(u): return "主页就是仓库页"
    return ""

def is_big_co(author, url):
    a = (author or "").lower()
    if a in BIG_CO or a.startswith("lark-") or a.endswith("-official") or BIG_CO_RE.search(a): return True
    return False

def is_domestic(u):
    return bool(re.search(r"\.(cn|com\.cn|net\.cn)(/|$|:)|gitee|coze|aliyun|tencent|bilibili|zhihu|xiaohongshu|feishu|qq\.com|163\.com|baidu|huggingface", u, re.I))

def http_get(u, proxy, timeout):
    handlers = [urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})] if (proxy and PROXY) else [urllib.request.ProxyHandler({})]
    op = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    with op.open(req, timeout=timeout) as r:
        return r.status, r.geturl(), r.read(400000).decode("utf-8", "ignore"), r.headers.get("Content-Type", "")

def alive(u):
    """返回 dict(ok, status, final_url, title, meta, has_ui, login_wall, body_len, via)"""
    out = {"ok": False, "status": 0, "final_url": u, "title": "", "meta": "", "has_ui": False, "login_wall": False, "body_len": 0, "via": "direct", "lang_hint": ""}
    attempts = [(False, 15)] if (is_domestic(u) or not PROXY) else [(False, 12), (True, 20)]
    last_err = None
    for proxy, to in attempts:
        try:
            st, fu, body, ctype = http_get(u, proxy, to)
            out.update(status=st, final_url=fu, via="proxy" if proxy else "direct", body_len=len(body))
            if "json" in ctype and "html" not in ctype:
                out["ok"] = True; out["title"] = "(JSON 接口)"; return out
            out["ok"] = 200 <= st < 400
            m = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.S | re.I)
            title = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""
            head = re.split(r"\s+[-–—|·:]\s+", title)[0].strip()
            title = head if len(head) >= 2 else title
            out["title"] = TITLE_JUNK.sub("", title).strip()[:60]
            m = re.search(r'<meta[^>]+(?:name=["\']description["\']|property=["\']og:description["\'])[^>]+content=["\']([^"\']{3,300})', body, flags=re.I) or \
                re.search(r'<meta[^>]+content=["\']([^"\']{3,300})["\'][^>]+(?:name=["\']description["\']|property=["\']og:description["\'])', body, flags=re.I)
            out["meta"] = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()[:200] if m else ""
            out["has_ui"] = bool(UI_RE.search(body))
            out["login_wall"] = bool(LOGIN_RE.search(out["title"])) and not out["has_ui"]
            lm = re.search(r"<html[^>]+lang=[\"']?([a-zA-Z-]+)", body)
            out["lang_hint"] = (lm.group(1).lower() if lm else "")
            if PLACEHOLDER_RE.search(out["title"] + " " + body[:3000]) and out["body_len"] < 20000: out["ok"] = False; out["title"] = out["title"] or "(占位页)"
            if out["ok"] and out["body_len"] < 300 and not out["has_ui"]: out["ok"] = False  # 空壳
            return out
        except urllib.error.HTTPError as e:
            out["status"] = e.code
            if e.code in (401, 403, 405, 429):  # 有防护也算活着
                out["ok"] = True; out["title"] = out["title"] or f"(HTTP {e.code} 有防护)"; return out
            last_err = e
        except Exception as e:
            last_err = e
    return out

def classify(text):
    """命中不同关键词最多的行业胜出；同数按列表顺序。一个词都没命中 = 其他。"""
    best, best_n = "其他", 0
    for name, rx in INDUSTRY_RE:
        n = len({m.group(0).lower() for m in rx.finditer(text)})
        if n > best_n: best, best_n = name, n
    return best

def lang_of(it, a):
    t = " ".join([it.get("name", ""), it.get("desc", ""), a.get("title", ""), a.get("meta", "")])
    if CJK.search(t) or a.get("lang_hint", "").startswith("zh"): return "zh"
    return "en"

def pick_name(it, a):
    """GitHub 仓名多是 slug，页面标题更像作品名；标题太泛或太长就回退。"""
    t = (a.get("title") or "").strip()
    head = re.split(r":\s|\s[|–—]\s", t)[0].strip()  # 「名字: 一句话」只留名字
    if 2 <= len(head) <= 30 and len(head) < len(t): t = head
    bad = re.search(r"(404|not found|error|just a moment|attention required|login|sign in|登录|vercel|netlify|streamlit$|gradio$|^\(|index|home$|首页|untitled|react app|vite \+|create next app|document$)", t, re.I)
    if t and 2 <= len(t) <= 40 and not bad: return t
    return it["name"]

def traction(it):
    s = it.get("signals") or {}
    return (s.get("stars", 0) or 0) >= 3 or (s.get("points", 0) or 0) >= 3 or (s.get("likes", 0) or 0) >= 2 or (s.get("replies", 0) or 0) >= 3 or (s.get("views", 0) or 0) >= 500

def hf_is_user(author, cache={}):
    if author in cache: return cache[author]
    try:
        _ = http_get(f"{HF_API}/api/users/{urllib.parse.quote(author)}/overview", False, 15)
        cache[author] = True
    except urllib.error.HTTPError as e:
        cache[author] = False if e.code == 404 else None
    except Exception:
        cache[author] = None
    return cache[author]

def main():
    date = sys.argv[1]
    threads = int(sys.argv[sys.argv.index("--threads") + 1]) if "--threads" in sys.argv else 16
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    stats, by_url = {}, {}
    for p in sorted(glob.glob(os.path.join(DATA, "found", f"*-{date}.json"))):
        for t in range(3):  # 登记处脚本可能正在并行写这个文件，读到半截就等一下再读
            try:
                d = json.load(open(p, encoding="utf-8")); break
            except json.JSONDecodeError:
                time.sleep(2); d = {"items": []}
        print(f"  {os.path.basename(p)}: {len(d['items'])} 条", file=sys.stderr)
        for it in d["items"]:
            st = stats.setdefault(it["src_name"], {"候选": 0, "网址不算网站": 0, "非个人或大厂": 0, "中转代理": 0, "打不开": 0, "没有可用界面": 0, "收录": 0})
            st["候选"] += 1
            u = norm_url(it.get("url"))
            why = is_junk_url(u, it.get("source_url"))
            if why or is_generic_name(it.get("name")): st["网址不算网站"] += 1; continue  # 占位名（My Model / test / demo）也不算一个网站
            if is_big_co(it.get("author"), u) or it.get("author_type") == "organization": st["非个人或大厂"] += 1; continue
            if RELAY_RE.search(f"{it.get('name','')} {it.get('desc','')}"): st["中转代理"] += 1; continue
            it["url"] = u
            if u in by_url:
                by_url[u]["also"].append({"src_name": it["src_name"], "source_url": it["source_url"], "signals": it.get("signals")})
            else:
                it["also"] = []; by_url[u] = it
    items = list(by_url.values())
    # Hugging Face 作者是不是个人，查一次（有缓存）
    if limit: items = items[:limit]
    # 同一期里已经打开过的网址不再开第二次：本期检测缓存 + 上一轮已收录的条目（登记处补拉后重筛只查新增）
    cache_p = os.path.join(DATA, "screened", f"alive-cache-{date}.json")
    acache = json.load(open(cache_p, encoding="utf-8")) if os.path.exists(cache_p) else {}
    prev_p = os.path.join(DATA, "screened", f"{date}.json")
    if os.path.exists(prev_p):
        for x in json.load(open(prev_p, encoding="utf-8")).get("items", []):
            acache.setdefault(x["url"], {"ok": True, "status": 200, "final_url": x.get("final_url") or x["url"], "title": x.get("title", ""), "meta": x.get("meta", ""),
                                         "has_ui": x.get("has_ui", True), "login_wall": False, "body_len": 0, "via": "cache", "lang_hint": "zh" if x.get("lang") == "zh" else ""})
    todo = [it for it in items if it["url"] not in acache]
    print(f"去重去杂后 {len(items)} 条，{len(items) - len(todo)} 条有缓存，开始逐条打开 {len(todo)} 条（{threads} 线程）…", file=sys.stderr)
    checked = datetime.date.today().strftime("%m-%d")
    out, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {ex.submit(alive, it["url"]): it for it in todo}
        done = [(it, acache[it["url"]]) for it in items if it["url"] in acache]
        def gen():
            for it, a in done: yield it, a
            for f in as_completed(futs):
                a = f.result(); acache[futs[f]["url"]] = a; yield futs[f], a
        for i, (it, a) in enumerate(gen(), 1):
            if i % 500 == 0: json.dump(acache, open(cache_p, "w", encoding="utf-8"), ensure_ascii=False)
            st = stats[it["src_name"]]
            if not a["ok"]:
                st["打不开"] += 1; continue
            if not a["has_ui"] and a["status"] not in (401, 403, 405, 429) and a["title"] != "(JSON 接口)":
                st["没有可用界面"] += 1; continue
            st["收录"] += 1
            it["desc"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(it.get("desc") or ""))).strip()
            if a["meta"] and (not it["desc"] or len(it["desc"]) > 160 or re.match(r"^(I |I'|We |Hey|Hi\b|Hello)", it["desc"])):
                it["desc"] = a["meta"]  # 帖子正文是第一人称长文时，用网站自己的一句话介绍
            if len(it["desc"]) > 170:  # 太长就在词边界截断
                cut = it["desc"][:170]; cut = cut[:cut.rfind(" ")] if " " in cut[100:] and not CJK.search(cut) else cut
                it["desc"] = cut.rstrip(" ,;:，；：") + "…"
            text = " ".join([it.get("name", ""), it.get("desc", ""), a["title"], a["meta"], " ".join((it.get("signals") or {}).get("topics") or [])])
            ind = classify(text)
            lang = lang_of(it, a)
            tr = traction(it)
            score = 40 + (10 if ind != "其他" else 0) + (10 if tr else 0) + (10 if it.get("source_url") else 0) + (10 if lang == "zh" else 0) + (10 if it["also"] else 0) + (10 if (it.get("desc") or a["meta"]) else 0)
            out.append({"name": pick_name(it, a), "url": it["url"], "final_url": a["final_url"] if a["final_url"] != it["url"] else "", "source_url": it.get("source_url"),
                        "src": it["src"], "src_name": it["src_name"], "also": it["also"], "author": it.get("author"), "author_url": it.get("author_url"), "author_type": it.get("author_type"),
                        "desc": it.get("desc") or a["meta"], "title": a["title"], "meta": a["meta"], "lang": lang, "industry": ind, "has_ui": a["has_ui"], "traction": tr,
                        "signals": it.get("signals") or {}, "created_at": it.get("created_at"), "found_at": it.get("found_at"), "checked": checked, "score": score})
            if i % 100 == 0: print(f"  {i}/{len(items)} 已检 {time.time()-t0:.0f}s 收录 {len(out)}", file=sys.stderr)
    json.dump(acache, open(cache_p, "w", encoding="utf-8"), ensure_ascii=False)
    # Hugging Face 作者是不是个人：只查活着且有界面的那些（没在跑的 Space 占大头，不必为它们问镜像）；查过的记在盘上
    hf_out = [x for x in out if x["src"] == "hf"]
    hf_cache_p = os.path.join(DATA, "screened", "hf-authors.json")
    if hf_out:
        if os.path.exists(hf_cache_p):
            for k, v in json.load(open(hf_cache_p, encoding="utf-8")).items():
                if v is not None: hf_is_user.__defaults__[0][k] = v
        authors = {x["author"] for x in hf_out}
        print(f"HF 作者类型查询 {len(authors)} 人（{len([a for a in authors if a in hf_is_user.__defaults__[0]])} 人有缓存）…", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=3) as ex:  # 镜像并发高了回 429，查不出的留给 tools/hf_authors.py 慢慢补
            list(ex.map(lambda a: (hf_is_user(a), time.sleep(0.3)), authors))
        for x in hf_out:
            r = hf_is_user(x["author"])
            x["author_type"] = "individual" if r else ("organization" if r is False else "unknown")
            if r is False:
                stats[x["src_name"]]["非个人或大厂"] += 1; stats[x["src_name"]]["收录"] -= 1; out.remove(x)
        json.dump({k: v for k, v in hf_is_user.__defaults__[0].items() if v is not None}, open(hf_cache_p, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  HF 收录 {len([x for x in out if x['src'] == 'hf'])}，其中作者待查 {len([x for x in out if x['src'] == 'hf' and x['author_type'] == 'unknown'])}", file=sys.stderr)
    out.sort(key=lambda x: (-x["score"], x["industry"], -(x["signals"].get("stars") or x["signals"].get("points") or x["signals"].get("likes") or 0)))
    os.makedirs(os.path.join(DATA, "screened"), exist_ok=True)
    p = os.path.join(DATA, "screened", f"{date}.json")
    json.dump({"date": date, "checked": checked, "stats": stats, "industries": [n for n, _ in INDUSTRIES] + ["其他"], "items": out}, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    import collections
    print("行业分布：", dict(collections.Counter(x["industry"] for x in out)))
    print("语言：", dict(collections.Counter(x["lang"] for x in out)))
    print(p)

if __name__ == "__main__":
    main()
