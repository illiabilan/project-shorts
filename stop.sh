#!/usr/bin/env bash
echo "🛑 Зупинка сервісів Project Shorts..."
pkill -f "uvicorn app:app" 2>/dev/null || true
pkill -f "automation/web_ui.py" 2>/dev/null || true
pkill -f "run_all.py" 2>/dev/null || true
echo "✓ Усі фонові процеси зупинено."
