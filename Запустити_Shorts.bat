@echo off
chcp 65001 >nul
title Project Shorts - Автономний комплекс
cd /d "%~dp0"

echo ===================================================================
echo    🎬 PROJECT SHORTS — ЗАПУСК ПРОГРАМИ
echo ===================================================================
echo.

:: 1. Check if .venv exists
if not exist ".venv\Scripts\python.exe" (
    echo [!] Віртуальне оточення .venv не знайдено!
    echo [!] Схоже, це перший запуск на цьому комп'ютері.
    echo.
    echo Зараз буде запущено майстер первинного встановлення...
    echo.
    timeout /t 3 >nul
    call "Встановити_Windows.bat"
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [X] Помилка: Встановлення не завершено.
        pause
        exit /b 1
    )
)

:: 2. Launch using run_all.py
echo [*] Запуск компонентів програми...
.venv\Scripts\python.exe run_all.py

if %errorlevel% neq 0 (
    echo.
    echo [X] Програма завершилась із помилкою (%errorlevel%).
    echo     Якщо виникли проблеми, запустіть "Зупинити_Shorts.bat" і спробуйте знову.
    pause
)
