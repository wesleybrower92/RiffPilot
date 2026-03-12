#!/bin/bash
set -e

APP_NAME="Riff Pilot"
DMG_NAME="RiffPilot_1.0.0_macOS"
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/${DMG_NAME}.dmg"

echo "============================================"
echo "  Creating DMG Installer for ${APP_NAME}"
echo "============================================"
echo ""

# Verify the .app exists
if [ ! -d "${APP_PATH}" ]; then
    echo "ERROR: ${APP_PATH} not found."
    echo "Run ./build_mac.sh first."
    exit 1
fi

# Remove old DMG if it exists
rm -f "${DMG_PATH}"

# Create a temporary directory for the DMG contents
DMG_TEMP="dist/dmg_temp"
rm -rf "${DMG_TEMP}"
mkdir -p "${DMG_TEMP}"

# Copy the app bundle
cp -R "${APP_PATH}" "${DMG_TEMP}/"

# Create a symlink to /Applications for drag-and-drop install
ln -s /Applications "${DMG_TEMP}/Applications"

# Create the DMG
echo "Creating DMG..."
hdiutil create -volname "${APP_NAME}" \
    -srcfolder "${DMG_TEMP}" \
    -ov -format UDZO \
    "${DMG_PATH}"

# Clean up
rm -rf "${DMG_TEMP}"

echo ""
echo "DMG created: ${DMG_PATH}"
echo ""
echo "Upload this file to GitHub Releases alongside the Windows installer."
