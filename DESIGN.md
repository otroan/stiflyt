# System Design - Stiflyt Route Backend

## 1. Architecture Overview

The system follows a three-layer architecture:

```
┌─────────────────────────────────────────┐
│         REST API Layer                  │
│    (FastAPI Endpoints)                  │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│      Service Layer                      │
│  (Route Processing Logic)               │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│      Data Layer                         │
│  ┌──────────────┐  ┌─────────────────┐ │
│  │ Source Tables│  │ Middle Layer    │ │
│  │ -turrutebasen│  │ -processed_routes│ │
│  │ -teig        │  │ -route_matrikkel│ │
│  └──────────────┘  │ -route_errors   │ │
│                    └─────────────────┘ │
└─────────────────────────────────────────┘
```

## 2. Database Design

### 2.1 Source Tables (Existing PostGIS Tables)

#### fotrute (Route Segments)
- **Schema**: `turogfriluftsruter_b9b25c7668da494b9894d492fc35290d`
- **Purpose**: Source route segments from Kartverket
- **Key Fields**:
  - `objid` (Integer, PK)
  - `senterlinje` (Geometry LINESTRING, SRID 25833) - Route centerline geometry
  - `rutefolger` (String) - Route type (ST, BV, TR, etc.)
  - `lokalid` (String) - Local identifier
  - `anleggsnummer` (String) - Facility number

#### fotruteinfo (Route Metadata)
- **Schema**: `turogfriluftsruter_b9b25c7668da494b9894d492fc35290d`
- **Purpose**: Route metadata and identification
- **Key Fields**:
  - `objid` (Integer, PK)
  - `rutenummer` (String) - Route identifier (e.g., "bre5", "osl", "PILEGRIM04")
  - `rutenavn` (String) - Route name
  - `vedlikeholdsansvarlig` (String) - Organization (e.g., "DNT | DNT Oslo og omegn")
  - `fotrute_fk` (Integer, FK → fotrute.objid) - Links to route segments

#### teig
- **Schema**: `matrikkeleneiendomskartteig_d56c3a44c39b43ae8081f08a97a28c7d`
- **Purpose**: Property units with matrikkelenhet information
- **Key Fields**:
  - `objid` (Integer, PK)
  - `omrade` (Geometry POLYGON, SRID 25833) - Property area geometry
  - `representasjonspunkt` (Geometry POINT, SRID 25833) - Representative point
  - `kommunenummer` (String) - Municipality number
  - `kommunenavn` (String) - Municipality name
  - `matrikkelnummertekst` (String) - Matrikkelenhet identifier (kommune-gardsnummer-bruksnummer)
  - `teigid` (BigInt) - Teig ID

### 2.2 Middle Layer Tables

#### processed_routes
- **Purpose**: Processed and corrected routes
- **Fields**:
  - `id` (UUID, PK)
  - `rute_id` (String, UNIQUE, INDEXED) - Route identifier (from `rutenummer`)
  - `rute_navn` (String)
  - `organisasjon` (String, INDEXED)
  - `geom` (Geometry LINESTRING, SRID 4326) - Combined route geometry
  - `total_length` (Float) - Total length in meters
  - `segment_count` (Integer) - Number of source segments
  - `is_valid` (Boolean) - Validation status
  - `has_gaps` (Boolean) - Has gaps between segments
  - `has_loose_ends` (Boolean) - Has loose ends
  - `validation_errors` (JSONB) - Error details
  - `is_corrected` (Boolean) - Manually corrected
  - `correction_notes` (Text)
  - `created_at` (DateTime)
  - `updated_at` (DateTime)
  - `processed_at` (DateTime)

#### processed_route_segments
- **Purpose**: Track individual segments of processed routes
- **Fields**:
  - `id` (Integer, PK)
  - `route_id` (UUID, FK → processed_routes.id)
  - `source_segment_id` (Integer, FK → turrutebasen.id)
  - `geom` (Geometry LINESTRING, SRID 4326)
  - `segment_index` (Integer) - Position in route (0-based)
  - `offset_from_start` (Float) - Distance from start in meters

#### route_matrikkelenheter
- **Purpose**: Matrikkelenhet per route offset (main output)
- **Fields**:
  - `id` (Integer, PK)
  - `route_id` (UUID, FK → processed_routes.id, INDEXED)
  - `matrikkelenhet` (String, INDEXED)
  - `kommune` (String, INDEXED)
  - `gardsnummer` (String)
  - `bruksnummer` (String)
  - `festenummer` (String)
  - `offset_from_start` (Float, INDEXED) - Distance from start
  - `start_offset` (Float) - Start of this matrikkelenhet segment
  - `end_offset` (Float) - End of this matrikkelenhet segment
  - `geom` (Geometry LINESTRING, SRID 4326) - Intersection geometry
- **Indexes**:
  - Composite index on (route_id, offset_from_start)
  - Spatial index on geom

#### route_errors
- **Purpose**: Track detected errors in routes
- **Fields**:
  - `id` (Integer, PK)
  - `route_id` (String, INDEXED) - Reference to rute_id
  - `error_type` (String, INDEXED) - 'gap', 'loose_end', 'missing_metadata'
  - `error_description` (Text)
  - `error_data` (JSONB) - Additional error context
  - `error_location` (Geometry POINT, SRID 4326) - Location of error
  - `is_resolved` (Boolean) - Resolution status
  - `resolution_notes` (Text)
  - `detected_at` (DateTime)
  - `resolved_at` (DateTime)

