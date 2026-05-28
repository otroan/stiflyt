"""Operational data storage helpers (endpoint names, number spaces)."""
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from .database import validate_schema_name, quote_identifier


OP_SCHEMA = os.getenv("OP_SCHEMA", "ops")


_OP_SCHEMA_INITIALIZED: bool = False


def _is_operational_schema_initialized(conn) -> bool:
    """Cheap probe: assume schema is fully set up if ops.sign_site_skilt exists.

    `ops.sign_site_skilt` is the last table created by migration 011, so its
    presence is a reliable proxy for "migration 011 has run". Cached in-process
    so we don't re-probe on every request.
    """
    global _OP_SCHEMA_INITIALIZED
    if _OP_SCHEMA_INITIALIZED:
        return True
    if not validate_schema_name(OP_SCHEMA):
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = 'sign_site_skilt'
            );
            """,
            (OP_SCHEMA,),
        )
        row = cur.fetchone()
        ok = bool(row and row[0])
    _OP_SCHEMA_INITIALIZED = ok
    return ok


def ensure_operational_schema(conn) -> None:
    """Ensure operational schema and core tables exist.

    Fast-path: if migration 011 has already run (see [[plan-breheimen-signs-2026-05]]),
    return immediately. The runtime DB user (typically `stiflyt_reader`) only
    has DML, not DDL — so attempting CREATE/ALTER on every call would fail.

    Legacy bootstrap path (full DDL below) only runs when the schema is missing
    pieces AND the connection has the privileges to add them — kept for first-
    time-setup convenience on dev boxes where the migration hasn't been run.
    """
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    if _is_operational_schema_initialized(conn):
        return

    schema_quoted = quote_identifier(OP_SCHEMA)

    # Try the legacy bootstrap. If any DDL fails with insufficient privileges,
    # surface a clear error message pointing at migration 011 rather than the
    # raw psycopg error.
    try:
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
            ADD COLUMN IF NOT EXISTS geom GEOMETRY(Point, 25833);
            """
        )
        # Migrate existing geom from 4326 to 25833 so all turrutebasen geometry uses same SRID
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.endpoint_names
            ALTER COLUMN geom TYPE GEOMETRY(Point, 25833)
            USING ST_Transform(geom, 25833);
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

        # Sign sites: stable identifier for sign locations (anchor or custom point on route)
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_quoted}.sign_sites (
                id BIGSERIAL PRIMARY KEY,
                rutenummer TEXT NULL,
                route_km DOUBLE PRECISION NULL,
                geom GEOMETRY(Point, 25833) NOT NULL,
                anchor_node_id INTEGER NULL,
                name TEXT NULL,
                back_text TEXT NULL DEFAULT 'Stier er ryddet og merket av DNT Oslo og Omegn',
                send_to_name TEXT NULL,
                send_to_address TEXT NULL,
                updated_by TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS sign_sites_rutenummer_idx
            ON {schema_quoted}.sign_sites (rutenummer);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS sign_sites_anchor_node_id_idx
            ON {schema_quoted}.sign_sites (anchor_node_id);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS sign_sites_geom_idx
            ON {schema_quoted}.sign_sites USING GIST (geom);
            """
        )

        # Extend sign_status to support sign_site_id (for custom sign locations)
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.sign_status
            ADD COLUMN IF NOT EXISTS sign_site_id BIGINT NULL;
            """
        )
        # Allow anchor_node_id to be NULL when sign_site_id is set
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.sign_status
            ALTER COLUMN anchor_node_id DROP NOT NULL;
            """
        )
        # Replace single unique constraint with partial uniques so we can have either anchor or sign_site
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.sign_status
            DROP CONSTRAINT IF EXISTS sign_status_anchor_node_id_direction_key;
            """
        )
        cur.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS sign_status_anchor_direction_key
            ON {schema_quoted}.sign_status (anchor_node_id, direction)
            WHERE anchor_node_id IS NOT NULL;
            """
        )
        cur.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS sign_status_site_direction_key
            ON {schema_quoted}.sign_status (sign_site_id, direction)
            WHERE sign_site_id IS NOT NULL;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.sign_sites
            ADD COLUMN IF NOT EXISTS skiltfarge TEXT NULL;
            """
        )
        # signs_app extensions: area-based proposed/accepted/rejected/installed status,
        # plus a sortable site code allocated from ops.number_spaces.
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.sign_sites
            ADD COLUMN IF NOT EXISTS area_code TEXT NULL;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.sign_sites
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'accepted';
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {schema_quoted}.sign_sites
            ADD COLUMN IF NOT EXISTS site_code TEXT NULL;
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS sign_sites_area_status_idx
            ON {schema_quoted}.sign_sites (area_code, status);
            """
        )
        cur.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS sign_sites_area_anchor_uidx
            ON {schema_quoted}.sign_sites (area_code, anchor_node_id)
            WHERE area_code IS NOT NULL AND anchor_node_id IS NOT NULL;
            """
        )
        cur.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS sign_sites_site_code_uidx
            ON {schema_quoted}.sign_sites (site_code)
            WHERE site_code IS NOT NULL;
            """
        )

        # Destinations (pil/skilt) per sign site: which anchors to show. Empty = use default (topology or route endpoints).
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_quoted}.sign_site_destinations (
                sign_site_id BIGINT NOT NULL REFERENCES {schema_quoted}.sign_sites(id) ON DELETE CASCADE,
                anchor_node_id INTEGER NOT NULL,
                display_order SMALLINT NOT NULL DEFAULT 0,
                PRIMARY KEY (sign_site_id, anchor_node_id)
            );
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS sign_site_destinations_site_idx
            ON {schema_quoted}.sign_site_destinations (sign_site_id);
            """
        )

        # Per-destination skilt (retning, status, farge, km) on a sign site
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_quoted}.sign_site_skilt (
                id BIGSERIAL PRIMARY KEY,
                sign_site_id BIGINT NOT NULL REFERENCES {schema_quoted}.sign_sites(id) ON DELETE CASCADE,
                anchor_node_id INTEGER NOT NULL,
                direction TEXT NULL,
                status TEXT NULL,
                skiltfarge TEXT NULL,
                distance_meters DOUBLE PRECISION NULL,
                updated_by TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (sign_site_id, anchor_node_id)
            );
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS sign_site_skilt_site_idx
            ON {schema_quoted}.sign_site_skilt (sign_site_id);
            """
        )

        # Polymorphic per-route annotations (Phase B of the signs_app expansion):
        # rutebok diary, inspections, dugnad reports, and georeferenced work
        # markers (klipping/bro/klopp/other) live in a single table keyed by
        # `kind`. Empty geom = a free-text entry; non-null geom + kind=work_*
        # also renders as a marker on the map.
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_quoted}.route_annotations (
                id BIGSERIAL PRIMARY KEY,
                area_code TEXT NOT NULL,
                rutenummer TEXT NOT NULL,
                kind TEXT NOT NULL,
                position_along_m DOUBLE PRECISION NULL,
                geom GEOMETRY(Point, 25833) NULL,
                title TEXT NULL,
                body TEXT NULL,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                recorded_by TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMPTZ NULL
            );
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS route_annotations_area_route_idx
            ON {schema_quoted}.route_annotations (area_code, rutenummer);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS route_annotations_area_kind_idx
            ON {schema_quoted}.route_annotations (area_code, kind);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS route_annotations_geom_idx
            ON {schema_quoted}.route_annotations USING GIST (geom)
            WHERE geom IS NOT NULL;
            """
        )
    except psycopg.errors.InsufficientPrivilege as e:
        raise RuntimeError(
            "ops schema is not initialized and the current DB user lacks DDL privileges. "
            "Run stiflyt-db/migrations/011_signs_app_extensions.sql as the schema owner."
        ) from e
    # Refresh the cached flag now that DDL has succeeded
    global _OP_SCHEMA_INITIALIZED
    _OP_SCHEMA_INITIALIZED = True


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
                ST_SetSRID(ST_GeomFromText(%s), 25833),
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
    direction: str,
    status: Optional[str] = None,
    last_inspected: Optional[datetime] = None,
    notes: Optional[str] = None,
    front_coords: Optional[tuple[float, float]] = None,
    back_coords: Optional[tuple[float, float]] = None,
    updated_by: Optional[str] = None,
    *,
    sign_site_id: int,
) -> Dict:
    """Upsert sign status metadata by sign_site_id only (robust to anchor_node_id changes when DB is refreshed)."""
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
                sign_site_id,
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
            VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sign_site_id, direction) WHERE sign_site_id IS NOT NULL
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
                id,
                anchor_node_id,
                sign_site_id,
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
                sign_site_id,
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


