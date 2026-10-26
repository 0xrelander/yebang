#!/bin/zsh
# 用本机 Chrome 无头截图海报页：shot.sh <html 文件> <输出 png> [宽 高]
# 默认 1080x1440（小红书 3:4），设备像素比 2 → 实际 2160x2880
set -e
HTML="$1"; OUT="$2"; W="${3:-1080}"; H="${4:-1440}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ABS=$(cd "$(dirname "$HTML")" && pwd)/$(basename "$HTML")
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check \
  --force-device-scale-factor=2 --window-size="${W},${H}" \
  --virtual-time-budget=3000 \
  --screenshot="$OUT" "file://$ABS" >/dev/null 2>&1
ls -la "$OUT"
