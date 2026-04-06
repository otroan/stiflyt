# Bug Investigation: Route 20160407 Endpoint Detection

## Problem Summary

Route `20160407` is incorrectly identified as going from **Slæom to Sunndalssetra**, when it should go from **Sunndalssetra to a junction**. The route is a duplicate of `bre26`, but there's a data quality issue causing incorrect endpoint detection.

## Root Cause

**Link 6279** incorrectly has route `20160407` in its `rutenummer_list`, causing node 91705 (Slæom) to be identified as an endpoint when it shouldn't be.

## Evidence

### Links with route 20160407:

1. **Link 6279** (BUGGY):
   - Nodes: 10455 → 91705
   - Routes: `['20160407', 'bre16']`
   - Segments: `[46626, 50222, 47409, 45081]`
   - **Issue**: This link should NOT have route `20160407` - it should only have `bre16`

2. **Link 6280** (CORRECT):
   - Nodes: 10455 → 16058
   - Routes: `['20160407', 'bre26']`
   - Segments: `[102558, 102564, 102557, 102574, 102572, ...]`
   - This link is correct

### Endpoint Detection Result:

- **First node**: 16058 (should be Sunndalssetra)
- **Last node**: 91705 (incorrectly identified as endpoint - this is Slæom)
- **Junction node**: 10455 (appears 2 times, correctly identified as junction)

### Comparison with bre26:

- **Shared links**: 1 (link 6280)
- **Only 20160407**: 1 (link 6279 - this is the bug)
- **Only bre26**: 3 (links that correctly have bre26 but not 20160407)

## Investigation Tasks

### 1. Verify Link 6279 Route Assignment

**Question**: Why does link 6279 have route `20160407` in its `rutenummer_list`?

Check:
- Do the segments `[46626, 50222, 47409, 45081]` actually have route `20160407` in the source data?
- Or is this a bug in the link-building process that aggregates routes from segments?

**SQL Query to check segments:**
```sql
SELECT
    rs.segment_objid,
    rs.rutenummer,
    rs.rutenavn
FROM stiflyt.route_segments rs
WHERE rs.segment_objid IN (46626, 50222, 47409, 45081)
ORDER BY rs.segment_objid, rs.rutenummer;
```

### 2. Check Source Data (turrutebasen)

**Question**: In the original turrutebasen data, do segments `[46626, 50222, 47409, 45081]` have route `20160407`?

If YES:
- This is a data quality issue in turrutebasen - segments incorrectly tagged with route 20160407
- These segments should probably only have route `bre16`

If NO:
- This is a bug in the link-building/aggregation process
- The link-building logic is incorrectly assigning route 20160407 to link 6279

### 3. Verify Node Names

**Question**: Can you confirm the node names?
- Node 91705 = Slæom?
- Node 16058 = Sunndalssetra?
- Node 10455 = Junction?

**SQL Query to check node names:**
```sql
-- Check operational database for node names
SELECT
    anchor_node_id,
    name,
    rutenummer,
    source_type
FROM ops.endpoint_names
WHERE anchor_node_id IN (91705, 16058, 10455)
ORDER BY anchor_node_id,
    CASE WHEN rutenummer IS NULL THEN 0 ELSE 1 END;
```

### 4. Check Link Building Logic

**Question**: How are routes aggregated into `rutenummer_list` for links?

Review the code/logic that builds `links_with_routes`:
- Does it aggregate routes from all segments in a link?
- Is there any validation to prevent incorrect route assignments?
- Should there be validation that checks if a route actually belongs to a link based on connectivity?

### 5. Expected Fix

**Option A - Data Fix** (if source data is wrong):
- Remove route `20160407` from segments `[46626, 50222, 47409, 45081]` in turrutebasen
- Or filter out route `20160407` from link 6279's `rutenummer_list` if it's a known duplicate

**Option B - Process Fix** (if link-building is wrong):
- Fix the link-building logic to correctly assign routes
- Add validation to prevent routes from being assigned to links they don't belong to

**Option C - Validation** (preventive):
- Add a validation query that detects links with routes that don't match their actual path:
  ```sql
  -- Find links with routes that create incorrect endpoints
  WITH route_endpoints AS (
      SELECT
          rutenummer,
          MIN(node_id) FILTER (WHERE occurrence_count = 1) as first_node,
          MAX(node_id) FILTER (WHERE occurrence_count = 1) as last_node
      FROM (
          SELECT
              UNNEST(lwr.rutenummer_list) as rutenummer,
              lwr.a_node as node_id,
              COUNT(*) OVER (PARTITION BY UNNEST(lwr.rutenummer_list), lwr.a_node) as occurrence_count
          FROM stiflyt.links_with_routes lwr
          -- ... (full endpoint detection logic)
      ) nodes
      GROUP BY rutenummer
  )
  -- Flag routes with suspicious endpoints
  SELECT * FROM route_endpoints WHERE ...;
  ```

## Files to Review

1. Link-building code that creates `links_with_routes`
2. Route aggregation logic
3. Any validation or data quality checks

## Expected Outcome

After investigation, we should:
1. Understand why link 6279 has route 20160407
2. Fix the root cause (data or process)
3. Verify that route 20160407 endpoints are correctly identified as: Sunndalssetra → Junction (not Slæom → Sunndalssetra)

## Related Files

- Investigation script: `scripts/investigate_route_20160407.py`
- SQL debug queries: `scripts/debug_route_20160407.sql`
- Debug guide: `scripts/DEBUG_ROUTE_20160407.md`
