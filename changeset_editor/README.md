# Route Changeset Editor - MVP

A fullstack MVP for editing route segments with event sourcing, validation, and GitHub PR integration.

## Architecture

- **Backend**: FastAPI (Python) with PostgreSQL/PostGIS
- **Frontend**: React + TypeScript + Leaflet + Geoman
- **Event Sourcing**: Append-only event log with materialization
- **GitHub Integration**: Automatic PR creation on publish

## Quick Start

### Prerequisites

- PostgreSQL 15+ with PostGIS
- Node.js 20+
- Python 3.11+
- GitHub CLI (`gh`) or GitHub token for PR creation

### Setup

### Backend Setup

1. **Setup virtual environment**:
```bash
cd changeset_editor/backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Set environment variables**:

**Unix Domain Socket (default, recommended)**:
```bash
export USE_UNIX_SOCKET="true"
export DB_SOCKET_DIR="/var/run/postgresql"
export DB_NAME="stiflyt"
export DB_USER="stiflyt_reader"
export DB_PASSWORD=""  # Optional, only if required
export ARTIFACTS_DIR="./artifacts"
export GITHUB_REPO_OWNER="dnt"
export GITHUB_REPO_NAME="route-changes"
export GITHUB_TOKEN="your_token"  # Optional, only needed for publish
export BASE_URL="http://localhost:8002"
```

**TCP Connection (alternative)**:
```bash
export USE_UNIX_SOCKET="false"
export DATABASE_URL="postgresql://stiflyt_reader:password@localhost:5432/stiflyt"
export ARTIFACTS_DIR="./artifacts"
export GITHUB_REPO_OWNER="dnt"
export GITHUB_REPO_NAME="route-changes"
export GITHUB_TOKEN="your_token"  # Optional, only needed for publish
export BASE_URL="http://localhost:8002"
```

3. **Run migrations** (against your database):
```bash
psql -U postgres -d stiflyt -f migrations/001_initial_schema.sql
psql -U postgres -d stiflyt -f ../scripts/setup_base_schema.sql
```

4. **Run backend**:
```bash
uvicorn app.main:app --reload
```

Backend will be available at: http://localhost:8002
API docs: http://localhost:8002/docs

### Frontend Setup

1. **Install dependencies**:
```bash
cd changeset_editor/frontend
npm install
```

2. **Set environment** (optional, create `.env` file):
```bash
VITE_API_BASE=http://localhost:8002/api
```

3. **Run dev server**:
```bash
npm run dev
```

Frontend will be available at: http://localhost:3000

## Database Setup

### Base Schema (Readonly)

The changeset editor expects a base schema with route segments. Example:

```sql
CREATE SCHEMA IF NOT EXISTS base;

