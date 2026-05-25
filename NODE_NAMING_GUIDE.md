# Node Naming Guide: How to Get Endpoint and Junction Names for Routes

## Overview

Nodes and anchor nodes can have names from multiple sources:
1. **ruteinfopunkt** (route info points) - Huts, parking areas (within 100m)
2. **stedsnavn** (place names) - Named locations (within 200m, fallback)
3. **Coordinate fallback** - UTM coordinates if no name found

## Node Naming Structure

### `stiflyt.node_names` (Materialized View)
Matches nodes to named locations:
- **Source**: `ruteinfopunkt` (prioritized) or `stedsnavn` (fallback)
- **Distance**: 100m for ruteinfopunkt, 200m for stedsnavn
- **Columns**:
  - `node_id` - Node identifier
  - `navn` - Name (from opphav/informasjon for ruteinfopunkt, or komplettskrivemate for stedsnavn)
  - `navn_kilde` - Source: 'ruteinfopunkt' or 'stedsnavn'
  - `distance_m` - Distance to named location

### `stiflyt.anchor_nodes` (Materialized View)
Anchor nodes (junctions, endpoints) with names:
- **Columns**:
  - `node_id` - Node identifier
  - `geom` - Point geometry
  - `degree` - Number of connections (1=endpoint, 2=pass-through, 3+=junction)
  - `anchor_type` - 'topology' (degree != 2), 'ruteinfopunkt' (near route point), 'unknown'
  - `navn` - Name (from node_names, or coordinate fallback)
  - `navn_kilde` - Source: 'ruteinfopunkt', 'stedsnavn', or 'koordinat' (fallback)
  - `navn_distance_m` - Distance to named location (NULL for coordinate fallback)

## Name Priority

1. **ruteinfopunkt** (highest priority)
   - Within 100m of node
   - Uses `opphav` field, falls back to `informasjon` if `opphav` is empty
   - Only for specific types: Hytte (12, 42, 43, 44), Parkeringsplass (22)

2. **stedsnavn** (fallback)
   - Within 200m of node
   - Only if no ruteinfopunkt match
   - Uses `komplettskrivemate` from `skrivemate` table

3. **Coordinate fallback** (lowest priority)
   - Format: `"UTM25833 {x} {y}"`
   - Used when no named location found within distance threshold

## Getting Endpoint/Junction Names for Routes

### Method 1: Via Links (Recommended)

Links connect anchor nodes (junctions/endpoints), so you can get names for both endpoints:

```sql
-- Get links for a route with endpoint names
SELECT DISTINCT ON (l.link_id)
    l.link_id,
    l.a_node,
    l.b_node,
    an_a.navn as a_node_navn,
    an_a.navn_kilde as a_node_navn_kilde,
    an_b.navn as b_node_navn,
    an_b.navn_kilde as b_node_navn_kilde,
    l.length_m,
    l.geom
FROM stiflyt.links l
JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = l.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = l.b_node
WHERE lri.rutenummer = 'bre10'
ORDER BY l.link_id, lri.rutenavn;
```

**Or using links_with_routes** (no duplicates):

```sql
-- Get links for a route with endpoint names (no duplicates)
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    an_a.navn as a_node_navn,
    an_a.navn_kilde as a_node_navn_kilde,
    an_b.navn as b_node_navn,
    an_b.navn_kilde as b_node_navn_kilde,
    lwr.length_m,
    lwr.geom
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE 'bre10' = ANY(lwr.rutenummer_list)
ORDER BY lwr.link_id;
```

### Method 2: Get All Anchor Nodes for a Route

Find all unique anchor nodes (endpoints/junctions) used by a route:

```sql
-- Get all anchor nodes for a route
WITH route_nodes AS (
    SELECT DISTINCT
        l.a_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
    UNION
    SELECT DISTINCT
        l.b_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
)
SELECT
    an.node_id,
    an.navn,
    an.navn_kilde,
    an.degree,
    an.anchor_type,
    an.geom
FROM route_nodes rn
JOIN stiflyt.anchor_nodes an ON an.node_id = rn.node_id
ORDER BY an.degree DESC, an.navn;
```

### Method 3: Get Route Endpoints Only (degree = 1)

Find only the route endpoints (start/end points):

```sql
-- Get route endpoints (degree = 1 nodes)
WITH route_nodes AS (
    SELECT DISTINCT l.a_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
    UNION
    SELECT DISTINCT l.b_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
)
SELECT
    an.node_id,
    an.navn,
    an.navn_kilde,
    an.geom
FROM route_nodes rn
JOIN stiflyt.anchor_nodes an ON an.node_id = rn.node_id
WHERE an.degree = 1  -- Endpoints only
ORDER BY an.navn;
```

### Method 4: Get Junctions Only (degree >= 3)

Find only the route junctions (where multiple routes meet):

```sql
-- Get route junctions (degree >= 3)
WITH route_nodes AS (
    SELECT DISTINCT l.a_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
    UNION
    SELECT DISTINCT l.b_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
)
SELECT
    an.node_id,
    an.navn,
    an.navn_kilde,
    an.degree,
    an.geom
FROM route_nodes rn
JOIN stiflyt.anchor_nodes an ON an.node_id = rn.node_id
WHERE an.degree >= 3  -- Junctions only
ORDER BY an.degree DESC, an.navn;
```

## Understanding Node Names

### Name Sources

