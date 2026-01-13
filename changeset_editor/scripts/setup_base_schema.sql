-- Setup base schema with example data for testing
-- This creates a minimal base schema that the changeset editor expects

CREATE SCHEMA IF NOT EXISTS base;

-- Segment base table
CREATE TABLE IF NOT EXISTS base.segment_base (
    id TEXT PRIMARY KEY,
    geom GEOMETRY(LINESTRING, 4326) NOT NULL,
    attrs JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_segment_base_geom ON base.segment_base USING GIST(geom);

-- Insert some example segments for testing
INSERT INTO base.segment_base (id, geom, attrs) VALUES
(
    'seg_001',
    ST_GeomFromGeoJSON('{"type":"LineString","coordinates":[[10.0,59.0],[10.1,59.1],[10.2,59.2]]}'),
    '{"route_ref": "BRE017", "name": "Example Route 1"}'::jsonb
),
(
    'seg_002',
    ST_GeomFromGeoJSON('{"type":"LineString","coordinates":[[10.2,59.2],[10.3,59.3],[10.4,59.4]]}'),
    '{"route_ref": "BRE018", "name": "Example Route 2"}'::jsonb
)
ON CONFLICT (id) DO NOTHING;

-- Route base table (optional, for reference)
CREATE TABLE IF NOT EXISTS base.route_base (
    id TEXT PRIMARY KEY,
    name TEXT,
    number TEXT,
    attrs JSONB DEFAULT '{}'::jsonb
);