CREATE TABLE base.segment_base (
    id TEXT PRIMARY KEY,
    geom GEOMETRY(LINESTRING, 4326) NOT NULL,
    attrs JSONB DEFAULT '{}'::jsonb,
    object_uuid TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_segment_base_geom ON base.segment_base USING GIST(geom);
```

### Example Data

```sql
-- Insert example segment
INSERT INTO base.segment_base (id, geom, attrs, object_uuid)
VALUES (
    'seg_001',
    ST_GeomFromGeoJSON('{"type":"LineString","coordinates":[[10.0,59.0],[10.1,59.1]]}'),
    '{"route_ref": "BRE017", "name": "Example Route"}'::jsonb,
    '9f9156fb-89db-4a65-8d53-6d5467a33a6f'
);
```

## API Endpoints

### Changesets

- `POST /api/changesets` - Create new changeset
- `GET /api/changesets/{id}` - Get changeset
- `GET /api/changesets` - List changesets

### Events

- `POST /api/changesets/{id}/events` - Add event to changeset
- `GET /api/changesets/{id}/events` - Get all events

### Validation & Materialization

- `POST /api/changesets/{id}/validate` - Validate changeset
- `GET /api/changesets/{id}/diff.geojson` - Get diff GeoJSON
- `GET /api/changesets/{id}/effective.geojson` - Get effective GeoJSON

### Publish

- `POST /api/changesets/{id}/publish` - Publish changeset (creates GitHub PR)

### Snap Targets

- `GET /api/snap-targets?bbox=min_lon,min_lat,max_lon,max_lat` - Get snap targets

## Event Types

### segment.update_attrs
Update segment attributes using JSON Patch:
```json
{
  "type": "segment.update_attrs",
  "target": {"kind": "segment", "id": "seg_001"},
  "patch": [
    {"op": "replace", "path": "/route_ref", "value": "BRE018"}
  ]
}
```

### segment.update_geom
Update segment geometry:
```json
{
  "type": "segment.update_geom",
  "target": {"kind": "segment", "id": "seg_001"},
  "geometry": {"type": "LineString", "coordinates": [...]},
  "srid": 4326
}
```

### segment.retire
Mark segment as retired:
```json
{
  "type": "segment.retire",
  "target": {"kind": "segment", "id": "seg_001"}
}
```

### segment.add
Add new segment:
```json
{
  "type": "segment.add",
  "temp_id": "tmp_uuid",
  "geometry": {"type": "LineString", "coordinates": [...]},
  "srid": 4326,
  "attrs": {"route_ref": "BRE019"}
}
```

### segment.delete_new
Delete newly added segment:
```json
{
  "type": "segment.delete_new",
  "target": {"kind": "segment", "temp_id": "tmp_uuid"}
}
```

## Usage

1. **Create a changeset**: Opens automatically when you visit the app
2. **Draw segments**: Click "Draw" button and draw on the map
3. **Edit segments**: Click on a segment to select it, then drag vertices
4. **Edit metadata**: Select a segment and edit in side panel (TODO: implement form)
5. **Validate**: Click "Validate" to check for errors/warnings
6. **Publish**: Click "Send to Review" to create GitHub PR

## GitHub Integration

When publishing a changeset:

1. Artifacts are generated in `artifacts/changesets/{id}/`
2. A branch `changeset/{id}` is created
3. Artifacts are committed to the branch
4. A PR is opened against `main`

PR includes:
- Changeset metadata
- Map view link
- Statistics (add/update/retire counts)
- Validation summary

## Validation Rules

- **Geometry validity**: ST_IsValid check
- **Geometry simplicity**: ST_IsSimple check (warns on self-intersections)
- **Minimum length**: 5 meters (configurable)
- **Endpoint snap**: Errors if >5m from network, warnings if 2-5m
- **Route ref format**: Basic regex validation

## Project Structure

```
changeset_editor/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── models.py            # Pydantic models
│   │   ├── database.py          # DB connection
│   │   ├── changeset_service.py
│   │   ├── event_store.py       # Event sourcing
│   │   ├── materializer.py    # Materialize events to GeoJSON
│   │   ├── validator.py         # Validation logic
│   │   ├── artifact_generator.py
│   │   └── github_client.py
│   ├── migrations/
│   │   └── 001_initial_schema.sql
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── MapView.tsx
│   │   │   └── SidePanel.tsx
│   │   ├── api/
│   │   │   └── client.ts
│   │   ├── utils/
│   │   │   └── snap.ts
│   │   ├── types.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   └── package.json
├── scripts/
│   ├── setup_base_schema.sql
│   └── run_local.sh
└── README.md
```

## Development Notes

### Idempotent Publish

The publish endpoint is idempotent:
- If changeset is already in "review" status, returns existing PR URL
- Prevents duplicate PRs

### Event Ordering

Events are processed in timestamp order. The materializer applies events sequentially to build the effective state.

### Snap Targets

Snap targets are loaded based on map viewport (bbox). The frontend uses RBush for efficient spatial queries.

### Geoman Integration

Leaflet Geoman is used for:
- Drawing new segments
- Editing existing segment geometry
- Cut mode for splitting segments (future)

## Limitations (MVP)

- No full metadata editing form (only event creation)
- Simplified validation (no full topology checks)
- Snap targets limited to viewport
- No undo/redo (can be added via event log)
- No conflict resolution (single user per changeset assumed)
- GitHub PR creation requires `gh` CLI or token

## Future Enhancements

- Full metadata editing UI
- Undo/redo functionality
- Multi-user collaboration
- Conflict detection and resolution
- Advanced validation rules
- Export to SOSI/GML
- GPKG export support
- Change log visualization

## License

[Your License Here]
