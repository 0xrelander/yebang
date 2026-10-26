#!/usr/bin/env python3
"""野榜静态站生成器：data/site.json + data/issues/*.json + data/method.md → site/

用法：python3 build.py            # 生成全部页面
      python3 build.py --poster  # 同时用本机 Chrome 截海报 PNG（需 tools/shot.sh）
零依赖，只用标准库。
"""
import json, os, re, sys, html, glob, subprocess, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "docs")  # GitHub Pages 从 main 分支 /docs 目录发布

site = json.load(open(os.path.join(DATA, "site.json"), encoding="utf-8"))
ACCENT = site.get("accent", "#FF4D00")

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

# ---------- 极简 markdown → html（只认 # / ## / ### / - / 数字. / 段落 / **粗** / [链接](url) / `code`） ----------
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
            tl = table_line(line)
            if tl: out.append(tl)
            continue
        para.append(line.strip())
    flush_para(); close_list()
    joined = "\n".join(out)
    # 把连续的表格行包进 <table>
    joined = re.sub(r"((?:<tr>.*?</tr>\n?)+)", r"<table>\1</table>", joined, flags=re.S)
    return joined

def table_line(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
        return ""
    tag = "td"
    return "<tr>" + "".join(f"<{tag}>{esc(c)}</{tag}>" for c in cells) + "</tr>"

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
.hero{{padding:48px 0 28px}}
.hero .issue{{color:var(--accent);font-weight:800;letter-spacing:.08em;font-size:14px;text-transform:uppercase}}
.hero h1{{font-size:44px;line-height:1.15;margin:8px 0 14px;font-weight:900;letter-spacing:-.01em}}
.hero p{{color:var(--muted);max-width:720px;margin:0;font-size:17px}}
.meta{{display:flex;flex-wrap:wrap;gap:14px 28px;color:var(--muted);font-size:14px;margin-top:18px}}
.meta b{{color:var(--ink);font-weight:600}}
section.board{{margin:36px 0 56px}}
section.board h2{{font-size:26px;margin:0 0 6px;display:flex;align-items:baseline;gap:12px}}
section.board h2 small{{font-size:14px;color:var(--muted);font-weight:500}}
section.board .sub{{color:var(--muted);margin:0 0 18px;font-size:15px}}
ol.rank{{list-style:none;margin:0;padding:0;border-top:1px solid var(--ink)}}
ol.rank li{{display:grid;grid-template-columns:56px 1fr 150px;gap:16px;padding:16px 0;border-bottom:1px solid var(--line);align-items:start}}
ol.rank .no{{font-size:30px;font-weight:900;line-height:1;color:var(--ink);font-variant-numeric:tabular-nums}}
ol.rank li:nth-child(-n+3) .no{{color:var(--accent)}}
ol.rank .name{{font-size:18px;font-weight:700;line-height:1.3}}
ol.rank .name a:hover{{text-decoration:underline}}
ol.rank .by{{color:var(--muted);font-size:14px;margin-top:2px}}
ol.rank .by a{{color:var(--ink)}}
ol.rank .desc{{margin-top:6px;font-size:15px;color:#333}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
.chip{{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:2px 9px;color:var(--muted);background:var(--soft)}}
.chip.ok{{border-color:#bfe3c6;color:#1f7a37;background:#eef9f0}}
.chip.src{{border-color:#f3cdbb;color:#b0400c;background:#fff3ec}}
.num{{text-align:right}}
.num .v{{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.1}}
.num .l{{font-size:12px;color:var(--muted);margin-top:3px}}
.num .d{{font-size:13px;color:#1f7a37;margin-top:3px;font-weight:600}}
.num .d.neg{{color:#b0400c}}
.note{{background:var(--soft);border-left:4px solid var(--accent);padding:14px 18px;border-radius:4px;color:#333;font-size:15px;margin:24px 0}}
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
 ol.rank li{{grid-template-columns:40px 1fr;gap:12px}}
 ol.rank .no{{font-size:24px}}
 .num{{grid-column:2;text-align:left;display:flex;gap:10px;align-items:baseline}}
 .num .l{{margin:0}}
 nav a{{margin-left:14px;font-size:14px}}
}}
"""

def page(title, body, active="", desc=None):
    nav = [("index.html", "本期", "index"), ("archive.html", "往期", "archive"),
           ("method.html", "方法", "method"), ("submit.html", "投稿 / 认领", "submit")]
    navh = "".join(f'<a href="{h}" class="{"on" if k==active else ""}">{t}</a>' for h, t, k in nav)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc or site['tagline'])}">
<style>{CSS}</style></head>
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

def render_item(it, kind):
    chips = []
    for p in it.get("platforms", []) or []:
        chips.append(f'<span class="chip">{esc(p)}</span>')
    if it.get("source") and it["source"] not in (it.get("platforms") or []):
        s = esc(it["source"])
        chips.append(f'<a class="chip src" href="{esc(it.get("source_url") or it.get("url"))}">{s}</a>')
    if kind == "apps" and it.get("alive") is True:
        chips.append(f'<span class="chip ok">{esc(it.get("checked","今日"))} 可打开</span>')
    by = it.get("author") or it.get("maker") or ""
    by_url = it.get("author_url") or it.get("maker_url")
    if by:
        byh = f'<a href="{esc(by_url)}">{esc(by)}</a>' if by_url else esc(by)
    else:
        byh = f'<a href="{esc(site["claim_url"])}" style="color:var(--accent)">作者未署名，是你做的来认领</a>'
    delta = it.get("delta")
    dh = ""
    if delta is not None and delta != "":
        try:
            dv = float(delta)
            sign = "+" if dv >= 0 else ""
            dh = f'<div class="d {"neg" if dv < 0 else ""}">{sign}{fmt_num(dv)} {esc(it.get("delta_label","本周"))}</div>'
        except Exception:
            dh = f'<div class="d">{esc(delta)}</div>'
    return f"""<li>
 <div class="no">{it.get('rank','')}</div>
 <div>
  <div class="name"><a href="{esc(it.get('url'))}" rel="noopener">{esc(it.get('name'))}</a></div>
  <div class="by">{byh}</div>
  <div class="desc">{esc(it.get('desc',''))}</div>
  <div class="chips">{''.join(chips)}</div>
 </div>
 <div class="num"><div class="v">{fmt_num(it.get('metric'))}</div><div class="l">{esc(it.get('metric_label',''))}</div>{dh}</div>
</li>"""

def render_issue(iss, latest=True):
    boards = ""
    for key, title, sub in [("skills", "技能榜", iss.get("skills_sub", "独立开发者做的 agent 技能 / 插件，按公开可核的使用数据排")),
                            ("apps", "应用榜", iss.get("apps_sub", "普通人做出来、搜不到但好用的 AI 应用，按公开热度 + 今日可用性排"))]:
        items = iss.get(key) or []
        if not items:
            continue
        boards += f"""<section class="board" id="{key}">
 <h2>{title} <small>Top {len(items)}</small></h2>
 <p class="sub">{esc(sub)}</p>
 <ol class="rank">{''.join(render_item(it, key) for it in items)}</ol>
</section>"""
    note = f'<div class="note">{md(iss["note"])}</div>' if iss.get("note") else ""
    body = f"""<div class="wrap">
<div class="hero">
 <div class="issue">第 {iss['issue']} 期 · {esc(iss['date'])}</div>
 <h1>{esc(iss.get('title') or site['tagline'])}</h1>
 <p>{esc(site['intro'])}</p>
 <div class="meta"><span>统计区间 <b>{esc(iss.get('period',''))}</b></span><span>数据截至 <b>{esc(iss.get('cutoff',''))}</b></span><span>收录 <b>{len(iss.get('skills',[]))} 技能 · {len(iss.get('apps',[]))} 应用</b></span></div>
 <div style="margin-top:22px;display:flex;gap:10px;flex-wrap:wrap"><a class="cta alt" href="{esc(site['submit_url'])}">我做了个东西，投稿</a><a class="cta" href="method.html">看排法</a></div>
</div>
{note}
{boards}
</div>"""
    return page(f"{site['name']} 第 {iss['issue']} 期 · {iss['date']}", body, active="index" if latest else "archive",
                desc=f"{site['name']}第{iss['issue']}期：{iss.get('title') or site['tagline']}")

def render_poster(iss, key):
    items = (iss.get(key) or [])[:10]
    title = "技能榜" if key == "skills" else "应用榜"
    sub = "独立开发者做的 agent 技能" if key == "skills" else "普通人做的、搜不到但好用的 AI 应用"
    rows = ""
    for it in items:
        by = it.get("author") or it.get("maker") or "未署名·待认领"
        plat = " · ".join((it.get("platforms") or [])[:2]) if key == "skills" else (it.get("source") or "")
        rows += f"""<div class="r"><div class="n">{it.get('rank')}</div>
 <div class="t"><div class="nm">{esc(it.get('name'))}</div><div class="by">{esc(by)}{(' · ' + esc(plat)) if plat else ''}</div></div>
 <div class="v">{fmt_num(it.get('metric'))}<small>{esc(it.get('metric_label',''))}</small></div></div>"""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;width:1080px;height:1440px;background:#fff;color:#111;font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;overflow:hidden;position:relative}}
.bar{{position:absolute;left:0;top:0;width:100%;height:18px;background:{ACCENT}}}
.wrap{{padding:64px 64px 0}}
.logo{{display:flex;align-items:center;gap:14px;font-weight:900;font-size:38px}}
.logo i{{display:inline-block;width:20px;height:20px;background:{ACCENT};transform:rotate(45deg);border-radius:3px}}
.logo span{{font-size:21px;color:#777;font-weight:600;margin-left:6px}}
h1{{font-size:76px;line-height:1;margin:30px 0 8px;font-weight:900;letter-spacing:-.02em}}
.sub{{font-size:24px;color:#555;margin:0 0 22px}}
.r{{display:grid;grid-template-columns:74px 1fr 230px;align-items:center;gap:18px;padding:11px 0;border-bottom:2px solid #eee}}
.r:first-child{{border-top:4px solid #111}}
.n{{font-size:44px;font-weight:900;font-variant-numeric:tabular-nums;line-height:1}}
.r:nth-child(-n+3) .n{{color:{ACCENT}}}
.nm{{font-size:29px;font-weight:800;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:620px}}
.by{{font-size:19px;color:#777;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:620px}}
.v{{text-align:right;font-size:34px;font-weight:900;font-variant-numeric:tabular-nums;line-height:1}}
.v small{{display:block;font-size:16px;color:#888;font-weight:500;margin-top:5px}}
.foot{{position:absolute;left:64px;right:64px;bottom:48px;display:flex;justify-content:space-between;align-items:flex-end;color:#666;font-size:20px;line-height:1.4}}
.foot b{{color:#111;font-weight:800}}
.foot .url{{font-weight:700;color:#111}}
</style></head><body>
<div class="bar"></div>
<div class="wrap">
 <div class="logo"><i></i>{esc(site['name'])}<span>第 {iss['issue']} 期 · {esc(iss['date'])}</span></div>
 <h1>{title}</h1>
 <div class="sub">{sub} · 本期 Top {len(items)}</div>
 <div class="list">{rows}</div>
</div>
<div class="foot"><div><b>方法公开 · 数据可核</b><br>{esc(iss.get('poster_note') or '被排到的人可以来认领；没排到的，来投稿。')}</div><div style="text-align:right"><span class="url">{esc(site['site_url'].replace('https://',''))}</span><br>{esc(site['byline'])}</div></div>
</body></html>"""

def main():
    os.makedirs(SITE, exist_ok=True)
    os.makedirs(os.path.join(SITE, "issues"), exist_ok=True)
    os.makedirs(os.path.join(SITE, "poster"), exist_ok=True)
    files = sorted(glob.glob(os.path.join(DATA, "issues", "*.json")))
    issues = [json.load(open(f, encoding="utf-8")) for f in files]
    pairs = [(f, i) for f, i in zip(files, issues) if int(i.get("issue", 0)) > 0]  # 第 0 期 = 渲染测试，不发布
    files, issues = [p[0] for p in pairs], [p[1] for p in pairs]
    if not issues:
        sys.exit("没有任何一期数据：data/issues/*.json")
    latest = issues[-1]
    # 本期
    open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(render_issue(latest, True))
    for iss in issues:
        open(os.path.join(SITE, "issues", f"{iss['date']}.html"), "w", encoding="utf-8").write(render_issue(iss, False))
        for key in ("skills", "apps"):
            if iss.get(key):
                open(os.path.join(SITE, "poster", f"{iss['date']}-{key}.html"), "w", encoding="utf-8").write(render_poster(iss, key))
    # 往期
    rows = "".join(f'<li><a href="issues/{esc(i["date"])}.html">第 {i["issue"]} 期 · {esc(i["date"])} · {esc(i.get("title",""))}</a><span style="color:#6b6b6b">{len(i.get("skills",[]))} 技能 · {len(i.get("apps",[]))} 应用</span></li>' for i in reversed(issues))
    open(os.path.join(SITE, "archive.html"), "w", encoding="utf-8").write(
        page(f"{site['name']} · 往期", f'<div class="wrap"><article><h2>往期</h2><ul class="archive">{rows}</ul></article></div>', "archive"))
    # 方法
    method_md = open(os.path.join(DATA, "method.md"), encoding="utf-8").read()
    open(os.path.join(SITE, "method.html"), "w", encoding="utf-8").write(
        page(f"{site['name']} · 方法", f'<div class="wrap"><article>{md(method_md)}</article></div>', "method"))
    # 投稿
    submit_md = open(os.path.join(DATA, "submit.md"), encoding="utf-8").read()
    open(os.path.join(SITE, "submit.html"), "w", encoding="utf-8").write(
        page(f"{site['name']} · 投稿 / 认领", f'<div class="wrap"><article>{md(submit_md)}</article></div>', "submit"))
    # 机器可读：每期 JSON 原样发布 + 最新期别名
    for f, iss in zip(files, issues):
        open(os.path.join(SITE, "issues", f"{iss['date']}.json"), "w", encoding="utf-8").write(json.dumps(iss, ensure_ascii=False, indent=1))
    open(os.path.join(SITE, "latest.json"), "w", encoding="utf-8").write(json.dumps(latest, ensure_ascii=False, indent=1))
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    print(f"built {len(issues)} issue(s) → {SITE}")
    if "--poster" in sys.argv:
        for key in ("skills", "apps"):
            h = os.path.join(SITE, "poster", f"{latest['date']}-{key}.html")
            if os.path.exists(h):
                subprocess.run(["zsh", os.path.join(ROOT, "tools", "shot.sh"), h, os.path.join(SITE, "poster", f"{latest['date']}-{key}.png")], check=False)

if __name__ == "__main__":
    main()
