@echo off
chcp 65001 >nul
title Зупинка Project Shorts
cd /d "%~dp0"

echo ===================================================================
echo    🛑  ЗУПИНКА СЕРВІСІВ PROJECT SHORTS
echo ===================================================================
echo.

echo [*] Пошук та зупинка процесів на портах 8000 та 8080...

:: Kill processes on port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [*] Зупиняємо рушій OpenShorts (PID %%a)...
    taskkill /F /PID %%a >nul 2>nul
)

:: Kill processes on port 8080
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080" ^| findstr "LISTENING"') do (
    echo [*] Зупиняємо панель керування (PID %%a)...
    taskkill /F /PID %%a >nul 2>nul
)

echo.
echo ✓ Усі сервіси Project Shorts успішно зупинено!
echo.
pause
