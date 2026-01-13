#!/bin/bash
# Script to run changeset editor locally

set -e

echo "Starting Changeset Editor locally..."

# Check if .env exists (optional)
if [ ! -f .env ]; then
    echo "Note: .env file not found. Using environment variables or defaults."
fi

# Check if PostgreSQL is running
if ! pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
    echo "ERROR: PostgreSQL is not running on localhost:5432"
    echo "Please start PostgreSQL manually"
    exit 1
fi

# Run migrations
echo "Running database migrations..."
export PGPASSWORD=${PGPASSWORD:-postgres}
psql -h localhost -U postgres -d stiflyt -f backend/migrations/001_initial_schema.sql || echo "Migration may have already been run"
psql -h localhost -U postgres -d stiflyt -f scripts/setup_base_schema.sql || echo "Base schema setup may have already been run"

# Start backend
echo "Starting backend..."
cd backend
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
uvicorn app.main:app --reload &
BACKEND_PID=$!
cd ..

# Start frontend
echo "Starting frontend..."
cd frontend
if [ ! -d node_modules ]; then
    npm install
fi
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "=========================================="
echo "Changeset Editor is running!"
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8002"
echo "API Docs: http://localhost:8002/docs"
echo ""
echo "Press Ctrl+C to stop"
echo "=========================================="

# Wait for user interrupt
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
