#!/usr/bin/env python3
"""
🦐 皮克敏 GPS USB 控制工具 (macOS App)
直接透過 USB 控制 iPhone GPS，插著就能用

需要：brew install libimobiledevice
"""

import os
import sys
import math
import time
import json
import subprocess
import threading
import random
import queue

# ============ USB 控制 ============

def get_iphone_udid():
    """取得連接的 iPhone UDID"""
    try:
        result = subprocess.run(['idevice_id', '-l'], capture_output=True, text=True, timeout=5)
        udids = [u.strip() for u in result.stdout.strip().split('\n') if u.strip()]
        for udid in udids:
            try:
                info = subprocess.run(['ideviceinfo', '-u', udid, '-k', 'ProductType'],
                                    capture_output=True, text=True, timeout=5)
                if 'iPhone' in info.stdout:
                    return udid
            except:
                pass
        return udids[0] if udids else None
    except:
        return None

def get_iphone_name():
    """取得 iPhone 名稱"""
    udid = get_iphone_udid()
    if not udid:
        return None
    try:
        result = subprocess.run(['idevicename', '-u', udid],
                              capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except:
        return None

def set_iphone_location(lat, lng, timeout=5):
    """透過 USB 設定 iPhone 位置"""
    udid = get_iphone_udid()
    if not udid:
        return False, "找不到 iPhone"
    try:
        proc = subprocess.Popen(
            ['idevicesetlocation', '-u', udid, str(lat), str(lng)],
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
            return False, "USB 命令超時"
    except FileNotFoundError:
        return False, "idevicesetlocation 未安裝，請執行：\nbrew install libimobiledevice"
    except Exception as e:
        return False, str(e)

def check_usb():
    """檢查 USB 連接狀態"""
    udid = get_iphone_udid()
    if udid:
        name = get_iphone_name()
        return True, f"已連接 {name or udid[:8]}", udid
    return False, "未連接", None

# ============ 定位引擎 ============

KMH_TO_MS = 1.0 / 3.6
STEPS_PER_KM = 1320

SPEED_PRESETS = [
    ("🌸 花園", 3.5),
    ("🚶 走路", 5.0),
    ("⚠️ 快走", 6.5),
    ("🚨 衝刺", 8.5),
]

class LocationEngine:
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
        self.session_start = time.time()
        self.last_fruit_check_km = 0.0
        self.patrol_active = False
        self.patrol_start_lat = 0.0
        self.patrol_start_lng = 0.0
        self.patrol_distance_m = 50
        self.patrol_direction = 1
        self.pet_mode = False
        self.pet_last_move = 0
        self._lock = threading.Lock()
        self._last_usb = (0, 0)

    def speed_ms(self):
        return self.speed_kmh * KMH_TO_MS

    def pikmin_status(self):
        if self.speed_kmh <= 5.5: return "🌱 緊密跟隨"
        elif self.speed_kmh <= 7.0: return "⚠️ 開始落後"
        else: return "🚨 走散了！"

    def get_fruit_status(self):
        km = self.walked_km - self.last_fruit_check_km
        prob = min(0.95, km * 1000 / 450)
        if km * 1000 >= 250:
            return f"🌸 果實可能已生成！({int(prob*100)}%)"
        return f"🌱 {int(prob*100)}%"

    def get_elapsed(self):
        if self.walk_start:
            return int(time.time() - self.walk_start)
        return 0

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

    def apply_to_usb(self):
        with self._lock:
            lat, lng = self.lat, self.lng
        if (abs(lat - self._last_usb[0]) < 0.00002 and
            abs(lng - self._last_usb[1]) < 0.00002):
            return
        ok, _ = set_iphone_location(lat, lng)
        if ok:
            with self._lock:
                self._last_usb = (lat, lng)

    def tick(self):
        with self._lock:
            if self.is_moving and self.speed_kmh > 0:
                if self.patrol_active:
                    self._patrol_tick()
                else:
                    self.move_toward(self.course, self.speed_ms())
            if self.pet_mode:
                self._pet_tick()

    def _patrol_tick(self):
        self.move_toward(self.course, self.speed_ms())
        moved = (abs(self.lat - self.patrol_start_lat) * 111000 +
                 abs(self.lng - self.patrol_start_lng) * 111000 * math.cos(math.radians(self.lat)))
        if moved >= self.patrol_distance_m:
            self.course = (self.course + 180) % 360

    def _pet_tick(self):
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
            self._last_usb = (float(lat), float(lng))

    def set_patrol(self, distance_m, active):
        with self._lock:
            self.patrol_active = active
            if active:
                self.patrol_distance_m = max(10, min(500, float(distance_m)))
                self.patrol_start_lat = self.lat
                self.patrol_start_lng = self.lng

    def set_pet_mode(self, enabled):
        with self._lock:
            self.pet_mode = enabled
            if enabled:
                self.pet_last_move = 0

engine = LocationEngine()

# ============ Tkinter UI ============

try:
    import tkinter as tk
except ImportError:
    print("需要 tkinter")
    sys.exit(1)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("皮克敏 GPS USB 控制")
        self.geometry("480x640")
        self.resizable(False, False)
        self.configure(bg="#1e1e1e")
        
        self.usb_udid = None
        self.worker_running = True
        self.msg_queue = queue.Queue()
        self._last_ui_update = 0
        
        self._build_ui()
        self._check_usb()
        self._start_worker()
        self._process_queue()
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Colors
        bg = "#1e1e1e"
        bg2 = "#2d2d2d"
        fg = "#ffffff"
        fg2 = "#8e8e93"
        green = "#34C759"
        orange = "#FF9F0A"
        red = "#FF3B30"
        blue = "#0a84ff"
        gray_btn = "#3d3d3d"
        
        def btn(parent, **kw):
            d = dict(bg=gray_btn, fg=fg, relief="flat", bd=0,
                    padx=10, pady=6, font=("SF Pro Display", 12),
                    activebackground="#5d5d5d")
            d.update(kw)
            return tk.Button(parent, **d)
        
        # Title
        tk.Label(self, text="皮克敏 GPS USB 控制",
                font=("SF Pro Display", 18, "bold"),
                bg=bg, fg=orange).pack(pady=(16, 8))
        
        # USB Status
        self.usb_frame = tk.Frame(self, bg=bg2)
        self.usb_frame.pack(fill="x", padx=20, pady=(0, 12))
        
        self.usb_label = tk.Label(self.usb_frame, text="  檢查 USB 連接...",
                                  font=("SF Pro Text", 13), bg=bg2, fg=fg2)
        self.usb_label.pack(pady=10)
        
        # Info
        info_frame = tk.Frame(self, bg=bg)
        info_frame.pack(fill="x", padx=20, pady=4)
        
        self.loc_label = tk.Label(info_frame, text="📍 位置: —",
                                  font=("SF Mono", 11), bg=bg, fg=green)
        self.loc_label.pack(anchor="w")
        
        self.status_label = tk.Label(info_frame, text="🚶 狀態: 待機",
                                     font=("SF Pro Text", 12), bg=bg, fg=fg2)
        self.status_label.pack(anchor="w")
        
        self.pikmin_label = tk.Label(info_frame, text="🌱 Pikmin: —",
                                     font=("SF Pro Text", 12), bg=bg, fg=green)
        self.pikmin_label.pack(anchor="w")
        
        self.fruit_label = tk.Label(info_frame, text="🌸 果實: —",
                                    font=("SF Pro Text", 12), bg=bg, fg=orange)
        self.fruit_label.pack(anchor="w")
        
        self.stats_label = tk.Label(info_frame, text="📊 累計: 0.00km | 0步 | 00:00",
                                    font=("SF Pro Text", 11), bg=bg, fg=fg2)
        self.stats_label.pack(anchor="w")
        
        # Separator
        tk.Frame(self, bg="#3d3d3d", height=1).pack(fill="x", padx=20, pady=10)
        
        # Speed
        speed_frame = tk.Frame(self, bg=bg)
        speed_frame.pack(fill="x", padx=20, pady=4)
        
        tk.Label(speed_frame, text="速度設定",
                 font=("SF Pro Text", 11, "bold"), bg=bg, fg=fg2).pack(anchor="w", pady=(0, 6))
        
        speed_btn_frame = tk.Frame(speed_frame, bg=bg)
        speed_btn_frame.pack(fill="x")
        
        for label, kmh in SPEED_PRESETS:
            b = btn(speed_btn_frame, text=label,
                   command=lambda k=kmh: self._set_speed(k),
                   bg=gray_btn)
            b.pack(side="left", expand=True, fill="x", padx=2)
        
        # Custom speed
        custom_frame = tk.Frame(speed_frame, bg=bg)
        custom_frame.pack(fill="x", pady=(6, 0))
        
        tk.Label(custom_frame, text="自訂 km/h:",
                 font=("SF Pro Text", 11), bg=bg, fg=fg2).pack(side="left")
        
        self.speed_entry = tk.Entry(custom_frame, width=8, font=("SF Mono", 12),
                                    bg=bg2, fg=fg, insertbackground=fg,
                                    relief="flat")
        self.speed_entry.insert(0, "5.0")
        self.speed_entry.pack(side="left", padx=8)
        self.speed_entry.bind("<Return>", lambda e: self._set_speed(float(self.speed_entry.get())))
        
        btn(custom_frame, text="設定", command=lambda: self._set_speed(float(self.speed_entry.get())),
           bg=blue).pack(side="left")
        
        # Direction
        dir_frame = tk.Frame(self, bg=bg)
        dir_frame.pack(fill="x", padx=20, pady=8)
        
        tk.Label(dir_frame, text="方向控制",
                 font=("SF Pro Text", 11, "bold"), bg=bg, fg=fg2).pack(anchor="w", pady=(0, 6))
        
        dirs = [("↑ 北 0°", 0), ("→ 東 90°", 90), ("↓ 南 180°", 180), ("← 西 270°", 270),
                ("↗ 東北 45°", 45), ("↘ 東南 135°", 135), ("↙ 西南 225°", 225), ("↖ 西北 315°", 315)]
        
        dir_btn_frame = tk.Frame(dir_frame, bg=bg)
        dir_btn_frame.pack()
        
        for i, (label, deg) in enumerate(dirs):
            b = btn(dir_btn_frame, text=label, wraplength=80,
                   command=lambda d=deg: self._set_direction(d),
                   bg=gray_btn, font=("SF Pro Text", 10))
            b.grid(row=i//4, column=i%4, padx=2, pady=2, sticky="ew")
        
        for i in range(4):
            dir_btn_frame.columnconfigure(i, weight=1)
        
        # Patrol & Pet
        mode_frame = tk.Frame(self, bg=bg)
        mode_frame.pack(fill="x", padx=20, pady=4)
        
        self.patrol_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mode_frame, text="🚶 來回巡邏模式（50m）",
                      variable=self.patrol_var, command=self._toggle_patrol,
                      bg=bg, fg=green, selectcolor=bg2,
                      activebackground=bg, font=("SF Pro Text", 12)).pack(anchor="w")
        
        self.pet_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mode_frame, text="🐾 寵物模式（自動小幅移動）",
                      variable=self.pet_var, command=self._toggle_pet,
                      bg=bg, fg=orange, selectcolor=bg2,
                      activebackground=bg, font=("SF Pro Text", 12)).pack(anchor="w")
        
        # Control Buttons
        ctrl_frame = tk.Frame(self, bg=bg)
        ctrl_frame.pack(fill="x", padx=20, pady=12)
        
        self.start_btn = btn(ctrl_frame, text="▶ 開始移動",
                           command=self._start,
                           bg=green, font=("SF Pro Display", 14, "bold"))
        self.start_btn.pack(side="left", expand=True, fill="x", padx=3)
        
        self.stop_btn = btn(ctrl_frame, text="⏹ 停止",
                           command=self._stop,
                           bg=red, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=3)
        
        self.reset_btn = btn(ctrl_frame, text="🔄 歸零",
                           command=self._reset, bg=gray_btn)
        self.reset_btn.pack(side="left", expand=True, fill="x", padx=3)
        
        # URL Info
        url_frame = tk.Frame(self, bg=bg2)
        url_frame.pack(fill="x", padx=20, pady=(8, 16))
        
        tk.Label(url_frame, text="📱 iPhone Safari 開啟控制面板：",
                 font=("SF Pro Text", 10), bg=bg2, fg=fg2).pack(anchor="w", padx=10, pady=(6, 0))
        tk.Label(url_frame, text="http://<Mac的IP>:5001",
                 font=("SF Mono", 11), bg=bg2, fg=blue).pack(anchor="w", padx=10)
        tk.Label(url_frame, text="（插著 USB 就能控制，WiFi 只是遙控顯示用）",
                 font=("SF Pro Text", 9), bg=bg2, fg="#636366").pack(anchor="w", padx=10, pady=(0, 6))
        
        # Log
        log_frame = tk.Frame(self, bg=bg)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        
        self.log_text = tk.Text(log_frame, height=3, font=("SF Mono", 9),
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

    def _check_usb(self):
        ok, msg, udid = check_usb()
        self.usb_udid = udid
        
        if ok:
            self.usb_frame.config(bg="#1d3d1d")
            self.usb_label.config(text=f"  🔌 {msg}", bg="#1d3d1d", fg="#34C759")
            self._log("USB 已連接，初始化定位...")
            self._apply_location()
        else:
            self.usb_frame.config(bg="#3d1d1d")
            self.usb_label.config(text=f"  ⚠️ {msg}", bg="#3d1d1d", fg="#FF3B30")
        
        self.after(3000, self._check_usb)

    def _apply_location(self):
        if not self.usb_udid:
            return
        ok, msg = set_iphone_location(engine.lat, engine.lng)
        if ok:
            self._log(f"位置: {engine.lat:.6f}, {engine.lng:.6f}")
        else:
            self._log(f"設定失敗: {msg[:50]}")

    def _set_speed(self, kmh):
        engine.set_speed(kmh)
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, str(kmh))
        self._log(f"速度: {kmh} km/h")

    def _set_direction(self, deg):
        engine.set_heading(deg)
        self._log(f"方向: {deg}")
        self._apply_location()

    def _toggle_patrol(self):
        if self.patrol_var.get():
            engine.set_patrol(50, True)
            self._log("巡邏模式啟動")
        else:
            engine.set_patrol(50, False)
            self._log("巡邏模式關閉")

    def _toggle_pet(self):
        if self.pet_var.get():
            engine.set_pet_mode(True)
            self._log("寵物模式啟動")
        else:
            engine.set_pet_mode(False)
            self._log("寵物模式關閉")

    def _start(self):
        engine.start()
        self._apply_location()
        self.start_btn.config(state="disabled", bg="#3d3d3d", fg="#8e8e93")
        self.stop_btn.config(state="normal", bg="#FF3B30", fg="#ffffff")
        self._log("開始移動")

    def _stop(self):
        engine.stop()
        self.start_btn.config(state="normal", bg="#34C759", fg="#ffffff")
        self.stop_btn.config(state="disabled", bg="#3d3d3d", fg="#8e8e93")
        self._log("停止移動")

    def _reset(self):
        engine.reset()
        self.patrol_var.set(False)
        self.pet_var.set(False)
        self._log("已歸零")
        self._update_ui()

    def _start_worker(self):
        def worker():
            while self.worker_running:
                engine.tick()
                if engine.is_moving or engine.pet_mode:
                    self._apply_location()
                time.sleep(1.0)
                # Update UI
                self.after(0, self._update_ui)
        
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _update_ui(self):
        try:
            elapsed = engine.get_elapsed()
            mm = f"{elapsed // 60:02d}"
            ss = f"{elapsed % 60:02d}"
            
            self.loc_label.config(text=f"📍 位置: {engine.lat:.6f}, {engine.lng:.6f}")
            
            if engine.is_moving:
                status = f"🚶 移動中 ({engine.speed_kmh} km/h)"
                color = "#34C759"
            elif engine.patrol_active:
                status = "🚶 巡邏中"
                color = "#30D158"
            elif engine.pet_mode:
                status = "🐾 寵物模式"
                color = "#FF9F0A"
            else:
                status = "⏸ 待機"
                color = "#8e8e93"
            
            self.status_label.config(text=status, fg=color)
            
            pikmin = engine.pikmin_status()
            pikmin_color = "#34C759" if "緊密" in pikmin else "#FF9F0A" if "落後" in pikmin else "#FF3B30"
            self.pikmin_label.config(text=f"🌱 Pikmin: {pikmin}", fg=pikmin_color)
            
            self.fruit_label.config(text=f"🌸 果實: {engine.get_fruit_status()}")
            
            self.stats_label.config(
                text=f"📊 {engine.walked_km:.2f}km | {engine.walked_steps:,}步 | {mm}:{ss}"
            )
        except:
            pass

    def _on_close(self):
        self.worker_running = False
        self.destroy()

    def run(self):
        self.mainloop()


if __name__ == '__main__':
    app = App()
    app.run()
