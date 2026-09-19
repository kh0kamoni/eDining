@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ==============================================
echo    eDining Management System - Docker Setup
echo ==============================================
echo.

echo [1/5] Checking Docker installation...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not installed.
    pause
    exit /b 1
)
echo   OK - Docker found.

docker compose version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: docker compose not available.
    pause
    exit /b 1
)
echo   OK - Docker Compose found.

echo [2/5] Checking configuration...

set "SKIP_SETUP=0"
if exist ".env" (
    findstr /b "ADMIN_USERNAME=" .env >nul
    if !errorlevel! equ 0 (
        echo   Existing configuration found in .env.
        set /p "RECONFIG=  Do you want to reconfigure Super Admin credentials? (y/N): "
        if /i "!RECONFIG!"=="y" (
            set "SKIP_SETUP=0"
        ) else (
            set "SKIP_SETUP=1"
        )
    )
)

if "!SKIP_SETUP!"=="0" (
    echo.
    echo   ==============================================
    echo      eDining First-Time Setup: Super Admin
    echo   ==============================================
    echo   Configure the initial Super Admin account.
    echo   This account will have full access to create halls,
    echo   assign managers, and register students.
    echo.
    echo   (Press Enter to accept defaults in brackets)
    echo.

    set /p "ADMIN_USERNAME=  Super Admin username [admin]: "
    if "!ADMIN_USERNAME!"=="" set "ADMIN_USERNAME=admin"

    set /p "ADMIN_PASSWORD=  Super Admin password [admin123]: "
    if "!ADMIN_PASSWORD!"=="" set "ADMIN_PASSWORD=admin123"

    set /p "ADMIN_NAME=  Admin display name [System Super Admin]: "
    if "!ADMIN_NAME!"=="" set "ADMIN_NAME=System Super Admin"

    set /p "ADMIN_PHONE=  Admin phone [01711223344]: "
    if "!ADMIN_PHONE!"=="" set "ADMIN_PHONE=01711223344"

    set /p "ADMIN_EMAIL=  Admin email [admin@example.com]: "
    if "!ADMIN_EMAIL!"=="" set "ADMIN_EMAIL=admin@example.com"

    set /p "DEFAULT_HALL_NAME=  Starter Dining Hall name [Main Dining Hall]: "
    if "!DEFAULT_HALL_NAME!"=="" set "DEFAULT_HALL_NAME=Main Dining Hall"

    set /p "APP_PORT=  Application Port [8090]: "
    if "!APP_PORT!"=="" set "APP_PORT=8090"

    (
        echo ADMIN_USERNAME=!ADMIN_USERNAME!
        echo ADMIN_PASSWORD=!ADMIN_PASSWORD!
        echo ADMIN_NAME=!ADMIN_NAME!
        echo ADMIN_PHONE=!ADMIN_PHONE!
        echo ADMIN_EMAIL=!ADMIN_EMAIL!
        echo DEFAULT_HALL_NAME=!DEFAULT_HALL_NAME!
        echo PORT=!APP_PORT!
    ) > ".env"
    echo.
    echo   Configuration saved to .env
)

:START_CONTAINERS

echo [3/5] Building and starting containers...
docker compose build --quiet
if %errorlevel% neq 0 (
    echo ERROR: Build failed.
    pause
    exit /b 1
)

docker compose up -d
if %errorlevel% neq 0 (
    echo ERROR: Failed to start.
    pause
    exit /b 1
)

echo [4/5] Waiting for application...
set "TIMEOUT=30"
:WAIT_LOOP
timeout /t 2 /nobreak >nul
docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/student/halls')" 2>nul
if !errorlevel! equ 0 goto READY
set /a TIMEOUT-=1
if !TIMEOUT! gtr 0 goto WAIT_LOOP

echo ERROR: App did not start.
pause
exit /b 1

:READY

set "APP_PORT=8090"

if exist ".env" (
    for /f "tokens=1,* delims==" %%a in (.env) do (
        if "%%a"=="ADMIN_USERNAME" set "SHOW_USER=%%b"
        if "%%a"=="ADMIN_PASSWORD" set "SHOW_PASS=%%b"
    )
)

cls
echo.
echo ==============================================
echo    eDining is now running!
echo ==============================================
echo.
echo   URL: http://localhost:!APP_PORT!
echo.
if not "!SHOW_USER!"=="" (
    echo   Super Admin Login:
    echo     Username: !SHOW_USER!
    echo     Password: !SHOW_PASS!
) else (
    echo   Super Admin Login: Check .env file for credentials.
)
echo.
echo   Next Steps:
echo     1. Open http://localhost:!APP_PORT! and log in as Super Admin.
echo     2. Go to Admin Panel -^> Tables -^> Halls to manage dining halls.
echo     3. Go to Admin Panel -^> Users to add managers and register students.
echo.
echo   Management Commands:
echo     docker compose logs app -f    View live logs
echo     docker compose down           Stop services
echo     docker compose up -d          Restart services
echo.
pause
endlocal
