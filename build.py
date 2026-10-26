#!/usr/bin/env python3
"""野榜静态站生成器：data/screened/*.json（搜索库）+ data/picks/*.json（每周精选）+ data/issues/*.json（创刊号旧格式）+ data/*.md → docs/

用法：python3 build.py            # 生成全部页面
      python3 build.py --poster  # 同时用本机 Chrome 截海报 PNG（需 tools/shot.sh）
零依赖，只用标准库。GitHub Pages 从 main 分支 /docs 目录发布。
"""
import json, os, re, sys, html, glob, subprocess, datetime, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "docs")

site = json.load(open(os.path.join(DATA, "site.json"), encoding="utf-8"))
ACCENT = site.get("accent", "#FF4D00")
DIMS = [("usable", "真能用"), ("specific", "解决具体环节"), ("novel", "第一次见"), ("wild", "野生"), ("used", "有真人用"), ("verifiable", "可核可认领")]
SRC_SHORT = {"GitHub 新仓": "GitHub", "Show HN": "Show HN", "Hugging Face Spaces": "HF Spaces", "V2EX 分享创造": "V2EX", "投稿": "投稿",
             "dev.to #showdev": "dev.to", "掘金": "掘金", "BetaList": "BetaList", "Uneed": "Uneed", "Indie Hackers": "Indie Hackers", "Microlaunch": "Microlaunch"}

def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)

def fmt_num(n):
    if n is None or n == "":
        return "—"
    try:
        n = float(n)
    except Exception:
        return esc(n)
    if n >= 1000000:
        return f"{n/10000:.0f}万"
    if n >= 10000:
        return f"{n/10000:.2f}".rstrip("0").rstrip(".") + "万"
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:.1f}"

# ---------- 极简 markdown → html（只认 # / ## / ### / - / 数字. / 段落 / **粗** / [链接](url) / `code` / 表格） ----------
def md(text):
    out, para, lst = [], [], None
    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para = []
    def close_list():
        nonlocal lst
        if lst:
            out.append(f"</{lst}>")
            lst = None
    def inline(s):
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
        return s
    for line in text.splitlines():
        if not line.strip():
            flush_para(); close_list(); continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flush_para(); close_list()
            lvl = len(m.group(1)) + 1
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); continue
        m = re.match(r"^\s*[-*]\s+(.*)", line)
        if m:
            flush_para()
            if lst != "ul": close_list(); out.append("<ul>"); lst = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>"); continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if m:
            flush_para()
            if lst != "ol": close_list(); out.append("<ol>"); lst = "ol"
            out.append(f"<li>{inline(m.group(1))}</li>"); continue
        if line.startswith("|"):
            flush_para(); close_list()
            tl = table_line(line, inline)
            if tl: out.append(tl)
            continue
        para.append(line.strip())
    flush_para(); close_list()
    joined = "\n".join(out)
    joined = re.sub(r"((?:<tr>.*?</tr>\n?)+)", r"<table>\1</table>", joined, flags=re.S)
    return joined

def table_line(line, inline):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
        return ""
    return "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>"

