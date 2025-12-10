# Task List - Stiflyt Route Backend

## Phase 1: Project Setup

### Task 1.1: Project Structure and Dependencies
- [ ] Create project directory structure
- [ ] Create `requirements.txt` with dependencies (FastAPI, SQLAlchemy, GeoAlchemy2, etc.)
- [ ] Create `.env.example` file
- [ ] Create `.gitignore` file
- [ ] Create basic README.md

### Task 1.2: Configuration Management
- [ ] Create `config.py` with Pydantic Settings
- [ ] Load database URL from environment variables
- [ ] Add PostGIS configuration

### Task 1.3: Database Connection
- [ ] Create `database.py` with SQLAlchemy engine and session
- [ ] Set up database connection with PostGIS support
- [ ] Create database session dependency for FastAPI

## Phase 2: Database Models

### Task 2.1: Source Table Models
- [ ] Create `Fotrute` model (read-only, reflects existing table in schema `turogfriluftsruter_b9b25c7668da494b9894d492fc35290d`)
- [ ] Create `FotruteInfo` model (read-only, reflects existing table)
- [ ] Create `Teig` model (read-only, reflects existing table in schema `matrikkeleneiendomskartteig_d56c3a44c39b43ae8081f08a97a28c7d`)

### Task 2.2: Middle Layer Models
- [ ] Create `ProcessedRoute` model
- [ ] Create `ProcessedRouteSegment` model
- [ ] Create `RouteMatrikkelenhet` model
- [ ] Create `RouteError` model
- [ ] Add appropriate indexes and relationships

### Task 2.3: Database Initialization
- [ ] Create `scripts/init_db.py` to create tables
- [ ] Add PostGIS extension creation
- [ ] Test table creation

## Phase 3: Route Processing Service

### Task 3.1: Route Combination
- [ ] Implement `_combine_segments()` method
- [ ] Query segments by `rutenummer` from `fotrute` joined with `fotruteinfo`
- [ ] Use PostGIS ST_LineMerge to combine `senterlinje` geometries (SRID 25833)
- [ ] Handle cases where segments don't connect
- [ ] Calculate total route length using ST_Length(ST_Transform(geom, 3857))

### Task 3.2: Route Validation
- [ ] Implement `_validate_route()` method
- [ ] Detect gaps between segments
- [ ] Detect loose ends
- [ ] Detect missing metadata
- [ ] Return validation result dictionary

### Task 3.3: Matrikkelenhet Calculation
- [ ] Implement `_process_matrikkelenhet()` method
- [ ] Find intersections between route `senterlinje` and teig `omrade` polygons (both SRID 25833)
- [ ] Parse `matrikkelnummertekst` to extract kommune, gardsnummer, bruksnummer
- [ ] Calculate offset from start for each intersection
- [ ] Store matrikkelenhet information with offsets

### Task 3.4: Error Reporting
- [ ] Implement `_report_errors()` method
- [ ] Store errors in route_errors table
- [ ] Avoid duplicate error reports

### Task 3.5: Main Processing Methods
- [ ] Implement `process_route(rutenummer)` method
- [ ] Implement `process_all_routes()` method (queries distinct `rutenummer` from `fotruteinfo`)
- [ ] Handle errors gracefully
- [ ] Add transaction management

## Phase 4: API Schemas

### Task 4.1: Request/Response Schemas
- [ ] Create `RouteMatrikkelenhetResponse` schema
- [ ] Create `ProcessedRouteResponse` schema
- [ ] Create `RouteDetailResponse` schema
- [ ] Create `RouteErrorResponse` schema
- [ ] Create `RouteListResponse` schema
- [ ] Create `RouteFilterParams` schema

## Phase 5: REST API Endpoints

### Task 5.1: Route Query Endpoints
- [ ] Implement `GET /api/routes/` with filtering (by `rutenummer`, prefix, `vedlikeholdsansvarlig`)
- [ ] Implement `GET /api/routes/{rutenummer}` endpoint
- [ ] Implement `GET /api/routes/{rutenummer}/matrikkelenheter` endpoint
- [ ] Add pagination support

### Task 5.2: Route Processing Endpoints
- [ ] Implement `POST /api/routes/process/{rutenummer}` endpoint
- [ ] Implement `POST /api/routes/process-all` endpoint
- [ ] Add error handling

### Task 5.3: Error Reporting Endpoints
- [ ] Implement `GET /api/routes/{rutenummer}/errors` endpoint
- [ ] Implement `GET /api/routes/errors/all` endpoint
- [ ] Add filtering and pagination

## Phase 6: Main Application

### Task 6.1: FastAPI Application Setup
- [ ] Create `main.py` with FastAPI app
- [ ] Add CORS middleware
- [ ] Include route router
- [ ] Add root endpoint
- [ ] Add health check endpoint

### Task 6.2: API Documentation
- [ ] Verify OpenAPI/Swagger documentation is generated
- [ ] Test API endpoints via Swagger UI

## Phase 7: Testing and Documentation

### Task 7.1: Documentation
- [ ] Update README.md with setup instructions
- [ ] Add API usage examples
- [ ] Document environment variables

### Task 7.2: Testing
- [ ] Test database connection
- [ ] Test route processing with sample data
- [ ] Test API endpoints
- [ ] Test error detection

## Implementation Order

1. **Phase 1**: Project Setup (Tasks 1.1-1.3)
2. **Phase 2**: Database Models (Tasks 2.1-2.3)
3. **Phase 3**: Route Processing Service (Tasks 3.1-3.5)
4. **Phase 4**: API Schemas (Task 4.1)
5. **Phase 5**: REST API Endpoints (Tasks 5.1-5.3)
6. **Phase 6**: Main Application (Tasks 6.1-6.2)
7. **Phase 7**: Testing and Documentation (Tasks 7.1-7.2)

