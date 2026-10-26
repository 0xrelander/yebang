# 野榜

野生好用的 AI 技能与应用，每周排一次。方法公开，数据可核。

- 网站：https://0xrelander.github.io/yebang/
- 方法：https://0xrelander.github.io/yebang/method.html
- 投稿 / 认领 / 纠错 / 下榜：用本仓库的 [Issue 表单](https://github.com/0xrelander/yebang/issues/new/choose)

## 排什么

- **技能榜**：独立开发者做的 agent 技能，跨 SkillHub、ClawHub、虾评Skill、skills.sh 合并后排。
- **应用榜**：普通人做出来、搜不到但好用的 AI 应用，来自扣子商店、V2EX 分享创造和投稿。

大厂官方出品、中转代理类、发布当天打不开的，不排。

## 仓库结构

```
data/site.json          站点文案与链接
data/method.md          方法页原文
data/submit.md          投稿页原文
data/raw/               每期各来源的原始回包（可核）
data/cands/             统一格式的候选
data/issues/<日期>.json  每期榜单
tools/collect.py        采集：python3 tools/collect.py xiaping skillhub clawhub skillssh coze v2ex
tools/rank.py           合并、打分、存活检查：python3 tools/rank.py <日期> <期号>
build.py                出静态站到 docs/：python3 build.py --poster
tools/shot.sh           海报截图（需本机 Chrome）
```

全部脚本只用 Python 标准库，没有第三方依赖。拉境外站点如需代理，设环境变量 `YEBANG_PROXY=http://host:port`。

## 自己跑一遍核对

```
python3 tools/collect.py xiaping skillhub clawhub skillssh coze v2ex
python3 tools/rank.py 2026-10-26 1
python3 build.py
```

得到的 `data/issues/2026-10-26.json` 应和仓库里的一致（存活检查在发布当天跑，隔天跑可能少几条）。