# ---------- 公共 CSS ----------
CSS = f"""
:root{{--accent:{ACCENT};--ink:#111;--muted:#6b6b6b;--line:#e6e6e6;--bg:#fff;--soft:#f6f6f4}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;line-height:1.55;font-size:16px}}
a{{color:inherit;text-decoration:none}}
a:hover{{text-decoration:underline;text-decoration-color:var(--accent)}}
.wrap{{max-width:960px;margin:0 auto;padding:0 20px}}
header.top{{border-bottom:1px solid var(--line)}}
header.top .wrap{{display:flex;align-items:center;justify-content:space-between;height:64px}}
.logo{{font-weight:900;font-size:26px;letter-spacing:.02em;display:flex;align-items:center;gap:10px}}
.logo i{{display:inline-block;width:14px;height:14px;background:var(--accent);border-radius:2px;transform:rotate(45deg)}}
nav a{{margin-left:22px;font-size:15px;color:var(--muted)}}
nav a.on{{color:var(--ink);font-weight:600}}
.hero{{padding:44px 0 20px}}
.hero .issue{{color:var(--accent);font-weight:800;letter-spacing:.08em;font-size:14px;text-transform:uppercase}}
.hero h1{{font-size:44px;line-height:1.15;margin:8px 0 14px;font-weight:900;letter-spacing:-.01em}}
.hero p{{color:var(--muted);max-width:720px;margin:0;font-size:17px}}
.meta{{display:flex;flex-wrap:wrap;gap:14px 28px;color:var(--muted);font-size:14px;margin-top:18px}}
.meta b{{color:var(--ink);font-weight:600}}
.search{{margin:22px 0 10px}}
.search input{{width:100%;font-size:20px;padding:14px 18px;border:2px solid var(--ink);border-radius:8px;outline:none;font-family:inherit;background:#fff}}
.search input:focus{{border-color:var(--accent)}}
.facets{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 6px}}
.facets button{{font:inherit;font-size:14px;border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 12px;cursor:pointer;color:#333}}
.facets button.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.facets button small{{color:#999;margin-left:4px}}
.facets button.on small{{color:#ccc}}
.count{{color:var(--muted);font-size:14px;margin:6px 0 18px}}
section.board{{margin:30px 0 48px}}
section.board h2{{font-size:26px;margin:0 0 6px;display:flex;align-items:baseline;gap:12px}}
section.board h2 small{{font-size:14px;color:var(--muted);font-weight:500}}
section.board .sub{{color:var(--muted);margin:0 0 18px;font-size:15px}}
h3.ind{{font-size:18px;margin:26px 0 8px;display:flex;align-items:center;gap:10px}}
h3.ind:before{{content:"";display:inline-block;width:10px;height:10px;background:var(--accent);transform:rotate(45deg)}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.card{{border:1px solid var(--line);border-radius:10px;padding:16px 18px;background:#fff}}
.card .name{{font-size:18px;font-weight:800;line-height:1.3}}
.card .by{{color:var(--muted);font-size:13px;margin-top:3px}}
.card .by a{{color:var(--ink)}}
.card .desc{{font-size:14.5px;color:#333;margin-top:8px}}
.card .why{{margin-top:10px;padding:10px 12px;background:var(--soft);border-left:3px solid var(--accent);font-size:14.5px;border-radius:3px}}
.card .why b{{color:var(--accent);font-weight:800;margin-right:4px}}
.dims{{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:10px;font-size:12px;color:var(--muted)}}
.dims span i{{display:inline-block;width:7px;height:7px;border-radius:50%;background:#ddd;margin-left:3px;vertical-align:middle}}
.dims span i.on{{background:var(--accent)}}
ol.rank,ul.lib{{list-style:none;margin:0;padding:0;border-top:1px solid var(--ink)}}
ol.rank li{{display:grid;grid-template-columns:56px 1fr 150px;gap:16px;padding:16px 0;border-bottom:1px solid var(--line);align-items:start}}
ul.lib li{{display:grid;grid-template-columns:1fr 120px;gap:16px;padding:13px 0;border-bottom:1px solid var(--line);align-items:start}}
ul.lib li.hide{{display:none}}
ol.rank .no{{font-size:30px;font-weight:900;line-height:1;color:var(--ink);font-variant-numeric:tabular-nums}}
ol.rank li:nth-child(-n+3) .no{{color:var(--accent)}}
.name{{font-size:18px;font-weight:700;line-height:1.3}}
ul.lib .name{{font-size:16.5px}}
.by{{color:var(--muted);font-size:14px;margin-top:2px}}
.by a{{color:var(--ink)}}
.desc{{margin-top:6px;font-size:15px;color:#333}}
ul.lib .desc{{font-size:14px;margin-top:3px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
.chip{{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:2px 9px;color:var(--muted);background:var(--soft)}}
.chip.ok{{border-color:#bfe3c6;color:#1f7a37;background:#eef9f0}}
.chip.src{{border-color:#f3cdbb;color:#b0400c;background:#fff3ec}}
.chip.ind{{border-color:#ddd;color:#333;background:#fff}}
.num{{text-align:right}}
.num .v{{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.1}}
.num .l{{font-size:12px;color:var(--muted);margin-top:3px}}
.num .d{{font-size:13px;color:#1f7a37;margin-top:3px;font-weight:600}}
.side{{text-align:right;font-size:12px;color:var(--muted);line-height:1.5}}
.side b{{color:var(--ink);font-weight:700;font-size:13px}}
.note{{background:var(--soft);border-left:4px solid var(--accent);padding:14px 18px;border-radius:4px;color:#333;font-size:15px;margin:24px 0}}
.stats{{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}}
.stats td{{border-bottom:1px solid var(--line);padding:7px 10px;vertical-align:top;text-align:right;font-variant-numeric:tabular-nums}}
.stats td:first-child{{text-align:left}}
.stats tr:first-child td{{font-weight:700;border-bottom:2px solid var(--ink)}}
footer{{border-top:1px solid var(--line);padding:28px 0 48px;color:var(--muted);font-size:14px}}
footer .wrap{{display:flex;flex-wrap:wrap;gap:12px 32px;justify-content:space-between}}
footer a{{color:var(--ink)}}
article{{max-width:720px;padding:32px 0 56px}}
article h2{{font-size:30px;margin:0 0 20px}}
article h3{{font-size:21px;margin:34px 0 10px}}
article h4{{font-size:17px;margin:26px 0 8px}}
article p,article li{{font-size:16.5px;color:#222}}
article code{{background:var(--soft);padding:1px 6px;border-radius:3px;font-size:14px}}
article table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:15px}}
article td{{border-bottom:1px solid var(--line);padding:8px 10px;vertical-align:top}}
article tr:first-child td{{font-weight:700;border-bottom:2px solid var(--ink)}}
ul.archive{{list-style:none;padding:0}}
ul.archive li{{padding:14px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}}
.cta{{display:inline-block;background:var(--ink);color:#fff;padding:10px 18px;border-radius:6px;font-weight:600;font-size:15px}}
.cta.alt{{background:var(--accent)}}
.cta:hover{{text-decoration:none;opacity:.9}}
@media (max-width:640px){{
 .hero h1{{font-size:32px}}
 .cards{{grid-template-columns:1fr}}
 ol.rank li{{grid-template-columns:40px 1fr;gap:12px}}
 ul.lib li{{grid-template-columns:1fr}}
 .side{{text-align:left}}
 ol.rank .no{{font-size:24px}}
 .num{{grid-column:2;text-align:left;display:flex;gap:10px;align-items:baseline}}
 .num .l{{margin:0}}
 nav a{{margin-left:12px;font-size:13px}}
 .logo{{font-size:22px}}
}}
"""

