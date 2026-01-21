# Database Fix: Create ruteinfopunkt view in stiflyt schema

## Problem Description

The `ruteinfopunkt` table exists in the `turogfriluftsruter_*` schema (with a dynamic hash suffix like `turogfriluftsruter_92290fd5ba3741c29b4a43fb03e99d5d`), but the application code expects it in the `stiflyt` schema. This causes ruteinfopunkt lookups to fail when trying to find route endpoint names.

The schema name changes with each data import because it contains a hash, making it difficult to reference directly.

## Solution

Create a view in the `stiflyt` schema that:
1. Points to the actual `ruteinfopunkt` table in the `turogfriluftsruter_*` schema
2. Maps columns for compatibility:
   - `informasjon` → `navn` (for code expecting a `navn` column)
   - `posisjon` → `geom` (for code expecting a `geom` column)
3. Automatically finds the correct schema even if the hash changes

## SQL Migration Script

```sql
-- ============================================================================
-- Migration: Create ruteinfopunkt view in stiflyt schema
-- Purpose: Provide stable access to ruteinfopunkt table regardless of schema hash
-- ============================================================================

BEGIN;

-- Step 1: Find the turogfriluftsruter schema containing ruteinfopunkt
DO $$
DECLARE
    turrute_schema TEXT;
    view_exists BOOLEAN;
BEGIN
    -- Find the turogfriluftsruter schema that contains ruteinfopunkt
    SELECT table_schema INTO turrute_schema
    FROM information_schema.tables
    WHERE table_name = 'ruteinfopunkt'
      AND table_schema LIKE 'turogfriluftsruter_%'
    ORDER BY table_schema
    LIMIT 1;
    
    IF turrute_schema IS NULL THEN
        RAISE WARNING 'No ruteinfopunkt table found in turogfriluftsruter_* schema. View will not be created.';
        RETURN;
    END IF;
    
    RAISE NOTICE 'Found ruteinfopunkt in schema: %', turrute_schema;
    
    -- Check if view already exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_schema = 'stiflyt' AND table_name = 'ruteinfopunkt'
    ) INTO view_exists;
    
    IF view_exists THEN
        RAISE NOTICE 'Dropping existing view stiflyt.ruteinfopunkt';
        DROP VIEW IF EXISTS stiflyt.ruteinfopunkt CASCADE;
    END IF;
    
    -- Create view in stiflyt schema pointing to the actual table
    -- Map columns for compatibility with existing code
    EXECUTE format('
        CREATE VIEW stiflyt.ruteinfopunkt AS
        SELECT 
            objid,
            objtype,
            posisjon,
            ruteinfoid,
            vedlikeholdsansvarlig,
            anleggsnummer,
            uukoblingsid,
            lokalid,
            navnerom,
            versjonid,
            datafangstdato,
            oppdateringsdato,
            noyaktighet,
            opphav,
            omradeid,
            originaldatavert,
            kopidato,
            informasjon,
            tilrettelegging,
            sesong,
            malemetode,
            -- Compatibility mappings for code expecting different column names
            informasjon AS navn,           -- Map informasjon to navn
            posisjon::geometry AS geom     -- Map posisjon to geom
        FROM %I.ruteinfopunkt
    ', turrute_schema);
    
    RAISE NOTICE 'Created view stiflyt.ruteinfopunkt pointing to %.ruteinfopunkt', turrute_schema;
    
    -- Grant permissions (adjust as needed for your setup)
    GRANT SELECT ON stiflyt.ruteinfopunkt TO PUBLIC;
    
END $$;

-- Step 2: Verify the view was created
DO $$
DECLARE
    view_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_schema = 'stiflyt' 
      AND table_name = 'ruteinfopunkt';
    
    IF view_count = 0 THEN
        RAISE WARNING 'View stiflyt.ruteinfopunkt was not created!';
    ELSE
        RAISE NOTICE 'View stiflyt.ruteinfopunkt created successfully';
    END IF;
END $$;

-- Step 3: Test the view
SELECT 
    COUNT(*) as total_count,
    COUNT(CASE WHEN navn IS NOT NULL THEN 1 END) as with_names,
    COUNT(CASE WHEN geom IS NOT NULL THEN 1 END) as with_geometry
FROM stiflyt.ruteinfopunkt;

COMMIT;
```

## Alternative: Function-based approach (if views don't work)

If you prefer a function that dynamically finds the schema:

```sql
-- Function to get the turogfriluftsruter schema name dynamically
CREATE OR REPLACE FUNCTION stiflyt.get_turrute_schema()
RETURNS TEXT AS $$
    SELECT table_schema
    FROM information_schema.tables
    WHERE table_name = 'ruteinfopunkt'
      AND table_schema LIKE 'turogfriluftsruter_%'
    ORDER BY table_schema
    LIMIT 1;
$$ LANGUAGE SQL STABLE;

COMMENT ON FUNCTION stiflyt.get_turrute_schema() IS 
'Returns the schema name containing ruteinfopunkt table. Schema name changes with hash on each import.';

-- Grant execute to appropriate users
GRANT EXECUTE ON FUNCTION stiflyt.get_turrute_schema() TO PUBLIC;
```

## Rollback Script

If you need to rollback:

```sql
BEGIN;

DROP VIEW IF EXISTS stiflyt.ruteinfopunkt CASCADE;

COMMIT;
```

## Verification Queries

After running the migration, verify with:

```sql
-- Check view exists
SELECT 
    table_schema,
    table_name,
    table_type
FROM information_schema.tables
WHERE table_schema = 'stiflyt' 
  AND table_name = 'ruteinfopunkt';

-- Test query using the view
SELECT 
    objid,
    navn,
    informasjon,
    ST_AsText(ST_Transform(geom, 4326)) as geom_wkt
FROM stiflyt.ruteinfopunkt
WHERE navn IS NOT NULL
LIMIT 5;

-- Test spatial query
SELECT 
    objid,
    navn,
    ST_Distance(
        ST_Transform(ST_SetSRID(ST_MakePoint(7.710764899, 61.809237843), 4326), 25833),
        ST_Transform(geom, 25833)
    ) as distance_meters
FROM stiflyt.ruteinfopunkt
WHERE ST_DWithin(
    ST_Transform(geom, 25833),
    ST_Transform(ST_SetSRID(ST_MakePoint(7.710764899, 61.809237843), 4326), 25833),
    500.0
)
AND navn IS NOT NULL
ORDER BY distance_meters ASC
LIMIT 5;
```

## Notes

1. **Column Mapping**: The view maps `informasjon` → `navn` and `posisjon` → `geom` for compatibility with code expecting these column names.

2. **Schema Changes**: If the `turogfriluftsruter_*` schema hash changes (e.g., after a new data import), you'll need to recreate the view. Consider adding this to your data import process.

3. **Performance**: Views in PostgreSQL are generally performant, but if you have performance issues, consider creating a materialized view or a function-based approach.

4. **Permissions**: Adjust the `GRANT` statement based on your security requirements.

5. **Testing**: After creating the view, test with the CLI command:
   ```bash
   query-routes --test-ruteinfopunkt <lon> <lat>
   ```

## Integration with Data Import Process

If you have an automated data import process, add this view creation step after importing turogfriluftsruter data:

```bash
# After importing turogfriluftsruter data
psql $DATABASE_URL -f scripts/fix_ruteinfopunkt_view.sql
```




