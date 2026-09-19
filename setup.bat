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
    if !errorlevel! equ 0 set "SKIP_SETUP=1"
)
if "!SKIP_SETUP!"=="1" echo   OK - Existing configuration found.

if "!SKIP_SETUP!"=="0" (
    echo   First-time setup. Creating admin account...
    echo.
    echo   (Press Enter to accept defaults in brackets)
    echo.

    set /p "ADMIN_USERNAME=  Admin username [admin]: "
    if "!ADMIN_USERNAME!"=="" set "ADMIN_USERNAME=admin"

    set /p "ADMIN_PASSWORD=  Admin password [admin123]: "
    if "!ADMIN_PASSWORD!"=="" set "ADMIN_PASSWORD=admin123"

    set /p "ADMIN_NAME=  Admin display name [System Super Admin]: "
    if "!ADMIN_NAME!"=="" set "ADMIN_NAME=System Super Admin"

    set /p "ADMIN_PHONE=  Admin phone [01711223344]: "
    if "!ADMIN_PHONE!"=="" set "ADMIN_PHONE=01711223344"

    (
        echo ADMIN_USERNAME=!ADMIN_USERNAME!
        echo ADMIN_PASSWORD=!ADMIN_PASSWORD!
        echo ADMIN_NAME=!ADMIN_NAME!
        echo ADMIN_PHONE=!ADMIN_PHONE!
    ) > ".env"
    echo   Saved.
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
    echo   Admin login: !SHOW_USER! / !SHOW_PASS!
) else (
    echo   Admin login: Check .env file for credentials.
)
echo.
docker compose exec -T app python -c "
import sys
sys.path.insert(0, '/app')
from database import SessionLocal
import models
db = SessionLocal()
users = db.query(models.User).order_by(models.User.role, models.User.id).all()
if users:
    w = max(len(u.username) for u in users)
    for u in users:
        hall = ''
        if u.hall_id:
            h = db.query(models.Hall).filter(models.Hall.id == u.hall_id).first()
            if h: hall = ' (' + h.name + ')'
        print('  [' + u.role.ljust(18) + '] ' + u.username.ljust(w) + hall)
else:
    print('  (no users found)')
db.close()
" 2>nul
echo.
echo   Commands:
echo     docker compose logs app -f    View logs
echo     docker compose down           Stop
echo     docker compose up -d          Start again
echo.
pause
endlocal