NAV = [("index.html", "搜索", "index"), ("weekly.html", "本周精选", "weekly"), ("archive.html", "往期", "archive"),
       ("method.html", "方法", "method"), ("submit.html", "投稿 / 认领", "submit")]

def page(title, body, active="", desc=None, extra_head=""):
    navh = "".join(f'<a href="{h}" class="{"on" if k==active else ""}">{t}</a>' for h, t, k in NAV)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc or site['tagline'])}">
<style>{CSS}</style>{extra_head}</head>
<body>
<header class="top"><div class="wrap">
 <a class="logo" href="index.html"><i></i>{esc(site['name'])}</a>
 <nav>{navh}</nav>
</div></header>
{body}
<footer><div class="wrap">
 <div>{esc(site['byline'])} · {esc(site['cadence'])}</div>
 <div><a href="method.html">方法公开</a> · <a href="{esc(site['claim_url'])}">认领 / 纠错</a> · <a href="{esc(site['repo_url'])}">数据与代码</a></div>
</div></footer>
</body></html>"""

# ---------- 数据装载 ----------
def load_library():
    """所有周的 screened 合并成一个搜索库；同一网址只留最近一次记录。"""
    lib, weeks = {}, []
    for f in sorted(glob.glob(os.path.join(DATA, "screened", "*.json"))):
        if not re.match(r"\d{4}-\d{2}-\d{2}\.json$", os.path.basename(f)): continue  # 同目录里还有筛选缓存文件
        d = json.load(open(f, encoding="utf-8"))
        weeks.append(d)
        for it in d["items"]:
            it = dict(it); it["week"] = d["date"]
            lib[it["url"]] = it
    return list(lib.values()), weeks

def load_picks():
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, "picks", "*.json"))):
        out.append(json.load(open(f, encoding="utf-8")))
    return out

def merge_pick(pk, lib_by_url):
    base = dict(lib_by_url.get(pk["url"], {}))
    base.update({k: v for k, v in pk.items() if v not in (None, "")})
    base["dim_total"] = sum(int((pk.get("dims") or {}).get(k, 0)) for k, _ in DIMS)
    return base

# ---------- 片段 ----------
def by_line(it):
    by = it.get("author") or ""
    by_url = it.get("author_url")
    if by:
        return f'<a href="{esc(by_url)}" rel="noopener">{esc(by)}</a>' if by_url else esc(by)
    return f'<a href="{esc(site["claim_url"])}" style="color:var(--accent)">作者未署名，是你做的来认领</a>'

def src_chips(it, with_ind=True):
    chips = []
    if with_ind and it.get("industry"):
        chips.append(f'<span class="chip ind">{esc(it["industry"])}</span>')
    seen = set()
    for a in [it] + (it.get("also") or []):
        if not a.get("src_name") or a["src_name"] in seen: continue
        seen.add(a["src_name"])
        chips.append(f'<a class="chip src" href="{esc(a.get("source_url") or it["url"])}" rel="noopener">{esc(SRC_SHORT.get(a["src_name"], a["src_name"]))}</a>')
    if it.get("checked"):
        chips.append(f'<span class="chip ok">{esc(it["checked"])} 打开过</span>')
    if it.get("lang") == "zh":
        chips.append('<span class="chip">中文</span>')
    return "".join(chips)

def signal_text(it):
    s = it.get("signals") or {}
    for k, label in (("stars", "star"), ("points", "HN 票"), ("likes", "赞"), ("replies", "回帖"), ("views", "浏览")):
        if s.get(k): return f"{fmt_num(s[k])} {label}"
    return ""

def dims_html(dims):
    out = []
    for k, label in DIMS:
        v = int((dims or {}).get(k, 0))
        out.append(f'<span>{label}<i class="{"on" if v>=1 else ""}"></i><i class="{"on" if v>=2 else ""}"></i></span>')
    return '<div class="dims">' + "".join(out) + "</div>"

def card(it):
    return f"""<div class="card">
 <div class="name"><a href="{esc(it['url'])}" rel="noopener">{esc(it.get('name'))}</a></div>
 <div class="by">{by_line(it)}{(' · ' + esc(it['created_at']) + ' 出生') if it.get('created_at') else ''}</div>
 <div class="desc">{esc(it.get('desc',''))}</div>
 <div class="why"><b>为什么有意思</b>{esc(it.get('why',''))}</div>
 {dims_html(it.get('dims'))}
 <div class="chips">{src_chips(it, with_ind=False)}</div>
