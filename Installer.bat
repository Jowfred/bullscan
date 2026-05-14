@echo off
setlocal enabledelayedexpansion
title Bull Scanner — Installer

REM ──────────────────────────────────────────────────────────────────────────
REM  BULL SCANNER INSTALLER (robust version)
REM  Tries multiple download methods, shows errors, never closes silently.
REM ──────────────────────────────────────────────────────────────────────────

echo.
echo ============================================================
echo    BULL SCANNER -- INSTALLER
echo ============================================================
echo.
echo  This will download and install the Pre-Market Bull Scanner
echo  to your user folder, and put an icon on your Desktop.
echo.
echo ============================================================
echo.
pause

REM ─── Settings ─────────────────────────────────────────────────────────────
set "GITHUB_USER=jowfred"
set "GITHUB_REPO=bullscan"
set "GITHUB_BRANCH=main"
set "GITHUB_RAW=https://raw.githubusercontent.com/%GITHUB_USER%/%GITHUB_REPO%/%GITHUB_BRANCH%/premarket_scanner.py"

set "INSTALL_DIR=%USERPROFILE%\BullScanner"
set "SCRIPT_PATH=%INSTALL_DIR%\premarket_scanner.py"
set "LAUNCHER_PATH=%INSTALL_DIR%\BullScanner.vbs"
set "ICON_PATH=%INSTALL_DIR%\bullscanner.ico"
set "ICON_BUILDER=%INSTALL_DIR%\_make_icon.py"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Bull Scanner.lnk"

REM ─── Step 1: Python check ─────────────────────────────────────────────────
echo.
echo [1/5] Checking for Python...
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python is not on your PATH.
    echo  Install Python 3.9 or newer from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo     Found: %%v

REM ─── Step 2: pip packages ─────────────────────────────────────────────────
echo.
echo [2/5] Installing Python packages (tzdata, Pillow)...
python -m pip install --quiet --disable-pip-version-check tzdata Pillow
if errorlevel 1 (
    echo  WARNING: Package install reported an error. Trying again with output:
    python -m pip install tzdata Pillow
    if errorlevel 1 (
        echo.
        echo  ERROR: Couldn't install required packages.
        echo  Try running this from an admin Command Prompt, or run manually:
        echo      python -m pip install tzdata Pillow
        echo.
        pause
        exit /b 1
    )
)
echo     Done.

REM ─── Step 3: Make install dir ─────────────────────────────────────────────
echo.
echo [3/5] Downloading scanner from GitHub...
echo     Source: %GITHUB_RAW%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM Delete any leftover from a failed previous run
if exist "%SCRIPT_PATH%" del "%SCRIPT_PATH%" >nul 2>&1

REM ─── Try Method A: curl (built into Windows 10 1803+ and Windows 11) ──────
echo     Trying curl...
where curl >nul 2>&1
if not errorlevel 1 (
    curl -L -f -s -o "%SCRIPT_PATH%" "%GITHUB_RAW%"
    if exist "%SCRIPT_PATH%" goto :download_ok
    echo     curl failed, trying PowerShell...
) else (
    echo     curl not available, trying PowerShell...
)

REM ─── Try Method B: PowerShell (force TLS 1.2, bypass execution policy) ────
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%GITHUB_RAW%', '%SCRIPT_PATH%') } catch { Write-Host ('     PS error: ' + $_.Exception.Message); exit 1 }"
if exist "%SCRIPT_PATH%" goto :download_ok

REM ─── Try Method C: Python (we know it's installed at this point) ──────────
echo     PowerShell failed, trying Python...
python -c "import urllib.request, ssl; urllib.request.urlretrieve('%GITHUB_RAW%', r'%SCRIPT_PATH%')"
if exist "%SCRIPT_PATH%" goto :download_ok

REM ─── All methods failed ───────────────────────────────────────────────────
echo.
echo ============================================================
echo  ERROR: All download methods failed.
echo ============================================================
echo.
echo  Possible causes:
echo    - No internet connection
echo    - Antivirus blocking downloads
echo    - Corporate firewall blocking GitHub
echo    - The GitHub repo URL is wrong or private
echo.
echo  Manual test: Paste this URL into your browser:
echo    %GITHUB_RAW%
echo.
echo  If you see Python code in the browser, the URL is fine,
echo  and your antivirus is probably blocking the download.
echo  If you see "404", the file isn't at that URL.
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

REM ─── Step 5: Launcher and shortcut ────────────────────────────────────────
echo.
echo [5/5] Creating launcher and Desktop shortcut...

> "%LAUNCHER_PATH%" echo Set WshShell = CreateObject("WScript.Shell")
>> "%LAUNCHER_PATH%" echo WshShell.CurrentDirectory = "%INSTALL_DIR%"
>> "%LAUNCHER_PATH%" echo WshShell.Run "pythonw """ ^& "%SCRIPT_PATH%" ^& """", 0, False

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$s = New-Object -ComObject WScript.Shell; $sc = $s.CreateShortcut('%SHORTCUT_PATH%'); $sc.TargetPath = '%LAUNCHER_PATH%'; $sc.WorkingDirectory = '%INSTALL_DIR%'; if (Test-Path '%ICON_PATH%') { $sc.IconLocation = '%ICON_PATH%' }; $sc.Description = 'Pre-Market Bullish News Scanner'; $sc.Save()"

if exist "%SHORTCUT_PATH%" (
    echo     Desktop shortcut created.
) else (
    echo  WARNING: Shortcut creation may have failed.
    echo  You can still launch with: %LAUNCHER_PATH%
)

echo.
echo ============================================================
echo    INSTALLATION COMPLETE
echo ============================================================
echo.
echo  Installed to:     %INSTALL_DIR%
echo  Desktop shortcut: "Bull Scanner"
echo.
echo  Look for the green $ icon on your Desktop.
echo  Double-click it to launch.
echo.
echo  To pin: right-click the Desktop icon, then
echo          "Pin to taskbar" or "Pin to Start".
echo.
echo ============================================================
echo.
pause
