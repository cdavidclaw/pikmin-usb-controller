# 🦐 皮克敏 GPS 控制工具 (macOS)

透過 Xcode devicectl 控制 iPhone GPS，穩定不崩潰。

## 功能

- ✅ **USB 直接控制** - 插著就能用，不需 WiFi
- ✅ **Xcode devicectl** - 使用 Apple 官方 Location Simulation，不會像 idevicesetlocation 那樣崩潰
- ✅ **速度控制** - 🌸 花園 / 🚶 走路 / ⚠️ 快走 / 🚨 衝刺
- ✅ **方向控制** - 8 方向 + 自訂角度
- ✅ **來回巡邏模式** - 自動來回走動
- ✅ **寵物模式** - 掛機時自動小幅移動
- ✅ **直接座標輸入** - 輸入經緯度一鍵傳送
- ✅ **狀態追蹤** - 累計距離、步數、時間

## 前置需求

### 1. Xcode Command Line Tools
```bash
sudo xcode-select --install
```

### 2. iPhone 設定
- 插上 USB 並信任此 Mac
- 開啟 **Developer Mode**：
  - 設定 → 隱私與安全性 → Developer Mode → 開啟
- 確保 iPhone 已解鎖

### 3. Xcode 識別設備
- 開啟 Xcode
- 插上 iPhone
- Xcode 選 Window → Devices and Simulators → 確認 iPhone 有出現

## 安裝

```bash
# Clone
git clone https://github.com/cdavidclaw/pikmin-usb-controller.git
cd pikmin-usb-controller

# 執行（需要 tkinter，macOS 內建）
python3 app.py
```

## 如果要打包成 App

```bash
pip3 install cx_Freeze
python3 setup.py build
```

## 常見問題

### Q: 執行後顯示 "Xcode Command Line Tools 未安裝"
**A:** 執行 `sudo xcode-select --install`，或從 App Store 安裝 Xcode

### Q: 找不到設備
**A:** 
1. 確認 iPhone USB 連接
2. iPhone 解鎖並信任此 Mac
3. 開啟 Xcode 確認能辨識到此設備
4. 確認 iPhone 已開啟 Developer Mode

### Q: idevicesetlocation 會崩潰，但這個版本不會嗎？
**A:** 這個版本使用 `xcrun devicectl`（Apple 官方工具），比 libimobiledevice 的 idevicesetlocation 穩定很多

## 技術原理

本工具使用 Apple 官方提供的 `xcrun devicectl` 指令：

```bash
xcrun devicectl devices set location \
  --device <UDID> \
  --latitude 25.033 \
  --longitude 121.565
```

這是 Xcode 對 iPhone 進行 Location Simulation 的底層工具，穩定度高。

## License

僅供個人學習使用。