</div>"""

def lib_item(it):
    sig = signal_text(it)
    return f"""<li data-ind="{esc(it.get('industry',''))}" data-lang="{esc(it.get('lang',''))}" data-u="{esc(it['url'])}">
 <div>
  <div class="name"><a href="{esc(it['url'])}" rel="noopener">{esc(it.get('name'))}</a></div>
  <div class="by">{by_line(it)}</div>
  <div class="desc">{esc(it.get('desc',''))}</div>
  <div class="chips">{src_chips(it)}</div>
 </div>
 <div class="side">{('<b>' + esc(sig) + '</b><br>') if sig else ''}{esc(it.get('created_at',''))} 出生</div>
</li>"""

SEARCH_JS = """<script>
(function(){
 var q=document.getElementById('q'),lis=[].slice.call(document.querySelectorAll('ul.lib li')),cnt=document.getElementById('cnt'),picks=document.getElementById('picks');
 var ind='',lang='';
 lis.forEach(function(li){li._s=(li.textContent+' '+li.dataset.u).toLowerCase().replace(/\\s+/g,' ');});
 function run(){
  var s=(q.value||'').trim().toLowerCase(),n=0,words=s.split(/\\s+/).filter(Boolean);
  lis.forEach(function(li){
   var ok=words.every(function(w){return li._s.indexOf(w)>-1;})&&(!ind||li.dataset.ind===ind)&&(!lang||li.dataset.lang===lang);
   li.classList.toggle('hide',!ok); if(ok)n++;
  });
  cnt.textContent=n+' 个网站'+(s||ind||lang?'（按初筛分排）':'');
  if(picks) picks.style.display=(s||ind||lang)?'none':'';
  var u=new URL(location); s?u.searchParams.set('q',s):u.searchParams.delete('q'); ind?u.searchParams.set('ind',ind):u.searchParams.delete('ind'); lang?u.searchParams.set('lang',lang):u.searchParams.delete('lang');
  history.replaceState(null,'',u);
 }
 q.addEventListener('input',run);
 document.querySelectorAll('.facets button').forEach(function(b){
  b.addEventListener('click',function(){
   var g=b.dataset.g,v=b.dataset.v;
   if(g==='ind'){ind=(ind===v)?'':v;} else {lang=(lang===v)?'':v;}
   document.querySelectorAll('.facets button[data-g="'+g+'"]').forEach(function(x){x.classList.toggle('on',x.dataset.v===(g==='ind'?ind:lang)&&x.dataset.v!=='');});
   run();
  });
 });
 var p=new URL(location).searchParams; q.value=p.get('q')||''; ind=p.get('ind')||''; lang=p.get('lang')||'';
 document.querySelectorAll('.facets button').forEach(function(x){x.classList.toggle('on',(x.dataset.g==='ind'&&x.dataset.v===ind&&ind)||(x.dataset.g==='lang'&&x.dataset.v===lang&&lang));});
 run(); if(!('ontouchstart' in window)) q.focus();
})();
</script>"""

# ---------- 页面 ----------
def stats_table(stats):
    cols = ["候选", "网址不算网站", "非个人或大厂", "中转代理", "打不开", "没有可用界面", "收录"]
    rows = "<tr><td>登记处</td>" + "".join(f"<td>{c}</td>" for c in cols) + "</tr>"
    tot = collections.Counter()
    for src, st in stats.items():
        rows += f"<tr><td>{esc(src)}</td>" + "".join(f"<td>{fmt_num(st.get(c,0))}</td>" for c in cols) + "</tr>"
        for c in cols: tot[c] += st.get(c, 0)
    rows += "<tr><td><b>合计</b></td>" + "".join(f"<td><b>{fmt_num(tot[c])}</b></td>" for c in cols) + "</tr>"
    return f'<table class="stats">{rows}</table>'

def render_search(lib, weeks, latest_picks, lib_by_url):
    inds = collections.Counter(it.get("industry", "其他") for it in lib)
    order = [n for n in (weeks[-1].get("industries") if weeks else []) if n in inds] + [n for n in inds if weeks and n not in weeks[-1].get("industries", [])]
    facets = "".join(f'<button data-g="ind" data-v="{esc(n)}">{esc(n)}<small>{inds[n]}</small></button>' for n in order)
    facets += f'<button data-g="lang" data-v="zh">中文<small>{sum(1 for i in lib if i.get("lang")=="zh")}</small></button>'
    lib_sorted = sorted(lib, key=lambda x: (-(x.get("score") or 0), x.get("industry", ""), x.get("name", "")))
    week_stats = weeks[-1]["stats"] if weeks else {}
    tot = collections.Counter()
    for st in week_stats.values():
        for k, v in st.items(): tot[k] += v
    picks_block = ""
    if latest_picks:
        merged = [merge_pick(p, lib_by_url) for p in latest_picks["picks"]]
        groups = collections.OrderedDict()
        for it in merged: groups.setdefault(it.get("industry", "其他"), []).append(it)
        inner = "".join(f'<h3 class="ind">{esc(ind)}</h3><div class="cards">{"".join(card(it) for it in its)}</div>' for ind, its in groups.items())
        picks_block = f"""<section class="board" id="picks" style="margin-top:8px">
 <h2>本周精选 <small>第 {latest_picks['issue']} 期 · {esc(latest_picks['date'])} · {len(merged)} 个 · <a href="weekly.html">看完整周报与挑法</a></small></h2>
 <p class="sub">{esc(latest_picks.get('title',''))}</p>
 {inner}
 <h2 style="margin-top:40px">全部收录 <small>过了四道门的全在这，按初筛分排；上面搜索框搜的就是这个库</small></h2>
