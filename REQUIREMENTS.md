# Functional Requirements - Stiflyt Route Backend

## 1. Overview

The backend system processes routes from the `turrutebasen` PostGIS table and creates a middle layer that maps matrikkelenhet (property units) to each route segment with offset from start.

## 2. Functional Requirements

### 2.1 Route Processing

**FR-1.1**: The system SHALL process routes from the `fotrute` and `fotruteinfo` tables
- **Input**: Route segments from `fotrute` table (schema: `stiflyt`)
- **Input**: Route metadata from `fotruteinfo` table with `rutenummer` (route identifier)
- **Relationship**: `fotruteinfo.fotrute_fk = fotrute.objid`
- **Output**: Processed routes in a middle layer table

**FR-1.2**: The system SHALL combine route segments into complete routes
- Segments are identified by `rutenummer` from `fotruteinfo` table
- Segments SHALL be combined into a single linestring geometry
- Geometry uses SRID 25833 (UTM zone 33N)
- The system SHALL handle cases where segments don't perfectly connect

**FR-1.3**: The system SHALL calculate matrikkelenhet per route offset
- For each route, the system SHALL determine which matrikkelenhet (from `teig` table) each segment passes through
- `teig` table is in schema: `stiflyt`
- The system SHALL store the offset from route start (in meters) for each matrikkelenhet
- The system SHALL store: kommune, gardsnummer, bruksnummer, festenummer, and offset_from_start
- Matrikkelenhet identifier is stored in `teig.matrikkelnummertekst`

**FR-1.4**: The system SHALL maintain a middle layer table
- Processed routes SHALL be stored separately from source `turrutebasen` data
- The middle layer SHALL allow for corrections and fixes
- The middle layer SHALL preserve traceability to source segments

### 2.2 Route Validation and Error Detection

**FR-2.1**: The system SHALL automatically detect errors in routes
- **Gaps**: Detect when route segments don't connect (distance > threshold)
- **Loose ends**: Detect segments that don't connect to other segments
- **Missing metadata**: Detect segments missing required route identification (`rutenummer` in `fotruteinfo`)

**FR-2.2**: The system SHALL generate error reports
- Errors SHALL be stored in a `route_errors` table
- Each error SHALL include: route_id, error_type, error_description, error_location
- Errors SHALL be queryable via API

**FR-2.3**: The system SHALL support route correction
- The middle layer SHALL allow storing corrected route geometries
- Corrected routes SHALL be marked as `is_corrected`
- The system SHALL track which errors have been resolved

### 2.3 REST API

**FR-3.1**: The system SHALL provide a REST API to query routes

**FR-3.2**: The API SHALL support filtering routes by:
- Exact route number (e.g., `rutenummer = 'bre5'`)
- Route number prefix (e.g., all routes starting with `bre`)
- Organization name (e.g., all routes where `vedlikeholdsansvarlig` contains `DNT Oslo`)

**FR-3.3**: The API SHALL return route information including:
- Route number (`rutenummer`), route name (`rutenavn`), organization (`vedlikeholdsansvarlig`)
- Route geometry (SRID 25833, may be transformed to 4326 for API)
- Total length
- Validation status
- List of matrikkelenheter with offsets

**FR-3.4**: The API SHALL provide endpoints for:
- `GET /api/routes/` - List routes with filters
- `GET /api/routes/{rute_id}` - Get detailed route information
- `GET /api/routes/{rute_id}/matrikkelenheter` - Get matrikkelenheter for a route
- `POST /api/routes/process/{rute_id}` - Process/reprocess a route
- `POST /api/routes/process-all` - Process all routes
- `GET /api/routes/{rute_id}/errors` - Get errors for a route
- `GET /api/routes/errors/all` - Get all errors (for reporting)

### 2.4 Data Sources

**FR-4.1**: The system SHALL read from PostGIS tables:
- **Route tables** (schema: `stiflyt`):
  - `fotrute`: Route segments with geometry (`senterlinje`)
  - `fotruteinfo`: Route metadata with `rutenummer`, `rutenavn`, `vedlikeholdsansvarlig`
- **Matrikkel tables** (schema: `stiflyt`):
  - `teig`: Property units with geometry (`omrade`) and `matrikkelnummertekst`

**FR-4.2**: The system SHALL assume:
- `fotrute` contains segments linked to `fotruteinfo` via `fotruteinfo.fotrute_fk = fotrute.objid`
- `fotruteinfo.rutenummer` is the route identifier
- `fotruteinfo.vedlikeholdsansvarlig` contains organization information
- `teig` table contains polygon geometries with matrikkelenhet fields
- All geometries use SRID 25833 (UTM zone 33N)

## 3. Non-Functional Requirements

**NFR-1**: The system SHALL use Python with FastAPI framework
**NFR-2**: The system SHALL use SQLAlchemy for database access
**NFR-3**: The system SHALL use GeoAlchemy2 for PostGIS support
**NFR-4**: The system SHALL provide API documentation (OpenAPI/Swagger)
**NFR-5**: The system SHALL handle errors gracefully and return appropriate HTTP status codes

## 4. Out of Scope (for this phase)

- User authentication/authorization
- Frontend interface
- GPX import/export
- Route editing UI
- Integration with Kartverket API for owner information
- Route status tracking
- Issue tracker
- Sign management

## 5. Success Criteria

- All routes from `turrutebasen` can be processed
- Matrikkelenhet is correctly mapped to route segments with accurate offsets
- Route errors are detected and reported
- REST API allows querying routes with specified filters
- Processed routes can be corrected and stored in middle layer

