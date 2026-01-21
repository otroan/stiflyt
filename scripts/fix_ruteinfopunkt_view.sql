-- ============================================================================
-- Migration: Create ruteinfopunkt view in stiflyt schema
-- Purpose: Provide stable access to ruteinfopunkt table regardless of schema hash
-- ============================================================================

BEGIN;

-- Find the turogfriluftsruter schema containing ruteinfopunkt
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

-- Verify the view was created
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

COMMIT;

-- Test the view
SELECT 
    COUNT(*) as total_count,
    COUNT(CASE WHEN navn IS NOT NULL THEN 1 END) as with_names,
    COUNT(CASE WHEN geom IS NOT NULL THEN 1 END) as with_geometry
FROM stiflyt.ruteinfopunkt;




