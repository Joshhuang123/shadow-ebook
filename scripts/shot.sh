#!/bin/bash
# 截图辅助脚本 (开发用,不属于应用)
#   ./scripts/shot.sh <输出名> [宽] [高] [URL后缀]
# 用一次性 profile 截图,避免上一次调试写进 localStorage 的状态(比如主题)污染结果。
set -euo pipefail
NAME="${1:?用法: shot.sh 输出名 [宽] [高] [URL后缀]}"
W="${2:-1180}"
H="${3:-860}"
SUFFIX="${4:-}"
PROFILE="$(mktemp -d)"
trap 'rm -rf "$PROFILE"' EXIT

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --headless --disable-gpu --hide-scrollbars \
    --user-data-dir="$PROFILE" \
    --window-size="$W,$H" \
    --virtual-time-budget=6000 \
    --screenshot="/tmp/$NAME.png" \
    "http://127.0.0.1:5002/$SUFFIX" 2>/dev/null
echo "/tmp/$NAME.png"
