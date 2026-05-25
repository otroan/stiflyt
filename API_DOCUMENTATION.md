# Stiflyt Backend API Documentation

**Version:** 0.1.0
**Base URL:** `/api/v1` (routes) or `/api` (changeset)
**Framework:** FastAPI
**Documentation Format:** Optimized for LLM consumption and code generation

## Table of Contents

1. [Authentication](#authentication)
2. [Routes API](#routes-api)
3. [Changeset API](#changeset-api)
4. [Utility Endpoints](#utility-endpoints)
5. [Data Models](#data-models)
6. [Error Handling](#error-handling)
7. [Coordinate Systems](#coordinate-systems)

---

## Authentication

### HTTP Basic Authentication

Most endpoints use HTTP Basic Authentication with shared credentials:

- **Username:** From environment variable `SHARED_USERNAME` (default: "dnt")
- **Password:** From environment variable `SHARED_PASSWORD` (default: "dnt")
- **Header:** `Authorization: Basic <base64(username:password)>`

**Endpoints requiring authentication:**
- `POST /api/v1/owners.xlsx` - Requires authentication
- `POST /api/v1/point/matrikkelenhet` - Optional authentication (returns owner info if authenticated)

**Endpoints with optional authentication:**
- `POST /api/v1/point/matrikkelenhet` - Owner information only included if authenticated

**Changeset API authentication:**
- Uses `X-User` header for user identification (optional, defaults to "anonymous")
- Example: `X-User: john.doe`

---

## Routes API

Base path: `/api/v1`

### Search Endpoints

#### `GET /api/v1/search/places`

Search across ruteinfopunkt, stedsnavn, and routes.

**Query Parameters:**
- `q` (required, string, min_length=2): Search string for place names, route points, or routes
- `limit` (optional, int, default=20, range=1-200): Maximum number of results

**Response:** `PlaceSearchResponse`
```json
{
  "results": [
    {
      "id": "string",
      "type": "ruteinfopunkt | stedsnavn | rute",
      "title": "string",
      "subtitle": "string | null",
      "lon": 10.7522,
      "lat": 59.9139,
      "rutenummer": "string | null"
    }
  ],
  "total": 5
}
```

**Example:**
```bash
GET /api/v1/search/places?q=oslo&limit=10
```

---

### Route Endpoints

#### `GET /api/v1/routes`

Get routes from stiflyt.routes materialized view with filtering.

**Query Parameters:**
- `prefix` (optional, string): Route number prefix (e.g., "bre", "jot", "ron")
- `vedlikeholdsansvarlig` (optional, string): Organization name (pattern match, case-insensitive)
- `bbox` (optional, string): Bounding box as "xmin,ymin,xmax,ymax" in WGS84 (EPSG:4326)
- `limit` (optional, int, default=100, range=1-1000): Maximum number of results
- `offset` (optional, int, default=0, min=0): Pagination offset
- `include_geometry` (optional, bool, default=false): Include GeoJSON geometry in response

**Response:** `RoutesResponse`
```json
{
  "routes": [
    {
      "rutenummer": "bre10",
      "rutenavn": "Breivasshytta - Gjendesheim",
      "vedlikeholdsansvarlig": "DNT Oslo og Omegn",
      "rutetype": "fotrute",
      "route_geometry": { "type": "LineString", "coordinates": [...] },
      "total_length_m": 12345.67,
      "segment_count": 5,
      "segment_objids": [123, 124, 125],
      "from_name": "Breivasshytta",
      "to_name": "Gjendesheim"
    }
  ],
  "total": 50,
  "limit": 100,
  "offset": 0
}
```

**Examples:**
```bash
# Get all routes with prefix "bre"
GET /api/v1/routes?prefix=bre

# Get routes by organization
GET /api/v1/routes?vedlikeholdsansvarlig=DNT

# Get routes in bounding box
GET /api/v1/routes?bbox=10.0,59.0,11.0,60.0&include_geometry=true

# Combined filters
GET /api/v1/routes?prefix=bre&vedlikeholdsansvarlig=DNT Oslo&limit=50
```

---

#### `GET /api/v1/routes/{rutenummer}`

Get a single route by rutenummer.

**Path Parameters:**
- `rutenummer` (required, string): Route number (e.g., "bre10", "jot-1")

**Query Parameters:**
- `include_geometry` (optional, bool, default=false): Include GeoJSON geometry

**Response:** `Route` (same structure as in routes array above)

**Example:**
```bash
GET /api/v1/routes/bre10?include_geometry=true
```

**Error Responses:**
- `404`: Route not found

---

#### `GET /api/v1/routes/{rutenummer}/complete`

Get a complete route by combining all segments with the same rutenummer.

**Path Parameters:**
- `rutenummer` (required, string): Route number

**Query Parameters:**
- `include_geometry` (optional, bool, default=true): Include GeoJSON geometry
- `include_segments` (optional, bool, default=false): Include individual segment details
- `include_endpoint_names` (optional, bool, default=true): Lookup and include from/to place names

**Response:** `CompleteRouteResponse`
```json
{
  "rutenummer": "bre10",
  "rutenavn": "Breivasshytta - Gjendesheim",
  "vedlikeholdsansvarlig": "DNT Oslo og Omegn",
  "geometry": {
    "type": "LineString",
    "coordinates": [[10.0, 59.0], [10.1, 59.1], ...]
  },
  "total_length_meters": 12345.67,
  "total_length_km": 12.35,
  "from_name": {
    "name": "Breivasshytta",
    "source": "ruteinfopunkt | stedsnavn | anchor_node",
    "distance_meters": 0.0,
    "coordinates": [10.0, 59.0],
    "tilrettelegging": "string | null"
  },
  "to_name": { ... },
  "is_connected": true,
  "segment_count": 5,
  "component_count": 1,
  "segments": [ ... ],
  "components": [ ... ]
}
```

**Example:**
```bash
GET /api/v1/routes/bre10/complete?include_segments=true
```

**Error Responses:**
- `404`: Route not found

---

#### `GET /api/v1/routes/{rutenummer}/segments`

Get route segments for a specific route from stiflyt.route_segments view.

**Path Parameters:**
- `rutenummer` (required, string): Route number

**Query Parameters:**
- `include_geometry` (optional, bool, default=false): Include GeoJSON geometry

**Response:** `RouteSegmentsDetailResponse`
```json
{
  "rutenummer": "bre10",
  "segments": [
    {
      "rutenummer": "bre10",
      "segment_objid": 123,
      "senterlinje": { "type": "LineString", "coordinates": [...] },
      "source_node": 1,
      "target_node": 2,
      "rutenavn": "Breivasshytta - Gjendesheim",
      "vedlikeholdsansvarlig": "DNT Oslo og Omegn",
      "rutetype": "fotrute",
      "gradering": "rød",
      "length_meters": 1234.56
    }
  ],
  "total": 5
}
```

**Example:**
```bash
GET /api/v1/routes/bre10/segments?include_geometry=true
```

**Error Responses:**
- `404`: Route not found

---

#### `GET /api/v1/routes/{rutenummer}/links`

Get routing links for a specific route from stiflyt.links table.

**Path Parameters:**
- `rutenummer` (required, string): Route number

**Query Parameters:**
- `include_geometry` (optional, bool, default=false): Include GeoJSON geometry

**Response:** `RouteLinksResponse`
```json
{
  "rutenummer": "bre10",
  "links": [
    {
      "link_id": 1,
      "a_node": 10,
      "b_node": 11,
      "a_node_name": "Breivasshytta",
      "b_node_name": "Junction A",
      "length_m": 500.0,
      "segment_objids": [123, 124],
      "geom": { "type": "LineString", "coordinates": [...] }
    }
  ],
  "total": 10
}
```

**Example:**
```bash
GET /api/v1/routes/bre10/links?include_geometry=true
```

**Error Responses:**
- `404`: Route not found

---

#### `GET /api/v1/routes/{rutenummer}/validate`

Validate a route for metadata consistency and geometry errors.

**Path Parameters:**
- `rutenummer` (required, string): Route number

**Response:** `RouteValidationResponse`
```json
{
  "rutenummer": "bre10",
  "segment_count": 5,
  "link_count": 10,
  "status": "OK | WARNING | ERROR",
  "errors": [
    {
      "type": "metadata_inconsistency",
      "message": "Multiple rutenavn values found",
      "severity": "error",
      "affected_segments": ["123", "124"],
      "affected_links": [1, 2],
      "metadata": { ... }
    }
  ],
  "warnings": [ ... ],
  "geometry_info": [ ... ],
  "segment_metadata": [
    {
      "segment_objid": "123",
      "length_meters": 1234.56,
      "fotruteinfo_count": 1,
      "fotruteinfo_rows": [ ... ]
    }
  ],
  "summary": {
    "total_segments": 5,
    "total_fotruteinfo_rows": 5,
    "total_links": 10,
    "error_count": 0,
    "warning_count": 2,
    "geometry_error_count": 0,
    "geometry_warning_count": 1,
    "rutenavn_values": ["Breivasshytta - Gjendesheim"],
    "vedlikeholdsansvarlig_values": ["DNT Oslo og Omegn"],
    "rutetype_values": ["fotrute"],
    "gradering_values": ["rød"]
  }
}
```

**Example:**
```bash
GET /api/v1/routes/bre10/validate
```

**Error Responses:**
- `404`: Route not found

---

#### `GET /api/v1/routes/bulk`

Get multiple routes by their route numbers in a single request (bulk fetch).

**Query Parameters:**
- `rutenummer` (required, string): Comma-separated list of route numbers (e.g., "bre10,bre11,jot5"). Maximum 100 route numbers per request.
- `include_geometry` (optional, bool, default=false): Include GeoJSON geometry in response

**Response:** `RoutesResponse` (same structure as GET /api/v1/routes)

**Example:**
```bash
GET /api/v1/routes/bulk?rutenummer=bre10,bre11,jot5
GET /api/v1/routes/bulk?rutenummer=bre10,bre11&include_geometry=true
```

**Error Responses:**
- `400`: No route numbers provided, or more than 100 route numbers

---

#### `GET /api/v1/routes/statistics`

Get aggregate statistics for routes: total count, total km (sum of route lengths), and distinct km (sum of link lengths without double-counting overlapping links).

**Query Parameters:**
- `prefix` (optional, string): Route number prefix (e.g., "bre", "jot")
- `vedlikeholdsansvarlig` (optional, string): Organization name (pattern match)
- `bbox` (optional, string): Bounding box as "xmin,ymin,xmax,ymax" in WGS84 (EPSG:4326)

**Note:** At least one filter (`prefix`, `vedlikeholdsansvarlig`, or `bbox`) must be provided.

**Response:** `RoutesStatisticsResponse`
```json
{
  "total_routes": 50,
  "total_km": 1234.56,
  "distinct_km": 1100.0
}
```

**Example:**
```bash
GET /api/v1/routes/statistics?prefix=bre
GET /api/v1/routes/statistics?vedlikeholdsansvarlig=DNT&bbox=10.0,59.0,11.0,60.0
```

**Error Responses:**
- `400`: At least one filter is required

---

#### `GET /api/v1/routes/areas`

Get unique 3-letter area prefixes from route segments (e.g., "bre", "jot").

**Query Parameters:**
- `vedlikeholdsansvarlig` (optional, string): Filter by organization (loose token match; all tokens must appear, case-insensitive)
- `debug` (optional, bool, default=false): Include debug token match info in response
- `debug_prefix` (optional, string): Debug: list vedlikeholdsansvarlig values for routes with this prefix

**Response:** `RouteAreasResponse`
```json
{
  "areas": ["bre", "jot", "ron"],
  "total": 3,
  "vedlikeholdsansvarlig": "DNT Oslo",
  "debug": null
}
```

**Example:**
```bash
GET /api/v1/routes/areas
GET /api/v1/routes/areas?vedlikeholdsansvarlig=DNT Oslo&debug=true
```

---

#### `GET /api/v1/routes/segments`

Get route segments filtered by rutenummer prefix and/or vedlikeholdsansvarlig.

**Query Parameters:**
- `rutenummer_prefix` (optional, string): Filter by route number prefix (e.g., "bre")
- `vedlikeholdsansvarlig` (optional, string): Filter by organization (pattern match, case-insensitive)
- `limit` (optional, int, default=100, range=1-1000): Maximum number of results
- `offset` (optional, int, default=0, min=0): Pagination offset
- `include_geometry` (optional, bool, default=false): Include GeoJSON geometry

**Note:** At least one filter (`rutenummer_prefix` or `vedlikeholdsansvarlig`) must be provided.

**Response:** `RouteSegmentsResponse`
```json
{
  "segments": [
    {
      "objid": 123,
      "object_uuid": "550e8400-e29b-41d4-a716-446655440000",
      "routes": [
        {
          "rutenummer": "bre10",
          "rutenavn": "Breivasshytta - Gjendesheim",
          "vedlikeholdsansvarlig": "DNT Oslo og Omegn"
        }
      ],
      "length_meters": 1234.56,
      "geometry": { "type": "LineString", "coordinates": [...] },
      "oppdateringsdato": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 50,
  "limit": 100,
  "offset": 0
}
```

**Example:**
```bash
GET /api/v1/routes/segments?rutenummer_prefix=bre&vedlikeholdsansvarlig=DNT Oslo&include_geometry=true
```

**Error Responses:**
- `400`: At least one filter must be provided

---

### Segment Endpoints

#### `GET /api/v1/segments/{segment_objid}/routes`

Get all rutenummer (route numbers) that use a specific segment.

**Path Parameters:**
- `segment_objid` (required, int): Segment object ID

**Response:**
```json
{
  "segment_objid": 123,
  "routes": [
    {
      "rutenummer": "bre10",
      "rutenavn": "Breivasshytta - Gjendesheim",
      "vedlikeholdsansvarlig": "DNT Oslo og Omegn",
      "rutetype": "fotrute",
      "gradering": "rød",
      "fotruteinfo_objid": 456
    }
  ],
  "total": 2
}
```

**Example:**
```bash
GET /api/v1/segments/123/routes
```

**Error Responses:**
- `404`: Segment not found

---

#### `GET /api/v1/segments/by-lokalid/{lokalid}`

Get a segment by its lokalId (turrutebasen identifier).

**Path Parameters:**
- `lokalid` (required, string): Segment lokalId

**Response:** `SegmentByLokalIdResponse`
```json
{
  "segment": { ... },
  "fotruteinfo_rows": [ ... ]
}
```

**Example:**
```bash
GET /api/v1/segments/by-lokalid/12345-67890
```

**Error Responses:**
- `404`: Segment not found

---

### Link and Node Endpoints

#### `GET /api/v1/links`

Get links filtered by bounding box and optionally by route number prefix.

**Query Parameters:**
- `bbox` (required, string): Bounding box as "xmin,ymin,xmax,ymax" in WGS84 (EPSG:4326)
- `limit` (optional, int, default=500, range=1-5000): Maximum number of results
- `offset` (optional, int, default=0, min=0): Pagination offset
- `rutenummer_prefix` (optional, string): Filter by route number prefix (e.g., "bre")

**Response:** GeoJSON FeatureCollection
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": {
        "type": "LineString",
        "coordinates": [[10.0, 59.0], [10.1, 59.1]]
      },
      "properties": {
        "length_m": 500.0,
        "a_node": 10,
        "b_node": 11,
        "routes": [
          {
            "rutenummer": "bre10",
            "rutenavn": "Breivasshytta - Gjendesheim",
            "rutetype": "fotrute",
            "vedlikeholdsansvarlig": "DNT Oslo og Omegn"
          }
        ]
      }
    }
  ]
}
```

**Example:**
```bash
GET /api/v1/links?bbox=10.0,59.0,11.0,60.0&limit=100
```

**Error Responses:**
- `400`: Invalid bbox format

---

#### `GET /api/v1/anchor-nodes`

Get anchor nodes with their names and geometry.

**Query Parameters:**
- `node_ids` (optional, string): Comma-separated list of node IDs (e.g., "1,2,3")
- `bbox` (optional, string): Bounding box as "xmin,ymin,xmax,ymax" in WGS84 (EPSG:4326)
- `limit` (optional, int, default=100, range=1-1000): Maximum number of results
- `offset` (optional, int, default=0, min=0): Pagination offset

**Response:** GeoJSON FeatureCollection
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": {
        "type": "Point",
        "coordinates": [10.0, 59.0]
      },
      "properties": {
        "node_id": 1,
        "navn": "Breivasshytta",
        "navn_kilde": "ruteinfopunkt",
        "navn_distance_m": 0.0
      }
    }
  ]
}
```

**Examples:**
```bash
# Get specific nodes
GET /api/v1/anchor-nodes?node_ids=1,2,3

# Get nodes in bounding box
GET /api/v1/anchor-nodes?bbox=10.0,59.0,11.0,60.0

# Get all nodes (up to limit)
GET /api/v1/anchor-nodes?limit=100
```

---

### Route Anchors and Placenames

#### `GET /api/v1/routes/{rutenummer}/anchors`

Get anchor nodes for a specific route with name and link count.

**Path Parameters:** `rutenummer` (required, string)

**Response:** `RouteAnchorsResponse` (rutenummer, anchors array with anchor_node_id, coordinates, link_count, name), total.

**Example:** `GET /api/v1/routes/bre10/anchors`

**Error Responses:** `404` Route not found

---

#### `GET /api/v1/anchors/{anchor_id}/placenames`

Get placename candidates and facilities near an anchor node.

**Path Parameters:** `anchor_id` (required, int)

**Response:** `PlacenameCandidatesResponse` (anchor_node_id, radius_meters, candidates, facilities)

**Example:** `GET /api/v1/anchors/1/placenames`

**Error Responses:** `404` Anchor not found

---

#### `POST /api/v1/anchors/{anchor_id}/name`

Upsert a validated endpoint name for an anchor node.

**Path Parameters:** `anchor_id` (required, int)

**Request Body:** `AnchorNameUpsertRequest` (name, source_type, source_id optional, distance_meters optional, rutenummer optional)

**Response:** `AnchorNameUpsertResponse`

**Error Responses:** `400` Invalid request, `404` Anchor not found

---

### Signs Endpoints

#### `GET /api/v1/routes/{rutenummer}/signs`

Get sign report for a route. **Response:** `SignsReportResponse`

#### `GET /api/v1/signs`

Get sign report by prefix. **Query:** `prefix` (optional). **Response:** `SignsReportResponse`

#### `GET /api/v1/signs/missing`

Missing signs report. **Query:** `prefix` (required). **Response:** `SignsMissingReport`

#### `GET /api/v1/signs/production`

Signs production export by prefix. **Query:** `prefix` (required). **Response:** `SignsProductionResponse`

#### `GET /api/v1/routes/{rutenummer}/signs/production`

Signs production for one route. **Response:** `SignsProductionResponse`. **Error:** `404` Route not found

---

### Geometry and Matrikkel Endpoints

#### `POST /api/v1/geometry/owners`

Get property owners for a LineString geometry.

**Request Body:** `GeometryOwnerRequest`
```json
{
  "geometry": {
    "type": "LineString",
    "coordinates": [[10.0, 59.0], [10.1, 59.1], [10.2, 59.2]]
  }
}
```

**Response:** `GeometryOwnerResponse`
```json
{
  "geometry": {
    "type": "LineString",
    "coordinates": [[10.0, 59.0], [10.1, 59.1], [10.2, 59.2]]
  },
  "total_length_meters": 1234.56,
  "total_length_km": 1.23,
  "matrikkelenhet_vector": [
    {
      "matrikkelenhet": "1234/45/67",
      "bruksnavn": "Hytteområde",
      "kommunenummer": "0301",
      "kommunenavn": "Oslo",
      "offset_meters": 0.0,
      "offset_km": 0.0,
      "length_meters": 500.0,
      "length_km": 0.5,
      "geometry": { "type": "LineString", "coordinates": [...] },
      "owners": "Eier 1, Eier 2"
    }
  ],
  "error_summary": null
}
```

**Example:**
```bash
POST /api/v1/geometry/owners
Content-Type: application/json

{
  "geometry": {
    "type": "LineString",
    "coordinates": [[10.0, 59.0], [10.1, 59.1]]
  }
}
```

**Error Responses:**
- `400`: Invalid geometry format
- `500`: Error processing geometry

---

#### `POST /api/v1/point/matrikkelenhet`

Get matrikkelenhet (teig polygon) for a point coordinate.

**Request Body:** `PointMatrikkelRequest`
```json
{
  "lat": 59.9139,
  "lon": 10.7522
}
```

**Response:** `PointMatrikkelResponse`
```json
{
  "matrikkelenhet": "1234/45/67",
  "matrikkelnummertekst": "1234-45-67",
  "bruksnavn": "Hytteområde",
  "kommunenummer": 301,
  "kommunenavn": "Oslo",
  "arealmerknadtekst": null,
  "lagretberegnetareal": 1234.56,
  "gardsnummer": 1234,
  "bruksnummer": 45,
  "festenummer": 67,
  "polygon_geometry": {
    "type": "Polygon",
    "coordinates": [[[10.0, 59.0], [10.1, 59.0], [10.1, 59.1], [10.0, 59.1], [10.0, 59.0]]]
  },
  "owners": "Eier 1, Eier 2",
  "owner_error": null,
  "teigid": 123456
}
```

**Note:** Owner information is only included if the user is authenticated (via HTTP Basic Auth).

**Example:**
```bash
POST /api/v1/point/matrikkelenhet
Content-Type: application/json
Authorization: Basic <credentials>

{
  "lat": 59.9139,
  "lon": 10.7522
}
```

**Error Responses:**
- `400`: Invalid coordinates
- `404`: No matrikkelenhet found at point
- `500`: Error processing point

---

#### `POST /api/v1/owners.xlsx`

Download Excel report with owners information from matrikkelenhet_vector.

**Authentication:** Required (HTTP Basic Auth)

**Request Body:** `ExcelReportRequest`
```json
{
  "matrikkelenhet_vector": [
    {
      "matrikkelenhet": "1234/45/67",
      "bruksnavn": "Hytteområde",
      "kommunenummer": "0301",
      "kommunenavn": "Oslo",
      "offset_meters": 0.0,
      "offset_km": 0.0,
      "length_meters": 500.0,
      "length_km": 0.5,
      "geometry": { "type": "LineString", "coordinates": [...] }
    }
  ],
  "metadata": {
    "rutenummer": "bre10",
    "rutenavn": "Breivasshytta - Gjendesheim",
    "total_length_km": 12.35
  },
  "title": "Eierliste for bre10"
}
```

**Response:** Excel file (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet)
- Filename format: `eierliste_YYYYMMDD.xlsx`

**Example:**
```bash
POST /api/v1/owners.xlsx
Content-Type: application/json
Authorization: Basic <credentials>

{
  "matrikkelenhet_vector": [ ... ],
  "metadata": { ... },
  "title": "Eierliste"
}
```

**Error Responses:**
- `400`: Matrikkel API errors detected
- `401`: Authentication required
- `500`: Error generating Excel report

---

## Changeset API

Base path: `/api`

The Changeset API provides endpoints for creating and managing route changesets (collections of route modifications).

### Changeset Endpoints

#### `POST /api/changesets`

Create a new changeset.

**Headers:**
- `X-User` (optional): User identifier (defaults to "anonymous")

**Request Body:** `CreateChangesetRequest`
```json
{
  "title": "Update route bre10",
  "description": "Fix geometry issues and update metadata",
  "area": "Jotunheimen",
  "linked_issue_url": "https://github.com/dnt/issues/123",
  "base_snapshot": "default"
}
```

**Response:** `ChangesetResponse`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Update route bre10",
  "description": "Fix geometry issues and update metadata",
  "area": "Jotunheimen",
  "status": "draft",
  "created_by": "john.doe",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "base_snapshot": "default",
  "linked_issue_url": "https://github.com/dnt/issues/123",
  "pr_url": null
}
```

**Example:**
```bash
POST /api/changesets
Content-Type: application/json
X-User: john.doe

{
  "title": "Update route bre10",
  "description": "Fix geometry issues"
}
```

---

#### `GET /api/changesets/{changeset_id}`

Get a changeset by ID.

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID

**Response:** `ChangesetResponse` (same structure as above)

**Example:**
```bash
GET /api/changesets/550e8400-e29b-41d4-a716-446655440000
```

**Error Responses:**
- `404`: Changeset not found

---

#### `GET /api/changesets`

List all changesets.

**Query Parameters:**
- `limit` (optional, int, default=100): Maximum number of results
- `offset` (optional, int, default=0): Pagination offset

**Response:** JSON array of `ChangesetResponse` objects (no wrapper object).
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Update route bre10",
    "description": "...",
    "area": "Jotunheimen",
    "status": "draft",
    "created_by": "john.doe",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "base_snapshot": "default",
    "linked_issue_url": null,
    "pr_url": null
  }
]
```

**Example:**
```bash
GET /api/changesets?limit=50&offset=0
```

---

#### `POST /api/changesets/{changeset_id}/events`

Add an event to a changeset.

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID

**Headers:**
- `X-User` (optional): User identifier

**Request Body:** `AddEventRequest`
```json
{
  "event": {
    "type": "segment.update_attrs",
    "target": {
      "kind": "segment",
      "id": "123"
    },
    "patch": [
      { "op": "replace", "path": "/rutenavn", "value": "New Route Name" }
    ],
    "comment": "Update route name"
  }
}
```

**Event Types:**
- `segment.update_attrs`: Update segment attributes (JSON Patch format)
- `segment.update_geom`: Update segment geometry
- `segment.retire`: Retire a segment
- `segment.add`: Add a new segment
- `segment.delete_new`: Delete a newly added segment

**Response:** `EventResponse`
```json
{
  "event_id": "660e8400-e29b-41d4-a716-446655440001",
  "changeset_id": "550e8400-e29b-41d4-a716-446655440000",
  "ts": "2024-01-15T10:35:00Z",
  "user_id": "john.doe",
  "event": { ... }
}
```

**Example:**
```bash
POST /api/changesets/550e8400-e29b-41d4-a716-446655440000/events
Content-Type: application/json
X-User: john.doe

{
  "event": {
    "type": "segment.add",
    "temp_id": "tmp_abc123",
    "geometry": {
      "type": "LineString",
      "coordinates": [[10.0, 59.0], [10.1, 59.1]]
    },
    "srid": 4326,
    "attrs": {
      "rutenummer": "bre10",
      "rutenavn": "New Segment"
    }
  }
}
```

**Error Responses:**
- `400`: Cannot add events to changeset (status not "draft")
- `404`: Changeset not found

---

#### `GET /api/changesets/{changeset_id}/events`

Get all events for a changeset.

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID

**Response:**
```json
{
  "events": [
    {
      "event_id": "660e8400-e29b-41d4-a716-446655440001",
      "changeset_id": "550e8400-e29b-41d4-a716-446655440000",
      "ts": "2024-01-15T10:35:00Z",
      "user_id": "john.doe",
      "event": { ... }
    }
  ]
}
```

**Example:**
```bash
GET /api/changesets/550e8400-e29b-41d4-a716-446655440000/events
```

**Error Responses:**
- `404`: Changeset not found

---

#### `POST /api/changesets/{changeset_id}/validate`

Validate a changeset.

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID

**Response:** `ValidationResponse`
```json
{
  "errors": [
    {
      "severity": "error",
      "code": "invalid_geometry",
      "message": "Geometry is invalid",
      "feature_ref": {
        "kind": "segment",
        "id": "123"
      },
      "location": {
        "lon": 10.0,
        "lat": 59.0
      }
    }
  ],
  "warnings": [ ... ]
}
```

**Example:**
```bash
POST /api/changesets/550e8400-e29b-41d4-a716-446655440000/validate
```

**Error Responses:**
- `404`: Changeset not found

---

#### `GET /api/changesets/{changeset_id}/diff.geojson`

Get diff GeoJSON for a changeset.

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID

**Response:** GeoJSON FeatureCollection with diff information

**Example:**
```bash
GET /api/changesets/550e8400-e29b-41d4-a716-446655440000/diff.geojson
```

**Error Responses:**
- `404`: Changeset not found

---

#### `GET /api/changesets/{changeset_id}/effective.geojson`

Get effective GeoJSON for a changeset (base + changes).

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID

**Response:** GeoJSON FeatureCollection with effective geometry

**Example:**
```bash
GET /api/changesets/550e8400-e29b-41d4-a716-446655440000/effective.geojson
```

**Error Responses:**
- `404`: Changeset not found

---

#### `GET /api/changesets/{changeset_id}/artifacts/{filename}`

Download a changeset artifact file (JSON only).

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID
- `filename` (required, string): Artifact filename (must end with `.json`)

**Response:** File (application/json)

**Example:**
```bash
GET /api/changesets/550e8400-e29b-41d4-a716-446655440000/artifacts/diff.geojson
```

**Error Responses:**
- `400`: Filename does not end with .json, or invalid path
- `404`: Changeset or artifact not found

---

#### `POST /api/changesets/{changeset_id}/publish`

Publish a changeset (send to review).

**Path Parameters:**
- `changeset_id` (required, string): Changeset UUID

**Headers:**
- `X-User` (optional): User identifier

**Response:** `PublishResponse`
```json
{
  "changeset_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "review",
  "pr_url": "https://github.com/dnt/route-changes/pull/123",
  "artifacts": {
    "meta.yaml": "changesets/550e8400-e29b-41d4-a716-446655440000/meta.yaml",
    "diff.geojson": "changesets/550e8400-e29b-41d4-a716-446655440000/diff.geojson"
  }
}
```

**Example:**
```bash
POST /api/changesets/550e8400-e29b-41d4-a716-446655440000/publish
X-User: john.doe
```

**Error Responses:**
- `400`: Changeset has validation errors or status is not "draft"
- `404`: Changeset not found

---

#### `GET /api/snap-targets`

Get snap targets for a bounding box (used for geometry snapping in editor).

**Query Parameters:**
- `bbox` (required, string): Bounding box as "min_lon,min_lat,max_lon,max_lat"

**Response:**
```json
{
  "targets": [
    {
      "id": "123",
      "geometry": {
        "type": "LineString",
        "coordinates": [[10.0, 59.0], [10.1, 59.1]]
      },
      "vertices": [[10.0, 59.0], [10.1, 59.1]]
    }
  ]
}
```

**Example:**
```bash
GET /api/snap-targets?bbox=10.0,59.0,11.0,60.0
```

---

## Utility Endpoints

### `GET /health`

Health check endpoint for monitoring and load balancers.

**Response:**
```json
{
  "status": "healthy"
}
```

**Example:**
```bash
GET /health
```

**Note:** This endpoint does not require authentication and always returns 200 OK if the server is running.

---

## Data Models

### Common Types

#### GeoJSON Geometry
All geometry fields use GeoJSON format:
- `Point`: `{"type": "Point", "coordinates": [lon, lat]}`
- `LineString`: `{"type": "LineString", "coordinates": [[lon1, lat1], [lon2, lat2], ...]}`
- `Polygon`: `{"type": "Polygon", "coordinates": [[[lon1, lat1], [lon2, lat2], ...]]}`
- `MultiLineString`: `{"type": "MultiLineString", "coordinates": [[[lon1, lat1], ...], ...]}`

**Coordinate Format:** `[longitude, latitude]` in WGS84 (EPSG:4326)

---

### Route Models

#### `RouteInfo`
```typescript
{
  rutenummer: string;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
}
```

#### `Route`
```typescript
{
  rutenummer: string;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
  rutetype: string | null;
  route_geometry: GeoJSON | null;
  total_length_m: number;
  segment_count: number;
  segment_objids: number[] | null;
  from_name: string | null;
  to_name: string | null;
}
```

#### `RouteSegment`
```typescript
{
  objid: number;
  object_uuid: string;
  routes: RouteInfo[];
  length_meters: number | null;
  geometry: GeoJSON | null;
  oppdateringsdato: string | null;  // Last updated in turrutebasen (ISO timestamp)
}
```

#### `RouteSegmentDetail`
```typescript
{
  rutenummer: string;
  segment_objid: number;
  object_uuid: string;
  senterlinje: GeoJSON | null;
  source_node: number | null;
  target_node: number | null;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
  rutetype: string | null;
  gradering: string | null;
  length_meters: number | null;
  oppdateringsdato: string | null;  // Last updated in turrutebasen (ISO timestamp)
}
```

#### `RouteLink`
```typescript
{
  link_id: number;
  a_node: number | null;
  b_node: number | null;
  a_node_name: string | null;
  b_node_name: string | null;
  length_m: number | null;
  segment_objids: number[] | null;
  geom: GeoJSON | null;
}
```

#### `EndpointName`
```typescript
{
  name: string;
  source: "ruteinfopunkt" | "stedsnavn" | "anchor_node";
  distance_meters: number | null;
  coordinates: [number, number] | null;  // [lon, lat]
  tilrettelegging: string | null;  // Only for ruteinfopunkt
}
```

#### `CompleteRouteResponse`
```typescript
{
  rutenummer: string;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
  geometry: GeoJSON | null;
  total_length_meters: number;
  total_length_km: number;
  from_name: EndpointName | null;
  to_name: EndpointName | null;
  is_connected: boolean;
  segment_count: number;
  component_count: number;
  segments: RouteSegment[] | null;
  components: RouteComponent[] | null;
}
```

---

### Matrikkel Models

#### `MatrikkelenhetItem`
```typescript
{
  matrikkelenhet: string;  // Format: "1234/45/67"
  bruksnavn: string | null;
  kommunenummer: string | null;
  kommunenavn: string | null;
  offset_meters: number;
  offset_km: number;
  length_meters: number;
  length_km: number;
  geometry: GeoJSON;
}
```

#### `MatrikkelenhetItemWithOwners`
Extends `MatrikkelenhetItem`:
```typescript
{
  ...MatrikkelenhetItem,
  owners: string | null;  // Owner information from Matrikkel API
}
```

#### `PointMatrikkelResponse`
```typescript
{
  matrikkelenhet: string;
  matrikkelnummertekst: string | null;
  bruksnavn: string | null;
  kommunenummer: number | null;
  kommunenavn: string | null;
  arealmerknadtekst: string | null;
  lagretberegnetareal: number | null;
  gardsnummer: number | null;
  bruksnummer: number | null;
  festenummer: number | null;
  polygon_geometry: GeoJSON;
  owners: string | null;
  owner_error: string | null;
  teigid: number | null;
}
```

---

### Changeset Models

#### `CreateChangesetRequest`
```typescript
{
  title: string;
  description: string | null;
  area: string | null;
  linked_issue_url: string | null;
  base_snapshot: string;  // Default: "default"
}
```

#### `ChangesetResponse`
```typescript
{
  id: string;  // UUID
  title: string;
  description: string | null;
  area: string | null;
  status: "draft" | "review" | "approved" | "exported";
  created_by: string;
  created_at: string;  // ISO 8601 datetime
  updated_at: string;  // ISO 8601 datetime
  base_snapshot: string;
  linked_issue_url: string | null;
  pr_url: string | null;
}
```

#### Event Types

**SegmentUpdateAttrsEvent:**
```typescript
{
  type: "segment.update_attrs";
  target: { kind: "segment"; id: string };
  patch: Array<{ op: string; path: string; value: any }>;  // JSON Patch
  comment: string | null;
}
```

**SegmentUpdateGeomEvent:**
```typescript
{
  type: "segment.update_geom";
  target: { kind: "segment"; id: string };
  geometry: GeoJSON;
  srid: number;  // Default: 4326
  comment: string | null;
}
```

**SegmentRetireEvent:**
```typescript
{
  type: "segment.retire";
  target: { kind: "segment"; id: string };
  comment: string | null;
}
```

**SegmentAddEvent:**
```typescript
{
  type: "segment.add";
  temp_id: string;  // Format: "tmp_[a-f0-9-]+"
  geometry: GeoJSON;
  srid: number;  // Default: 4326
  attrs: Record<string, any>;
  comment: string | null;
}
```

**SegmentDeleteNewEvent:**
```typescript
{
  type: "segment.delete_new";
  target: { kind: "segment"; temp_id: string };
  comment: string | null;
}
```

---

## Error Handling

### Error Response Format

All errors follow a consistent format:

```json
{
  "error": "Error type",
  "detail": "Detailed error message"
}
```

### HTTP Status Codes

- `200 OK`: Successful request
- `400 Bad Request`: Invalid request parameters or validation errors
- `401 Unauthorized`: Authentication required or invalid credentials
- `404 Not Found`: Resource not found (route, changeset, segment, etc.)
- `500 Internal Server Error`: Server error

### Common Error Scenarios

#### Invalid Bounding Box
```json
{
  "error": "Invalid bbox format",
  "detail": "bbox must have exactly 4 values: xmin,ymin,xmax,ymax"
}
```

#### Route Not Found
```json
{
  "error": "Route not found",
  "detail": "Route with rutenummer 'bre10' not found"
}
```

#### Authentication Required
```json
{
  "error": "Invalid authentication credentials",
  "detail": "Invalid authentication credentials"
}
```

#### Validation Errors
```json
{
  "error": "Validation failed",
  "detail": "Changeset has validation errors: [list of errors]"
}
```

---

## Coordinate Systems

### Primary Coordinate System
- **WGS84 (EPSG:4326)**: Used for all API requests and responses
- **Format:** `[longitude, latitude]` (note: lon first, lat second)
- **Example:** `[10.7522, 59.9139]` (Oslo, Norway)

### Internal Coordinate Systems
- **UTM 33N (EPSG:25833)**: Used internally for spatial queries and storage
- **Links SRID:** 25833 (UTM 33N) - used for links table geometry

### Coordinate Transformations
The API automatically handles coordinate transformations:
- Input bbox in WGS84 (4326) → transformed to UTM 33N (25833) for spatial queries
- Database geometries in UTM 33N → transformed to WGS84 (4326) for API responses

### Bounding Box Format
Bounding boxes are specified as: `"xmin,ymin,xmax,ymax"` in WGS84 (EPSG:4326)

**Example:**
```
bbox=10.0,59.0,11.0,60.0
```
This represents:
- Minimum longitude: 10.0
- Minimum latitude: 59.0
- Maximum longitude: 11.0
- Maximum latitude: 60.0

---

## Usage Examples

### Complete Workflow: Get Route and Generate Owner Report

```bash
# 1. Search for a route
GET /api/v1/search/places?q=breivasshytta

# 2. Get complete route information
GET /api/v1/routes/bre10/complete?include_geometry=true

# 3. Get owners for route geometry
POST /api/v1/geometry/owners
{
  "geometry": { ... }  # From step 2
}

# 4. Generate Excel report
POST /api/v1/owners.xlsx
Authorization: Basic <credentials>
{
  "matrikkelenhet_vector": [ ... ],  # From step 3
  "metadata": {
    "rutenummer": "bre10",
    "rutenavn": "Breivasshytta - Gjendesheim"
  },
  "title": "Eierliste for bre10"
}
```

### Changeset Workflow

```bash
# 1. Create changeset
POST /api/changesets
X-User: john.doe
{
  "title": "Fix route geometry",
  "description": "Update segment 123 geometry"
}

# 2. Add events
POST /api/changesets/{changeset_id}/events
X-User: john.doe
{
  "event": {
    "type": "segment.update_geom",
    "target": { "kind": "segment", "id": "123" },
    "geometry": { ... }
  }
}

# 3. Validate changeset
POST /api/changesets/{changeset_id}/validate

# 4. Get diff visualization
GET /api/changesets/{changeset_id}/diff.geojson

# 5. Publish changeset
POST /api/changesets/{changeset_id}/publish
X-User: john.doe
```

---

## Notes for LLM Code Generation

1. **Always use WGS84 (EPSG:4326)** for coordinates in API requests
2. **Coordinate order:** `[longitude, latitude]` (not lat, lon)
3. **Bounding boxes:** Format as `"xmin,ymin,xmax,ymax"` string
4. **Authentication:** Use HTTP Basic Auth for protected endpoints
5. **GeoJSON:** All geometry fields use standard GeoJSON format
6. **Pagination:** Use `limit` and `offset` for large result sets
7. **Error handling:** Always check status codes and error response format
8. **Changeset events:** Use JSON Patch format for attribute updates
9. **Temporary IDs:** New segments use `tmp_` prefix with UUID format
10. **Validation:** Validate changesets before publishing

---

## Additional Resources

- FastAPI automatically generates OpenAPI/Swagger documentation at `/docs`
- Interactive API documentation available at `/docs` (Swagger UI)
- Alternative API documentation at `/redoc` (ReDoc)
