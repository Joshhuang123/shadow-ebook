#!/bin/bash
# Shadow Learning - Quick Setup Script

echo "🦊 Shadow Learning Setup"
echo "========================"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
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
echo "  2. Run app: python3 main.py"
echo "  3. Load audio: load ted_Do schools_kill_creativity.wav"
echo "  4. Start practicing: practice"
echo ""
echo "Tip: Add this to your shell profile for auto-activation:"
echo "  echo 'source $(pwd)/venv/bin/activate' >> ~/.zshrc"