def update_sign_status_row_by_id(
    conn,
    status_row_id: int,
    sign_site_id: int,
    direction: str,
    status: Optional[str] = None,
    last_inspected: Optional[datetime] = None,
    notes: Optional[str] = None,
    front_coords: Optional[tuple[float, float]] = None,
    back_coords: Optional[tuple[float, float]] = None,
    updated_by: Optional[str] = None,
) -> Optional[Dict]:
    """Update one sign_status row by id; must belong to sign_site_id. Returns row or None if not found."""
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
            UPDATE {schema_quoted}.sign_status SET
                direction = %s,
                status = %s,
                last_inspected = %s,
                notes = %s,
                front_lon = %s,
                front_lat = %s,
                back_lon = %s,
                back_lat = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s AND sign_site_id = %s
            RETURNING
                id,
                anchor_node_id,
                sign_site_id,
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
                direction,
                status,
                last_inspected,
                notes,
                front_lon,
                front_lat,
                back_lon,
                back_lat,
                updated_by or "anonymous",
                status_row_id,
                sign_site_id,
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else None


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
                id,
                anchor_node_id,
                sign_site_id,
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


def get_sign_status_for_sign_sites(
    conn,
    sign_site_ids: List[int],
) -> Dict[int, List[Dict]]:
    """Fetch sign status rows for sign sites."""
    ensure_operational_schema(conn)
    if not sign_site_ids:
        return {}
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                id,
                anchor_node_id,
                sign_site_id,
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
            WHERE sign_site_id = ANY(%s)
            ORDER BY sign_site_id, direction;
            """,
            (sign_site_ids,),
        )
        rows = cur.fetchall()
    grouped: Dict[int, List[Dict]] = {}
    for row in rows:
        sid = row.get("sign_site_id")
        if sid is None:
            continue
        grouped.setdefault(int(sid), []).append(dict(row))
    return grouped


# Default back text for sign sites (baksidetekst). The template lives in
# `data/sign_export.yaml`; this is the static-only render (no per-site
# name/coords), used as a fallback where those values aren't available.
from .sign_back_template import DEFAULT_BACK_TEXT  # noqa: E402, F401


def create_sign_site(
    conn,
    rutenummer: Optional[str],
    route_km: Optional[float],
    geom_wkt: str,
    anchor_node_id: Optional[int] = None,
    name: Optional[str] = None,
    back_text: Optional[str] = None,
    send_to_name: Optional[str] = None,
    send_to_address: Optional[str] = None,
    skiltfarge: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> Dict:
    """Create a sign site. geom_wkt in SRID 25833 (UTM 33N). skiltfarge: 'grønn' or 'trehvit'."""
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    if back_text is None:
        back_text = DEFAULT_BACK_TEXT
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO {schema_quoted}.sign_sites (
                rutenummer,
                route_km,
                geom,
                anchor_node_id,
                name,
                back_text,
                send_to_name,
                send_to_address,
                skiltfarge,
                updated_by
            )
            VALUES (%s, %s, ST_SetSRID(ST_GeomFromText(%s), 25833), %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id,
                rutenummer,
                route_km,
                anchor_node_id,
                name,
                back_text,
                send_to_name,
                send_to_address,
                skiltfarge,
                created_at,
                updated_at;
            """,
            (
                rutenummer,
                route_km,
                geom_wkt,
                anchor_node_id,
                name,
                back_text,
                send_to_name,
                send_to_address,
                skiltfarge,
                updated_by,
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def get_sign_sites_for_route(conn, rutenummer: str) -> List[Dict]:
    """List sign sites for a route (by rutenummer or anchor_node_id matched from route)."""
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                id,
                rutenummer,
                route_km,
                ST_X(ST_Transform(geom, 4326)) as lon,
                ST_Y(ST_Transform(geom, 4326)) as lat,
                anchor_node_id,
                name,
                back_text,
                send_to_name,
                send_to_address,
                skiltfarge,
                created_at,
                updated_at
            FROM {schema_quoted}.sign_sites
            WHERE rutenummer = %s
            ORDER BY route_km NULLS LAST, id;
            """,
            (rutenummer,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_sign_sites_by_anchor_ids(conn, anchor_node_ids: List[int]) -> Dict[int, Dict]:
    """Get sign_site row by anchor_node_id (one per anchor)."""
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
                id,
                rutenummer,
                route_km,
                ST_X(ST_Transform(geom, 4326)) as lon,
                ST_Y(ST_Transform(geom, 4326)) as lat,
                anchor_node_id,
                name,
                back_text,
                send_to_name,
                send_to_address,
                skiltfarge,
                created_at,
                updated_at
            FROM {schema_quoted}.sign_sites
            WHERE anchor_node_id = ANY(%s);
            """,
            (anchor_node_ids,),
        )
        rows = cur.fetchall()
    return {int(r["anchor_node_id"]): dict(r) for r in rows if r.get("anchor_node_id") is not None}


