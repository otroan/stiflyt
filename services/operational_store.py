"""Operational data storage helpers (endpoint names, number spaces)."""
import os
from typing import Dict, List, Optional
from datetime import datetime

from psycopg.rows import dict_row

from .database import validate_schema_name, quote_identifier


OP_SCHEMA = os.getenv("OP_SCHEMA", "ops")


def ensure_operational_schema(conn) -> None:
    """Ensure operational schema and core tables exist."""
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    schema_quoted = quote_identifier(OP_SCHEMA)

    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_quoted};")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_quoted}.endpoint_names (
                id BIGSERIAL PRIMARY KEY,
                anchor_node_id INTEGER NOT NULL,
                rutenummer TEXT NULL,
                rutenummer_key TEXT GENERATED ALWAYS AS (COALESCE(rutenummer, '')) STORED,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NULL,
                distance_meters DOUBLE PRECISION NULL,
                anchor_lon DOUBLE PRECISION NULL,
                anchor_lat DOUBLE PRECISION NULL,
                validated_by TEXT NULL,
                validated_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (anchor_node_id, rutenummer_key)
            );
            """
        )

        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.endpoint_names
            ADD COLUMN IF NOT EXISTS anchor_lon DOUBLE PRECISION;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.endpoint_names
            ADD COLUMN IF NOT EXISTS anchor_lat DOUBLE PRECISION;
            """
        )

        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.endpoint_names
            ADD COLUMN IF NOT EXISTS geom GEOMETRY(Point, 4326);
            """
        )

        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS endpoint_names_anchor_idx
            ON {schema_quoted}.endpoint_names (anchor_node_id);
            """
        )

        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS endpoint_names_geom_idx
            ON {schema_quoted}.endpoint_names USING GIST (geom);
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_quoted}.number_spaces (
                id BIGSERIAL PRIMARY KEY,
                scope TEXT NOT NULL,
                prefix TEXT NOT NULL,
                number TEXT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                metadata JSONB NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (scope, prefix, number)
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_quoted}.sign_status (
                id BIGSERIAL PRIMARY KEY,
                anchor_node_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                status TEXT NULL,
                last_inspected TIMESTAMPTZ NULL,
                notes TEXT NULL,
                front_lon DOUBLE PRECISION NULL,
                front_lat DOUBLE PRECISION NULL,
                back_lon DOUBLE PRECISION NULL,
                back_lat DOUBLE PRECISION NULL,
                updated_by TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (anchor_node_id, direction)
            );
            """
        )

        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS sign_status_anchor_idx
            ON {schema_quoted}.sign_status (anchor_node_id);
            """
        )


def upsert_endpoint_name(
    conn,
    anchor_node_id: int,
    name: str,
    source_type: str,
    geom: str,
    rutenummer: Optional[str] = None,
    source_id: Optional[str] = None,
    distance_meters: Optional[float] = None,
    validated_by: Optional[str] = None,
    anchor_lon: Optional[float] = None,
    anchor_lat: Optional[float] = None,
) -> Dict:
    """Upsert validated endpoint name. Geometry is required for synchronization after database refresh."""
    ensure_operational_schema(conn)

    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    schema_quoted = quote_identifier(OP_SCHEMA)
    now = datetime.utcnow()

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO {schema_quoted}.endpoint_names (
                anchor_node_id,
                rutenummer,
                name,
                source_type,
                source_id,
                distance_meters,
                anchor_lon,
                anchor_lat,
                geom,
                validated_by,
                validated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                ST_SetSRID(ST_GeomFromText(%s), 4326),
                %s, %s
            )
            ON CONFLICT (anchor_node_id, rutenummer_key)
            DO UPDATE SET
                name = EXCLUDED.name,
                source_type = EXCLUDED.source_type,
                source_id = EXCLUDED.source_id,
                distance_meters = EXCLUDED.distance_meters,
                anchor_lon = EXCLUDED.anchor_lon,
                anchor_lat = EXCLUDED.anchor_lat,
                geom = EXCLUDED.geom,
                validated_by = EXCLUDED.validated_by,
                validated_at = EXCLUDED.validated_at,
                updated_at = NOW()
            RETURNING
                anchor_node_id,
                rutenummer,
                name,
                source_type,
                source_id,
                distance_meters,
                anchor_lon,
                anchor_lat,
                validated_by,
                validated_at,
                created_at,
                updated_at;
            """,
            (
                anchor_node_id,
                rutenummer,
                name,
                source_type,
                source_id,
                distance_meters,
                anchor_lon,
                anchor_lat,
                geom,
                validated_by,
                now,
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def get_endpoint_names_for_anchors(
    conn,
    anchor_node_ids: List[int],
    rutenummer: Optional[str] = None,
) -> Dict[int, Dict]:
    """Fetch validated endpoint names for anchor nodes, preferring route-specific."""
    ensure_operational_schema(conn)

    if not anchor_node_ids:
        return {}

    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    schema_quoted = quote_identifier(OP_SCHEMA)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                anchor_node_id,
                rutenummer,
                name,
                source_type,
                source_id,
                distance_meters,
                validated_by,
                validated_at
            FROM {schema_quoted}.endpoint_names
            WHERE anchor_node_id = ANY(%s)
              AND (%s::text IS NULL OR rutenummer = %s::text OR rutenummer IS NULL);
            """,
            (anchor_node_ids, rutenummer, rutenummer),
        )
        rows = cur.fetchall()

    grouped: Dict[int, List[Dict]] = {}
    for row in rows:
        anchor_id = row["anchor_node_id"]
        grouped.setdefault(anchor_id, []).append(dict(row))

    resolved: Dict[int, Dict] = {}
    for anchor_id, items in grouped.items():
        if rutenummer:
            exact = next((i for i in items if i.get("rutenummer") == rutenummer), None)
            if exact:
                resolved[anchor_id] = exact
                continue
        fallback = next((i for i in items if i.get("rutenummer") is None), None)
        if fallback:
            resolved[anchor_id] = fallback

    return resolved


