#!/bin/bash
# Shadow Learning - 启动 HTTPS 服务（iOS Safari 麦克风支持）
# 用法: bash start_https.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 生成自签名证书（如不存在）
bash scripts/gen_https_cert.sh

# 2. 获取本机局域网 IP
if [[ "$OSTYPE" == "darwin"* ]]; then
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "localhost")
else
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
fi

# 3. 激活虚拟环境
if [ ! -d "venv" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
fi
source venv/bin/activate

# 4. 检查依赖
pip install -r requirements.txt -q 2>/dev/null

echo ""
echo "🚀 启动 HTTPS 服务中..."
echo "   本机访问:   https://localhost:5002"
echo "   局域网访问: https://$LOCAL_IP:5002"
echo "   按 Ctrl+C 停止服务"
echo ""

python3 app.py