def get_sign_site_by_id(conn, sign_site_id: int) -> Optional[Dict]:
    """Get a sign site by id."""
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                id,
                rutenummer,
                route_km,
                ST_X(ST_Transform(geom, 4326)) as lon,
                ST_Y(ST_Transform(geom, 4326)) as lat,
                anchor_node_id,
                name,
                back_text,
                send_to_name,
                send_to_address,
                skiltfarge,
                created_at,
                updated_at
            FROM {schema_quoted}.sign_sites
            WHERE id = %s;
            """,
            (sign_site_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def update_sign_site(
    conn,
    sign_site_id: int,
    name: Optional[str] = None,
    back_text: Optional[str] = None,
    send_to_name: Optional[str] = None,
    send_to_address: Optional[str] = None,
    skiltfarge: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> Optional[Dict]:
    """Update sign site metadata. skiltfarge: 'grønn' or 'trehvit'."""
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    updates = []
    params = []
    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if back_text is not None:
        updates.append("back_text = %s")
        params.append(back_text)
    if send_to_name is not None:
        updates.append("send_to_name = %s")
        params.append(send_to_name)
    if send_to_address is not None:
        updates.append("send_to_address = %s")
        params.append(send_to_address)
    if skiltfarge is not None:
        updates.append("skiltfarge = %s")
        params.append(skiltfarge)
    if updated_by is not None:
        updates.append("updated_by = %s")
        params.append(updated_by)
    if not updates:
        return get_sign_site_by_id(conn, sign_site_id)
    updates.append("updated_at = NOW()")
    params.append(sign_site_id)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE {schema_quoted}.sign_sites
            SET {", ".join(updates)}
            WHERE id = %s
            RETURNING
                id,
                rutenummer,
                route_km,
                ST_X(ST_Transform(geom, 4326)) as lon,
                ST_Y(ST_Transform(geom, 4326)) as lat,
                anchor_node_id,
                name,
                back_text,
                send_to_name,
                send_to_address,
                skiltfarge,
                created_at,
                updated_at;
            """,
            params,
        )
        row = cur.fetchone()
    return dict(row) if row else None


