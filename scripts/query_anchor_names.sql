-- Query anchor points with names from operational database
-- Usage: psql -d <database> -f query_anchor_names.sql

-- List all anchor points with names (most recent first)
SELECT
    anchor_node_id,
    rutenummer,
    name,
    source_type,
    validated_by,
    validated_at,
    created_at,
    updated_at
FROM ops.endpoint_names
ORDER BY updated_at DESC;

-- List only global names (rutenummer IS NULL)
SELECT
    anchor_node_id,
    name,
    source_type,
    validated_by,
    validated_at,
    updated_at
FROM ops.endpoint_names
WHERE rutenummer IS NULL
ORDER BY anchor_node_id;

-- List route-specific names
SELECT
    anchor_node_id,
    rutenummer,
    name,
    source_type,
    validated_by,
    validated_at,
    updated_at
FROM ops.endpoint_names
WHERE rutenummer IS NOT NULL
ORDER BY rutenummer, anchor_node_id;

-- Count names by type
SELECT
    source_type,
    COUNT(*) as count,
    COUNT(DISTINCT anchor_node_id) as unique_anchors
FROM ops.endpoint_names
GROUP BY source_type
ORDER BY count DESC;

-- Find all names for a specific anchor node
-- Replace 61409 with your anchor_node_id
SELECT
    anchor_node_id,
    rutenummer,
    name,
    source_type,
    validated_by,
    validated_at,
    updated_at
FROM ops.endpoint_names
WHERE anchor_node_id = 61409
ORDER BY
    CASE WHEN rutenummer IS NULL THEN 0 ELSE 1 END,
    rutenummer;

-- Find all names for a specific route
-- Replace 'bre10' with your rutenummer
SELECT
    anchor_node_id,
    rutenummer,
    name,
    source_type,
    validated_by,
    validated_at,
    updated_at
FROM ops.endpoint_names
WHERE rutenummer = 'bre10' OR (rutenummer IS NULL AND anchor_node_id IN (
    SELECT DISTINCT anchor_node_id
    FROM ops.endpoint_names
    WHERE rutenummer = 'bre10'
))
ORDER BY
    CASE WHEN rutenummer IS NULL THEN 1 ELSE 0 END,
    anchor_node_id;
