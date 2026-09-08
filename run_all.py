#!/usr/bin/env python3
"""
Master Application Launcher for Project Shorts.
Coordinates OpenShorts Engine (port 8000) and Web Control Center (port 8080),
performs health checks, and automatically launches the user's browser.
Handles clean shutdown on Windows, macOS, and Linux.
"""

import os
import sys
import time
import socket
import signal
import atexit
import subprocess
import webbrowser
from pathlib import Path

# Force UTF-8 encoding on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("Project Shorts - Автономний комплекс")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
OPENSHORTS_DIR = PROJECT_ROOT / "openshorts-repo"
AUTOMATION_DIR = PROJECT_ROOT / "automation"
BIN_DIR = PROJECT_ROOT / "bin"

# Prepend local bin directory to PATH so portable ffmpeg.exe is found first
if BIN_DIR.exists():
    os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

PROCESSES = []

def print_banner():
    banner = """
===================================================================
   🎬 PROJECT SHORTS — АВТОНОМНИЙ КОМПЛЕКС YOUTUBE SHORTS
===================================================================
 [1/3] Перевірка компонентів...
"""
    print(banner)

def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a local TCP port is already open and accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def kill_process_tree(proc):
    """Terminates a process and all its children cleanly."""
    if proc is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass

def cleanup():
    """Cleanup hook to ensure no orphaned processes stay running."""
    if PROCESSES:
        print("\n🛑 Зупинка фонових процесів...")
        for p in PROCESSES:
            kill_process_tree(p)
        print("✓ Усі сервіси успішно зупинено.")

atexit.register(cleanup)

def signal_handler(sig, frame):
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def wait_for_service(port: int, name: str, timeout_sec: int = 30) -> bool:
    """Waits until a port is open."""
    start_time = time.time()
    print(f"   ⏳ Очікуємо запуску {name} (порт {port})...", end="", flush=True)
    while time.time() - start_time < timeout_sec:
        if is_port_open(port):
            print(" [ГОТОВО]")
            return True
        time.sleep(0.6)
        print(".", end="", flush=True)
    print(" [ТАЙМАУТ]")
    return False

def main():
    print_banner()

    # Verify python executable
    python_exe = sys.executable
    print(f"   Використовується Python: {python_exe}")

    # Check FFmpeg
    ffmpeg_found = False
    try:
        res = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ffmpeg_found = (res.returncode == 0)
    except Exception:
        pass

    if ffmpeg_found:
        print("   ✓ FFmpeg знайдено і готовий до роботи.")
    else:
        print("   ⚠️ УВАГА: FFmpeg не знайдено у PATH або bin/!")
        print("      Відеокодування може не працювати. Запустіть 'Встановити_Windows.bat'.")

    # Start OpenShorts Engine (port 8000)
    print("\n [2/3] Запуск рушія OpenShorts Engine (порт 8000)...")
    openshorts_env = os.environ.copy()
    openshorts_env["PYTHONIOENCODING"] = "utf-8"
    
    # Run uvicorn app:app inside openshorts-repo
    p_engine = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(OPENSHORTS_DIR),
        env=openshorts_env,
        stdout=subprocess.DEVNULL,  # Keep console clean; logs viewable in UI
        stderr=subprocess.DEVNULL
    )
    PROCESSES.append(p_engine)

    # Start Web Control Center & Scheduler (port 8080)
    print(" [3/3] Запуск веб-панелі керування та планувальника (порт 8080)...")
    web_env = os.environ.copy()
    web_env["PYTHONIOENCODING"] = "utf-8"
    
    p_web = subprocess.Popen(
        [python_exe, str(AUTOMATION_DIR / "web_ui.py")],
        cwd=str(PROJECT_ROOT),
        env=web_env
    )
    PROCESSES.append(p_web)

    # Wait for services to respond
    engine_ready = wait_for_service(8000, "OpenShorts Engine", timeout_sec=25)
    web_ready = wait_for_service(8080, "Панель керування", timeout_sec=20)

    if not web_ready:
        print("\n❌ Помилка: Не вдалося запустити веб-панель на порту 8080.")
        print("   Перевірте логи або запустіть 'Зупинити_Shorts.bat' і спробуйте знову.")
        sys.exit(1)

    url = "http://localhost:8080"
    print("\n" + "=" * 67)
    print("   🚀 ПРОГРАМА УСПІШНО ЗАПУЩЕНА І ПРАЦЮЄ!")
    print(f"   🌐 Адреса панелі керування: {url}")
    print("   (Відкриваємо ваш браузер автоматично...)")
    print("-------------------------------------------------------------------")
    print("   💡 Порада для користувача:")
    print("   - У вкладці 'Налаштування' оберіть ШІ-провайдера (OpenRouter / Gemini тощо).")
    print("   - Вставте посилання на YouTube-відео у чергу для генерації Shorts.")
    print("   - Для повної зупинки програми просто закрийте це вікно (або Ctrl+C).")
    print("===================================================================\n")

    # Automatically open browser
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Не вдалося відкрити браузер автоматично: {e}")
        print(f"Будь ласка, відкрийте посилання вручну: {url}")

    # Monitor subprocesses
    try:
        while True:
            time.sleep(1)
            # Check if any child process exited prematurely
            if p_engine.poll() is not None:
                print(f"⚠️ Рушій OpenShorts завершив роботу з кодом {p_engine.returncode}.")
                break
            if p_web.poll() is not None:
                print(f"⚠️ Веб-панель завершила роботу з кодом {p_web.returncode}.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

if __name__ == "__main__":
    main()