def get_sign_site_destinations(conn, sign_site_id: int) -> List[Dict]:
    """List custom destinations (anchor_node_id, display_order) for a sign site. Empty = use default destinations."""
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        return []
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT sign_site_id, anchor_node_id, display_order
            FROM {schema_quoted}.sign_site_destinations
            WHERE sign_site_id = %s
            ORDER BY display_order, anchor_node_id;
            """,
            (sign_site_id,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_sign_site_destinations_bulk(conn, sign_site_ids: List[int]) -> Dict[int, List[Dict]]:
    """Return custom destinations keyed by sign_site_id. Only includes sites that have at least one row."""
    if not sign_site_ids:
        return {}
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        return {}
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT sign_site_id, anchor_node_id, display_order
            FROM {schema_quoted}.sign_site_destinations
            WHERE sign_site_id = ANY(%s)
            ORDER BY sign_site_id, display_order, anchor_node_id;
            """,
            (sign_site_ids,),
        )
        rows = cur.fetchall()
    out: Dict[int, List[Dict]] = {}
    for r in rows:
        sid = int(r["sign_site_id"])
        if sid not in out:
            out[sid] = []
        out[sid].append({"anchor_node_id": int(r["anchor_node_id"]), "display_order": int(r["display_order"])})
    return out


def set_sign_site_destinations(
    conn,
    sign_site_id: int,
    destinations: List[Dict],
) -> List[Dict]:
    """Replace custom destinations for a sign site. Each item: {anchor_node_id, display_order?}. Returns new list."""
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"DELETE FROM {schema_quoted}.sign_site_destinations WHERE sign_site_id = %s;",
            (sign_site_id,),
        )
        for i, d in enumerate(destinations):
            aid = d.get("anchor_node_id")
            if aid is None:
                continue
            order = d.get("display_order", i)
            cur.execute(
                f"""
                INSERT INTO {schema_quoted}.sign_site_destinations (sign_site_id, anchor_node_id, display_order)
                VALUES (%s, %s, %s)
                ON CONFLICT (sign_site_id, anchor_node_id) DO UPDATE SET display_order = EXCLUDED.display_order;
                """,
                (sign_site_id, int(aid), order),
            )
    return get_sign_site_destinations(conn, sign_site_id)


