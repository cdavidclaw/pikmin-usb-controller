"""
Xcode Location Simulation Bridge
透過 xcrun devicectl 控制 iPhone GPS

原理：使用 Xcode Developer Tools 的 devicectl 指令
不需要 idevicesetlocation，不會崩潰
"""

import subprocess
import time
import re
from typing import Optional, Tuple, List

def get_xcode_devices() -> List[dict]:
    """取得已連接的 iOS 設備（透過 xcrun devicectl）"""
    try:
        result = subprocess.run(
            ['xcrun', 'devicectl', 'list', 'devices', 'output-format', 'json'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return []
        
        import json
        data = json.loads(result.stdout)
        
        devices = []
        for dev in data.get('devices', []):
            if dev.get('platform') == 'com.apple.platform.iphoneos':
                devices.append({
                    'udid': dev.get('udid', ''),
                    'name': dev.get('name', 'Unknown iPhone'),
                    'status': dev.get('status', 'unknown'),
                    'model': dev.get('model', ''),
                })
        return devices
    except FileNotFoundError:
        return []
    except Exception:
        return []

def set_location_via_xcode(udid: str, lat: float, lng: float) -> Tuple[bool, str]:
    """
    透過 Xcode devicectl 設定 iPhone 位置
    這是最乾淨的方法，不會像 idevicesetlocation 那樣崩潰
    """
    try:
        # 方法1: xcrun devicectl (Xcode 15+)
        result = subprocess.run(
            ['xcrun', 'devicectl', 'devices', 'set', 'location',
             '--device', udid,
             '--latitude', str(lat),
             '--longitude', str(lng)],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            return True, "Xcode location set successfully"
        
        # 方法2: 嘗試舊語法
        result2 = subprocess.run(
            ['xcrun', 'devicectl', 'device', 'process', 'setlocation',
             '--device', udid,
             '--latitude', str(lat),
             '--longitude', str(lng)],
            capture_output=True, text=True, timeout=10
        )
        
        if result2.returncode == 0:
            return True, "Xcode location set (legacy)"
        
        return False, f"devicectl failed: {result.stderr[:100]}"
        
    except FileNotFoundError:
        return False, "xcrun not found. Please install Xcode Command Line Tools:\nsudo xcode-select --install"
    except subprocess.TimeoutExpired:
        return False, "Xcode devicectl timeout"
    except Exception as e:
        return False, str(e)

def reset_location_via_xcode(udid: str) -> Tuple[bool, str]:
    """重置 iPhone 到真實位置"""
    try:
        result = subprocess.run(
            ['xcrun', 'devicectl', 'devices', 'set', 'location',
             '--device', udid, '--location', 'gps'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, "Location reset"
        return False, result.stderr[:100]
    except Exception as e:
        return False, str(e)

def check_xcode_available() -> Tuple[bool, str]:
    """檢查 Xcode Command Line Tools 是否可用"""
    try:
        result = subprocess.run(
            ['xcrun', '--version'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0] if result.stdout else "unknown"
            return True, version
        return False, "xcrun not working"
    except FileNotFoundError:
        return False, "Xcode Command Line Tools not installed"
    except Exception as e:
        return False, str(e)

def get_idevices_id() -> List[str]:
    """使用 libimobiledevice 取得 UDID（當作備用）"""
    try:
        result = subprocess.run(
            ['idevice_id', '-l'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return [u.strip() for u in result.stdout.strip().split('\n') if u.strip()]
    except:
        pass
    return []

def test_xcode_location():
    """測試 Xcode location 控制"""
    print("=" * 50)
    print("Xcode Location Simulation 測試")
    print("=" * 50)
    
    # 檢查 Xcode
    ok, msg = check_xcode_available()
    print(f"Xcode CLT: {'✅' if ok else '❌'} {msg}")
    
    if not ok:
        print("\n請安裝 Xcode Command Line Tools:")
        print("  sudo xcode-select --install")
        print("\n或從 App Store 安裝 Xcode")
        return
    
    # 取得設備
    print("\n掃描已連接的 iOS 設備...")
    devices = get_xcode_devices()
    
    if devices:
        print(f"找到 {len(devices)} 個設備:")
        for d in devices:
            print(f"  ✅ {d['name']} ({d['udid'][:8]}...) - {d['status']}")
    else:
        # 嘗試用 idevice_id
        udids = get_idevices_id()
        if udids:
            print(f"找到 {len(udids)} 個設備 (via idevice_id):")
            for u in udids:
                print(f"  ✅ {u}")
        else:
            print("❌ 找不到任何 iOS 設備")
            print("\n請確認:")
            print("  1. iPhone 已用 USB 連接")
            print("  2. iPhone 已信任此 Mac")
            print("  3. iPhone 已解鎖")
            print("  4. Xcode 已開啟並辨識到此設備")
    
    print()
    print("=" * 50)

if __name__ == "__main__":
    test_xcode_location()
