-- Quick debug queries - run these one by one in psql

-- 1. Check structure of links_with_routes table
\d stiflyt.links_with_routes

-- 2. Find a link with multiple routes (if any exist)
SELECT
    link_id,
    rutenummer_list,
    array_length(rutenummer_list, 1) as route_count
FROM stiflyt.links_with_routes
WHERE rutenummer_list IS NOT NULL
  AND array_length(rutenummer_list, 1) > 1
LIMIT 5;

-- 3. Check a specific link (replace LINK_ID with actual ID from frontend console)
-- First, get a link_id from the frontend debug console, then run:
-- SELECT
--     link_id,
--     a_node,
--     b_node,
--     rutenummer_list,
--     rutenavn_list,
--     array_length(rutenummer_list, 1) as route_count
-- FROM stiflyt.links_with_routes
-- WHERE link_id = LINK_ID;

-- 4. Statistics on route distribution
SELECT
    array_length(rutenummer_list, 1) as routes_per_link,
    COUNT(*) as link_count
FROM stiflyt.links_with_routes
WHERE rutenummer_list IS NOT NULL
GROUP BY array_length(rutenummer_list, 1)
ORDER BY routes_per_link;

-- 5. Sample of links with their routes
SELECT
    link_id,
    rutenummer_list,
    rutenavn_list
FROM stiflyt.links_with_routes
WHERE rutenummer_list IS NOT NULL
ORDER BY array_length(rutenummer_list, 1) DESC
LIMIT 10;
