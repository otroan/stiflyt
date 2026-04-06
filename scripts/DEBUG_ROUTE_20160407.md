# Debug Guide: Route 20160407 Endpoint Detection Bug

## Problem Description

Route 20160407 should go from **Sunndalssetra to a junction**, but the tool incorrectly identifies it as going from **Slæom to Sunndalssetra**.

The key issue: **The link from Slæom to that junction does NOT have rutenummer 20160407**, yet the endpoint detection algorithm incorrectly identifies Slæom as an endpoint.

## Root Cause Analysis

The endpoint detection logic is in `services/route_service.py` (lines 1613-1651). It works as follows:

1. **Expand links**: Find all links where the route number appears in `rutenummer_list`
   ```sql
   SELECT UNNEST(lwr.rutenummer_list) as rutenummer, lwr.link_id, lwr.a_node, lwr.b_node
   FROM links_with_routes lwr
   WHERE lwr.rutenummer_list && ARRAY['20160407']
   ```

2. **Count node occurrences**: Count how many times each node appears (as either a_node or b_node)
   ```sql
   SELECT node_id, COUNT(*) as occurrence_count
   FROM (a_nodes UNION ALL b_nodes)
   GROUP BY node_id
   ```

3. **Identify endpoints**: Nodes that appear only once are endpoints
   ```sql
   SELECT MIN(node_id) FILTER (WHERE occurrence_count = 1) as first_node,
          MAX(node_id) FILTER (WHERE occurrence_count = 1) as last_node
   ```

4. **Problem**: If a link incorrectly has `20160407` in its `rutenummer_list`, then:
   - That link's nodes get included in the endpoint calculation
   - If one of those nodes (e.g., Slæom) appears only once across all links with 20160407, it gets identified as an endpoint
   - The MIN/MAX logic then picks Slæom as the first endpoint

## How to Find the Bug

### Method 1: SQL Query (Recommended)

Run the SQL script:
```bash
psql -d <your_database> -f scripts/debug_route_20160407.sql
```

This will show:
1. All endpoints detected for route 20160407
2. All links that have 20160407 in their rutenummer_list
3. Comparison with bre26 (should be duplicate)
4. Links that have 20160407 but don't contain matching segments (BUG INDICATOR)

### Method 2: Python Script

Run the Python investigation script:
```bash
python scripts/investigate_route_20160407.py 20160407
```

