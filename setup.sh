#!/usr/bin/env bash
set -e

# Change to script directory
cd "$(dirname "$0")"

echo ""
echo "=============================================="
echo "   eDining Management System - Docker Setup"
echo "=============================================="
echo ""

# 1. Check Docker
echo "[1/5] Checking Docker installation..."
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker is not installed. Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi
echo "  OK - Docker found."

if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: 'docker compose' is not available. Please install Docker Compose v2."
    exit 1
fi
echo "  OK - Docker Compose found."

# 2. Check / create .env
echo "[2/5] Checking configuration..."
SKIP_SETUP=0
if [ -f ".env" ] && grep -q "^ADMIN_USERNAME=" ".env"; then
    echo "  Existing configuration found in .env."
    read -p "  Do you want to reconfigure Super Admin credentials? (y/N): " RECONFIG
    if [ "$RECONFIG" != "y" ] && [ "$RECONFIG" != "Y" ]; then
        SKIP_SETUP=1
    fi
fi

if [ "$SKIP_SETUP" -eq 0 ]; then
    echo ""
    echo "  =============================================="
    echo "     eDining First-Time Setup: Super Admin"
    echo "  =============================================="
    echo "  Configure the initial Super Admin account."
    echo "  This account will have full access to create halls,"
    echo "  assign managers, and register students."
    echo ""
    echo "  (Press Enter to accept defaults in brackets)"
    echo ""

    read -p "  Super Admin username [admin]: " ADMIN_USERNAME
    ADMIN_USERNAME=${ADMIN_USERNAME:-admin}

    read -p "  Super Admin password [admin123]: " ADMIN_PASSWORD
    ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin123}

    read -p "  Admin display name [System Super Admin]: " ADMIN_NAME
    ADMIN_NAME=${ADMIN_NAME:-System Super Admin}

    read -p "  Admin phone [01711223344]: " ADMIN_PHONE
    ADMIN_PHONE=${ADMIN_PHONE:-01711223344}

    read -p "  Admin email [admin@example.com]: " ADMIN_EMAIL
    ADMIN_EMAIL=${ADMIN_EMAIL:-admin@example.com}

    read -p "  Starter Dining Hall name [Main Dining Hall]: " DEFAULT_HALL_NAME
    DEFAULT_HALL_NAME=${DEFAULT_HALL_NAME:-Main Dining Hall}

    read -p "  Application Port [8090]: " APP_PORT
    APP_PORT=${APP_PORT:-8090}

    INIT_HALLS=1
    if [ -f "halls.csv" ]; then
        echo ""
        read -p "  Found halls.csv. Initialize existing dining halls from halls.csv? [Y/n]: " ASK_HALLS
        if [ "$ASK_HALLS" = "n" ] || [ "$ASK_HALLS" = "N" ]; then
            INIT_HALLS=0
        else
            INIT_HALLS=1
        fi
    fi

    INIT_USERS=1
    if [ -f "users.csv" ]; then
        read -p "  Found users.csv. Initialize existing users from users.csv? [Y/n]: " ASK_USERS
        if [ "$ASK_USERS" = "n" ] || [ "$ASK_USERS" = "N" ]; then
            INIT_USERS=0
        else
            INIT_USERS=1
        fi
    fi

    cat <<EOF > .env
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
ADMIN_NAME=${ADMIN_NAME}
ADMIN_PHONE=${ADMIN_PHONE}
ADMIN_EMAIL=${ADMIN_EMAIL}
DEFAULT_HALL_NAME=${DEFAULT_HALL_NAME}
INIT_HALLS=${INIT_HALLS}
INIT_USERS=${INIT_USERS}
PORT=${APP_PORT}
EOF
    echo ""
    echo "  Configuration saved to .env"
fi

# 3. Build & Run
echo "[3/5] Building and starting containers..."
docker compose build --quiet
docker compose up -d

# 4. Wait for app readiness
echo "[4/5] Waiting for application to initialize..."
TIMEOUT=30
until docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/student/halls')" >/dev/null 2>&1 || [ $TIMEOUT -eq 0 ]; do
    sleep 2
    TIMEOUT=$((TIMEOUT - 1))
done

if [ $TIMEOUT -eq 0 ]; then
    echo "ERROR: Application startup timed out. Check logs with 'docker compose logs app'."
    exit 1
fi

APP_PORT=$(grep "^PORT=" .env 2>/dev/null | cut -d '=' -f2)
APP_PORT=${APP_PORT:-8090}
SHOW_USER=$(grep "^ADMIN_USERNAME=" .env 2>/dev/null | cut -d '=' -f2)
SHOW_PASS=$(grep "^ADMIN_PASSWORD=" .env 2>/dev/null | cut -d '=' -f2)

echo ""
echo "=============================================="
echo "   eDining is now running!"
echo "=============================================="
echo ""
echo "  URL: http://localhost:${APP_PORT}"
echo ""
if [ -n "$SHOW_USER" ]; then
    echo "  Super Admin Login:"
    echo "    Username: ${SHOW_USER}"
    echo "    Password: ${SHOW_PASS}"
else
    echo "  Super Admin Login: Check .env file for credentials."
fi
echo ""
echo "  Next Steps:"
echo "    1. Open http://localhost:${APP_PORT} and log in as Super Admin."
echo "    2. Go to Admin Panel -> Tables -> Halls to manage dining halls."
echo "    3. Go to Admin Panel -> Users to add managers and register students."
echo ""
echo "  Management Commands:"
echo "    docker compose logs app -f    View live logs"
echo "    docker compose down           Stop services"
echo "    docker compose up -d          Restart services"
echo ""
