-- Setup base schema with example data for testing
-- This creates a minimal base schema that the changeset editor expects

CREATE SCHEMA IF NOT EXISTS base;

-- Segment base table
CREATE TABLE IF NOT EXISTS base.segment_base (
    id TEXT PRIMARY KEY,
    geom GEOMETRY(LINESTRING, 4326) NOT NULL,
    attrs JSONB DEFAULT '{}'::jsonb,
    object_uuid TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_segment_base_geom ON base.segment_base USING GIST(geom);

-- Insert some example segments for testing
INSERT INTO base.segment_base (id, geom, attrs, object_uuid) VALUES
(
    'seg_001',
    ST_GeomFromGeoJSON('{"type":"LineString","coordinates":[[10.0,59.0],[10.1,59.1],[10.2,59.2]]}'),
    '{"route_ref": "BRE017", "name": "Example Route 1"}'::jsonb,
    '9f9156fb-89db-4a65-8d53-6d5467a33a6f'
),
(
    'seg_002',
    ST_GeomFromGeoJSON('{"type":"LineString","coordinates":[[10.2,59.2],[10.3,59.3],[10.4,59.4]]}'),
    '{"route_ref": "BRE018", "name": "Example Route 2"}'::jsonb,
    '0e7f5321-7868-43a8-9cbb-2f90612d9dc1'
)
ON CONFLICT (id) DO NOTHING;

-- Route base table (optional, for reference)
CREATE TABLE IF NOT EXISTS base.route_base (
    id TEXT PRIMARY KEY,
    name TEXT,
    number TEXT,
    attrs JSONB DEFAULT '{}'::jsonb
);