</section>"""
    body = f"""<div class="wrap">
<div class="hero">
 <div class="issue">野生 AI 网站搜索库 · 每周一更新</div>
 <h1>{esc(site['tagline'])}</h1>
 <p>{esc(site['intro'])}</p>
 <div class="meta"><span>库里 <b>{len(lib)} 个</b>网站</span><span>最近一周扫了 <b>{fmt_num(tot['候选'])}</b> 个新候选，<b>{fmt_num(tot['收录'])}</b> 个过了四道门</span><span>数据截至 <b>{esc(weeks[-1]['date'] if weeks else '')}</b></span></div>
</div>
<div class="search"><input id="q" type="search" placeholder="搜行业、用途、关键词：股票 / 简历 / 字幕 / 菜谱 / mcp …" autocomplete="off"></div>
<div class="facets">{facets}</div>
<div class="count" id="cnt">{len(lib)} 个网站</div>
{picks_block}
<ul class="lib">{''.join(lib_item(it) for it in lib_sorted)}</ul>
<div style="margin:28px 0 8px;display:flex;gap:10px;flex-wrap:wrap"><a class="cta alt" href="{esc(site['submit_url'])}">我做了个网站，投稿</a><a class="cta" href="method.html">看方法</a></div>
</div>"""
    return page(f"{site['name']} · {site['tagline']}", body, active="index", extra_head="", desc=site["intro"][:120]) .replace("</body>", SEARCH_JS + "</body>")

def render_weekly(pk, lib_by_url, week):
    merged = [merge_pick(p, lib_by_url) for p in pk["picks"]]
    groups = collections.OrderedDict()
    for it in merged: groups.setdefault(it.get("industry", "其他"), []).append(it)
    inner = "".join(f'<h3 class="ind">{esc(ind)} <small style="font-weight:500;color:var(--muted);font-size:13px">{len(its)} 个</small></h3><div class="cards">{"".join(card(it) for it in its)}</div>' for ind, its in groups.items())
    note = f'<div class="note">{md(pk["note"])}</div>' if pk.get("note") else ""
    stats = stats_table(week["stats"]) if week else ""
    ind_dist = collections.Counter(it.get("industry", "其他") for it in (week or {}).get("items", []))
    dist = "、".join(f"{k} {v}" for k, v in ind_dist.most_common())
    body = f"""<div class="wrap">
