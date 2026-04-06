-- Debug script to check routes for links
-- Run with: psql -d <database> -f debug_link_routes.sql

-- 1. Check if links_with_routes table exists and has route columns
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'stiflyt'
  AND table_name IN ('links_with_routes', 'links')
  AND column_name IN ('link_id', 'rutenummer_list', 'rutenavn_list', 'rutetype_list', 'vedlikeholdsansvarlig_list')
ORDER BY table_name, column_name;

-- 2. Find a link that should have multiple routes (sample)
-- Look for links with multiple route numbers in the array
SELECT
    link_id,
    a_node,
    b_node,
    length_m,
    rutenummer_list,
    rutenavn_list,
    array_length(rutenummer_list, 1) as route_count,
    rutenummer_list[1] as first_route,
    rutenummer_list[2] as second_route
FROM stiflyt.links_with_routes
WHERE rutenummer_list IS NOT NULL
  AND array_length(rutenummer_list, 1) > 1
LIMIT 10;

-- 3. Check a specific link by ID (replace with actual link_id from frontend debug)
-- Example: Check link_id = 12345
-- SELECT
--     link_id,
--     a_node,
--     b_node,
--     length_m,
--     rutenummer_list,
--     rutenavn_list,
--     rutetype_list,
--     vedlikeholdsansvarlig_list,
--     array_length(rutenummer_list, 1) as route_count
-- FROM stiflyt.links_with_routes
-- WHERE link_id = 12345;

-- 4. Compare with actual segments to see if routes are missing
-- Find links that appear in multiple routes but only show one route in links_with_routes
WITH link_routes AS (
    SELECT
        lwr.link_id,
        lwr.rutenummer_list,
        array_length(lwr.rutenummer_list, 1) as route_count_in_link
    FROM stiflyt.links_with_routes lwr
    WHERE lwr.rutenummer_list IS NOT NULL
),
segment_routes AS (
    SELECT DISTINCT
        s.objid as segment_objid,
        s.rutenummer,
        -- Find which link this segment belongs to
        -- This is a simplified check - actual link_id might come from a different source
        NULL as link_id
    FROM stiflyt.segments s
    WHERE s.rutenummer IS NOT NULL
)
SELECT
    lr.link_id,
    lr.route_count_in_link,
    lr.rutenummer_list,
    -- Count how many different routes use segments that might be in this link
    (SELECT COUNT(DISTINCT sr.rutenummer)
     FROM segment_routes sr
     WHERE sr.segment_objid IN (
         -- This is a placeholder - actual relationship between segments and links
         -- needs to be determined from your schema
         SELECT segment_objid FROM stiflyt.segments WHERE rutenummer IS NOT NULL LIMIT 100
     )
    ) as expected_route_count
FROM link_routes lr
WHERE lr.route_count_in_link = 1
LIMIT 20;

-- 5. Check if rutenummer_list arrays are properly populated
-- Look for NULL arrays or empty arrays
SELECT
    COUNT(*) as total_links,
    COUNT(rutenummer_list) as links_with_routes_array,
    COUNT(*) FILTER (WHERE rutenummer_list IS NULL) as links_with_null_array,
    COUNT(*) FILTER (WHERE rutenummer_list IS NOT NULL AND array_length(rutenummer_list, 1) = 0) as links_with_empty_array,
    COUNT(*) FILTER (WHERE rutenummer_list IS NOT NULL AND array_length(rutenummer_list, 1) = 1) as links_with_one_route,
    COUNT(*) FILTER (WHERE rutenummer_list IS NOT NULL AND array_length(rutenummer_list, 1) > 1) as links_with_multiple_routes,
    AVG(array_length(rutenummer_list, 1)) FILTER (WHERE rutenummer_list IS NOT NULL) as avg_routes_per_link
FROM stiflyt.links_with_routes;

-- 6. Find links in a specific bbox (replace with actual bbox from frontend)
-- Example bbox: 10.0,59.0,11.0,60.0 (WGS84)
-- This shows what the API would return
SELECT
    link_id,
    a_node,
    b_node,
    length_m,
    rutenummer_list,
    rutenavn_list,
    array_length(rutenummer_list, 1) as route_count,
    ST_AsText(ST_Transform(geom, 4326)) as geom_wgs84
FROM stiflyt.links_with_routes
WHERE geom && ST_Transform(ST_MakeEnvelope(10.0, 59.0, 11.0, 60.0, 4326), 25833)
  AND geom IS NOT NULL
ORDER BY link_id
LIMIT 20;

-- 7. Check if the view/table is a materialized view that needs refreshing
SELECT
    schemaname,
    matviewname,
    hasindexes,
    ispopulated
FROM pg_matviews
WHERE schemaname = 'stiflyt'
  AND matviewname IN ('links_with_routes', 'links');

-- 8. If it's a materialized view, check when it was last refreshed
-- (This query might need adjustment based on your PostgreSQL version)
SELECT
    schemaname,
    matviewname,
    -- Note: last refresh time might not be directly available in all PostgreSQL versions
    -- You may need to check logs or add a refresh timestamp column
    hasindexes,
    ispopulated
FROM pg_matviews
WHERE schemaname = 'stiflyt'
  AND matviewname IN ('links_with_routes', 'links');
