#!/bin/bash
# Create macOS Desktop App for Shadow Learning

echo "🦊 Creating Desktop App..."

APP_DIR="$HOME/Desktop/ShadowLearning.app"
APP_CONTENTS="$APP_DIR/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"

# Create app structure
mkdir -p "$APP_MACOS"
mkdir -p "$APP_RESOURCES"

# Create main script
cat > "$APP_MACOS/ShadowLearning" << 'SCRIPT'
#!/bin/bash
# Shadow Learning - English Shadowing Practice App

cd "$HOME/shadow-learning"

# Check if venv exists
if [ ! -d "venv" ]; then
    osascript -e 'display dialog "First run: Setting up environment..." with title "Shadow Learning"'
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt 2>/dev/null
    osascript -e 'display dialog "Setup complete! Click OK to start." with title "Shadow Learning"'
fi

# Create terminal window and run
osascript << APPLESCRIPT
tell application "Terminal"
    do script "cd $HOME/shadow-learning && source venv/bin/activate && python3 main.py"
    set current settings of first window to settings set "Pro"
    activate
end tell
APPLESCRIPT
SCRIPT

chmod +x "$APP_MACOS/ShadowLearning"

# Create Info.plist
cat > "$APP_CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleExecutable</key><string>ShadowLearning</string>
    <key>CFBundleIconFile</key><string>icon.icns</string>
    <key>CFBundleIdentifier</key><string>com.shadowlearning.app</key>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleName</key><string>ShadowLearning</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>10.15</string>
    <key>NSHumanReadableCopyright</key><string>Copyright 2026. English Shadowing Practice.</string>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
</dict>
</plist>
PLIST

# Create icon using system tools
# Try to create a simple fox icon using sips and iconutil
ICON_SVG="$APP_RESOURCES/icon.svg"

# Create a simple SVG icon
cat > "$ICON_SVG" << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <rect width="256" height="256" fill="#FF6B35" rx="48"/>
  <text x="128" y="160" font-family="Arial" font-size="120" fill="white" text-anchor="middle">🦊</text>
  <text x="128" y="220" font-family="Arial" font-size="24" fill="white" text-anchor="middle">Shadow Learning</text>
</svg>
SVG

# Convert to PNG then to ICNS (requires imagemagick)
PNG_ICON="$APP_RESOURCES/icon.icns"
if command -v convert &> /dev/null; then
    convert -resize 256x256 "$ICON_SVG" "$PNG_ICON"
else
    # Use system icon as fallback - create a basic .icns structure
    # This is a placeholder; user can replace with real icon
    cat > "$APP_RESOURCES/README.txt" << 'README'
To customize the icon:
1. Create a 256x256 PNG image
2. Run: iconutil -c icns icon.png -o icon.icns
3. Replace this file with icon.icns
README
fi

echo "✅ Desktop app created at: $APP_DIR"
echo ""
echo "Next steps:"
echo "1. Open Desktop/ShadowLearning.app to run"
echo "2. First run will set up the environment"
echo ""
echo "Tip: Right-click the app → Get Info → Replace the icon for a custom look!"
