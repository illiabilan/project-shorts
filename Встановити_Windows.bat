@echo off
chcp 65001 >nul
title Встановлення Project Shorts на Windows
cd /d "%~dp0"

echo ===================================================================
echo    🛠️  МАЙСТЕР ВСТАНОВЛЕННЯ PROJECT SHORTS ДЛЯ WINDOWS
echo ===================================================================
echo.
echo Цей скрипт автоматично підготує все необхідне для роботи:
echo 1. Перевірить наявність Python
echo 2. Створить віртуальне оточення (.venv)
echo 3. Встановить необхідні модулі та ШІ-бібліотеки
echo 4. Завантажить портативний FFmpeg для Windows (якщо відсутній)
echo 5. Створить зручний ярлик на Робочому столі
echo.
echo -------------------------------------------------------------------
pause

:: --- КРОК 1: Перевірка Python ---
echo.
echo [1/5] Перевірка Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo [!] Python не знайдено на вашому комп'ютері.
        echo [*] Завантажуємо офіційний Python 3.11 для Windows...
        powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', 'python_installer.exe')"
        if exist "python_installer.exe" (
            echo.
            echo ===================================================================
            echo [!] ЗАРАЗ ВІДКРИЄТЬСЯ ВСТАНОВЛЮВАЧ PYTHON.
            echo [!] ДУЖЕ ВАЖЛИВО: Поставте галочку "Add python.exe to PATH" знизу!
            echo ===================================================================
            start /wait python_installer.exe PrependPath=1 Include_test=0
            del python_installer.exe
            echo.
            echo Після встановлення Python перезапустіть цей файл "Встановити_Windows.bat".
            pause
            exit /b 0
        ) else (
            echo [X] Не вдалося завантажити Python автоматично.
            echo Будь ласка, завантажте та встановіть Python з сайту: https://www.python.org/
            echo Обов'язково поставте галочку "Add Python to PATH" при встановленні!
            pause
            exit /b 1
        )
    ) else (
        set PYTHON_CMD=py
    )
) else (
    set PYTHON_CMD=python
)

echo    ✓ Python знайдено.

:: --- КРОК 2: Створення .venv ---
echo.
echo [2/5] Створення віртуального оточення .venv...
if not exist ".venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [X] Помилка створення віртуального оточення.
        pause
        exit /b 1
    )
    echo    ✓ Віртуальне оточення успішно створено.
) else (
    echo    ✓ Віртуальне оточення вже існує.
)

:: --- КРОК 3: Встановлення бібліотек ---
echo.
echo [3/5] Встановлення бібліотек (може тривати 2-4 хвилини, зачекайте)...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>nul
.venv\Scripts\python.exe -m pip install -r openshorts-repo\requirements.txt
.venv\Scripts\python.exe -m pip install -r automation\requirements.txt
echo    ✓ Усі бібліотеки встановлено.

:: --- КРОК 4: Перевірка FFmpeg ---
echo.
echo [4/5] Перевірка відеорушія FFmpeg...
if not exist "bin" mkdir "bin"

set FFMPEG_EXISTS=0
if exist "bin\ffmpeg.exe" (
    set FFMPEG_EXISTS=1
) else (
    where ffmpeg >nul 2>nul
    if %errorlevel% equ 0 set FFMPEG_EXISTS=1
)

if %FFMPEG_EXISTS% equ 1 (
    echo    ✓ FFmpeg вже встановлено та готовий до роботи.
) else (
    echo    [*] FFmpeg не знайдено. Завантажуємо портативний FFmpeg для Windows...
    echo        (Це робиться один раз, розмір ~30 МБ)...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { (New-Object System.Net.WebClient).DownloadFile('https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip', 'ffmpeg.zip'); Expand-Archive -Path 'ffmpeg.zip' -DestinationPath 'ffmpeg_temp' -Force; Copy-Item 'ffmpeg_temp\*\bin\ffmpeg.exe' -Destination 'bin\' -Force; Copy-Item 'ffmpeg_temp\*\bin\ffprobe.exe' -Destination 'bin\' -Force; Remove-Item 'ffmpeg_temp' -Recurse -Force; Remove-Item 'ffmpeg.zip' -Force; Write-Host '✓ FFmpeg успішно завантажено!' } catch { Write-Host 'Не вдалося завантажити автоматично: ' $_ }"
    if exist "bin\ffmpeg.exe" (
        echo    ✓ Портативний FFmpeg успішно встановлено у папку bin/.
    ) else (
        echo    ⚠️ Завантаження FFmpeg не вдалося або з'єднання перервано.
        echo       Ви можете покласти ffmpeg.exe вручну у папку bin/.
    )
)

:: --- КРОК 5: Налаштування .env та створення ярлика ---
echo.
echo [5/5] Створення конфігурації та ярлика...
if not exist ".env" (
    copy .env.example .env >nul
    echo    ✓ Створено початковий файл конфігурації .env.
)

:: Створення ярлика на Робочому столі через PowerShell
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $shortcut = $ws.CreateShortcut(\"$desktop\Project Shorts.lnk\"); $shortcut.TargetPath = \"%~dp0Запустити_Shorts.bat\"; $shortcut.WorkingDirectory = \"%~dp0\"; $shortcut.Description = \"Project Shorts - Автономний комплекс\"; $shortcut.Save()"

echo    ✓ Ярлик "Project Shorts" успішно створено на вашому Робочому столі!

echo.
echo ===================================================================
echo    🎉 ВСТАНОВЛЕННЯ УСПІШНО ЗАВЕРШЕНО!
echo ===================================================================
echo.
echo Як користуватись програмою:
echo 1. Знайдіть на Робочому столі ярлик "Project Shorts" (або запустіть
echo    файл "Запустити_Shorts.bat" у цій папці).
echo 2. Автоматично відкриється веб-браузер із панеллю керування.
echo 3. У вкладці "Налаштування" оберіть ШІ-провайдера (наприклад,
echo    OpenRouter або Google AI Studio) та введіть ваш API-ключ.
echo 4. Вставляйте YouTube посилання і натискайте "Додати в чергу"!
echo.
echo ===================================================================
pause
