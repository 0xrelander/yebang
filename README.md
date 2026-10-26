# 野榜

找那些搜不到的野生 AI 网站。每周去「出生登记处」把最近 7 天新上线、个人做的 AI 网站找出来，逐个打开试过，按行业放进搜索库；再挑出有意思的写一句为什么。方法公开，数据可核。

- 网站：https://0xrelander.github.io/yebang/
- 方法：https://0xrelander.github.io/yebang/method.html
- 投稿 / 认领 / 纠错 / 下榜：用本仓库的 [Issue 表单](https://github.com/0xrelander/yebang/issues/new/choose)
- 机器可读：`docs/index.json`（全库）、`docs/latest.json`（最新一期精选）

## 怎么找、怎么筛、怎么挑

1. **找**：不顺着链接爬（新站没有入链），去登记处拉最近 7 天新出生的：GitHub 新仓的 homepage 字段、Show HN、Hugging Face Spaces 新建、V2EX 分享创造、投稿。
2. **筛**：四道门全由脚本跑——网址得是独立网站（不是仓库页/文档/商店/社交帖）；作者得是个人（不是机构、大厂、中转代理）；发布当天逐条打开，打不开不收；页面得有可操作的界面。过门的全部进搜索库。
3. **挑**：每周从库里挑 20 个左右有意思的，六个维度（真能用 / 解决具体环节 / 第一次见 / 野生 / 有真人用 / 可核可认领）各 0–2 分，每条一句为什么。分是编辑打的，每周公开。

## 仓库结构

```
data/site.json             站点文案与链接
data/method.md             方法页原文
data/submit.md             投稿页原文
data/found/<登记处>-<日期>.json   各登记处拉到的候选（可核）
data/screened/<日期>.json  过了四道门的网站 + 每道门的数字（搜索库的一周）
data/picks/<日期>.json     当周精选：网址 + 行业 + 为什么 + 六维度分
data/issues/<日期>.json    创刊号（旧方法：技能榜 + 应用榜），保留作对照
tools/discover.py          找：python3 tools/discover.py github hn hf v2ex   （github 可按天并行：--day 2026-10-20）
tools/screen.py            筛：python3 tools/screen.py <日期>
tools/collect.py / rank.py 创刊号用的采集与排名，v2ex 采集仍在用
build.py                   出静态站到 docs/：python3 build.py --poster
tools/shot.sh              海报截图（需本机 Chrome）
```

全部脚本只用 Python 标准库，没有第三方依赖。拉境外站点如需代理，设环境变量 `YEBANG_PROXY=http://host:port`；GitHub 搜索建议设 `GITHUB_TOKEN`（匿名每分钟只给 10 次）。

## 自己跑一遍核对

```
python3 tools/collect.py v2ex
python3 tools/discover.py hn hf v2ex
for d in 2026-10-19 2026-10-20 2026-10-21 2026-10-22 2026-10-23 2026-10-24 2026-10-25 2026-10-26; do python3 tools/discover.py github --day $d; done
python3 tools/screen.py 2026-10-26
python3 build.py
```

得到的 `data/screened/2026-10-26.json` 应和仓库里的大致一致（登记处的数据在变、存活检查在发布当天跑，隔天跑会差一些）。精选 `data/picks/` 是编辑挑的，不由脚本生成。