def get_sign_site_skilt_full(conn, sign_site_ids: List[int]) -> Dict[int, List[Dict]]:
    """Return ALL skilt rows per site as a list (preserves first_link_id discrimination).

    Use this when you need to distinguish multiple panel rows that share an
    anchor_node_id but differ on first_link_id (the parallel-path case).
    The legacy `get_sign_site_skilt_for_sites` collapses such rows.
    """
    if not sign_site_ids:
        return {}
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        return {}
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, sign_site_id, anchor_node_id, first_link_id, direction, status, skiltfarge,
                   distance_meters, destination_name, updated_by, created_at, updated_at
            FROM {schema_quoted}.sign_site_skilt
            WHERE sign_site_id = ANY(%s)
            ORDER BY sign_site_id, anchor_node_id, first_link_id NULLS FIRST;
            """,
            (sign_site_ids,),
        )
        rows = cur.fetchall()
    grouped: Dict[int, List[Dict]] = {}
    for r in rows:
        sid = int(r["sign_site_id"])
        grouped.setdefault(sid, []).append(dict(r))
    return grouped


def get_sign_site_skilt_for_sites(conn, sign_site_ids: List[int]) -> Dict[int, Dict[int, Dict]]:
    """Return skilt rows: sign_site_id -> anchor_node_id -> row dict."""
    if not sign_site_ids:
        return {}
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        return {}
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, sign_site_id, anchor_node_id, first_link_id, direction, status, skiltfarge,
                   distance_meters, destination_name, updated_by, created_at, updated_at
            FROM {schema_quoted}.sign_site_skilt
            WHERE sign_site_id = ANY(%s)
            ORDER BY sign_site_id, anchor_node_id, first_link_id NULLS FIRST;
            """,
            (sign_site_ids,),
        )
        rows = cur.fetchall()
    grouped: Dict[int, Dict[int, Dict]] = {}
    for r in rows:
        sid = int(r["sign_site_id"])
        aid = int(r["anchor_node_id"])
        grouped.setdefault(sid, {})[aid] = dict(r)
    return grouped


def allocate_site_code(conn, area_code: str) -> str:
    """Allocate the next BRE-SS-NNNN style site code for an area via ops.number_spaces.

    The scope is `sign_sites`; prefix is the area_code uppercase. The numeric
    suffix is monotonically increasing per scope/prefix.
    """
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    scope = "sign_sites"
    prefix_upper = area_code.upper()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT MAX((number)::int) AS max_n
            FROM {schema_quoted}.number_spaces
            WHERE scope = %s AND prefix = %s AND number ~ '^[0-9]+$';
            """,
            (scope, prefix_upper),
        )
        row = cur.fetchone()
        next_n = (row.get("max_n") or 0) + 1 if row else 1
        # Loop to handle race: try inserting; bump on conflict.
        for _ in range(1000):
            try:
                cur.execute(
                    f"""
                    INSERT INTO {schema_quoted}.number_spaces (scope, prefix, number, status)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (scope, prefix_upper, str(next_n), "allocated"),
                )
                break
            except psycopg.errors.UniqueViolation:  # type: ignore[attr-defined]
                next_n += 1
        else:
            raise RuntimeError("Could not allocate site code after 1000 attempts")
    return f"{prefix_upper}-SS-{next_n:04d}"


