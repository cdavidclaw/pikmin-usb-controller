#!/usr/bin/env python3
"""
🦐 皮克敏 GPS 控制工具 (macOS App)
透過 Xcode devicectl 控制 iPhone GPS，穩定不崩潰

使用方法：
  python3 app.py

需求：
  1. Xcode Command Line Tools: sudo xcode-select --install
  2. iPhone 插上 USB 並信任此 Mac
  3. iPhone 開啟 Developer Mode（設定 > 隱私與安全性 > Developer Mode）
"""

import os
import sys
import math
import time
import json
import subprocess
import threading
import queue
import random

# ============ Xcode Location Bridge ============

def get_xcode_devices():
    """取得已連接的 iOS 設備"""
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
                })
        return devices
    except Exception:
        return []

def get_idevice_udid():
    """用 idevice_id 取得 UDID（備用）"""
    try:
        result = subprocess.run(['idevice_id', '-l'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            udids = [u.strip() for u in result.stdout.strip().split('\n') if u.strip()]
            return udids[0] if udids else None
    except:
        pass
    return None

def set_location_xcode(udid: str, lat: float, lng: float, timeout: int = 10) -> tuple:
    """透過 Xcode devicectl 設定位置"""
    try:
        proc = subprocess.Popen(
            ['xcrun', 'devicectl', 'devices', 'set', 'location',
             '--device', udid,
             '--latitude', str(lat),
             '--longitude', str(lng)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            if proc.returncode == 0:
                return True, "OK"
            err = stderr.decode().strip()
            return False, err or "設定失敗"
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return False, "Xcode 命令超時"
    except FileNotFoundError:
        return False, "xcrun not found\n請安裝 Xcode Command Line Tools:\nsudo xcode-select --install"
    except Exception as e:
        return False, str(e)

def check_xcode() -> tuple:
    """檢查 Xcode 是否可用"""
    try:
        result = subprocess.run(['xcrun', '--version'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0] if result.stdout else "OK"
            return True, version
        return False, "xcrun not working"
    except FileNotFoundError:
        return False, "Xcode Command Line Tools 未安裝"
    except Exception as e:
        return False, str(e)

# ============ GPS Engine ============

KMH_TO_MS = 1.0 / 3.6
STEPS_PER_KM = 1320

SPEED_PRESETS = [
    ("🌸 花園", 3.5),
    ("🚶 走路", 5.0),
    ("⚠️ 快走", 6.5),
    ("🚨 衝刺", 8.5),
]

class GPSEngine:
    def __init__(self):
        self.lat = 25.0330
        self.lng = 121.5654
        self.altitude = 30.0
        self.speed_kmh = 5.0
        self.course = 0.0
        self.is_moving = False
        self.walked_km = 0.0
        self.walked_steps = 0
        self.walk_start = None
        self.last_fruit_check_km = 0.0
        self.patrol_active = False
        self.patrol_start_lat = 0.0
        self.patrol_start_lng = 0.0
        self.patrol_distance_m = 50
        self.pet_mode = False
        self.pet_last_move = 0
        self._lock = threading.Lock()
        self._last_set = (0, 0)
        self._set_count = 0

    def speed_ms(self):
        return self.speed_kmh * KMH_TO_MS

    def move_toward(self, bearing, dist_m):
        b = math.radians(bearing)
        R = 6371000
        lat1 = math.radians(self.lat)
        lng1 = math.radians(self.lng)
        lat2 = math.asin(math.sin(lat1)*math.cos(dist_m/R) +
                         math.cos(lat1)*math.sin(dist_m/R)*math.cos(b))
        lng2 = lng1 + math.atan2(
            math.sin(b)*math.sin(dist_m/R)*math.cos(lat1),
            math.cos(dist_m/R) - math.sin(lat1)*math.sin(lat2))
        with self._lock:
            self.lat = math.degrees(lat2)
            self.lng = math.degrees(lng2)
            self.walked_km += dist_m / 1000.0
            self.walked_steps += int(dist_m / (1000.0 / STEPS_PER_KM))

    def apply_location(self, udid: str, force: bool = False):
        with self._lock:
            lat, lng = self.lat, self.lng
        
        # 避免重複設定（位置變化夠大才設）
        if not force:
            if (abs(lat - self._last_set[0]) < 0.000015 and
                abs(lng - self._last_set[1]) < 0.000015):
                return  # 位置沒變，不重設
        
        ok, msg = set_location_xcode(udid, lat, lng)
        if ok:
            with self._lock:
                self._last_set = (lat, lng)
                self._set_count += 1
        return ok, msg

    def tick(self):
        with self._lock:
            if self.is_moving and self.speed_kmh > 0:
                if self.patrol_active:
                    self._patrol()
                else:
                    self.move_toward(self.course, self.speed_ms())
            if self.pet_mode:
                self._pet_move()

    def _patrol(self):
        self.move_toward(self.course, self.speed_ms())
        moved = (abs(self.lat - self.patrol_start_lat) * 111000 +
                 abs(self.lng - self.patrol_start_lng) * 111000 * math.cos(math.radians(self.lat)))
        if moved >= self.patrol_distance_m:
            self.course = (self.course + 180) % 360

    def _pet_move(self):
        if time.time() - self.pet_last_move < 30:
            return
        angle = random.uniform(0, 360)
        dist = 2
        b = math.radians(angle)
        lat1 = math.radians(self.lat)
        R = 6371000
        lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) +
                         math.cos(lat1)*math.sin(dist/R)*math.cos(b))
        lng1 = math.radians(self.lng)
        lng2 = lng1 + math.atan2(math.sin(b)*math.sin(dist/R)*math.cos(lat1),
                                  math.cos(dist/R)-math.sin(lat1)*math.sin(lat2))
        with self._lock:
            self.lat = math.degrees(lat2)
            self.lng = math.degrees(lng2)
        self.pet_last_move = time.time()

    def start(self):
        with self._lock:
            self.is_moving = True
            if not self.walk_start:
                self.walk_start = time.time()
            if self.patrol_active:
                self.patrol_start_lat = self.lat
                self.patrol_start_lng = self.lng

    def stop(self):
        with self._lock:
            self.is_moving = False

    def reset(self):
        with self._lock:
            self.walked_km = 0.0
            self.walked_steps = 0
            self.walk_start = time.time()
            self.last_fruit_check_km = 0.0
            self.patrol_active = False
            self.pet_mode = False

    def set_speed(self, kmh):
        with self._lock:
            self.speed_kmh = max(0.5, min(50.0, float(kmh)))

    def set_heading(self, deg):
        with self._lock:
            self.course = float(deg) % 360

    def set_pos(self, lat, lng):
        with self._lock:
            self.lat = float(lat)
            self.lng = float(lng)
            self._last_set = (float(lat), float(lng))

    def set_patrol(self, on):
        with self._lock:
            self.patrol_active = on
            if on:
                self.patrol_start_lat = self.lat
                self.patrol_start_lng = self.lng

    def set_pet(self, on):
        with self._lock:
            self.pet_mode = on
            if on:
                self.pet_last_move = 0

    def get_elapsed(self):
        if self.walk_start:
            return int(time.time() - self.walk_start)
        return 0

engine = GPSEngine()

# ============ UI ============

try:
    import tkinter as tk
except ImportError:
    print("需要 tkinter")
    sys.exit(1)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("皮克敏 GPS 控制")
        self.geometry("480x680")
        self.resizable(False, False)
        self.configure(bg="#1e1e1e")
        
        self.udid = None
        self.worker_running = True
        self.msg_queue = queue.Queue()
        
        # Colors
        self.green = "#34C759"
        self.orange = "#FF9F0A"
        self.red = "#FF3B30"
        self.blue = "#0a84ff"
        self.gray = "#3d3d3d"
        self.fg2 = "#8e8e93"
        
        self._build_ui()
        self._check_device()
        self._start_worker()
        self._process_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        bg = "#1e1e1e"
        bg2 = "#2d2d2d"
        fg = "#ffffff"
        fg2 = "#8e8e93"
        green = "#34C759"
        orange = "#FF9F0A"
        red = "#FF3B30"
        blue = "#0a84ff"
        gray = "#3d3d3d"

        def btn(parent, text, cmd, **kw):
            d = dict(bg=gray, fg=fg, relief="flat", bd=0,
                    padx=10, pady=6, font=("SF Pro Display", 12))
            d.update(kw)
            return tk.Button(parent, command=cmd, **d)

        # Title
        tk.Label(self, text="皮克敏 GPS 控制",
                font=("SF Pro Display", 18, "bold"),
                bg=bg, fg=orange).pack(pady=(16, 4))
        
        tk.Label(self, text="使用 Xcode devicectl · 穩定不崩潰",
                font=("SF Pro Text", 10), bg=bg, fg=fg2).pack(pady=(0, 12))

        # Device Status
        self.dev_frame = tk.Frame(self, bg=bg2)
        self.dev_frame.pack(fill="x", padx=20, pady=(0, 12))
        self.dev_label = tk.Label(self.dev_frame, text="  掃描設備...",
                                  font=("SF Pro Text", 12), bg=bg2, fg=fg2)
        self.dev_label.pack(pady=10)

        # Status Info
        info = tk.Frame(self, bg=bg)
        info.pack(fill="x", padx=20, pady=4)
        
        self.loc_label = tk.Label(info, text="📍 位置: —",
                                  font=("SF Mono", 11), bg=bg, fg=green)
        self.loc_label.pack(anchor="w")
        
        self.status_label = tk.Label(info, text="🚶 待機",
                                     font=("SF Pro Text", 12), bg=bg, fg=fg2)
        self.status_label.pack(anchor="w")
        
        self.stats_label = tk.Label(info, text="📊 0.00km | 0步 | 00:00",
                                    font=("SF Pro Text", 11), bg=bg, fg=fg2)
        self.stats_label.pack(anchor="w")
        
        self.setcount_label = tk.Label(info, text="✅ 已設定: 0 次",
                                      font=("SF Pro Text", 10), bg=bg, fg=fg2)
        self.setcount_label.pack(anchor="w")

        tk.Frame(self, bg="#3d3d3d", height=1).pack(fill="x", padx=20, pady=10)

        # Speed
        sf = tk.Frame(self, bg=bg)
        sf.pack(fill="x", padx=20, pady=4)
        tk.Label(sf, text="速度", font=("SF Pro Text", 11, "bold"),
                 bg=bg, fg=fg2).pack(anchor="w", pady=(0, 6))
        
        sb = tk.Frame(sf, bg=bg)
        sb.pack()
        for label, kmh in SPEED_PRESETS:
            btn(sb, label, lambda k=kmh: self._set_speed(k),
               bg=gray).pack(side="left", expand=True, fill="x", padx=2)
        
        cf = tk.Frame(sf, bg=bg)
        cf.pack(fill="x", pady=(6, 0))
        tk.Label(cf, text="自訂 km/h:", bg=bg, fg=fg2).pack(side="left")
        self.speed_entry = tk.Entry(cf, width=8, font=("SF Mono", 12),
                                    bg=bg2, fg=fg, insertbackground=fg, relief="flat")
        self.speed_entry.insert(0, "5.0")
        self.speed_entry.pack(side="left", padx=8)
        self.speed_entry.bind("<Return>", lambda e: self._set_speed(float(self.speed_entry.get())))
        btn(cf, "設定", lambda: self._set_speed(float(self.speed_entry.get())),
           bg=blue).pack(side="left")

        # Direction
        df = tk.Frame(self, bg=bg)
        df.pack(fill="x", padx=20, pady=8)
        tk.Label(df, text="方向", font=("SF Pro Text", 11, "bold"),
                 bg=bg, fg=fg2).pack(anchor="w", pady=(0, 6))
        
        dirs = [("↑ 北", 0), ("→ 東", 90), ("↓ 南", 180), ("← 西", 270),
                ("↗ NE", 45), ("↘ SE", 135), ("↙ SW", 225), ("↖ NW", 315)]
        
        db = tk.Frame(df, bg=bg)
        db.pack()
        for i, (label, deg) in enumerate(dirs):
            btn(db, label, lambda d=deg: self._set_dir(d),
               bg=gray, font=("SF Pro Text", 10)).grid(
                   row=i//4, column=i%4, padx=2, pady=2, sticky="ew")
        for i in range(4):
            db.columnconfigure(i, weight=1)

        # Mode
        mf = tk.Frame(self, bg=bg)
        mf.pack(fill="x", padx=20, pady=4)
        
        self.patrol_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mf, text="🚶 來回巡邏（50m）",
                      variable=self.patrol_var, command=self._toggle_patrol,
                      bg=bg, fg=green, selectcolor=bg2,
                      activebackground=bg, font=("SF Pro Text", 12)).pack(anchor="w")
        
        self.pet_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mf, text="🐾 寵物模式（自動小幅移動）",
                      variable=self.pet_var, command=self._toggle_pet,
                      bg=bg, fg=orange, selectcolor=bg2,
                      activebackground=bg, font=("SF Pro Text", 12)).pack(anchor="w")

        # Control
        cf = tk.Frame(self, bg=bg)
        cf.pack(fill="x", padx=20, pady=12)
        
        self.start_btn = btn(cf, "▶ 開始", self._start,
                           bg=green, font=("SF Pro Display", 14, "bold"))
        self.start_btn.pack(side="left", expand=True, fill="x", padx=3)
        
        self.stop_btn = btn(cf, "⏹ 停止", self._stop,
                           bg=red, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=3)
        
        self.reset_btn = btn(cf, "🔄 歸零", self._reset, bg=gray)
        self.reset_btn.pack(side="left", expand=True, fill="x", padx=3)

        # Direct coordinate input
        coord_frame = tk.Frame(self, bg=bg2)
        coord_frame.pack(fill="x", padx=20, pady=(0, 12))
        
        tk.Label(coord_frame, text="📍 直接輸入座標（一鍵傳送）",
                 font=("SF Pro Text", 10), bg=bg2, fg=fg2).pack(anchor="w", padx=10, pady=(6, 0))
        
        coord_input = tk.Frame(coord_frame, bg=bg2)
        coord_input.pack(pady=6, padx=10)
        
        tk.Label(coord_input, text="緯度:", bg=bg2, fg=fg).pack(side="left")
        self.lat_entry = tk.Entry(coord_input, width=14, font=("SF Mono", 11),
                                 bg=bg, fg=fg, insertbackground=fg, relief="flat")
        self.lat_entry.insert(0, "25.0330")
        self.lat_entry.pack(side="left", padx=(4, 12))
        
        tk.Label(coord_input, text="經度:", bg=bg2, fg=fg).pack(side="left")
        self.lng_entry = tk.Entry(coord_input, width=14, font=("SF Mono", 11),
                                 bg=bg, fg=fg, insertbackground=fg, relief="flat")
        self.lng_entry.insert(0, "121.5654")
        self.lng_entry.pack(side="left", padx=(4, 0))
        
        btn(coord_frame, "🚀 傳送到 iPhone",
           self._send_coord, bg=blue, font=("SF Pro Text", 11)).pack(pady=(0, 8))

        # Log
        log_frame = tk.Frame(self, bg=bg)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        
        self.log_text = tk.Text(log_frame, height=4, font=("SF Mono", 9),
                                bg=bg, fg="#636366", relief="flat", bd=0,
                                state="disabled", wrap="word")
        self.log_text.pack(fill="x")

    def _log(self, msg):
        self.msg_queue.put(msg)

    def _process_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self.log_text.config(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._process_queue)

    def _check_device(self):
        ok, msg = check_xcode()
        if ok:
            self._log(f"Xcode: {msg}")
            devices = get_xcode_devices()
            if devices:
                self.udid = devices[0]['udid']
                self.dev_label.config(text=f"  🔌 {devices[0]['name']}", fg=self.green)
                self.dev_frame.config(bg="#1d3d1d")
                self.dev_label.config(bg="#1d3d1d")
                self._log(f"設備: {devices[0]['name']}")
                # 立即設定一次
                ok2, msg2 = engine.apply_location(self.udid, force=True)
                if ok2:
                    self._log(f"初始位置設定成功")
                else:
                    self._log(f"初始位置: {msg2}")
            else:
                # 嘗試用 idevice_id
                udid = get_idevice_udid()
                if udid:
                    self.udid = udid
                    self.dev_label.config(text=f"  🔌 iPhone ({udid[:8]})", fg=self.orange)
                    self._log(f"找到設備 (idevice): {udid}")
                else:
                    self.dev_label.config(text="  ⚠️ 未找到設備", fg=self.red)
                    self.dev_frame.config(bg="#3d1d1d")
                    self.dev_label.config(bg="#3d1d1d")
        else:
            self.dev_label.config(text=f"  ❌ {msg}", fg=self.red)
            self.dev_frame.config(bg="#3d1d1d")
            self.dev_label.config(bg="#3d1d1d")
            self._log(f"Xcode 問題: {msg}")
        
        self.after(3000, self._check_device)

    def _set_speed(self, kmh):
        engine.set_speed(kmh)
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, str(kmh))
        self._log(f"速度: {kmh} km/h")

    def _set_dir(self, deg):
        engine.set_heading(deg)
        self._log(f"方向: {deg}°")
        if self.udid:
            ok, msg = engine.apply_location(self.udid, force=True)
            if ok:
                self._log(f"位置: {engine.lat:.6f}, {engine.lng:.6f}")

    def _toggle_patrol(self):
        engine.set_patrol(self.patrol_var.get())
        self._log(f"巡邏: {'開' if self.patrol_var.get() else '關'}")

    def _toggle_pet(self):
        engine.set_pet(self.pet_var.get())
        self._log(f"寵物: {'開' if self.pet_var.get() else '關'}")

    def _start(self):
        engine.start()
        self.start_btn.config(state="disabled", bg=self.gray, fg=self.fg2)
        self.stop_btn.config(state="normal", bg=self.red, fg="#ffffff")
        if self.udid:
            ok, _ = engine.apply_location(self.udid, force=True)
            if ok:
                self._log(f"開始移動 ({engine.speed_kmh} km/h)")
            else:
                self._log(f"開始移動（位置設定失敗）")
        else:
            self._log(f"⚠️ 無設備，無法設定位置")

    def _stop(self):
        engine.stop()
        self.start_btn.config(state="normal", bg=self.green, fg="#ffffff")
        self.stop_btn.config(state="disabled", bg=self.gray, fg=self.fg2)
        self._log("停止")

    def _reset(self):
        engine.reset()
        self.patrol_var.set(False)
        self.pet_var.set(False)
        self._log("歸零")
        self._update_ui()

    def _send_coord(self):
        try:
            lat = float(self.lat_entry.get())
            lng = float(self.lng_entry.get())
            engine.set_pos(lat, lng)
            if self.udid:
                ok, msg = engine.apply_location(self.udid, force=True)
                if ok:
                    self._log(f"📍 已傳送: {lat}, {lng}")
                else:
                    self._log(f"❌ {msg}")
            else:
                self._log(f"⚠️ 無設備")
        except ValueError:
            self._log("⚠️ 座標格式錯誤")

    def _start_worker(self):
        def worker():
            while self.worker_running:
                engine.tick()
                if engine.is_moving or engine.pet_mode:
                    if self.udid:
                        engine.apply_location(self.udid)
                time.sleep(1.0)
                self.after(0, self._update_ui)
        
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _update_ui(self):
        try:
            e = engine.get_elapsed()
            self.loc_label.config(text=f"📍 {engine.lat:.6f}, {engine.lng:.6f}")
            
            if engine.is_moving:
                s = f"🚶 移動中 ({engine.speed_kmh} km/h)"
                c = "#34C759"
            elif engine.pet_mode:
                s, c = "🐾 寵物模式", "#FF9F0A"
            elif engine.patrol_active:
                s, c = "🚶 巡邏中", "#30D158"
            else:
                s, c = "⏸ 待機", "#8e8e93"
            
            self.status_label.config(text=s, fg=c)
            self.stats_label.config(
                text=f"📊 {engine.walked_km:.2f}km | {engine.walked_steps:,}步 | {e//60:02d}:{e%60:02d}")
            
            with engine._lock:
                sc = engine._set_count
            self.setcount_label.config(text=f"✅ 已設定: {sc} 次")
        except:
            pass

    def _on_close(self):
        self.worker_running = False
        self.destroy()

    def run(self):
        self.mainloop()


if __name__ == "__main__":
    print("皮克敏 GPS 控制工具")
    print("=" * 40)
    
    # 測試 Xcode
    ok, msg = check_xcode()
    print(f"Xcode: {'OK' if ok else 'FAIL'} - {msg}")
    
    if not ok:
        print("\n請先安裝 Xcode Command Line Tools:")
        print("  sudo xcode-select --install")
        print("\n或從 App Store 安裝 Xcode")
        print()
    
    # 測試設備
    devices = get_xcode_devices()
    if devices:
        print(f"找到設備: {devices[0]['name']}")
    else:
        udid = get_idevice_udid()
        if udid:
            print(f"找到設備 (idevice): {udid}")
        else:
            print("未找到 iOS 設備，請確認:")
            print("  1. USB 連接")
            print("  2. 已信任此 Mac")
            print("  3. iPhone 已解鎖")
    
    print("\n啟動 GUI...")
    print("=" * 40)
    
    app = App()
    app.run()
