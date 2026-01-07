-- Check and create spatial index for fotrute.senterlinje
-- This is critical for bounding box query performance
--
-- NOTE: This should be run in the stiflyt-db repository as part of
-- database setup/migration, not in this application repository.
-- See DATABASE_INDEXES.md for details.

-- Check if index exists
-- NOTE: Always use fixed schema name 'stiflyt' (not dynamic schema names)
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'stiflyt'
AND tablename = 'fotrute'
AND indexdef LIKE '%GIST%';

-- Create spatial index if it doesn't exist
-- This may take several minutes on large tables
-- IMPORTANT: Run this in stiflyt-db repository after data import
CREATE INDEX IF NOT EXISTS idx_fotrute_senterlinje_gist
ON stiflyt.fotrute
USING GIST (senterlinje);

-- Analyze table to update statistics
ANALYZE stiflyt.fotrute;
ANALYZE stiflyt.fotruteinfo;