def accept_sign_candidate(
    conn,
    area_code: str,
    anchor_node_id: int,
    geom_wkt_25833: str,
    name: Optional[str],
    updated_by: Optional[str] = None,
) -> Dict:
    """Persist an auto-proposed anchor as an accepted sign site.

    Idempotent: if a row already exists for (area_code, anchor_node_id), updates
    its status to 'accepted' and returns it (preserves the existing site_code).
    """
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, site_code FROM {schema_quoted}.sign_sites
            WHERE area_code = %s AND anchor_node_id = %s;
            """,
            (area_code, anchor_node_id),
        )
        existing = cur.fetchone()
    if existing:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                UPDATE {schema_quoted}.sign_sites
                SET status = 'accepted', updated_by = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, site_code, status, area_code, anchor_node_id, name;
                """,
                (updated_by, existing["id"]),
            )
            return dict(cur.fetchone())
    site_code = allocate_site_code(conn, area_code)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO {schema_quoted}.sign_sites
                (geom, anchor_node_id, name, area_code, status, site_code, updated_by)
            VALUES (ST_SetSRID(ST_GeomFromText(%s), 25833), %s, %s, %s, 'accepted', %s, %s)
            RETURNING id, site_code, status, area_code, anchor_node_id, name;
            """,
            (geom_wkt_25833, anchor_node_id, name, area_code, site_code, updated_by),
        )
        return dict(cur.fetchone())


def reject_sign_candidate(
    conn,
    area_code: str,
    anchor_node_id: int,
    geom_wkt_25833: str,
    name: Optional[str],
    updated_by: Optional[str] = None,
) -> Dict:
    """Soft-reject a candidate: persist a sign_sites row with status='rejected'.

    Idempotent (same upsert pattern as :func:`accept_sign_candidate`). No site
    code is allocated for rejects to avoid burning numbers; a rejected row
    that's later accepted will get a code at that time.
    """
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id FROM {schema_quoted}.sign_sites
            WHERE area_code = %s AND anchor_node_id = %s;
            """,
            (area_code, anchor_node_id),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                f"""
                UPDATE {schema_quoted}.sign_sites
                SET status = 'rejected', updated_by = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, site_code, status, area_code, anchor_node_id, name;
                """,
                (updated_by, existing["id"]),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO {schema_quoted}.sign_sites
                    (geom, anchor_node_id, name, area_code, status, updated_by)
                VALUES (ST_SetSRID(ST_GeomFromText(%s), 25833), %s, %s, %s, 'rejected', %s)
                RETURNING id, site_code, status, area_code, anchor_node_id, name;
                """,
                (geom_wkt_25833, anchor_node_id, name, area_code, updated_by),
            )
        return dict(cur.fetchone())


DEFAULT_DISTANCE_CORRECTION = 1.05


def get_distance_correction_factor(conn, area_code: str) -> float:
    """Look up the per-area distance correction (×1.05 default).

    Heuristic — see [[plan-breheimen-signs-2026-05]] / README. The factor
    blends polyline-chord shortcut + 2D→3D elevation + Kartverket
    generalisation. Configurable per area via ops.distance_correction.

    History: started at ×1.125 (community heuristic); lowered to ×1.05 in
    2026-05 after GPX comparison showed measured walked-vs-mapped factors of
    ~1.03–1.05 (see GPS-fasit card in the Validering tab).
    """
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        return DEFAULT_DISTANCE_CORRECTION
    schema_quoted = quote_identifier(OP_SCHEMA)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT factor FROM {schema_quoted}.distance_correction WHERE area_code = %s;",
                (area_code,),
            )
            row = cur.fetchone()
        if row and row.get("factor") is not None:
            return float(row["factor"])
    except psycopg.errors.UndefinedTable:
        # Table not yet created (migration 012 not run); fall back to default.
        return DEFAULT_DISTANCE_CORRECTION
    return DEFAULT_DISTANCE_CORRECTION


def set_distance_correction_factor(
    conn,
    area_code: str,
    factor: float,
    comment: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert the correction factor for an area. Returns the persisted row."""
    if not (0 < factor < 5):
        raise ValueError("factor must be in (0, 5)")
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO {schema_quoted}.distance_correction (area_code, factor, comment, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (area_code) DO UPDATE
                SET factor = EXCLUDED.factor,
                    comment = COALESCE(EXCLUDED.comment, {schema_quoted}.distance_correction.comment),
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
            RETURNING area_code, factor, comment, updated_by, updated_at;
            """,
            (area_code, factor, comment, updated_by),
        )
        return dict(cur.fetchone())


def delete_sign_site(conn, sign_site_id: int) -> bool:
    """Hard-delete a sign_site row. CASCADEs to sign_site_destinations,
    sign_site_skilt, sign_status. Returns True if a row was deleted.

    For an anchor-based site this reverts the anchor to its "proposed"
    candidate state on the next /signs/candidates fetch (since the overlay
    row is gone). For a manual site the sign disappears entirely.
    """
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {schema_quoted}.sign_sites WHERE id = %s;",
            (sign_site_id,),
        )
        return cur.rowcount > 0


def get_sign_sites_status_by_area_anchor(
    conn,
    area_code: str,
) -> Dict[int, Dict]:
    """Return per-anchor persisted status for an area: anchor_node_id -> {status, site_code, ...}."""
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        return {}
    schema_quoted = quote_identifier(OP_SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, anchor_node_id, site_code, status, name,
                   send_to_name, send_to_address, updated_at
            FROM {schema_quoted}.sign_sites
            WHERE area_code = %s AND anchor_node_id IS NOT NULL;
            """,
            (area_code,),
        )
        rows = cur.fetchall()
    return {int(r["anchor_node_id"]): dict(r) for r in rows if r.get("anchor_node_id") is not None}


