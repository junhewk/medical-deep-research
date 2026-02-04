@echo off
setlocal enabledelayedexpansion

:: Medical Deep Research v2.0 - Windows Startup Script
:: TypeScript-only stack (Next.js + Drizzle ORM + SQLite)

echo.
echo ========================================
echo   Medical Deep Research v2.0
echo   Evidence-Based Research Assistant
echo ========================================
echo.

:: Get script directory
set "SCRIPT_DIR=%~dp0"
set "WEB_DIR=%SCRIPT_DIR%web"

:: Check Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is not installed
    echo         Please install Node.js 18+ from https://nodejs.org/
    pause
    exit /b 1
)

:: Check Node version
for /f "tokens=1 delims=v" %%a in ('node -v') do set "NODE_VER=%%a"
for /f "tokens=1 delims=." %%a in ('node -v') do set "NODE_MAJOR=%%a"
set "NODE_MAJOR=%NODE_MAJOR:v=%"

if %NODE_MAJOR% lss 18 (
    echo [ERROR] Node.js 18+ is required ^(found v%NODE_MAJOR%^)
    echo         Please upgrade Node.js from https://nodejs.org/
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('node -v') do echo [OK] Node.js %%v detected

:: Check if web directory exists
if not exist "%WEB_DIR%" (
    echo [ERROR] web directory not found
    echo         Please run this script from the medical-deep-research root
    pause
    exit /b 1
)

cd /d "%WEB_DIR%"

:: Install dependencies if needed
if not exist "node_modules" (
    echo.
    echo [INFO] Installing dependencies...
    call npm install
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
)

:: Create data directory
if not exist "data" mkdir data

:: Run database migrations if needed
if not exist "data\medical-deep-research.db" (
    echo.
    echo [INFO] Setting up database...
    call npm run db:generate 2>nul
    call npm run db:migrate 2>nul
)

:: Copy .env if it doesn't exist
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [INFO] Created .env from .env.example
    )
)

echo.
echo ========================================
echo   Starting Medical Deep Research...
echo ========================================
echo.
echo   Web UI: http://localhost:3000
echo.
echo   First time? Configure API keys at:
echo   http://localhost:3000/settings/api-keys
echo.
echo   Press Ctrl+C to stop
echo.

:: Start browser opener in background
start /b cmd /c "call :wait_and_open"

:: Start Next.js development server
call npm run dev

pause
goto :eof

:wait_and_open
echo [INFO] Waiting for server to be ready...
set attempts=0
:wait_loop
if %attempts% geq 30 (
    echo [WARN] Timeout waiting for server. Please open http://localhost:3000 manually.
    goto :eof
)
timeout /t 1 /nobreak >nul
curl -s http://localhost:3000 >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Server is ready!
    start http://localhost:3000
    goto :eof
)
set /a attempts+=1
goto :wait_loop
