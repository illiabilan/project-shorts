#!/usr/bin/env python3
"""
Desktop GUI Control Center for Project Shorts (No-Terminal Windows App).
Can be launched via pythonw.exe without any black terminal console.
Provides intuitive buttons: Start, Stop, Open Browser, Open Video Folder, Settings.
"""

import os
import sys
import time
import socket
import threading
import subprocess
import webbrowser
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    print("Tkinter is required for windows_launcher.py")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent
OPENSHORTS_DIR = PROJECT_ROOT / "openshorts-repo"
AUTOMATION_DIR = PROJECT_ROOT / "automation"
OUTPUT_DIR = PROJECT_ROOT / "processed_shorts"
BIN_DIR = PROJECT_ROOT / "bin"

if BIN_DIR.exists():
    os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

class ShortsAppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Project Shorts — Автономний комплекс")
        self.root.geometry("520x420")
        self.root.minsize(480, 380)
        self.root.configure(bg="#0f172a")

        self.processes = []
        self.is_running = False

        self._setup_ui()
        self._check_initial_ports()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Background status poller
        self.poller_thread = threading.Thread(target=self._status_loop, daemon=True)
        self.poller_thread.start()

    def _setup_ui(self):
        # Header Frame
        header_frame = tk.Frame(self.root, bg="#1e293b", padx=20, pady=16)
        header_frame.pack(fill="x")

        title_label = tk.Label(
            header_frame,
            text="🎬 Project Shorts",
            font=("Segoe UI", 16, "bold"),
            fg="#f8fafc",
            bg="#1e293b"
        )
        title_label.pack(anchor="w")

        subtitle_label = tk.Label(
            header_frame,
            text="Автоматична нарізка вірусних Shorts 9:16 з YouTube",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e293b"
        )
        subtitle_label.pack(anchor="w", pady=(2, 0))

        # Status Indicators Frame
        status_frame = tk.Frame(self.root, bg="#0f172a", padx=20, pady=16)
        status_frame.pack(fill="x")

        # OpenShorts Engine Status
        self.lbl_engine_status = tk.Label(
            status_frame,
            text="⚪ Рушій OpenShorts: Зупинено (порт 8000)",
            font=("Segoe UI", 10),
            fg="#94a3b8",
            bg="#0f172a"
        )
        self.lbl_engine_status.pack(anchor="w", pady=2)

        # Web UI Status
        self.lbl_web_status = tk.Label(
            status_frame,
            text="⚪ Панель керування: Зупинено (порт 8080)",
            font=("Segoe UI", 10),
            fg="#94a3b8",
            bg="#0f172a"
        )
        self.lbl_web_status.pack(anchor="w", pady=2)

        # Auto open browser check
        self.var_auto_open = tk.BooleanVar(value=True)
        chk_auto = tk.Checkbutton(
            status_frame,
            text="Автоматично відкривати браузер при запуску",
            variable=self.var_auto_open,
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#0f172a",
            selectcolor="#1e293b",
            activebackground="#0f172a",
            activeforeground="#f8fafc"
        )
        chk_auto.pack(anchor="w", pady=(8, 0))

        # Action Buttons Frame
        btn_frame = tk.Frame(self.root, bg="#0f172a", padx=20, pady=10)
        btn_frame.pack(fill="both", expand=True)

        # Start / Stop buttons row
        row1 = tk.Frame(btn_frame, bg="#0f172a")
        row1.pack(fill="x", pady=5)

        self.btn_start = tk.Button(
            row1,
            text="🚀  Запустити програму",
            font=("Segoe UI", 10, "bold"),
            bg="#4f46e5",
            fg="white",
            activebackground="#4338ca",
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            command=self.start_services
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_stop = tk.Button(
            row1,
            text="🛑  Зупинити",
            font=("Segoe UI", 10, "bold"),
            bg="#ef4444",
            fg="white",
            activebackground="#dc2626",
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            state="disabled",
            command=self.stop_services
        )
        self.btn_stop.pack(side="right", fill="x", expand=True, padx=(5, 0))

        # Secondary buttons row
        row2 = tk.Frame(btn_frame, bg="#0f172a")
        row2.pack(fill="x", pady=5)

        self.btn_browser = tk.Button(
            row2,
            text="🌐  Відкрити у браузері",
            font=("Segoe UI", 9),
            bg="#334155",
            fg="#f8fafc",
            activebackground="#475569",
            activeforeground="white",
            relief="flat",
            pady=6,
            cursor="hand2",
            command=self.open_browser
        )
        self.btn_browser.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_folder = tk.Button(
            row2,
            text="📁  Папка з відео",
            font=("Segoe UI", 9),
            bg="#334155",
            fg="#f8fafc",
            activebackground="#475569",
            activeforeground="white",
            relief="flat",
            pady=6,
            cursor="hand2",
            command=self.open_output_folder
        )
        self.btn_folder.pack(side="right", fill="x", expand=True, padx=(5, 0))

        # Settings button
        row3 = tk.Frame(btn_frame, bg="#0f172a")
        row3.pack(fill="x", pady=5)

        self.btn_settings = tk.Button(
            row3,
            text="⚙️  Налаштування провайдерів (OpenRouter, Gemini, Anthropic...)",
            font=("Segoe UI", 9),
            bg="#1e293b",
            fg="#cbd5e1",
            activebackground="#334155",
            activeforeground="white",
            relief="flat",
            pady=6,
            cursor="hand2",
            command=self.open_settings
        )
        self.btn_settings.pack(fill="x")

        # Bottom info bar
        bottom_frame = tk.Frame(self.root, bg="#1e293b", padx=20, pady=8)
        bottom_frame.pack(side="bottom", fill="x")

        self.lbl_info = tk.Label(
            bottom_frame,
            text="Готово до роботи. Натисніть 'Запустити програму'.",
            font=("Segoe UI", 8),
            fg="#94a3b8",
            bg="#1e293b"
        )
        self.lbl_info.pack(anchor="w")

    def _is_port_open(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _check_initial_ports(self):
        e_open = self._is_port_open(8000)
        w_open = self._is_port_open(8080)
        if e_open and w_open:
            self.is_running = True
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self._update_labels(True, True)

    def _update_labels(self, engine_up, web_up):
        if engine_up:
            self.lbl_engine_status.config(text="🟢 Рушій OpenShorts: Активний (http://127.0.0.1:8000)", fg="#4ade80")
        else:
            self.lbl_engine_status.config(text="⚪ Рушій OpenShorts: Зупинено (порт 8000)", fg="#94a3b8")

        if web_up:
            self.lbl_web_status.config(text="🟢 Панель керування: Активна (http://localhost:8080)", fg="#4ade80")
        else:
            self.lbl_web_status.config(text="⚪ Панель керування: Зупинено (порт 8080)", fg="#94a3b8")

    def _status_loop(self):
        while True:
            time.sleep(2)
            e_open = self._is_port_open(8000)
            w_open = self._is_port_open(8080)
            self.root.after(0, lambda e=e_open, w=w_open: self._update_labels(e, w))

    def start_services(self):
        if self.is_running:
            return

        self.btn_start.config(state="disabled")
        self.lbl_info.config(text="Запуск серверів у фоновому режимі...")

        def _worker():
            python_exe = sys.executable
            # If running via pythonw, locate normal python in same dir for child processes
            if "pythonw" in python_exe.lower():
                candidate = python_exe.lower().replace("pythonw.exe", "python.exe")
                if os.path.exists(candidate):
                    python_exe = candidate

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            # 1. Start Engine
            p_engine = subprocess.Popen(
                [python_exe, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=str(OPENSHORTS_DIR),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.processes.append(p_engine)

            # 2. Start Web UI & Scheduler
            p_web = subprocess.Popen(
                [python_exe, str(AUTOMATION_DIR / "web_ui.py")],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.processes.append(p_web)

            # Wait for ports
            for _ in range(25):
                if self._is_port_open(8000) and self._is_port_open(8080):
                    break
                time.sleep(0.8)

            self.is_running = True
            self.root.after(0, self._on_start_finished)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_start_finished(self):
        self.btn_stop.config(state="normal")
        self.lbl_info.config(text="Програма активна! Порт 8080 доступний.")
        if self.var_auto_open.get():
            self.open_browser()

    def stop_services(self):
        self.lbl_info.config(text="Зупинка серверів...")
        self.btn_stop.config(state="disabled")

        def _worker():
            for p in self.processes:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    p.terminate()
            self.processes.clear()

            # Extra safety: kill anything left on ports 8000/8080
            if sys.platform == "win32":
                for port in (8000, 8080):
                    try:
                        out = subprocess.check_output(f'netstat -ano | findstr :{port}', shell=True).decode()
                        for line in out.splitlines():
                            parts = line.strip().split()
                            if len(parts) >= 5 and "LISTENING" in line:
                                pid = parts[-1]
                                subprocess.run(f'taskkill /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass

            self.is_running = False
            self.root.after(0, self._on_stop_finished)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_stop_finished(self):
        self.btn_start.config(state="normal")
        self.lbl_info.config(text="Сервери успішно зупинено.")

    def open_browser(self):
        webbrowser.open("http://localhost:8080")

    def open_settings(self):
        webbrowser.open("http://localhost:8080#settings")

    def open_output_folder(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(OUTPUT_DIR))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(OUTPUT_DIR)])
        else:
            subprocess.run(["xdg-open", str(OUTPUT_DIR)])

    def on_close(self):
        if self.is_running:
            if messagebox.askyesno("Зупинка Project Shorts", "Зупинити сервери перед закриттям?"):
                self.stop_services()
                time.sleep(1)
        self.root.destroy()

def main():
    root = tk.Tk()
    app = ShortsAppGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
