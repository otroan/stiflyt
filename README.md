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
DB_NAME=stiflyt
DB_USER=your_username
```

**TCP Connection**:
```bash
USE_UNIX_SOCKET=false
DATABASE_URL=postgresql://user:password@localhost:5432/stiflyt
```

### 3. Query turrutebasen

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
- `scripts/` - Utility scripts

## Development Status

Currently in waterfall development phase. See `TASKS.md` for implementation progress.

