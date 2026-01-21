# Fix ruteinfopunkt alias/view in stiflyt schema

## Problem
The `ruteinfopunkt` table exists in the `turogfriluftsruter_*` schema (with a hash suffix that changes), but the code expects it in the `stiflyt` schema. This causes ruteinfopunkt lookups to fail.

## Solution
Create a view or synonym in the `stiflyt` schema that points to the actual `ruteinfopunkt` table in the `turogfriluftsruter_*` schema.

## SQL Script

```sql
-- Find the turogfriluftsruter schema with ruteinfopunkt
DO $$
DECLARE
    turrute_schema TEXT;
BEGIN
    -- Find the turogfriluftsruter schema that contains ruteinfopunkt
    SELECT table_schema INTO turrute_schema
    FROM information_schema.tables
    WHERE table_name = 'ruteinfopunkt'
      AND table_schema LIKE 'turogfriluftsruter_%'
    ORDER BY table_schema
    LIMIT 1;
    
    IF turrute_schema IS NULL THEN
        RAISE EXCEPTION 'No ruteinfopunkt table found in turogfriluftsruter_* schema';
    END IF;
    
    RAISE NOTICE 'Found ruteinfopunkt in schema: %', turrute_schema;
    
    -- Drop existing view if it exists
    DROP VIEW IF EXISTS stiflyt.ruteinfopunkt CASCADE;
    
    -- Create view in stiflyt schema pointing to the actual table
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
            -- Map informasjon to navn for compatibility
            informasjon AS navn,
            -- Map posisjon to geom for compatibility
            posisjon::geometry AS geom
        FROM %I.ruteinfopunkt
    ', turrute_schema);
    
    RAISE NOTICE 'Created view stiflyt.ruteinfopunkt pointing to %.ruteinfopunkt', turrute_schema;
END $$;

-- Verify the view was created
SELECT 
    table_schema,
    table_name,
    table_type
FROM information_schema.tables
WHERE table_schema = 'stiflyt' 
  AND table_name = 'ruteinfopunkt';

-- Test query
SELECT COUNT(*) as total_count
FROM stiflyt.ruteinfopunkt;

SELECT COUNT(*) as with_names
FROM stiflyt.ruteinfopunkt
WHERE navn IS NOT NULL;
```

## Alternative: Create a function to find the schema dynamically

If you prefer a more dynamic approach that doesn't require a view:

```sql
-- Function to get the turogfriluftsruter schema name
CREATE OR REPLACE FUNCTION stiflyt.get_turrute_schema()
RETURNS TEXT AS $$
    SELECT table_schema
    FROM information_schema.tables
    WHERE table_name = 'ruteinfopunkt'
      AND table_schema LIKE 'turogfriluftsruter_%'
    ORDER BY table_schema
    LIMIT 1;
$$ LANGUAGE SQL STABLE;

-- Grant execute to appropriate users
GRANT EXECUTE ON FUNCTION stiflyt.get_turrute_schema() TO PUBLIC;
```

## Notes

1. The view maps `informasjon` column to `navn` for compatibility with code that expects a `navn` column
2. The view maps `posisjon` to `geom` for compatibility with code that expects a `geom` column
3. The view will automatically point to the correct schema even if the hash changes
4. If the schema hash changes, you'll need to recreate the view (or use a function-based approach)

## Migration Script

For use in database migrations:

```sql
-- Migration: Create ruteinfopunkt view in stiflyt schema
-- This should be run after importing turogfriluftsruter data

BEGIN;

-- Find and create view (see SQL script above)
-- ... (insert the DO block from above)

COMMIT;
```




