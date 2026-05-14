@echo off
setlocal enabledelayedexpansion
title Bull Scanner — Installer



echo.
echo ============================================================
echo    BULL SCANNER — INSTALLER
echo ============================================================
echo.
echo  This will install the Pre-Market Bullish News Scanner.
echo.
echo  Steps:
echo    1. Verify Python is installed
echo    2. Install required Python packages (tzdata, Pillow)
echo    3. Download the latest scanner from GitHub
echo    4. Generate the green money-sign app icon
echo    5. Create a launcher and Desktop shortcut
echo.
echo ============================================================
echo.
pause

REM ─── Settings ─────────────────────────────────────────────────────────────
set "GITHUB_RAW=https://raw.githubusercontent.com/jowfred/bullscan/main/premarket_scanner.py"
set "INSTALL_DIR=%USERPROFILE%\BullScanner"
set "SCRIPT_PATH=%INSTALL_DIR%\premarket_scanner.py"
set "LAUNCHER_PATH=%INSTALL_DIR%\BullScanner.vbs"
set "ICON_PATH=%INSTALL_DIR%\bullscanner.ico"
set "ICON_BUILDER=%INSTALL_DIR%\_make_icon.py"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Bull Scanner.lnk"

REM ─── Step 1: Verify Python ────────────────────────────────────────────────
echo.
echo [1/5] Checking for Python...
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  X  Python is not installed or not on PATH.
    echo     Download from https://www.python.org/downloads/
    echo     Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo     Found: %%v

REM ─── Step 2: Install Python dependencies ──────────────────────────────────
echo.
echo [2/5] Installing required Python packages...
python -m pip install --quiet --upgrade pip >nul 2>&1
python -m pip install --quiet tzdata Pillow
if errorlevel 1 (
    echo  !  Some packages failed to install. Continuing anyway...
)
echo     Done.

REM ─── Step 3: Create install dir and download script ───────────────────────
echo.
echo [3/5] Downloading latest scanner from GitHub...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

powershell -NoProfile -Command ^
    "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%GITHUB_RAW%' -OutFile '%SCRIPT_PATH%' -UseBasicParsing; Write-Host '     Downloaded:' (Get-Item '%SCRIPT_PATH%').Length 'bytes' } catch { Write-Host '     X Download failed:' $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo.
    echo  X  Couldn't download the scanner. Check your internet connection.
    pause
    exit /b 1
)

REM ─── Step 4: Build the icon ───────────────────────────────────────────────
echo.
echo [4/5] Generating green money-sign icon...

REM Write the icon-builder script inline
> "%ICON_BUILDER%" echo from PIL import Image, ImageDraw, ImageFont
>> "%ICON_BUILDER%" echo import os, sys
>> "%ICON_BUILDER%" echo.
>> "%ICON_BUILDER%" echo def draw_icon(size):
>> "%ICON_BUILDER%" echo     img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
>> "%ICON_BUILDER%" echo     d = ImageDraw.Draw(img)
>> "%ICON_BUILDER%" echo     # Rounded square background, deep green
>> "%ICON_BUILDER%" echo     pad = int(size * 0.04)
>> "%ICON_BUILDER%" echo     radius = int(size * 0.22)
>> "%ICON_BUILDER%" echo     d.rounded_rectangle([pad, pad, size-pad, size-pad], radius=radius, fill=(7, 89, 56, 255))
>> "%ICON_BUILDER%" echo     # Inner gradient hint - lighter green inset
>> "%ICON_BUILDER%" echo     inset = int(size * 0.07)
>> "%ICON_BUILDER%" echo     d.rounded_rectangle([inset, inset, size-inset, size-inset], radius=int(radius*0.85), outline=(16, 185, 129, 255), width=max(1, int(size*0.015)))
>> "%ICON_BUILDER%" echo     # Pick a bold font for the $ - try several
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
>> "%ICON_BUILDER%" echo     # Measure and center the $
>> "%ICON_BUILDER%" echo     bbox = d.textbbox((0, 0), "$", font=font)
>> "%ICON_BUILDER%" echo     tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
>> "%ICON_BUILDER%" echo     x = (size - tw) // 2 - bbox[0]
>> "%ICON_BUILDER%" echo     y = (size - th) // 2 - bbox[1] - int(size*0.02)
>> "%ICON_BUILDER%" echo     # Drop shadow for depth
>> "%ICON_BUILDER%" echo     d.text((x + int(size*0.02), y + int(size*0.02)), "$", font=font, fill=(0, 0, 0, 100))
>> "%ICON_BUILDER%" echo     # Main bright money sign
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
    echo  !  Icon generation failed. The app will still work without a custom icon.
)
del "%ICON_BUILDER%" >nul 2>&1

REM ─── Step 5: Create launcher and shortcut ─────────────────────────────────
echo.
echo [5/5] Creating launcher and Desktop shortcut...

REM VBS launcher — runs pythonw with no console window flash
> "%LAUNCHER_PATH%" echo Set WshShell = CreateObject("WScript.Shell")
>> "%LAUNCHER_PATH%" echo WshShell.CurrentDirectory = "%INSTALL_DIR%"
>> "%LAUNCHER_PATH%" echo WshShell.Run "pythonw """ ^& "%SCRIPT_PATH%" ^& """", 0, False

REM PowerShell script to create a real .lnk shortcut with the custom icon
powershell -NoProfile -Command ^
    "$s = New-Object -ComObject WScript.Shell; $sc = $s.CreateShortcut('%SHORTCUT_PATH%'); $sc.TargetPath = '%LAUNCHER_PATH%'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.IconLocation = '%ICON_PATH%'; $sc.Description = 'Pre-Market Bullish News Scanner'; $sc.Save()"

if exist "%SHORTCUT_PATH%" (
    echo     Desktop shortcut created.
) else (
    echo  !  Shortcut creation may have failed. You can still run %LAUNCHER_PATH%
)

echo.
echo ============================================================
echo    INSTALLATION COMPLETE
echo ============================================================
echo.
echo  Installed to:    %INSTALL_DIR%
echo  Desktop shortcut: Bull Scanner
echo.
echo  Look for the green $ icon on your Desktop.
echo  Double-click it to launch the scanner.
echo.
echo  To pin to taskbar/Start: right-click the Desktop shortcut.
echo.
echo ============================================================
echo.
pause