def patch_sign_site_skilt(
    conn,
    sign_site_id: int,
    anchor_node_id: int,
    updates: Dict[str, Any],
    updated_by: Optional[str] = None,
    first_link_id: Optional[int] = None,
) -> Optional[Dict]:
    """Create or update skilt metadata for one panel on a sign site.

    Panels are keyed by (sign_site_id, anchor_node_id, first_link_id). When
    first_link_id is None, the row addresses the legacy "no-discriminator"
    slot for that (site, anchor) — used for manual signs and for any panel
    that hasn't been split-by-direction. Edits to one panel never leak to
    another panel sharing the same anchor but a different first_link_id.
    """
    ensure_operational_schema(conn)
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")
    allowed = frozenset({"direction", "status", "skiltfarge", "distance_meters", "destination_name"})
    cleaned = {k: v for k, v in updates.items() if k in allowed}
    if not cleaned:
        return None
    schema_quoted = quote_identifier(OP_SCHEMA)
    ub = updated_by or "anonymous"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, direction, status, skiltfarge, distance_meters, destination_name, first_link_id
            FROM {schema_quoted}.sign_site_skilt
            WHERE sign_site_id = %s
              AND anchor_node_id = %s
              AND COALESCE(first_link_id, -1) = COALESCE(%s::int, -1);
            """,
            (sign_site_id, anchor_node_id, first_link_id),
        )
        existing = cur.fetchone()
        if existing:
            merged = {
                "direction": existing["direction"],
                "status": existing["status"],
                "skiltfarge": existing["skiltfarge"],
                "distance_meters": existing["distance_meters"],
                "destination_name": existing["destination_name"],
            }
            merged.update(cleaned)
            cur.execute(
                f"""
                UPDATE {schema_quoted}.sign_site_skilt SET
                    direction = %s,
                    status = %s,
                    skiltfarge = %s,
                    distance_meters = %s,
                    destination_name = %s,
                    updated_by = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, sign_site_id, anchor_node_id, first_link_id, direction, status, skiltfarge,
                          distance_meters, destination_name, updated_by, created_at, updated_at;
                """,
                (
                    merged["direction"],
                    merged["status"],
                    merged["skiltfarge"],
                    merged["distance_meters"],
                    merged["destination_name"],
                    ub,
                    existing["id"],
                ),
            )
        else:
            merged = {
                "direction": None,
                "status": None,
                "skiltfarge": None,
                "distance_meters": None,
                "destination_name": None,
            }
            merged.update(cleaned)
            cur.execute(
                f"""
                INSERT INTO {schema_quoted}.sign_site_skilt (
                    sign_site_id, anchor_node_id, first_link_id, direction, status, skiltfarge,
                    distance_meters, destination_name, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, sign_site_id, anchor_node_id, first_link_id, direction, status, skiltfarge,
                          distance_meters, destination_name, updated_by, created_at, updated_at;
                """,
                (
                    sign_site_id,
                    anchor_node_id,
                    first_link_id,
                    merged["direction"],
                    merged["status"],
                    merged["skiltfarge"],
                    merged["distance_meters"],
                    merged["destination_name"],
                    ub,
                ),
            )
        row = cur.fetchone()
        return dict(row) if row else None