<div class="hero">
 <div class="issue">第 {pk['issue']} 期 · {esc(pk['date'])}</div>
 <h1>{esc(pk.get('title') or '本周精选')}</h1>
 <p>从本周过了四道门的 {len((week or {}).get('items', []))} 个野生网站里挑出 {len(merged)} 个有意思的，每个写一句为什么。六个维度每个 0–2 分，分是编辑打的，<a href="method.html">挑法在这</a>。</p>
 <div style="margin-top:22px;display:flex;gap:10px;flex-wrap:wrap"><a class="cta" href="index.html">搜全部 {len((week or {}).get('items', []))} 个</a><a class="cta alt" href="{esc(site['submit_url'])}">我做了个网站，投稿</a></div>
</div>
{note}
<section class="board">{inner}</section>
<section class="board" id="stats">
 <h2>这周扫了多少 <small>四道门的数字</small></h2>
 <p class="sub">每个登记处拉了多少候选、拦在哪道门、最后收录多少。收录的 {len((week or {}).get('items', []))} 个按行业：{esc(dist)}。</p>
 {stats}
</section>
</div>"""
    return page(f"{site['name']} 第 {pk['issue']} 期 · {pk['date']}", body, active="weekly", desc=f"{site['name']}第{pk['issue']}期：{pk.get('title','')}")

def render_poster(pk, lib_by_url):
    merged = [merge_pick(p, lib_by_url) for p in pk["picks"]]
    merged.sort(key=lambda x: -x["dim_total"])
    items = merged[:10]
    rows = ""
    for it in items:
        why = re.sub(r"\s+", " ", it.get("why", ""))
        rows += f"""<div class="r"><div class="ind">{esc(it.get('industry',''))}</div>
 <div class="t"><div class="nm">{esc(it.get('name'))}<span>{esc(it.get('author') or '')}</span></div><div class="why">{esc(why)}</div></div></div>"""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>野榜 第 {pk['issue']} 期</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;width:1080px;height:1440px;background:#fff;color:#111;font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;overflow:hidden;position:relative}}
.bar{{position:absolute;left:0;top:0;width:100%;height:18px;background:{ACCENT}}}
.wrap{{padding:60px 64px 0}}
.logo{{display:flex;align-items:center;gap:14px;font-weight:900;font-size:38px}}
.logo i{{display:inline-block;width:20px;height:20px;background:{ACCENT};transform:rotate(45deg);border-radius:3px}}
.logo span{{font-size:21px;color:#777;font-weight:600;margin-left:6px}}
h1{{font-size:62px;line-height:1.08;margin:26px 0 6px;font-weight:900;letter-spacing:-.02em}}
.sub{{font-size:23px;color:#555;margin:0 0 18px}}
.r{{display:grid;grid-template-columns:118px 1fr;align-items:start;gap:16px;padding:12px 0;border-bottom:2px solid #eee}}
.r:first-child{{border-top:4px solid #111}}
.ind{{font-size:17px;font-weight:800;color:{ACCENT};line-height:1.25;padding-top:5px}}
.nm{{font-size:27px;font-weight:800;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.nm span{{font-size:16px;color:#888;font-weight:500;margin-left:10px}}
.why{{font-size:17.5px;color:#444;margin-top:3px;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.foot{{position:absolute;left:64px;right:64px;bottom:44px;display:flex;justify-content:space-between;align-items:flex-end;color:#666;font-size:19px;line-height:1.4}}
.foot b{{color:#111;font-weight:800}}
.foot .url{{font-weight:700;color:#111}}
</style></head><body>
<div class="bar"></div>
<div class="wrap">
 <div class="logo"><i></i>{esc(site['name'])}<span>第 {pk['issue']} 期 · {esc(pk['date'])}</span></div>
 <h1>{esc(pk.get('poster_title') or '这周新出生的野生 AI 网站')}</h1>
 <div class="sub">{esc(pk.get('poster_sub') or f"个人做的、搜索引擎还看不见的 · 本期挑了 {len(merged)} 个，这是其中 {len(items)} 个")}</div>
 <div class="list">{rows}</div>
</div>
<div class="foot"><div><b>方法公开 · 数据可核</b><br>{esc(pk.get('poster_note') or '全部收录可搜；是你做的，来认领。')}</div><div style="text-align:right"><span class="url">{esc(site['site_url'].replace('https://',''))}</span><br>{esc(site['byline'])}</div></div>
</body></html>"""

