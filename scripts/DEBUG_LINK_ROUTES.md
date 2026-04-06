# Debug Guide: Links with Multiple Routes

## Problem
Frontend shows `routesCount: 1` even when a link should have multiple routes.

## Debugging Steps

### 1. Check Frontend Console
Look for debug logs when hovering over a link:
- `Link X belongs to routes: [...]`
- `Binding tooltip for link X: { routesCount: N, routeNumbers: [...] }`
- `Tooltip opened for link X: { routesCount: N, ... }`

**Note the `link_id` from the console** - you'll need it for database queries.

### 2. Check Backend Logs
Look for backend debug output:
```
[DEBUG] Link X: rutenummer_list=[...], length=N
[DEBUG] Link X: Built N route(s): [...]
```

### 3. Query Database Directly

#### Quick Check (Simple)
```bash
psql -d <your_database> -f scripts/debug_link_routes_simple.sql
```

#### Detailed Check
```bash
psql -d <your_database> -f scripts/debug_link_routes.sql
```

#### Manual Query (Replace LINK_ID with actual ID from frontend)
```sql
-- Connect to database
psql -d <your_database>

-- Check specific link
SELECT
    link_id,
    a_node,
    b_node,
    rutenummer_list,
    rutenavn_list,
    array_length(rutenummer_list, 1) as route_count,
    rutenummer_list[1] as first_route,
    rutenummer_list[2] as second_route
FROM stiflyt.links_with_routes
WHERE link_id = LINK_ID;

-- Check if arrays are synchronized
SELECT
    link_id,
    array_length(rutenummer_list, 1) as num_count,
    array_length(rutenavn_list, 1) as navn_count,
    array_length(rutetype_list, 1) as type_count,
    array_length(vedlikeholdsansvarlig_list, 1) as ansvarlig_count
FROM stiflyt.links_with_routes
WHERE link_id = LINK_ID;
```

### 4. Check API Response Directly

Test the API endpoint directly:
```bash
# Replace bbox with actual coordinates from your map view
curl "http://localhost:8000/api/v1/links?bbox=10.0,59.0,11.0,60.0&limit=10" | jq '.features[] | {link_id: .id, routes: .properties.routes}'
```

Or use browser DevTools Network tab to inspect the actual API response.

### 5. Possible Issues

#### Issue A: Database has only one route per link
**Symptom**: Database query shows `array_length(rutenummer_list, 1) = 1`
**Solution**: Check how `links_with_routes` table/view is populated. It might need:
- Materialized view refresh: `REFRESH MATERIALIZED VIEW stiflyt.links_with_routes;`
- Rebuilding the view/table to aggregate routes correctly

#### Issue B: Arrays are not synchronized
**Symptom**: `rutenummer_list` has 2 elements but `rutenavn_list` has 1
**Solution**: The `build_routes_info_from_arrays` function now pads arrays, but the root cause should be fixed in the view/table definition.

#### Issue C: Frontend filtering
**Symptom**: Backend returns multiple routes but frontend shows only one
**Solution**: Check frontend code for any filtering logic (there shouldn't be any in the current code)

#### Issue D: View/Table needs refresh
**Symptom**: Database shows old data
**Solution**:
```sql
-- If it's a materialized view
REFRESH MATERIALIZED VIEW CONCURRENTLY stiflyt.links_with_routes;

-- Or rebuild the table/view
```

### 6. Check View/Table Definition

```sql
-- Check if it's a view or table
SELECT
    table_type,
    table_name
FROM information_schema.tables
WHERE table_schema = 'stiflyt'
  AND table_name IN ('links_with_routes', 'links');

-- If it's a view, see the definition
\d+ stiflyt.links_with_routes

-- Or
SELECT pg_get_viewdef('stiflyt.links_with_routes', true);
```

### 7. Expected Behavior

A link that is shared by multiple routes should have:
- `rutenummer_list` with multiple elements: `['bre10', 'bre11']`
- `rutenavn_list` with corresponding names: `['Rute 10', 'Rute 11']`
- All arrays should have the same length

The API should return:
```json
{
  "properties": {
    "routes": [
      {"rutenummer": "bre10", "rutenavn": "Rute 10", ...},
      {"rutenummer": "bre11", "rutenavn": "Rute 11", ...}
    ]
  }
}
```

## Next Steps

1. Run the debug queries above
2. Check backend logs for the debug output
3. Share the results to identify the root cause
4. Fix either the database view/table or the backend code accordingly
