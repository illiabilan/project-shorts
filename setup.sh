#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "==================================================================="
echo "   🎬 PROJECT SHORTS — НАЛАШТУВАННЯ ДЛЯ LINUX / MACOS"
echo "==================================================================="

# 1. Ensure uv is installed
if ! command -v uv &>/dev/null; then
    if [ -f "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "[*] Встановлюємо uv (швидкий менеджер оточень Python)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi
echo "   ✓ uv доступний ($(uv --version))"

# 2. Check FFmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "   ⚠️ УВАГА: ffmpeg не знайдено в системі!"
    echo "      Встановіть FFmpeg через системний менеджер пакетів:"
    echo "      - Arch Linux: sudo pacman -S ffmpeg"
    echo "      - Ubuntu / Debian: sudo apt update && sudo apt install -y ffmpeg"
    echo "      - macOS: brew install ffmpeg"
else
    echo "   ✓ FFmpeg знайдено: $(ffmpeg -version | head -n 1)"
fi

# 3. Clone openshorts-repo if missing
if [ ! -d "openshorts-repo" ]; then
    echo "[*] Клонуємо кастомізований рушій OpenShorts..."
    git clone https://github.com/illiabilan/openshorts.git openshorts-repo || git clone https://github.com/mutonby/openshorts.git openshorts-repo
fi

# 4. Create virtual environment with Python 3.11
if [ ! -d ".venv" ]; then
    echo "[*] Створюємо віртуальне оточення (.venv) з Python 3.11..."
    uv python install 3.11
    uv venv .venv --python 3.11
fi

# 5. Install dependencies
echo "[*] Встановлення залежностей проєкту..."
uv pip install --python .venv/bin/python -r openshorts-repo/requirements.txt
uv pip install --python .venv/bin/python -r automation/requirements.txt
echo "   ✓ Всі залежності успішно встановлено!"

# 6. Initialize configuration files & directories
if [ ! -f ".env" ]; then
    echo "[*] Створюємо .env файл на основі .env.example..."
    cp .env.example .env
fi
if [ -d "openshorts-repo" ] && [ ! -f "openshorts-repo/.env" ]; then
    cp .env openshorts-repo/.env
fi
if [ ! -f "queue.json" ]; then
    echo "[*] Створюємо queue.json..."
    cp queue.example.json queue.json
fi

mkdir -p processed_shorts output uploads credentials

echo "==================================================================="
echo "   ✅ Налаштування успішно завершено!"
echo "   Для запуску виконайте: ./start.sh або python3 run_all.py"
echo "==================================================================="
