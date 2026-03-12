#!/bin/bash
set -e

echo "============================================"
echo "  Building Riff Pilot for macOS"
echo "============================================"
echo ""

# Step 1: Convert .ico to .icns if needed
if [ ! -f "app_icon.icns" ]; then
    echo "[0/3] Converting icon to macOS format..."
    if [ -f "app_icon.ico" ]; then
        # Create temporary iconset
        mkdir -p app_icon.iconset
        sips -z 16 16     app_icon.ico --out app_icon.iconset/icon_16x16.png      2>/dev/null || true
        sips -z 32 32     app_icon.ico --out app_icon.iconset/icon_16x16@2x.png   2>/dev/null || true
        sips -z 32 32     app_icon.ico --out app_icon.iconset/icon_32x32.png      2>/dev/null || true
        sips -z 64 64     app_icon.ico --out app_icon.iconset/icon_32x32@2x.png   2>/dev/null || true
        sips -z 128 128   app_icon.ico --out app_icon.iconset/icon_128x128.png    2>/dev/null || true
        sips -z 256 256   app_icon.ico --out app_icon.iconset/icon_128x128@2x.png 2>/dev/null || true
        sips -z 256 256   app_icon.ico --out app_icon.iconset/icon_256x256.png    2>/dev/null || true
        sips -z 512 512   app_icon.ico --out app_icon.iconset/icon_256x256@2x.png 2>/dev/null || true
        sips -z 512 512   app_icon.ico --out app_icon.iconset/icon_512x512.png    2>/dev/null || true
        sips -z 1024 1024 app_icon.ico --out app_icon.iconset/icon_512x512@2x.png 2>/dev/null || true
        iconutil -c icns app_icon.iconset -o app_icon.icns
        rm -rf app_icon.iconset
        echo "  Icon converted to app_icon.icns"
    else
        echo "  WARNING: app_icon.ico not found. Build will proceed without a custom icon."
    fi
fi

# Step 2: Build with PyInstaller
echo "[1/2] Building application with PyInstaller..."
python3 -m PyInstaller --clean --noconfirm RiffPilot_mac.spec
if [ $? -ne 0 ]; then
    echo "BUILD FAILED"
    exit 1
fi

echo ""
echo "[2/2] Build complete!"
echo ""
echo "Output:  dist/Riff Pilot.app"
echo ""
echo "To create a DMG installer, run:  ./create_dmg.sh"
