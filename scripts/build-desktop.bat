@echo off
setlocal enabledelayedexpansion

echo === Medical Deep Research — Desktop Build (Windows) ===
echo.

set "PROJECT_ROOT=%~dp0.."
set "WEB_DIR=%PROJECT_ROOT%\web"
set "TAURI_DIR=%PROJECT_ROOT%\src-tauri"

:: Detect architecture
if "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
    set "TARGET_TRIPLE=x86_64-pc-windows-msvc"
    set "BUN_SUFFIX=windows-x64"
) else if "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "TARGET_TRIPLE=aarch64-pc-windows-msvc"
    set "BUN_SUFFIX=windows-aarch64"
) else (
    echo Unsupported architecture: %PROCESSOR_ARCHITECTURE%
    exit /b 1
)

echo Platform: Windows %PROCESSOR_ARCHITECTURE% (%TARGET_TRIPLE%)
echo.

:: --- Step 1: Check prerequisites ---
echo === Step 1: Checking prerequisites ===
where rustc >nul 2>&1 || (echo ERROR: Rust is not installed. Install from https://rustup.rs && exit /b 1)
where cargo >nul 2>&1 || (echo ERROR: Cargo is not installed. Install from https://rustup.rs && exit /b 1)
where node >nul 2>&1 || (echo ERROR: Node.js is not installed. Install from https://nodejs.org && exit /b 1)
where npm >nul 2>&1 || (echo ERROR: npm is not installed. Install from https://nodejs.org && exit /b 1)

:: Check for cargo-tauri
cargo tauri --version >nul 2>&1 || (
    echo Installing Tauri CLI...
    cargo install tauri-cli
)
echo Prerequisites OK
echo.

:: --- Step 2: Download Bun sidecar ---
set "BUN_VERSION=1.3.11"
set "BUN_SIDECAR=%TAURI_DIR%\binaries\bun-%TARGET_TRIPLE%.exe"

if not exist "%BUN_SIDECAR%" (
    echo === Step 2: Downloading Bun sidecar ===
    if not exist "%TAURI_DIR%\binaries" mkdir "%TAURI_DIR%\binaries"

    set "BUN_URL=https://github.com/oven-sh/bun/releases/download/bun-v%BUN_VERSION%/bun-%BUN_SUFFIX%.zip"
    set "DL_TMP=%TEMP%\bun-download-%RANDOM%"
    mkdir "!DL_TMP!"

    echo Downloading Bun %BUN_VERSION% for %TARGET_TRIPLE%
    echo   URL: !BUN_URL!

    powershell -Command "Invoke-WebRequest -Uri '!BUN_URL!' -OutFile '!DL_TMP!\bun.zip'"
    if errorlevel 1 (echo ERROR: Failed to download Bun && exit /b 1)

    powershell -Command "Expand-Archive -Path '!DL_TMP!\bun.zip' -DestinationPath '!DL_TMP!' -Force"
    if errorlevel 1 (echo ERROR: Failed to extract Bun && exit /b 1)

    :: Find and copy bun.exe from extracted directory
    for /d %%d in ("!DL_TMP!\bun-*") do (
        copy "%%d\bun.exe" "%BUN_SIDECAR%" >nul
    )
    rmdir /s /q "!DL_TMP!"
    echo   Saved to: %BUN_SIDECAR%
    echo.
) else (
    echo === Step 2: Bun sidecar already exists ===
    echo   %BUN_SIDECAR%
    echo.
)

:: --- Step 3: Build Next.js standalone ---
echo === Step 3: Building Next.js standalone ===
pushd "%WEB_DIR%"
call npm run build
if errorlevel 1 (echo ERROR: Next.js build failed && popd && exit /b 1)
popd
echo.

:: --- Step 4: Copy standalone output to Tauri resources ---
echo === Step 4: Copying standalone output to Tauri resources ===
set "STANDALONE_DEST=%TAURI_DIR%\resources\standalone"
if exist "%STANDALONE_DEST%" rmdir /s /q "%STANDALONE_DEST%"
xcopy "%WEB_DIR%\.next\standalone" "%STANDALONE_DEST%" /e /i /q >nul

:: Copy static assets (Next.js standalone doesn't include these)
if not exist "%STANDALONE_DEST%\.next\static" mkdir "%STANDALONE_DEST%\.next\static"
xcopy "%WEB_DIR%\.next\static" "%STANDALONE_DEST%\.next\static" /e /i /q >nul

:: Copy public dir if it exists
if exist "%WEB_DIR%\public" (
    xcopy "%WEB_DIR%\public" "%STANDALONE_DEST%\public" /e /i /q >nul
)
echo Standalone server copied to %STANDALONE_DEST%
echo.

:: --- Step 5: Build Tauri app ---
echo === Step 5: Building Tauri desktop app ===
pushd "%PROJECT_ROOT%"
cargo tauri build --bundles nsis
if errorlevel 1 (echo ERROR: Tauri build failed && popd && exit /b 1)
popd
echo.

echo === Build complete ===
echo Installer: %TAURI_DIR%\target\release\bundle\nsis\
dir "%TAURI_DIR%\target\release\bundle\nsis\*.exe" 2>nul || echo (check target\release\bundle\)
