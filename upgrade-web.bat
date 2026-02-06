@echo off
setlocal enabledelayedexpansion

REM Medical Deep Research - Upgrade Script
REM Safely upgrades the database and dependencies

echo ========================================
echo   Medical Deep Research - Upgrade
echo ========================================
echo.

set SCRIPT_DIR=%~dp0
set WEB_DIR=%SCRIPT_DIR%web
set DATA_DIR=%WEB_DIR%\data
set DB_FILE=%DATA_DIR%\medical-deep-research.db

REM Check Node.js
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js is not installed
    echo         Please install Node.js 18+ from https://nodejs.org/
    pause
    exit /b 1
)

for /f "tokens=1 delims=v" %%i in ('node -v') do set NODE_VER=%%i
echo [OK] Node.js detected

REM Check if web directory exists
if not exist "%WEB_DIR%" (
    echo [ERROR] web directory not found
    echo         Please run this script from the medical-deep-research root
    pause
    exit /b 1
)

REM Step 1: Backup database if exists
if exist "%DB_FILE%" (
    echo.
    echo [*] Backing up database...
    if not exist "%DATA_DIR%\backups" mkdir "%DATA_DIR%\backups"

    REM Get timestamp
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set datetime=%%I
    set TIMESTAMP=!datetime:~0,8!_!datetime:~8,6!

    copy "%DB_FILE%" "%DATA_DIR%\backups\medical-deep-research_!TIMESTAMP!.db" >nul
    echo     Backed up to backups\medical-deep-research_!TIMESTAMP!.db
) else (
    echo.
    echo [INFO] No existing database found (new installation)
)

REM Step 2: Update dependencies
cd /d "%WEB_DIR%"
echo.
echo [*] Updating dependencies...
call npm install

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

REM Step 3: Run database migration
echo.
echo [*] Upgrading database schema...
call npm run db:init

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Database migration failed
    echo         Check the error messages above
    pause
    exit /b 1
)

REM Step 4: Verify database
if exist "%DB_FILE%" (
    echo.
    echo [*] Database upgrade complete

    REM Try to get table count using sqlite3 if available
    where sqlite3 >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo.
        echo     Tables in database:
        sqlite3 "%DB_FILE%" "SELECT '     - ' || name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
)

echo.
echo ========================================
echo   [OK] Upgrade complete!
echo ========================================
echo.
echo Run 'start-web.bat' to start the application.
echo.

pause
