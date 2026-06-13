#!/bin/bash
# Shadow Learning 启动脚本（局域网版）
# 用于社团部署，一台电脑服务，多台平板/电脑访问

echo "🦊 Shadow Learning - 原版阅读社团版"
echo "======================================"
echo ""

# 获取本机局域网 IP
if [[ "$OSTYPE" == "darwin"* ]]; then
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "localhost")
else
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
fi

echo "📡 局域网地址: http://$LOCAL_IP:5002"
echo "📱 在平板/电脑上打开浏览器，访问上面的地址"
echo ""

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
    echo "✅ 虚拟环境已创建"
fi

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source venv/bin/activate

# 检查依赖
echo "📦 检查依赖..."
pip install -r requirements.txt -q 2>/dev/null

echo ""
echo "🚀 启动服务中..."
echo "   按 Ctrl+C 停止服务"
echo ""

# 启动服务（绑定 0.0.0.0 局域网可访问）
python3 app.py
