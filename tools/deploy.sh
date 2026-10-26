#!/bin/zsh
# 发布到 GitHub Pages：第一次建公开仓并开 Pages（main 分支 /docs 目录），之后只 commit + push
# 用法：tools/deploy.sh "提交说明"
set -e
cd "$(dirname "$0")/.."
OWNER=0xrelander; REPO=yebang
MSG="${1:-update}"
python3 build.py --poster
git add -A
git commit -qm "$MSG" || true
git config http.postBuffer 524288000   # 每期 raw 数据几十 MB，默认 buffer 会被远端掐断
if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  gh repo create "$OWNER/$REPO" --public --source=. --remote=origin \
    --description "野榜：野生好用的 AI 技能与应用，每周排一次。方法公开，数据可核。"
fi
git push -q -u origin HEAD:main
if ! gh api "repos/$OWNER/$REPO/pages" >/dev/null 2>&1; then
  gh api -X POST "repos/$OWNER/$REPO/pages" -f 'source[branch]=main' -f 'source[path]=/docs' >/dev/null
fi
echo "pages: $(gh api repos/$OWNER/$REPO/pages --jq .html_url 2>/dev/null)"
