@echo off
setlocal enabledelayedexpansion
title Bull Scanner — Installer

REM ──────────────────────────────────────────────────────────────────────────
REM  BULL SCANNER INSTALLER (v2 — taskbar-friendly)
REM ──────────────────────────────────────────────────────────────────────────

echo.
echo ============================================================
echo    BULL SCANNER -- INSTALLER
echo ============================================================
echo.
echo  This will install the Pre-Market Bull Scanner to your
echo  user folder, generate a green money-sign icon, and put
echo  a Desktop shortcut you can pin to the taskbar.
echo.
echo ============================================================
echo.
pause

set "GITHUB_USER=jowfred"
set "GITHUB_REPO=bullscan"
set "GITHUB_BRANCH=main"
set "GITHUB_RAW=https://raw.githubusercontent.com/%GITHUB_USER%/%GITHUB_REPO%/%GITHUB_BRANCH%/premarket_scanner.py"

set "INSTALL_DIR=%USERPROFILE%\BullScanner"
set "SCRIPT_PATH=%INSTALL_DIR%\premarket_scanner.py"
set "ICON_PATH=%INSTALL_DIR%\bullscanner.ico"
set "ICON_BUILDER=%INSTALL_DIR%\_make_icon.py"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Bull Scanner.lnk"

REM Clean up the old .vbs launcher if it exists from a previous install
set "OLD_LAUNCHER=%INSTALL_DIR%\BullScanner.vbs"

REM ─── Step 1: Python check ─────────────────────────────────────────────────
echo.
echo [1/5] Checking for Python...
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python is not on your PATH.
    echo  Install Python 3.9+ from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo     Found: %%v

REM Locate pythonw.exe (the GUI version of Python, no console window)
for /f "tokens=*" %%p in ('where pythonw 2^>nul') do (
    set "PYTHONW=%%p"
    goto :pythonw_found
)
echo.
echo  WARNING: pythonw.exe not found. Falling back to python.exe (will show console window).
for /f "tokens=*" %%p in ('where python 2^>nul') do (
    set "PYTHONW=%%p"
    goto :pythonw_found
)
echo  ERROR: Couldn't locate Python executable.
pause
exit /b 1
:pythonw_found
echo     Using launcher: !PYTHONW!

REM ─── Step 2: pip packages ─────────────────────────────────────────────────
echo.
echo [2/5] Installing Python packages (tzdata, Pillow)...
python -m pip install --quiet --disable-pip-version-check tzdata Pillow
if errorlevel 1 (
    python -m pip install tzdata Pillow
    if errorlevel 1 (
        echo  ERROR: Couldn't install required packages.
        pause
        exit /b 1
    )
)
echo     Done.

REM ─── Step 3: Download script ──────────────────────────────────────────────
echo.
echo [3/5] Downloading scanner from GitHub...
echo     Source: %GITHUB_RAW%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if exist "%SCRIPT_PATH%" del "%SCRIPT_PATH%" >nul 2>&1

REM Try curl first
echo     Trying curl...
where curl >nul 2>&1
if not errorlevel 1 (
    curl -L -f -s -o "%SCRIPT_PATH%" "%GITHUB_RAW%"
    if exist "%SCRIPT_PATH%" goto :download_ok
    echo     curl failed, trying PowerShell...
) else (
    echo     curl not available, trying PowerShell...
)

REM PowerShell fallback
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%GITHUB_RAW%', '%SCRIPT_PATH%') } catch { Write-Host ('     PS error: ' + $_.Exception.Message); exit 1 }"
if exist "%SCRIPT_PATH%" goto :download_ok

REM Python fallback
echo     PowerShell failed, trying Python...
python -c "import urllib.request; urllib.request.urlretrieve('%GITHUB_RAW%', r'%SCRIPT_PATH%')"
if exist "%SCRIPT_PATH%" goto :download_ok

echo.
echo ============================================================
echo  ERROR: All download methods failed.
echo ============================================================
echo  Test the URL in your browser: %GITHUB_RAW%
echo  If you see code there, your antivirus is likely blocking.
echo.
pause
exit /b 1

:download_ok
for %%A in ("%SCRIPT_PATH%") do echo     Downloaded %%~zA bytes.

REM ─── Step 4: Build the icon ───────────────────────────────────────────────
echo.
echo [4/5] Generating green money-sign icon...