# ---------- 创刊号旧格式（第 1 期：技能榜 + 应用榜）照旧渲染，放在往期 ----------
def render_item_legacy(it, kind):
    chips = []
    for p in it.get("platforms", []) or []:
        chips.append(f'<span class="chip">{esc(p)}</span>')
    if it.get("source") and it["source"] not in (it.get("platforms") or []):
        chips.append(f'<a class="chip src" href="{esc(it.get("source_url") or it.get("url"))}">{esc(it["source"])}</a>')
    if kind == "apps" and it.get("alive") is True:
        chips.append(f'<span class="chip ok">{esc(it.get("checked","今日"))} 可打开</span>')
    by = it.get("author") or ""
    byh = (f'<a href="{esc(it.get("author_url"))}">{esc(by)}</a>' if it.get("author_url") else esc(by)) if by else f'<a href="{esc(site["claim_url"])}" style="color:var(--accent)">作者未署名，是你做的来认领</a>'
    return f"""<li>
 <div class="no">{it.get('rank','')}</div>
 <div>
  <div class="name"><a href="{esc(it.get('url'))}" rel="noopener">{esc(it.get('name'))}</a></div>
  <div class="by">{byh}</div>
  <div class="desc">{esc(it.get('desc',''))}</div>
  <div class="chips">{''.join(chips)}</div>
 </div>
 <div class="num"><div class="v">{fmt_num(it.get('metric'))}</div><div class="l">{esc(it.get('metric_label',''))}</div></div>
</li>"""

def render_issue_legacy(iss):
    boards = ""
    for key, title, sub in [("skills", "技能榜", iss.get("skills_sub", "独立开发者做的 agent 技能 / 插件，按公开可核的使用数据排")),
                            ("apps", "应用榜", iss.get("apps_sub", "普通人做出来、搜不到但好用的 AI 应用，按公开热度 + 当日可用性排"))]:
        items = iss.get(key) or []
        if not items: continue
        boards += f"""<section class="board" id="{key}"><h2>{title} <small>Top {len(items)}</small></h2><p class="sub">{esc(sub)}</p>
 <ol class="rank">{''.join(render_item_legacy(it, key) for it in items)}</ol></section>"""
    note = f'<div class="note">{md(iss["note"])}</div>' if iss.get("note") else ""
    body = f"""<div class="wrap">
<div class="hero">
 <div class="issue">第 {iss['issue']} 期 · {esc(iss['date'])} · 创刊号</div>
 <h1>{esc(iss.get('title') or '野生好用的 AI 技能与应用')}</h1>
 <p>创刊号用的是旧方法：从六个技能市场和社区拉公开使用数据，按热度合并排序。从第 2 期起改为「出生登记处 + 四道门 + 六维度」，见<a href="../method.html">方法</a>。这期保留作对照。</p>
 <div class="meta"><span>统计区间 <b>{esc(iss.get('period',''))}</b></span><span>数据截至 <b>{esc(iss.get('cutoff',''))}</b></span><span>收录 <b>{len(iss.get('skills',[]))} 技能 · {len(iss.get('apps',[]))} 应用</b></span></div>
</div>
{note}
{boards}
</div>"""
    return page(f"{site['name']} 第 {iss['issue']} 期 · {iss['date']}", body, active="archive").replace('href="index.html"', 'href="../index.html"').replace('href="weekly.html"', 'href="../weekly.html"').replace('href="archive.html"', 'href="../archive.html"').replace('href="method.html"', 'href="../method.html"').replace('href="submit.html"', 'href="../submit.html"')

