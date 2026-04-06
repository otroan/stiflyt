-- Debug script for route 20160407 endpoint detection bug
-- The route should go from Sunndalssetra to a junction, but the tool thinks it goes from Slæom to Sunndalssetra
-- The link from Slæom to that junction does NOT have rutenummer 20160407

-- 1. Find all links that have route 20160407 in their rutenummer_list
WITH route_links_expanded AS (
    SELECT
        lwr.link_id,
        lwr.a_node,
        lwr.b_node,
        lwr.rutenummer_list,
        lwr.length_m,
        UNNEST(lwr.rutenummer_list) as rutenummer
    FROM stiflyt.links_with_routes lwr
    WHERE '20160407' = ANY(lwr.rutenummer_list)
),
-- 2. Count node occurrences for route 20160407
route_nodes AS (
    SELECT
        node_id,
        COUNT(*) as occurrence_count,
        array_agg(DISTINCT link_id ORDER BY link_id) as link_ids
    FROM (
        SELECT rutenummer, a_node as node_id, link_id FROM route_links_expanded WHERE rutenummer = '20160407'
        UNION ALL
        SELECT rutenummer, b_node as node_id, link_id FROM route_links_expanded WHERE rutenummer = '20160407'
    ) all_nodes
    WHERE rutenummer = '20160407'
    GROUP BY node_id
),
-- 3. Identify endpoints (nodes that appear only once)
route_endpoints AS (
    SELECT
        node_id,
        occurrence_count,
        link_ids
    FROM route_nodes
    WHERE occurrence_count = 1
),
-- 4. Get node names from anchor_nodes
endpoints_with_names AS (
    SELECT
        re.node_id,
        re.occurrence_count,
        re.link_ids,
        an.navn as node_name,
        an.anchor_type,
        ST_X(ST_Transform(an.geom, 4326)) as lon,
        ST_Y(ST_Transform(an.geom, 4326)) as lat
    FROM route_endpoints re
    LEFT JOIN stiflyt.anchor_nodes an ON an.node_id = re.node_id
)
-- 5. Show all endpoints with their names
SELECT
    node_id,
    node_name,
    anchor_type,
    occurrence_count,
    link_ids,
    lon,
    lat,
    CASE
        WHEN node_name ILIKE '%Slæom%' THEN '*** SLÆOM FOUND ***'
        WHEN node_name ILIKE '%Sunndalssetra%' THEN '*** SUNNDALSSETRA FOUND ***'
        ELSE ''
    END as marker
FROM endpoints_with_names
ORDER BY node_id;

-- 6. Check all links for route 20160407 with their nodes and names
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    lwr.rutenummer_list,
    lwr.length_m,
    an_a.navn as a_node_name,
    an_b.navn as b_node_name,
    CASE
        WHEN an_a.navn ILIKE '%Slæom%' OR an_b.navn ILIKE '%Slæom%' THEN '*** CONTAINS SLÆOM ***'
        WHEN an_a.navn ILIKE '%Sunndalssetra%' OR an_b.navn ILIKE '%Sunndalssetra%' THEN '*** CONTAINS SUNNDALSSETRA ***'
        ELSE ''
    END as marker
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE '20160407' = ANY(lwr.rutenummer_list)
ORDER BY lwr.link_id;

-- 7. Check if bre26 shares any links with 20160407 (they should be duplicates)
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    lwr.rutenummer_list,
    an_a.navn as a_node_name,
    an_b.navn as b_node_name,
    CASE
        WHEN '20160407' = ANY(lwr.rutenummer_list) AND 'bre26' = ANY(lwr.rutenummer_list) THEN '*** SHARED BY BOTH ***'
        WHEN '20160407' = ANY(lwr.rutenummer_list) THEN '*** ONLY 20160407 ***'
        WHEN 'bre26' = ANY(lwr.rutenummer_list) THEN '*** ONLY bre26 ***'
        ELSE ''
    END as route_marker
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE '20160407' = ANY(lwr.rutenummer_list) OR 'bre26' = ANY(lwr.rutenummer_list)
ORDER BY lwr.link_id;

-- 8. Find links that have bre26 but NOT 20160407, and check if they connect to Slæom
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    lwr.rutenummer_list,
    an_a.navn as a_node_name,
    an_b.navn as b_node_name,
    CASE
        WHEN an_a.navn ILIKE '%Slæom%' OR an_b.navn ILIKE '%Slæom%' THEN '*** CONTAINS SLÆOM ***'
        ELSE ''
    END as marker
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE 'bre26' = ANY(lwr.rutenummer_list)
  AND NOT ('20160407' = ANY(lwr.rutenummer_list))
ORDER BY lwr.link_id;

-- 9. Find links that incorrectly have 20160407 but shouldn't (check segments)
-- Compare links_with_routes with actual route_segments
WITH links_with_20160407 AS (
    SELECT DISTINCT
        lwr.link_id,
        lwr.a_node,
        lwr.b_node,
        lwr.rutenummer_list,
        lwr.segment_objids
    FROM stiflyt.links_with_routes lwr
    WHERE '20160407' = ANY(lwr.rutenummer_list)
),
segments_with_20160407 AS (
    SELECT DISTINCT
        rs.objid as segment_objid,
        rs.rutenummer
    FROM stiflyt.route_segments rs
    WHERE rs.rutenummer = '20160407'
)
SELECT
    l.link_id,
    l.a_node,
    l.b_node,
    l.rutenummer_list,
    l.segment_objids,
    CASE
        WHEN l.segment_objids && ARRAY(SELECT segment_objid FROM segments_with_20160407)::bigint[]
        THEN '*** HAS CORRECT SEGMENTS ***'
        ELSE '*** NO MATCHING SEGMENTS - POTENTIAL BUG ***'
    END as validation
FROM links_with_20160407 l
ORDER BY l.link_id;
