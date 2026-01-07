# Stiflyt Route Backend

Backend system for processing routes from turrutebasen and mapping matrikkelenhet.

## Quick Start

### 1. Create Virtual Environment

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Or use the setup script
bash scripts/setup_venv.sh
```

### 2. Install Dependencies

```bash
# Install project (editable mode)
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

### 3. Configure Database

Copy `.env.example` to `.env` and update with your database credentials:

```bash
cp .env.example .env
# Edit .env with your database connection details
```

**Unix Domain Socket (default)**:
```bash
USE_UNIX_SOCKET=true
DB_SOCKET_DIR=/var/run/postgresql  # Default PostgreSQL socket directory
DB_NAME=matrikkel
DB_USER=stiflyt_reader
```

**TCP Connection**:
```bash
USE_UNIX_SOCKET=false
DATABASE_URL=postgresql://stiflyt_reader:password@localhost:5432/matrikkel
```

**Important:** The database uses a fixed schema name `stiflyt` (not dynamic schema names). All tables and views are in the `stiflyt` schema.

### 3. Run the Services

**Using Makefile (recommended):**

```bash
# Start backend (Terminal 1)
make backend

# Start frontend (Terminal 2)
make frontend
```

**Or manually:**

```bash
# Backend (serves frontend automatically)
export DB_USER=stiflyt_reader
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend is available at http://localhost:8000/
# API is available at http://localhost:8000/api/v1/routes/{rutenummer}

# Alternative: Run frontend separately (in another terminal)
cd frontend
python3 -m http.server 8080
# Then configure backend URL in frontend (click ⚙️ button)
```

**Makefile commands:**
- `make help` - Show all available commands
- `make backend` - Start FastAPI backend server (default port 8000)
- `make frontend` - Start frontend HTTP server (default port 8080)
- `make install` - Install dependencies
- `make install-dev` - Install with dev dependencies
- `make test` - Run tests
- `make lint` - Run linter
- `make format` - Format code
- `make db-test` - Test database connection
- `make api-test` - Test API endpoint

**Customize ports and DB user:**
```bash
# Custom backend port
make backend BACKEND_PORT=9000

# Custom frontend port
make frontend FRONTEND_PORT=9000

# Custom database user
make backend DB_USER=myuser
```

The API will be available at:
- API: http://localhost:8000/api/v1/routes/{rutenummer}
- Interactive docs: http://localhost:8000/docs
- OpenAPI schema: http://localhost:8000/openapi.json

The frontend will be available at:
- Frontend: http://localhost:8080

**Example API request:**
```bash
curl http://localhost:8000/api/v1/routes/bre10
```

**Response includes:**
- `geometry`: GeoJSON geometry of the route
- `metadata`: Route metadata (name, organization, length, etc.)
- `matrikkelenhet_vector`: 1D vector of matrikkelenhet and bruksnavn along the route

**Note:** CORS is enabled for all origins in development. In production, configure specific allowed origins.

**Frontend Features:**
- Interactive map with colored route segments by property
- Property table with detailed information
- Timeline view showing properties in order
- Circular markers at property boundaries
- Clickable popups with property details

See `frontend/README.md` for more details.

### 5. Query turrutebasen

Run the query script to inspect the turrutebasen table:

```bash
python scripts/query_turrutebasen.py
```

This will show:
- Table structure (columns, data types)
- Row count
- Unique routes
- Sample data
- Example route with segments

## Project Structure

- `REQUIREMENTS.md` - Functional requirements
- `DESIGN.md` - System design
- `TASKS.md` - Task breakdown and implementation plan
- `PROBLEM.md` - Original problem description
- `api/` - FastAPI routes and schemas
- `services/` - Business logic and database services
- `frontend/` - Leaflet-based web frontend
- `scripts/` - Utility scripts

## Development Status

Currently in waterfall development phase. See `TASKS.md` for implementation progress.