def main():
    for d in ("", "issues", "weekly", "poster"):
        os.makedirs(os.path.join(SITE, d), exist_ok=True)
    lib, weeks = load_library()
    lib_by_url = {it["url"]: it for it in lib}
    picks = load_picks()
    # 编辑在精选里改过的行业 / 名字 / 介绍，同步回搜索库那条，首页筛选和精选卡片说的是同一个行业
    for pk in picks:
        for p in pk["picks"]:
            if p["url"] in lib_by_url:
                lib_by_url[p["url"]].update({k: p[k] for k in ("industry", "name", "desc") if p.get(k)})
    legacy = [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(os.path.join(DATA, "issues", "*.json")))]
    legacy = [i for i in legacy if int(i.get("issue", 0)) > 0]
    latest_picks = picks[-1] if picks else None
    # 搜索首页
    open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(render_search(lib, weeks, latest_picks, lib_by_url))
    # 周报
    week_by_date = {w["date"]: w for w in weeks}
    for pk in picks:
        h = render_weekly(pk, lib_by_url, week_by_date.get(pk["date"]))
        open(os.path.join(SITE, "weekly", f"{pk['date']}.html"), "w", encoding="utf-8").write(h.replace('href="index.html"', 'href="../index.html"').replace('href="weekly.html"', 'href="../weekly.html"').replace('href="archive.html"', 'href="../archive.html"').replace('href="method.html"', 'href="../method.html"').replace('href="submit.html"', 'href="../submit.html"'))
        open(os.path.join(SITE, "poster", f"{pk['date']}-picks.html"), "w", encoding="utf-8").write(render_poster(pk, lib_by_url))
        open(os.path.join(SITE, "weekly", f"{pk['date']}.json"), "w", encoding="utf-8").write(json.dumps({**pk, "picks": [merge_pick(p, lib_by_url) for p in pk["picks"]]}, ensure_ascii=False, indent=1))
    if latest_picks:
        open(os.path.join(SITE, "weekly.html"), "w", encoding="utf-8").write(render_weekly(latest_picks, lib_by_url, week_by_date.get(latest_picks["date"])))
        open(os.path.join(SITE, "latest.json"), "w", encoding="utf-8").write(json.dumps({**latest_picks, "picks": [merge_pick(p, lib_by_url) for p in latest_picks["picks"]]}, ensure_ascii=False, indent=1))
    # 创刊号旧格式
    for iss in legacy:
        open(os.path.join(SITE, "issues", f"{iss['date']}.html"), "w", encoding="utf-8").write(render_issue_legacy(iss))
        open(os.path.join(SITE, "issues", f"{iss['date']}.json"), "w", encoding="utf-8").write(json.dumps(iss, ensure_ascii=False, indent=1))
    # 往期
    rows = "".join(f'<li><a href="weekly/{esc(p["date"])}.html">第 {p["issue"]} 期 · {esc(p["date"])} · {esc(p.get("title",""))}</a><span style="color:#6b6b6b">精选 {len(p["picks"])} · 收录 {len(week_by_date.get(p["date"],{}).get("items",[]))}</span></li>' for p in reversed(picks))
    rows += "".join(f'<li><a href="issues/{esc(i["date"])}.html">第 {i["issue"]} 期 · {esc(i["date"])} · {esc(i.get("title",""))}（创刊号，旧方法）</a><span style="color:#6b6b6b">{len(i.get("skills",[]))} 技能 · {len(i.get("apps",[]))} 应用</span></li>' for i in reversed(legacy))
    open(os.path.join(SITE, "archive.html"), "w", encoding="utf-8").write(
        page(f"{site['name']} · 往期", f'<div class="wrap"><article><h2>往期</h2><ul class="archive">{rows}</ul></article></div>', "archive"))
    # 方法 / 投稿
    for name, fn in (("method", "method.md"), ("submit", "submit.md")):
        text = open(os.path.join(DATA, fn), encoding="utf-8").read()
        open(os.path.join(SITE, f"{name}.html"), "w", encoding="utf-8").write(page(f"{site['name']} · {'方法' if name=='method' else '投稿 / 认领'}", f'<div class="wrap"><article>{md(text)}</article></div>', name))
    # 机器可读：全库
    slim = [{k: it.get(k) for k in ("name", "url", "source_url", "src_name", "author", "author_url", "desc", "lang", "industry", "signals", "created_at", "checked", "week")} for it in lib]
    open(os.path.join(SITE, "index.json"), "w", encoding="utf-8").write(json.dumps({"updated": weeks[-1]["date"] if weeks else "", "count": len(slim), "items": slim}, ensure_ascii=False))
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    print(f"built: 库 {len(lib)} 个网站, {len(picks)} 期精选, {len(legacy)} 期旧榜 → {SITE}")
    if "--poster" in sys.argv and latest_picks:
        h = os.path.join(SITE, "poster", f"{latest_picks['date']}-picks.html")
        subprocess.run(["zsh", os.path.join(ROOT, "tools", "shot.sh"), h, os.path.join(SITE, "poster", f"{latest_picks['date']}-picks.png")], check=False)

if __name__ == "__main__":
    main()
