#!/bin/bash
# Shadow Learning - Quick Setup Script

echo "🦊 Shadow Learning Setup"
echo "========================"

# === Python 版本门槛 ===
# 代码用了 `dict | None` 语法 (PEP 604, 3.10+) 和 match 之类的新特性,
# 实测 3.9 会在 import 阶段就 TypeError,不是运行时才炸。所以必须在建 venv 之前拦。
# 坑: macOS 自带 /usr/bin/python3 常年是 3.9,而 `python3` 命中的就是它。
#     brew 装的 3.11+ 在 /opt/homebrew/bin,不一定在 PATH 最前面。
MIN_PY_MAJOR=3
MIN_PY_MINOR=11

# CI (.github/workflows/test.yml) 固定在 3.12,优先挑它 —— 默认路径要和 CI 验证过的
# 版本一致,而不是"能装上最新的就装最新的"。requirements-dev.txt 里的
# torch / openai-whisper / PyAudio 都是要编译或挑预编译 wheel 的重依赖,
# 刚发布的 Python 版本往往还没有对应 wheel,装 venv 容易卡在最后一步。
PREFERRED_PYTHON=python3.12

_meets_min() {
    v=$("$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || return 1
    major=${v%%.*}; minor=${v##*.}
    [ "$major" -gt "$MIN_PY_MAJOR" ] || { [ "$major" -eq "$MIN_PY_MAJOR" ] && [ "$minor" -ge "$MIN_PY_MINOR" ]; }
}

find_python() {
    # 优先用用户显式指定的 SHADOW_PYTHON(显式指定就不做版本判断,用户自己负责)
    if [ -n "$SHADOW_PYTHON" ]; then
        echo "$SHADOW_PYTHON"
        return
    fi
    # 先找 CI 同款
    if command -v "$PREFERRED_PYTHON" >/dev/null 2>&1 && _meets_min "$PREFERRED_PYTHON"; then
        echo "$PREFERRED_PYTHON"
        return
    fi
    # 再退而求其次,任何满足门槛的解释器
    for c in python3.13 python3.12 python3.11 python3 python; do
        command -v "$c" >/dev/null 2>&1 || continue
        if _meets_min "$c"; then
            echo "$c"
            return
        fi
    done
    echo ""
}

PYTHON_BIN=$(find_python)
if [ -z "$PYTHON_BIN" ]; then
    echo ""
    echo "❌ 没找到 Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+"
    echo ""
    echo "   本项目用了 PEP 604 联合类型语法 (dict | None),3.10 以下 import 就崩。"
    echo "   macOS 自带的 /usr/bin/python3 是 3.9,不能直接用。"
    echo ""
    echo "   装一个:"
    echo "     brew install python@3.12        # 推荐"
    echo "   或指定已有的解释器:"
    echo "     SHADOW_PYTHON=/path/to/python3.12 bash setup.sh"
    echo ""
    exit 1
fi

PY_VERSION=$("$PYTHON_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
echo "🐍 Using $PYTHON_BIN (Python $PY_VERSION)"
if [ "$PYTHON_BIN" != "python3" ]; then
    echo "   (系统默认的 python3 版本不够,已自动改用这个)"
fi
echo ""

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    "$PYTHON_BIN" -m venv venv
    echo "✅ Virtual environment created"
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "📦 Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Install system dependencies for phonemizer (if needed)
echo "🔧 Installing system dependencies for phonemizer..."
# For phonemizer on macOS:
if [[ "$OSTYPE" == "darwin"* ]]; then
    # No additional system deps needed for basic phonemizer
    echo "  ✅ Phonemizer ready"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Activate venv: source venv/bin/activate"
echo "  2. Run app: python app.py"
echo "  3. Open browser: http://localhost:5002"
echo "  4. Import an EPUB and start reading"
echo ""
echo "Optional extras (录音跟读 AI 反馈 / 桌面打包 / e2e):"
echo "  pip install -r requirements-dev.txt"
echo ""
echo "Tip: Add this to your shell profile for auto-activation:"
echo "  echo 'source $(pwd)/venv/bin/activate' >> ~/.zshrc"