1. **ruteinfopunkt** (`navn_kilde = 'ruteinfopunkt'`)
   - Named route points: Huts, parking areas
   - Most reliable source
   - Example: "Trulsbu", "Hardangervidda Turisthytte"

2. **stedsnavn** (`navn_kilde = 'stedsnavn'`)
   - Named places from official place name database
   - Fallback if no ruteinfopunkt match
   - Example: "Lundadalen", "Finse"

3. **koordinat** (`navn_kilde = 'koordinat'`)
   - Coordinate-based fallback
   - Format: "UTM25833 {x} {y}"
   - Used when no named location found within distance threshold
   - Example: "UTM25833 143569 6873953"

### Why Some Nodes Have Coordinate Names

Not all nodes have named locations nearby:
- **Distance threshold**: ruteinfopunkt must be within 100m, stedsnavn within 200m
- **No nearby features**: Node may be in remote area without huts or named places
- **Route endpoints**: May be in wilderness without nearby infrastructure

This is **normal and expected** - coordinate names indicate the node location when no named place is available.

## Example: Complete Route with Endpoint Names

```sql
-- Get complete route information with endpoint names
WITH route_links AS (
    SELECT DISTINCT ON (l.link_id)
        l.link_id,
        l.a_node,
        l.b_node,
        l.length_m,
        l.geom
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
    ORDER BY l.link_id, lri.rutenavn
),
route_endpoints AS (
    SELECT DISTINCT node_id
    FROM (
        SELECT a_node as node_id FROM route_links
        UNION
        SELECT b_node as node_id FROM route_links
    ) nodes
)
SELECT
    r.rutenummer,
    r.rutenavn,
    r.total_length_m,
    -- Get start endpoint (first a_node or b_node)
    (SELECT navn FROM stiflyt.anchor_nodes WHERE node_id = (
        SELECT a_node FROM route_links ORDER BY link_id LIMIT 1
    )) as start_navn,
    -- Get end endpoint (last a_node or b_node)
    (SELECT navn FROM stiflyt.anchor_nodes WHERE node_id = (
        SELECT b_node FROM route_links ORDER BY link_id DESC LIMIT 1
    )) as end_navn,
    -- Count named vs coordinate endpoints
    (SELECT COUNT(*) FROM route_endpoints re
     JOIN stiflyt.anchor_nodes an ON an.node_id = re.node_id
     WHERE an.navn_kilde != 'koordinat') as named_endpoints,
    (SELECT COUNT(*) FROM route_endpoints re
     JOIN stiflyt.anchor_nodes an ON an.node_id = re.node_id
     WHERE an.navn_kilde = 'koordinat') as coordinate_endpoints
FROM stiflyt.routes r
WHERE r.rutenummer = 'bre10';
```

## Best Practices

1. **Always use DISTINCT ON** when querying `link_ruteinfo` to avoid duplicates
2. **Use links_with_routes** for cleaner queries (no duplicates)
3. **Handle coordinate names gracefully** - they're valid when no named location exists
4. **Check navn_kilde** to understand name source (ruteinfopunkt > stedsnavn > koordinat)
5. **Filter by degree** to get specific node types:
   - `degree = 1`: Endpoints
   - `degree = 2`: Pass-through nodes (usually not anchor nodes)
   - `degree >= 3`: Junctions

## API Endpoint Examples

### GET /routes/{rutenummer}/endpoints
```sql
-- Get route endpoints with names
WITH route_nodes AS (
    SELECT DISTINCT l.a_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
    UNION
    SELECT DISTINCT l.b_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
)
SELECT
    an.node_id,
    an.navn,
    an.navn_kilde,
    an.degree,
    ST_AsGeoJSON(an.geom) as geometry
FROM route_nodes rn
JOIN stiflyt.anchor_nodes an ON an.node_id = rn.node_id
WHERE an.degree = 1  -- Endpoints only
ORDER BY an.navn;
```

### GET /routes/{rutenummer}/junctions
```sql
-- Get route junctions with names
WITH route_nodes AS (
    SELECT DISTINCT l.a_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
    UNION
    SELECT DISTINCT l.b_node as node_id
    FROM stiflyt.links l
    JOIN stiflyt.link_ruteinfo lri ON lri.link_id = l.link_id
    WHERE lri.rutenummer = 'bre10'
)
SELECT
    an.node_id,
    an.navn,
    an.navn_kilde,
    an.degree,
    ST_AsGeoJSON(an.geom) as geometry
FROM route_nodes rn
JOIN stiflyt.anchor_nodes an ON an.node_id = rn.node_id
WHERE an.degree >= 3  -- Junctions only
ORDER BY an.degree DESC, an.navn;
```

### GET /routes/{rutenummer}/links?with_names=true
```sql
-- Get links with endpoint names
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    an_a.navn as a_node_navn,
    an_a.navn_kilde as a_node_navn_kilde,
    an_b.navn as b_node_navn,
    an_b.navn_kilde as b_node_navn_kilde,
    lwr.length_m,
    ST_AsGeoJSON(lwr.geom) as geometry
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE 'bre10' = ANY(lwr.rutenummer_list)
ORDER BY lwr.link_id;
```

## Summary

- **Node names come from**: ruteinfopunkt (prioritized), stedsnavn (fallback), or coordinates (if no name found)
- **Get endpoint names via**: Join `links` with `anchor_nodes` on `a_node` and `b_node`
- **Coordinate names are valid**: They indicate node location when no named place exists nearby
- **Always use DISTINCT ON** or `links_with_routes` to avoid duplicates when querying links for routes
