#!/bin/bash
# 建構 macOS App + DMG
# 用法: ./build.sh

set -e
cd "$(dirname "$0")"

APP_NAME="PikminUSB"
VERSION="1.0.0"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"

echo "========================================"
echo "🦐 皮克敏 GPS USB 控制 - macOS 建構"
echo "========================================"

# 1. Build with cx_Freeze
echo ""
echo "[1/3] 使用 cx_Freeze 建構 App..."
python3 setup.py build 2>&1

APP_PATH="dist/${APP_NAME}.app"

if [ ! -d "$APP_PATH" ]; then
    echo "❌ 建構失敗，找不到 $APP_PATH"
    exit 1
fi

echo "✅ App 建構完成: $APP_PATH"

# 2. 複製必要資源
echo ""
echo "[2/3] 複製必要資源..."
# The app.py 已經包含所有程式碼，不需要額外複製

# 3. 建立 DMG
echo ""
echo "[3/3] 建立 DMG..."

# 建立暫時目錄
TEMP_DIR="/tmp/${APP_NAME}_dmg"
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

# 複製 App
cp -R "$APP_PATH" "$TEMP_DIR/"

# 建立 Applications 連結
ln -s "/Applications" "$TEMP_DIR/Applications"

# 建立 DMG
hdiutil create -volname "${APP_NAME} ${VERSION}" \
    -srcfolder "$TEMP_DIR" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "dist/${DMG_NAME}" 2>&1

rm -rf "$TEMP_DIR"

echo ""
echo "========================================"
echo "✅ 建構完成！"
echo "========================================"
echo ""
echo "📦 DMG 位置: dist/${DMG_NAME}"
echo "📱 安裝方式: 雙擊 DMG 將 App 拖到 Applications"
echo ""
echo "⚠️  首次執行需要在 Mac 終端機執行一次:"
echo "   xattr -cr '/Applications/PikminUSB.app'"
echo ""
echo "📋 前置需求:"
echo "   1. brew install libimobiledevice"
echo "   2. 插上 iPhone 並信任此 Mac"
echo "   3. 開啟 App 即可控制 GPS"
echo ""
ls -lh "dist/${DMG_NAME}"