This will show:
1. All links with route 20160407 and their node names
2. The endpoint detection result
3. Node occurrence counts (showing which nodes are incorrectly identified as endpoints)
4. Comparison with bre26
5. Segment-based validation (links that have the route but don't contain matching segments)

### Method 3: Manual Database Query

Run these queries step by step:

#### Step 1: Find all links with route 20160407
```sql
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    lwr.rutenummer_list,
    lwr.segment_objids,
    an_a.navn as a_node_name,
    an_b.navn as b_node_name
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE '20160407' = ANY(lwr.rutenummer_list)
ORDER BY lwr.link_id;
```

#### Step 2: Check node occurrence counts
```sql
WITH route_links_expanded AS (
    SELECT
        UNNEST(lwr.rutenummer_list) as rutenummer,
        lwr.link_id,
        lwr.a_node,
        lwr.b_node
    FROM stiflyt.links_with_routes lwr
    WHERE '20160407' = ANY(lwr.rutenummer_list)
),
route_nodes AS (
    SELECT
        node_id,
        COUNT(*) as occurrence_count,
        array_agg(DISTINCT link_id ORDER BY link_id) as link_ids
    FROM (
        SELECT a_node as node_id, link_id FROM route_links_expanded WHERE rutenummer = '20160407'
        UNION ALL
        SELECT b_node as node_id, link_id FROM route_links_expanded WHERE rutenummer = '20160407'
    ) all_nodes
    GROUP BY node_id
)
SELECT
    rn.node_id,
    rn.occurrence_count,
    rn.link_ids,
    an.navn as node_name
FROM route_nodes rn
LEFT JOIN stiflyt.anchor_nodes an ON an.node_id = rn.node_id
ORDER BY rn.occurrence_count, rn.node_id;
```

**Look for**: Nodes with `occurrence_count = 1` that shouldn't be endpoints (like Slæom)

#### Step 3: Validate links against segments
```sql
-- Get segments with route 20160407
WITH segments_with_route AS (
    SELECT DISTINCT objid as segment_objid
    FROM stiflyt.route_segments
    WHERE rutenummer = '20160407'
)
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    lwr.rutenummer_list,
    lwr.segment_objids,
    an_a.navn as a_node_name,
    an_b.navn as b_node_name,
    CASE
        WHEN lwr.segment_objids && ARRAY(SELECT segment_objid FROM segments_with_route)::bigint[]
        THEN 'VALID'
        ELSE 'INVALID - NO MATCHING SEGMENTS'
    END as validation
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE '20160407' = ANY(lwr.rutenummer_list)
ORDER BY validation, lwr.link_id;
```

**Look for**: Links marked as "INVALID - NO MATCHING SEGMENTS" - these are the buggy links!

#### Step 4: Compare with bre26
```sql
SELECT
    lwr.link_id,
    lwr.a_node,
    lwr.b_node,
    lwr.rutenummer_list,
    an_a.navn as a_node_name,
    an_b.navn as b_node_name,
    CASE
        WHEN '20160407' = ANY(lwr.rutenummer_list) AND 'bre26' = ANY(lwr.rutenummer_list) THEN 'SHARED'
        WHEN '20160407' = ANY(lwr.rutenummer_list) THEN 'ONLY_20160407'
        WHEN 'bre26' = ANY(lwr.rutenummer_list) THEN 'ONLY_bre26'
    END as route_marker
FROM stiflyt.links_with_routes lwr
LEFT JOIN stiflyt.anchor_nodes an_a ON an_a.node_id = lwr.a_node
LEFT JOIN stiflyt.anchor_nodes an_b ON an_b.node_id = lwr.b_node
WHERE '20160407' = ANY(lwr.rutenummer_list) OR 'bre26' = ANY(lwr.rutenummer_list)
ORDER BY lwr.link_id;
```

**Look for**: Links marked as "ONLY_20160407" - these might be incorrectly tagged

## Expected Findings

1. **Links with incorrect rutenummer_list**: Some link(s) will have `20160407` in their `rutenummer_list` but:
   - Don't contain any segments with route 20160407
   - Connect to Slæom (or another node that shouldn't be an endpoint)

2. **Incorrect endpoint detection**: Slæom will appear as a node with `occurrence_count = 1`, making it an endpoint

3. **Comparison with bre26**: Links that have bre26 but NOT 20160407 will show the correct route path

## Next Steps After Finding the Bug

Once you've identified the problematic link(s):

1. **Check the source data**: Why does this link have 20160407 in its rutenummer_list?
   - Is it a data quality issue in turrutebasen?
   - Is it a bug in the link-building process?

2. **Fix options**:
   - **Data fix**: Remove 20160407 from the incorrect link's rutenummer_list
   - **Process fix**: Fix the link-building logic to prevent incorrect route assignments
   - **Validation**: Add validation to detect links with routes that don't match their segments

3. **Prevention**: Consider adding a validation query that checks:
   ```sql
   -- Find links with routes that don't match their segments
   SELECT lwr.link_id, lwr.rutenummer_list, lwr.segment_objids
   FROM stiflyt.links_with_routes lwr
   WHERE EXISTS (
       SELECT 1 FROM UNNEST(lwr.rutenummer_list) as route_num
       WHERE NOT EXISTS (
           SELECT 1 FROM stiflyt.route_segments rs
           WHERE rs.rutenummer = route_num
           AND rs.objid = ANY(lwr.segment_objids)
       )
   )
   ```

## Related Files

- `services/route_service.py` (lines 1613-1651): Endpoint detection logic
- `scripts/debug_route_20160407.sql`: SQL diagnostic queries
- `scripts/investigate_route_20160407.py`: Python investigation script
