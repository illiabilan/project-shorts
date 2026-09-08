#!/usr/bin/env bash
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
    echo "[!] Віртуальне оточення не знайдено. Запускаємо налаштування..."
    ./setup.sh
fi

exec "$PROJECT_ROOT/.venv/bin/python" run_all.py "$@"