## 3. Component Design

### 3.1 Route Processor Service

**Class**: `RouteProcessor`

**Responsibilities**:
- Combine route segments into complete routes
- Validate routes for errors
- Calculate matrikkelenhet intersections
- Store processed routes in middle layer
- Report errors

**Key Methods**:
- `process_route(rute_id: str) -> ProcessedRoute`
- `process_all_routes() -> Dict[str, int]`
- `_combine_segments(segments: List) -> Geometry`
- `_validate_route(segments: List, combined_geom: Geometry) -> Dict`
- `_process_matrikkelenhet(route: ProcessedRoute) -> None`
- `_report_errors(rute_id: str, validation_result: Dict) -> None`

**Algorithm for Route Combination**:
1. Query all segments for `rutenummer` from `fotrute` joined with `fotruteinfo`
2. Use PostGIS `ST_LineMerge(ST_Collect(senterlinje))` to combine segments
3. If segments don't connect, use `ST_Collect` without merge
4. Calculate total length using `ST_Length(ST_Transform(senterlinje, 3857))`
5. Geometry is in SRID 25833 (UTM zone 33N)

**Algorithm for Matrikkelenhet Calculation**:
1. Find all intersections between route linestring (`senterlinje`) and teig polygons (`omrade`)
2. Both geometries are in SRID 25833
3. For each intersection:
   - Calculate start offset using `ST_LineLocatePoint` on route geometry
   - Calculate end offset similarly
   - Calculate intersection length
   - Extract matrikkelenhet from `matrikkelnummertekst` (parse kommune-gardsnummer-bruksnummer)
4. Store matrikkelenhet information with offsets

**Algorithm for Error Detection**:
1. **Gap Detection**: For each pair of consecutive segments:
   - Get endpoint of segment N (`ST_EndPoint(senterlinje)`)
   - Get startpoint of segment N+1 (`ST_StartPoint(senterlinje)`)
   - Calculate distance between points
   - If distance > threshold (1mm), report gap
2. **Missing Metadata**: Check for NULL or empty `rutenummer` in `fotruteinfo`
3. **Loose Ends**: Detect segments that don't connect to any other segment
4. **Missing Route Info**: Detect `fotrute` segments without corresponding `fotruteinfo` record

### 3.2 REST API Design

**Framework**: FastAPI

**Endpoints**:

```
GET  /api/routes/
     Query params: rute_id (rutenummer), rute_prefix, organisasjon, is_valid, page, page_size
     Returns: List of routes with pagination

GET  /api/routes/{rutenummer}
     Returns: Detailed route with matrikkelenheter

GET  /api/routes/{rutenummer}/matrikkelenheter
     Returns: List of matrikkelenheter ordered by offset

POST /api/routes/process/{rutenummer}
     Processes/reprocesses a single route

POST /api/routes/process-all
     Processes all routes from fotrute/fotruteinfo

GET  /api/routes/{rutenummer}/errors
     Returns: List of errors for route

GET  /api/routes/errors/all
     Query params: error_type, is_resolved, page, page_size
     Returns: List of all errors with pagination
```

**Response Schemas**:
- `RouteListResponse`: Paginated list of routes
- `RouteDetailResponse`: Full route details with matrikkelenheter
- `RouteMatrikkelenhetResponse`: Matrikkelenhet information
- `RouteErrorResponse`: Error information

### 3.3 Data Access Layer

**ORM**: SQLAlchemy with GeoAlchemy2

**Database Connection**:
- Connection string from environment variable `DATABASE_URL`
- Session management via dependency injection
- PostGIS extension enabled on connection

## 4. Processing Flow

### 4.1 Route Processing Flow

```
1. Query turrutebasen for all segments with rute_id
   ↓
2. Combine segments into single linestring
   ↓
3. Validate route (check gaps, loose ends, metadata)
   ↓
4. Calculate intersections with teig polygons
   ↓
5. Calculate offsets for each matrikkelenhet
   ↓
6. Store processed route in middle layer
   ↓
7. Store matrikkelenheter with offsets
   ↓
8. Report errors if validation failed
```

### 4.2 API Request Flow

```
Client Request
   ↓
FastAPI Router
   ↓
Service Layer (RouteProcessor)
   ↓
Database Query (SQLAlchemy)
   ↓
PostGIS Database
   ↓
Response (Pydantic Schema)
   ↓
JSON Response
```

## 5. Error Handling

- Database errors: Return 500 with error message
- Route not found: Return 404
- Invalid parameters: Return 400 with validation errors
- Processing errors: Log and return 500 with error details

## 6. Technology Stack

- **Language**: Python 3.9+
- **Web Framework**: FastAPI
- **ORM**: SQLAlchemy 2.0
- **PostGIS Support**: GeoAlchemy2
- **Database**: PostgreSQL with PostGIS extension
- **Validation**: Pydantic
- **API Documentation**: OpenAPI/Swagger (auto-generated by FastAPI)

## 7. Configuration

- Database connection via `DATABASE_URL` environment variable
- PostGIS enabled by default
- Configuration managed via Pydantic Settings

## 8. Deployment Considerations

- Database migrations: Use Alembic (future enhancement)
- Environment variables: Use `.env` file for local development
- API documentation: Available at `/docs` endpoint
- Health check: `/health` endpoint