def get_endpoint_names_for_anchor_routes(
    conn,
    anchor_node_ids: List[int],
    rutenummer_list: List[str],
) -> Dict[str, Dict[int, Dict]]:
    """Fetch endpoint names for anchors across multiple routes."""
    ensure_operational_schema(conn)

    if not anchor_node_ids or not rutenummer_list:
        return {}

    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    schema_quoted = quote_identifier(OP_SCHEMA)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                anchor_node_id,
                rutenummer,
                name,
                source_type,
                source_id,
                distance_meters,
                validated_by,
                validated_at
            FROM {schema_quoted}.endpoint_names
            WHERE anchor_node_id = ANY(%s)
              AND (rutenummer IS NULL OR rutenummer = ANY(%s::text[]));
            """,
            (anchor_node_ids, rutenummer_list),
        )
        rows = cur.fetchall()

    grouped: Dict[str, Dict[int, List[Dict]]] = {}
    for row in rows:
        anchor_id = row["anchor_node_id"]
        rute = row.get("rutenummer")
        if rute is None:
            for r in rutenummer_list:
                grouped.setdefault(r, {}).setdefault(anchor_id, []).append(dict(row))
        else:
            grouped.setdefault(rute, {}).setdefault(anchor_id, []).append(dict(row))

    resolved: Dict[str, Dict[int, Dict]] = {}
    for rutenummer in rutenummer_list:
        anchor_map: Dict[int, Dict] = {}
        for anchor_id, items in grouped.get(rutenummer, {}).items():
            exact = next((i for i in items if i.get("rutenummer") == rutenummer), None)
            if exact:
                anchor_map[anchor_id] = exact
                continue
            fallback = next((i for i in items if i.get("rutenummer") is None), None)
            if fallback:
                anchor_map[anchor_id] = fallback
        if anchor_map:
            resolved[rutenummer] = anchor_map

    return resolved


def upsert_sign_status(
    conn,
    anchor_node_id: int,
    direction: str,
    status: Optional[str] = None,
    last_inspected: Optional[datetime] = None,
    notes: Optional[str] = None,
    front_coords: Optional[tuple[float, float]] = None,
    back_coords: Optional[tuple[float, float]] = None,
    updated_by: Optional[str] = None,
) -> Dict:
    """Upsert sign status metadata."""
    ensure_operational_schema(conn)

    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    schema_quoted = quote_identifier(OP_SCHEMA)
    now = datetime.utcnow()
    front_lon = front_coords[0] if front_coords else None
    front_lat = front_coords[1] if front_coords else None
    back_lon = back_coords[0] if back_coords else None
    back_lat = back_coords[1] if back_coords else None

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO {schema_quoted}.sign_status (
                anchor_node_id,
                direction,
                status,
                last_inspected,
                notes,
                front_lon,
                front_lat,
                back_lon,
                back_lat,
                updated_by,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (anchor_node_id, direction)
            DO UPDATE SET
                status = EXCLUDED.status,
                last_inspected = EXCLUDED.last_inspected,
                notes = EXCLUDED.notes,
                front_lon = EXCLUDED.front_lon,
                front_lat = EXCLUDED.front_lat,
                back_lon = EXCLUDED.back_lon,
                back_lat = EXCLUDED.back_lat,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            RETURNING
                anchor_node_id,
                direction,
                status,
                last_inspected,
                notes,
                front_lon,
                front_lat,
                back_lon,
                back_lat,
                updated_by,
                created_at,
                updated_at;
            """,
            (
                anchor_node_id,
                direction,
                status,
                last_inspected,
                notes,
                front_lon,
                front_lat,
                back_lon,
                back_lat,
                updated_by,
                now,
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def get_sign_status_for_anchors(
    conn,
    anchor_node_ids: List[int],
) -> Dict[int, List[Dict]]:
    """Fetch sign status rows for anchors."""
    ensure_operational_schema(conn)

    if not anchor_node_ids:
        return {}

    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    schema_quoted = quote_identifier(OP_SCHEMA)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                anchor_node_id,
                direction,
                status,
                last_inspected,
                notes,
                front_lon,
                front_lat,
                back_lon,
                back_lat,
                updated_by,
                created_at,
                updated_at
            FROM {schema_quoted}.sign_status
            WHERE anchor_node_id = ANY(%s)
            ORDER BY anchor_node_id, direction;
            """,
            (anchor_node_ids,),
        )
        rows = cur.fetchall()

    grouped: Dict[int, List[Dict]] = {}
    for row in rows:
        anchor_id = row.get("anchor_node_id")
        if anchor_id is None:
            continue
        grouped.setdefault(int(anchor_id), []).append(dict(row))

    return grouped
