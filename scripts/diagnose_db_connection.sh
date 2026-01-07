#!/bin/bash
# Database connection diagnostic script

echo "=== Database Connection Diagnostics ==="
echo ""

# Check if running as stiflyt user
if [ "$(whoami)" != "stiflyt" ]; then
    echo "⚠ Running as $(whoami), not stiflyt"
    echo "Some checks may need to be run as stiflyt user"
    echo ""
fi

echo "1. Checking PostgreSQL service status..."
if systemctl is-active --quiet postgresql || systemctl is-active --quiet postgresql@*; then
    echo "   ✓ PostgreSQL service is running"
else
    echo "   ✗ PostgreSQL service is NOT running"
    echo "   Run: sudo systemctl status postgresql"
fi
echo ""

echo "2. Checking PostgreSQL socket directory..."
SOCKET_DIR="${DB_SOCKET_DIR:-/var/run/postgresql}"
if [ -d "$SOCKET_DIR" ]; then
    echo "   ✓ Socket directory exists: $SOCKET_DIR"
    ls -la "$SOCKET_DIR" 2>/dev/null | head -5 || echo "   ⚠ Cannot list socket directory"

    # Check for socket files
    SOCKET_COUNT=$(find "$SOCKET_DIR" -name "*.s.PGSQL.*" 2>/dev/null | wc -l)
    if [ "$SOCKET_COUNT" -gt 0 ]; then
        echo "   ✓ Found $SOCKET_COUNT PostgreSQL socket file(s)"
    else
        echo "   ⚠ No PostgreSQL socket files found"
    fi
else
    echo "   ✗ Socket directory does not exist: $SOCKET_DIR"
fi
echo ""

echo "3. Checking .env file..."
ENV_FILE="/opt/stiflyt/.env"
if [ -f "$ENV_FILE" ]; then
    echo "   ✓ .env file exists: $ENV_FILE"
    echo "   Current settings:"
    grep -E "^(USE_UNIX_SOCKET|DB_SOCKET_DIR|DB_NAME|DB_USER|DATABASE_URL)=" "$ENV_FILE" 2>/dev/null | sed 's/^/     /' || echo "     (no relevant settings found)"
else
    echo "   ✗ .env file does not exist: $ENV_FILE"
    echo "   Create it from .env.example"
fi
echo ""

echo "4. Testing database connection as current user..."
cd /opt/stiflyt 2>/dev/null || {
    echo "   ⚠ Cannot cd to /opt/stiflyt"
    exit 1
}

# Try to test connection using Python
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate 2>/dev/null
    python3 -c "
from services.database import get_db_connection
try:
    conn = get_db_connection()
    print('   ✓ Database connection successful!')
    cur = conn.cursor()
    cur.execute('SELECT version();')
    version = cur.fetchone()[0]
    print(f'   PostgreSQL version: {version.split()[0]} {version.split()[1]}')
    cur.close()
    conn.close()
except Exception as e:
    print(f'   ✗ Database connection failed: {type(e).__name__}: {e}')
" 2>&1 | sed 's/^/     /'
else
    echo "   ⚠ Virtual environment not found"
fi
echo ""

echo "5. Checking database user permissions..."
DB_USER="${DB_USER:-stiflyt_reader}"
echo "   Testing if user '$DB_USER' can connect..."
if command -v psql >/dev/null 2>&1; then
    if [ -d "$SOCKET_DIR" ]; then
        if sudo -u postgres psql -h "$SOCKET_DIR" -d "${DB_NAME:-matrikkel}" -U "$DB_USER" -c "SELECT 1;" >/dev/null 2>&1; then
            echo "   ✓ User $DB_USER can connect"
        else
            echo "   ✗ User $DB_USER cannot connect"
            echo "   Check if user exists: sudo -u postgres psql -c \"\\du $DB_USER\""
        fi
    else
        echo "   ⚠ Cannot test (socket directory missing)"
    fi
else
    echo "   ⚠ psql not available for testing"
fi
echo ""

echo "6. Checking schema 'stiflyt'..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate 2>/dev/null
    python3 -c "
from services.database import db_connection
try:
    with db_connection() as conn:
        cur = conn.cursor()
        cur.execute(\"SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'stiflyt');\")
        exists = cur.fetchone()[0]
        if exists:
            print('   ✓ Schema \"stiflyt\" exists')
            cur.execute(\"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'stiflyt';\")
            table_count = cur.fetchone()[0]
            print(f'   Found {table_count} table(s) in stiflyt schema')
        else:
            print('   ✗ Schema \"stiflyt\" does NOT exist')
        cur.close()
except Exception as e:
    print(f'   ✗ Error checking schema: {type(e).__name__}: {e}')
" 2>&1 | sed 's/^/     /'
fi
echo ""

echo "=== Summary ==="
echo "If connection fails, check:"
echo "  1. PostgreSQL is running: sudo systemctl status postgresql"
echo "  2. Socket directory exists and is accessible: ls -la $SOCKET_DIR"
echo "  3. .env file is configured correctly: cat /opt/stiflyt/.env"
echo "  4. Database user exists: sudo -u postgres psql -c \"\\du\""
echo "  5. Schema exists: sudo -u postgres psql -d ${DB_NAME:-matrikkel} -c \"\\dn stiflyt\""

