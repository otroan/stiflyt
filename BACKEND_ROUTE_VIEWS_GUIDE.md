# Backend Guide: Using Route Views

## Overview

New route views have been added to the `stiflyt` schema for easy route querying and visualization:
- `stiflyt.routes` - Complete routes with aggregated geometry (materialized view)
- `stiflyt.route_segments` - Individual segments with route info (view)

## Available Views

### `stiflyt.routes` (Materialized View)
Complete route information with aggregated geometry.

**Columns:**
- `rutenummer` (TEXT) - Route identifier (e.g., "bre10", "DNT-1")
- `rutenavn` (TEXT) - Route name
- `vedlikeholdsansvarlig` (TEXT) - Maintenance responsible/organization
- `rutetype` (TEXT) - Route type
- `route_geometry` (GEOMETRY) - Aggregated MULTILINESTRING (all segments combined)
- `total_length_m` (DOUBLE PRECISION) - Total route length in meters
- `segment_count` (BIGINT) - Number of segments
- `segment_objids` (BIGINT[]) - Array of segment IDs

**Indexes:**
- Unique index on `rutenummer` (fast lookup)
- GIST index on `route_geometry` (spatial queries)
- Index on `vedlikeholdsansvarlig` (organization filtering)

### `stiflyt.route_segments` (View)
Individual route segments with route metadata.

**Columns:**
- `rutenummer` (TEXT) - Route identifier
- `segment_objid` (BIGINT) - Segment ID
- `senterlinje` (GEOMETRY) - Segment geometry (LINESTRING)
- `source_node`, `target_node` (INTEGER) - Topology nodes
- `rutenavn`, `vedlikeholdsansvarlig`, `rutetype`, `gradering`, etc. - Route metadata

## Common Query Patterns

### 1. Get Complete Route by Rutenummer

```sql
SELECT
    rutenummer,
    rutenavn,
    route_geometry,
    total_length_m,
    segment_count
FROM stiflyt.routes
WHERE rutenummer = 'bre10';
```

**Use Case:** Route overview, complete geometry for visualization

### 2. List All Routes

```sql
SELECT
    rutenummer,
    rutenavn,
    vedlikeholdsansvarlig,
    total_length_m,
    segment_count
FROM stiflyt.routes
ORDER BY rutenummer;
```

### 3. Filter Routes by Prefix

```sql
-- Get all routes starting with "bre"
SELECT * FROM stiflyt.routes
WHERE rutenummer LIKE 'bre%'
ORDER BY rutenummer;

-- Get all routes starting with "jot"
SELECT * FROM stiflyt.routes
WHERE rutenummer LIKE 'jot%'
ORDER BY rutenummer;
```

### 4. Filter Routes by Organization

```sql
SELECT * FROM stiflyt.routes
WHERE vedlikeholdsansvarlig = 'DNT'
ORDER BY rutenummer;
```

### 5. Get Routes in Bounding Box (Spatial Query)

```sql
SELECT
    rutenummer,
    rutenavn,
    route_geometry,
    total_length_m
FROM stiflyt.routes
WHERE ST_Intersects(
    route_geometry,
    ST_MakeEnvelope(minx, miny, maxx, maxy, 25833)
);
```

**Use Case:** Map viewport queries, show routes in visible area

### 6. Get Individual Segments for a Route

```sql
SELECT
    segment_objid,
    senterlinje,
    source_node,
    target_node,
    rutenavn,
    rutenummer
FROM stiflyt.route_segments
WHERE rutenummer = 'bre10'
ORDER BY segment_objid;
```

**Use Case:** Detailed visualization, segment-level editing

### 7. Get Segments in Bounding Box (For Manual Editing)

```sql
SELECT
    f.objid,
    f.senterlinje,
    f.source_node,
    f.target_node,
    array_agg(DISTINCT fi.rutenummer) FILTER (WHERE fi.rutenummer IS NOT NULL) as rutenummer_list,
    array_agg(DISTINCT fi.rutenavn) FILTER (WHERE fi.rutenavn IS NOT NULL) as rutenavn_list,
    CASE WHEN COUNT(fi.fotrute_fk) > 0 THEN true ELSE false END as has_route_metadata
FROM stiflyt.fotrute f
LEFT JOIN stiflyt.fotruteinfo fi ON fi.fotrute_fk = f.objid
WHERE ST_Intersects(
    f.senterlinje,
    ST_MakeEnvelope(minx, miny, maxx, maxy, 25833)
)
GROUP BY f.objid, f.senterlinje, f.source_node, f.target_node;
```

**Use Case:** Show all segments in viewport for manual metadata editing

## API Endpoint Examples

### GET /routes
```sql
SELECT rutenummer, rutenavn, vedlikeholdsansvarlig, total_length_m, segment_count
FROM stiflyt.routes
ORDER BY rutenummer;
```

### GET /routes?prefix=bre
```sql
SELECT * FROM stiflyt.routes
WHERE rutenummer LIKE 'bre%'
ORDER BY rutenummer;
```

### GET /routes?bbox=minx,miny,maxx,maxy
```sql
SELECT * FROM stiflyt.routes
WHERE ST_Intersects(route_geometry, ST_MakeEnvelope(minx, miny, maxx, maxy, 25833));
```

### GET /routes/{rutenummer}
```sql
SELECT * FROM stiflyt.routes WHERE rutenummer = 'bre10';
```

### GET /routes/{rutenummer}/segments
```sql
SELECT * FROM stiflyt.route_segments
WHERE rutenummer = 'bre10'
ORDER BY segment_objid;
```

## Performance Notes

- **`stiflyt.routes`** is a materialized view - fast lookups, but needs refresh after data updates
- **Unique index on `rutenummer`** - O(log n) route lookup
- **GIST index on `route_geometry`** - Fast spatial queries
- **`stiflyt.route_segments`** is a regular view - always up-to-date, but may be slower for large routes

## Important Notes

1. **Always use `stiflyt` schema** - Never reference dynamic schema names
2. **Routes can have multiple components** - Disconnected segments are often valid (glaciers, lakes)
3. **Routes can overlap** - Same segment can belong to multiple routes
4. **Missing segments** - Some segments may not have rutenummer (belong to other organizations)
5. **Geometry SRID** - All geometries use SRID 25833 (UTM Zone 33N)

## Example: Complete Route with Segments

```python
# Get complete route
route = db.query("""
    SELECT * FROM stiflyt.routes WHERE rutenummer = %s
""", (rutenummer,))

# Get individual segments
segments = db.query("""
    SELECT * FROM stiflyt.route_segments
    WHERE rutenummer = %s
    ORDER BY segment_objid
""", (rutenummer,))

# Return both in API response
return {
    'route': route,
    'segments': segments
}
```

## Routing Topology

For routing along routes, use existing `stiflyt.links` filtered by route:

```sql
-- Get links for a route (routing topology)
SELECT
    l.link_id,
    l.a_node,
    l.b_node,
    l.length_m,
    l.geom,
    l.segment_objids
FROM stiflyt.links l
JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
WHERE lri.rutenummer = 'bre10'
ORDER BY l.link_id;
```

Links provide routing topology (segments between junctions) - see `ROUTE_VISUALIZATION_PLAN.md` for details.

