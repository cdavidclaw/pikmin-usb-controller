#!/usr/bin/env python3
"""
皮克敏 GPS 控制工具 (macOS)
使用 Xcode devicectl，worker thread 不直接碰 UI
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
    try:
        result = subprocess.run(
            ['xcrun', 'devicectl', 'list', 'devices', 'output-format', 'json'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        devices = []
        for dev in data.get('devices', []):
            if dev.get('platform') == 'com.apple.platform.iphoneos':
                devices.append({
                    'udid': dev.get('udid', ''),
                    'name': dev.get('name', 'iPhone'),
                })
        return devices
    except Exception:
        return []

def get_idevice_udid():
    try:
        result = subprocess.run(['idevice_id', '-l'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            udids = [u.strip() for u in result.stdout.strip().split('\n') if u.strip()]
            return udids[0] if udids else None
    except:
        pass
    return None

def set_location_xcode(udid, lat, lng, timeout=8):
    try:
        proc = subprocess.Popen(
            ['xcrun', 'devicectl', 'devices', 'set', 'location',
             '--device', udid,
             '--latitude', str(lat),
             '--longitude', str(lng)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        if proc.returncode == 0:
            return True, "OK"
        return False, (stderr.decode().strip() or stdout.decode().strip())[:80]
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, "Xcode timeout"
    except FileNotFoundError:
        return False, "xcrun not found"
    except Exception as e:
        return False, str(e)[:80]

def check_xcode():
    try:
        r = subprocess.run(['xcrun', '--version'],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return True, r.stdout.strip().split('\n')[0]
        return False, "xcrun error"
    except Exception as e:
        return False, str(e)

# ============ GPS Engine ============

KMH_TO_MS = 1.0 / 3.6
STEPS_PER_KM = 1320

class GPSEngine:
    def __init__(self):
        self.lat = 25.0330
        self.lng = 121.5654
        self.speed_kmh = 5.0
        self.course = 0.0
        self.is_moving = False
        self.walked_km = 0.0
        self.walked_steps = 0
        self.walk_start = None
        self.patrol_active = False
        self.patrol_start_lat = 0.0
        self.patrol_start_lng = 0.0
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

    def set_location(self, udid):
        with self._lock:
            lat, lng = self.lat, self.lng
            sc = self._set_count
        # 避免重複設定
        if (abs(lat - self._last_set[0]) < 0.000015 and
            abs(lng - self._last_set[1]) < 0.000015):
            return None  # 位置沒變
        ok, msg = set_location_xcode(udid, lat, lng)
        if ok:
            with self._lock:
                self._last_set = (lat, lng)
                self._set_count += 1
        return (ok, lat, lng)

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
        with self._lock:
            moved = (abs(self.lat - self.patrol_start_lat) * 111000 +
                     abs(self.lng - self.patrol_start_lng) * 111000 * math.cos(math.radians(self.lat)))
            if moved >= 50:
                self.course = (self.course + 180) % 360

    def _pet_move(self):
        if time.time() - self.pet_last_move < 30:
            return
        angle = random.uniform(0, 360)
        dist = 2
        b = math.radians(angle)
        R = 6371000
        lat1 = math.radians(self.lat)
        lng1 = math.radians(self.lng)
        lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) +
                         math.cos(lat1)*math.sin(dist/R)*math.cos(b))
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

    def get_state(self):
        with self._lock:
            return {
                'lat': self.lat,
                'lng': self.lng,
                'speed': self.speed_kmh,
                'course': self.course,
                'moving': self.is_moving,
                'patrol': self.patrol_active,
                'pet': self.pet_mode,
                'walked_km': self.walked_km,
                'walked_steps': self.walked_steps,
                'walk_start': self.walk_start,
                'set_count': self._set_count,
            }

engine = GPSEngine()

# ============ Tkinter UI ============

try:
    import tkinter as tk
except ImportError:
    print("需要 tkinter")
    sys.exit(1)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("皮克敏 GPS 控制")
        self.geometry("480x700")
        self.resizable(False, False)
        self.configure(bg="#1e1e1e")
        
        self.udid = None
        self.worker_running = True
        self.ui_queue = queue.Queue()
        
        # 顏色
        self.C_GREEN = "#34C759"
        self.C_ORANGE = "#FF9F0A"
        self.C_RED = "#FF3B30"
        self.C_BLUE = "#0a84ff"
        self.C_GRAY = "#3d3d3d"
        self.C_BG = "#1e1e1e"
        self.C_BG2 = "#2d2d2d"
        self.C_FG = "#ffffff"
        self.C_FG2 = "#8e8e93"
        
        self._build_ui()
        self._check_device()
        self._start_worker()
        self._process_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        bg = self.C_BG
        bg2 = self.C_BG2
        fg = self.C_FG
        fg2 = self.C_FG2
        green = self.C_GREEN
        gray = self.C_GRAY
        blue = self.C_BLUE

        def btn(parent, text, cmd, **kw):
            d = dict(bg=gray, fg=fg, relief="flat", bd=0,
                    padx=10, pady=6, font=("SF Pro Display", 12))
            d.update(kw)
            return tk.Button(parent, command=cmd, **d)

        # Title
        tk.Label(self, text="皮克敏 GPS 控制",
                font=("SF Pro Display", 18, "bold"),
                bg=bg, fg=self.C_ORANGE).pack(pady=(16, 4))
        tk.Label(self, text="Xcode devicectl · 穩定版",
                font=("SF Pro Text", 10), bg=bg, fg=fg2).pack(pady=(0, 12))

        # Device
        self.dev_frame = tk.Frame(self, bg=bg2)
        self.dev_frame.pack(fill="x", padx=20, pady=(0, 12))
        self.dev_label = tk.Label(self.dev_frame, text="  掃描設備...",
                                  font=("SF Pro Text", 12), bg=bg2, fg=fg2)
        self.dev_label.pack(pady=10)

        # Info
        info = tk.Frame(self, bg=bg)
        info.pack(fill="x", padx=20, pady=4)
        self.loc_lbl = tk.Label(info, text="📍 位置: —",
                               font=("SF Mono", 11), bg=bg, fg=green)
        self.loc_lbl.pack(anchor="w")
        self.status_lbl = tk.Label(info, text="⏸ 待機",
                                  font=("SF Pro Text", 12), bg=bg, fg=fg2)
        self.status_lbl.pack(anchor="w")
        self.stats_lbl = tk.Label(info, text="📊 0.00km | 0步 | 00:00",
                                font=("SF Pro Text", 11), bg=bg, fg=fg2)
        self.stats_lbl.pack(anchor="w")
        self.setcount_lbl = tk.Label(info, text="✅ 已設定: 0 次",
                                    font=("SF Pro Text", 10), bg=bg, fg=fg2)
        self.setcount_lbl.pack(anchor="w")

        tk.Frame(self, bg="#3d3d3d", height=1).pack(fill="x", padx=20, pady=10)

        # Speed
        sf = tk.Frame(self, bg=bg)
        sf.pack(fill="x", padx=20, pady=4)
        tk.Label(sf, text="速度", font=("SF Pro Text", 11, "bold"),
                 bg=bg, fg=fg2).pack(anchor="w", pady=(0, 6))
        sb = tk.Frame(sf, bg=bg)
        sb.pack()
        for label, kmh in [("🌸 花園", 3.5), ("🚶 走路", 5.0), ("⚠️ 快走", 6.5), ("🚨 衝刺", 8.5)]:
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
        for i, (lbl, deg) in enumerate(dirs):
            btn(db, lbl, lambda d=deg: self._set_dir(d),
               bg=gray, font=("SF Pro Text", 10)).grid(
                   row=i//4, column=i%4, padx=2, pady=2, sticky="ew")
        for i in range(4):
            db.columnconfigure(i, weight=1)

        # Modes
        mf = tk.Frame(self, bg=bg)
        mf.pack(fill="x", padx=20, pady=4)
        self.patrol_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mf, text="🚶 來回巡邏（50m）",
                      variable=self.patrol_var, command=self._toggle_patrol,
                      bg=bg, fg=green, selectcolor=bg2,
                      activebackground=bg, font=("SF Pro Text", 12)).pack(anchor="w")
        self.pet_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mf, text="🐾 寵物模式",
                      variable=self.pet_var, command=self._toggle_pet,
                      bg=bg, fg=self.C_ORANGE, selectcolor=bg2,
                      activebackground=bg, font=("SF Pro Text", 12)).pack(anchor="w")

        # Control buttons
        ctrl = tk.Frame(self, bg=bg)
        ctrl.pack(fill="x", padx=20, pady=12)
        self.start_btn = btn(ctrl, "▶ 開始", self._do_start,
                           bg=green, font=("SF Pro Display", 14, "bold"))
        self.start_btn.pack(side="left", expand=True, fill="x", padx=3)
        self.stop_btn = btn(ctrl, "⏹ 停止", self._do_stop,
                           bg=self.C_RED, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=3)
        self.reset_btn = btn(ctrl, "🔄 歸零", self._do_reset, bg=gray)
        self.reset_btn.pack(side="left", expand=True, fill="x", padx=3)

        # Direct coordinate
        cf = tk.Frame(self, bg=bg2)
        cf.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(cf, text="📍 直接傳送座標到 iPhone",
                 font=("SF Pro Text", 10), bg=bg2, fg=fg2).pack(anchor="w", padx=10, pady=(6, 0))
        inp = tk.Frame(cf, bg=bg2)
        inp.pack(pady=6, padx=10)
        tk.Label(inp, text="緯度:", bg=bg2, fg=fg).pack(side="left")
        self.lat_entry = tk.Entry(inp, width=14, font=("SF Mono", 11),
                                 bg=bg, fg=fg, insertbackground=fg, relief="flat")
        self.lat_entry.insert(0, "25.0330")
        self.lat_entry.pack(side="left", padx=(4, 8))
        tk.Label(inp, text="經度:", bg=bg2, fg=fg).pack(side="left")
        self.lng_entry = tk.Entry(inp, width=14, font=("SF Mono", 11),
                                 bg=bg, fg=fg, insertbackground=fg, relief="flat")
        self.lng_entry.insert(0, "121.5654")
        self.lng_entry.pack(side="left", padx=(4, 0))
        btn(cf, "🚀 傳送", self._send_coord, bg=blue,
           font=("SF Pro Text", 11)).pack(pady=(0, 8))

        # Log
        log_frame = tk.Frame(self, bg=bg)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        self.log_text = tk.Text(log_frame, height=4, font=("Menlo", 9),
                               bg=bg, fg="#555555", relief="flat", bd=0,
                               state="disabled", wrap="word")
        self.log_text.pack(fill="x")

    def _log(self, msg):
        self.ui_queue.put(('log', msg))

    def _process_queue(self):
        """在主執行緒處理所有 UI 更新"""
        try:
            while True:
                try:
                    msg = self.ui_queue.get_nowait()
                    tag, data = msg if isinstance(msg, tuple) else ('log', msg)
                    
                    if tag == 'log':
                        self.log_text.config(state="normal")
                        self.log_text.insert("end", data + "\n")
                        self.log_text.see("end")
                        self.log_text.config(state="disabled")
                    
                    elif tag == 'location':
                        lat, lng, ok = data
                        self.loc_lbl.config(text=f"📍 {lat:.6f}, {lng:.6f}")
                    
                    elif tag == 'state':
                        s = data
                        if s['moving']:
                            self.status_lbl.config(text=f"🚶 移動中 ({s['speed']} km/h)", fg=self.C_GREEN)
                        elif s['pet']:
                            self.status_lbl.config(text="🐾 寵物模式", fg=self.C_ORANGE)
                        elif s['patrol']:
                            self.status_lbl.config(text="🚶 巡邏中", fg=self.C_GREEN)
                        else:
                            self.status_lbl.config(text="⏸ 待機", fg=self.C_FG2)
                        
                        e = int(time.time() - s['walk_start']) if s['walk_start'] else 0
                        self.stats_lbl.config(
                            text=f"📊 {s['walked_km']:.2f}km | {s['walked_steps']:,}步 | {e//60:02d}:{e%60:02d}")
                        self.setcount_lbl.config(text=f"✅ 已設定: {s['set_count']} 次")
                    
                    elif tag == 'start_ok':
                        self.start_btn.config(state="disabled", bg=self.C_GRAY, fg=self.C_FG2)
                        self.stop_btn.config(state="normal", bg=self.C_RED, fg=self.C_FG)
                    
                    elif tag == 'stop_ok':
                        self.start_btn.config(state="normal", bg=self.C_GREEN, fg=self.C_FG)
                        self.stop_btn.config(state="disabled", bg=self.C_GRAY, fg=self.C_FG2)
                    
                    elif tag == 'dev_found':
                        name, has_xcode = data
                        if has_xcode:
                            self.dev_label.config(text=f"  🔌 {name}", fg=self.C_GREEN)
                            self.dev_frame.config(bg="#1d3d1d")
                            self.dev_label.config(bg="#1d3d1d")
                        else:
                            self.dev_label.config(text=f"  ⚠️ {name}", fg=self.C_ORANGE)
                            self.dev_frame.config(bg="#3d3d1d")
                            self.dev_label.config(bg="#3d3d1d")
                    
                    elif tag == 'dev_error':
                        self.dev_label.config(text=f"  ❌ {data}", fg=self.C_RED)
                        self.dev_frame.config(bg="#3d1d1d")
                        self.dev_label.config(bg="#3d1d1d")
                
                except queue.Empty:
                    break
        except Exception as e:
            pass  # 不要讓 queue 處理拋出異常
        
        # 之後再檢查
        self.after(100, self._process_queue)

    def _check_device(self):
        ok, msg = check_xcode()
        if ok:
            self._log(f"Xcode: {msg}")
            devs = get_xcode_devices()
            if devs:
                self.udid = devs[0]['udid']
                self.ui_queue.put(('dev_found', (devs[0]['name'], True)))
                self._log(f"設備(xcrun): {devs[0]['name']}")
                # 立即設定一次
                r = engine.set_location(self.udid)
                if r:
                    self._log("初始位置設定成功")
                else:
                    self._log("初始位置已設定")
            else:
                udid = get_idevice_udid()
                if udid:
                    self.udid = udid
                    self.ui_queue.put(('dev_found', (f"iPhone ({udid[:8]})", False)))
                    self._log(f"設備(idevice): {udid}")
                else:
                    self.ui_queue.put(('dev_error', "未找到 iOS 設備"))
        else:
            self.ui_queue.put(('dev_error', msg))
        
        self.after(5000, self._check_device)

    def _set_speed(self, kmh):
        engine.set_speed(kmh)
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, str(kmh))
        self._log(f"速度: {kmh} km/h")

    def _set_dir(self, deg):
        engine.set_heading(deg)
        self._log(f"方向: {deg}")
        if self.udid:
            r = engine.set_location(self.udid)
            if r:
                self._log(f"位置: {r[1]:.6f}, {r[2]:.6f}")

    def _toggle_patrol(self):
        engine.set_patrol(self.patrol_var.get())
        self._log(f"巡邏: {'開' if self.patrol_var.get() else '關'}")

    def _toggle_pet(self):
        engine.set_pet(self.pet_var.get())
        self._log(f"寵物: {'開' if self.pet_var.get() else '關'}")

    def _do_start(self):
        engine.start()
        self.ui_queue.put(('start_ok', None))
        if self.udid:
            r = engine.set_location(self.udid)
            if r:
                self._log(f"開始移動 ({engine.speed_kmh} km/h)")
            else:
                self._log("開始移動")
        else:
            self._log("⚠️ 無設備")

    def _do_stop(self):
        engine.stop()
        self.ui_queue.put(('stop_ok', None))
        self._log("停止")

    def _do_reset(self):
        engine.reset()
        self.patrol_var.set(False)
        self.pet_var.set(False)
        self._log("歸零")
        self.ui_queue.put(('state', engine.get_state()))

    def _send_coord(self):
        try:
            lat = float(self.lat_entry.get())
            lng = float(self.lng_entry.get())
            engine.set_pos(lat, lng)
            if self.udid:
                r = engine.set_location(self.udid)
                if r:
                    self._log(f"📍 已傳送: {lat}, {lng}")
                else:
                    self._log(f"📍 座標已設定(位置相同): {lat}, {lng}")
            else:
                self._log("⚠️ 無設備")
        except ValueError:
            self._log("⚠️ 座標格式錯誤")

    def _start_worker(self):
        def worker():
            while self.worker_running:
                engine.tick()
                if engine.is_moving or engine.pet_mode:
                    if self.udid:
                        r = engine.set_location(self.udid)
                        # 把狀態更新放到 queue，不直接改 UI
                        self.ui_queue.put(('state', engine.get_state()))
                else:
                    # 停止時也定期更新 UI（因為有 set_count）
                    self.ui_queue.put(('state', engine.get_state()))
                time.sleep(1.0)
        
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_close(self):
        self.worker_running = False
        self.destroy()

    def run(self):
        self.mainloop()


if __name__ == "__main__":
    print("皮克敏 GPS 控制工具")
    print("=" * 40)
    
    ok, msg = check_xcode()
    print(f"Xcode: {'OK' if ok else 'FAIL'} - {msg}")
    
    devs = get_xcode_devices()
    if devs:
        print(f"xcrun 設備: {devs[0]['name']}")
    else:
        udid = get_idevice_udid()
        if udid:
            print(f"idevice 設備: {udid}")
        else:
            print("未找到 iOS 設備")
    
    print("\n啟動 GUI...")
    app = App()
    app.run()