> "%ICON_BUILDER%" echo from PIL import Image, ImageDraw, ImageFont
>> "%ICON_BUILDER%" echo import sys
>> "%ICON_BUILDER%" echo.
>> "%ICON_BUILDER%" echo def draw_icon(size):
>> "%ICON_BUILDER%" echo     img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
>> "%ICON_BUILDER%" echo     d = ImageDraw.Draw(img)
>> "%ICON_BUILDER%" echo     pad = int(size * 0.04)
>> "%ICON_BUILDER%" echo     radius = int(size * 0.22)
>> "%ICON_BUILDER%" echo     d.rounded_rectangle([pad, pad, size-pad, size-pad], radius=radius, fill=(7, 89, 56, 255))
>> "%ICON_BUILDER%" echo     inset = int(size * 0.07)
>> "%ICON_BUILDER%" echo     d.rounded_rectangle([inset, inset, size-inset, size-inset], radius=int(radius*0.85), outline=(16, 185, 129, 255), width=max(1, int(size*0.015)))
>> "%ICON_BUILDER%" echo     font_size = int(size * 0.78)
>> "%ICON_BUILDER%" echo     font = None
>> "%ICON_BUILDER%" echo     for name in ["arialbd.ttf", "segoeuib.ttf", "calibrib.ttf", "verdanab.ttf"]:
>> "%ICON_BUILDER%" echo         try:
>> "%ICON_BUILDER%" echo             font = ImageFont.truetype(name, font_size)
>> "%ICON_BUILDER%" echo             break
>> "%ICON_BUILDER%" echo         except (OSError, IOError):
>> "%ICON_BUILDER%" echo             continue
>> "%ICON_BUILDER%" echo     if font is None:
>> "%ICON_BUILDER%" echo         font = ImageFont.load_default()
>> "%ICON_BUILDER%" echo     bbox = d.textbbox((0, 0), "$", font=font)
>> "%ICON_BUILDER%" echo     tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
>> "%ICON_BUILDER%" echo     x = (size - tw) // 2 - bbox[0]
>> "%ICON_BUILDER%" echo     y = (size - th) // 2 - bbox[1] - int(size*0.02)
>> "%ICON_BUILDER%" echo     d.text((x + int(size*0.02), y + int(size*0.02)), "$", font=font, fill=(0, 0, 0, 100))
>> "%ICON_BUILDER%" echo     d.text((x, y), "$", font=font, fill=(187, 247, 208, 255))
>> "%ICON_BUILDER%" echo     return img
>> "%ICON_BUILDER%" echo.
>> "%ICON_BUILDER%" echo sizes = [16, 32, 48, 64, 128, 256]
>> "%ICON_BUILDER%" echo images = [draw_icon(s) for s in sizes]
>> "%ICON_BUILDER%" echo out = sys.argv[1] if len(sys.argv) ^> 1 else "bullscanner.ico"
>> "%ICON_BUILDER%" echo images[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])
>> "%ICON_BUILDER%" echo print("     Icon created:", out)

python "%ICON_BUILDER%" "%ICON_PATH%"
if errorlevel 1 (
    echo  WARNING: Icon generation failed. Using default icon.
)
if exist "%ICON_BUILDER%" del "%ICON_BUILDER%" >nul 2>&1

REM ─── Step 5: Create shortcut pointing DIRECTLY at pythonw ─────────────────
echo.
echo [5/5] Creating Desktop shortcut...

REM Remove old .vbs launcher and old shortcuts so we don't have duplicates
if exist "%OLD_LAUNCHER%" del "%OLD_LAUNCHER%" >nul 2>&1
if exist "%SHORTCUT_PATH%" del "%SHORTCUT_PATH%" >nul 2>&1

REM Create a real .lnk shortcut that points DIRECTLY at pythonw.exe with the script as an argument.
REM This is what makes the taskbar work correctly: Windows sees the actual Python process,
REM and "Pin to taskbar" works as expected.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$s = New-Object -ComObject WScript.Shell; $sc = $s.CreateShortcut('%SHORTCUT_PATH%'); $sc.TargetPath = '!PYTHONW!'; $sc.Arguments = '\"%SCRIPT_PATH%\"'; $sc.WorkingDirectory = '%INSTALL_DIR%'; if (Test-Path '%ICON_PATH%') { $sc.IconLocation = '%ICON_PATH%' }; $sc.Description = 'Pre-Market Bullish News Scanner'; $sc.WindowStyle = 1; $sc.Save()"

if exist "%SHORTCUT_PATH%" (
    echo     Desktop shortcut created.
) else (
    echo  WARNING: Shortcut creation failed.
    echo  You can launch manually: !PYTHONW! "%SCRIPT_PATH%"
)

echo.
echo ============================================================
echo    INSTALLATION COMPLETE
echo ============================================================
echo.
echo  Installed to:     %INSTALL_DIR%
echo  Desktop shortcut: "Bull Scanner" (green $ icon)
echo.
echo  TO PIN TO TASKBAR:
echo    1. Double-click the Desktop icon to launch the app
echo    2. Right-click its taskbar icon while it's running
echo    3. Click "Pin to taskbar"
echo.
echo  This time the taskbar icon will actually open the app.
echo.
echo ============================================================
echo.
pause
