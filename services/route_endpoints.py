"""
Service for looking up route endpoint names (start and end points).
Uses stedsnavn for names; ruteinfopunkt is used for facility signals.
"""
import json
import re
import time
from typing import Optional, Dict, Any, Tuple, List
from psycopg.rows import dict_row
from .database import ROUTE_SCHEMA, validate_schema_name
from .operational_database import op_db_connection
from .operational_store import get_endpoint_names_for_anchors


def format_utm_shortform(name: str) -> str:
    """
    Convert UTM fallback name to zone+letter shortform with full coords.
    Accepts both UTM25833 and UTM33N (or similar zone+letter) input.

    Example:
        "UTM25833 341443 6902893" -> "UTM33N 341443 6902893"
    """
    if not name:
        return name
    s = str(name).strip()
    # UTM25833 easting northing, or already UTM<zone><letter> easting northing
    match = re.match(r'^UTM(?:25833|\d{2}[A-Z])\s+(\d+)\s+(\d+)$', s, re.IGNORECASE)
    if not match:
        return name
    try:
        easting = int(match.group(1))
        northing = int(match.group(2))
    except ValueError:
        return name
    # 25833 = zone 33N; output zone + letter
    if s.upper().startswith('UTM25833'):
        return f"UTM33N {easting} {northing}"
    return name


STEDSNAVN_CACHE_TTL_SECONDS = 600
_STEDSNAVN_CACHE: Dict[Tuple[Optional[int], float], Tuple[float, Optional[Dict[str, Any]]]] = {}
CLUSTER_RADIUS_METERS = 200.0


def extract_route_endpoints(route_geometry_geojson: Dict[str, Any]) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """
    Extract start and end point coordinates from a route geometry.

    Args:
        route_geometry_geojson: GeoJSON geometry (LineString or MultiLineString)

    Returns:
        Tuple of (start_point, end_point) where each point is (lon, lat) or None
    """
    if not route_geometry_geojson:
        return None, None

    geom_type = route_geometry_geojson.get('type')
    coordinates = route_geometry_geojson.get('coordinates')

    if not coordinates:
        return None, None

    if geom_type == 'LineString':
        if len(coordinates) < 2:
            return None, None
        start_point = tuple(coordinates[0])  # (lon, lat)
        end_point = tuple(coordinates[-1])  # (lon, lat)
        return start_point, end_point

    elif geom_type == 'MultiLineString':
        if not coordinates or len(coordinates) == 0:
            return None, None

        # Get start from first line, end from last line
        first_line = coordinates[0]
        last_line = coordinates[-1]

        if not first_line or len(first_line) == 0:
            return None, None
        if not last_line or len(last_line) == 0:
            return None, None

        start_point = tuple(first_line[0])  # (lon, lat)
        end_point = tuple(last_line[-1])  # (lon, lat)
        return start_point, end_point

    return None, None


def lookup_name_in_ruteinfopunkt(conn, point_lon: float, point_lat: float, rutenummer: Optional[str] = None, search_radius_meters: float = 100.0) -> Optional[Dict[str, Any]]:
    """
    Look up a name for a point in the ruteinfopunkt view in stiflyt schema.

    Uses the stable stiflyt.ruteinfopunkt view which provides access to ruteinfopunkt data.
    Only searches for hytter (cabins) and parkering (parking) facilities, prioritizing hytter over parkering:
    - '12': Hytte
    - '42': Hytte betjent
    - '43': Hytte selvbetjent
    - '44': Hytte ubetjent
    - '22': Parkeringsplass (lowest priority)

    Args:
        conn: Database connection
        point_lon: Longitude of the point (WGS84)
        point_lat: Latitude of the point (WGS84)
        rutenummer: Optional route number to filter by (not currently used)
        search_radius_meters: Search radius in meters (default: 100m)

    Returns:
        Dict with name, distance, and source, or None if not found
    """
    from .database import ROUTE_SCHEMA, quote_identifier, validate_schema_name

    if not validate_schema_name(ROUTE_SCHEMA):
        return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # Check if view exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.views
                    WHERE table_schema = %s AND table_name = 'ruteinfopunkt'
                ) as exists
            """, (ROUTE_SCHEMA,))
            result = cur.fetchone()
            view_exists = result.get('exists') if result else False

            if not view_exists:
                return None

            # Use the stable view - columns are: informasjon (for name) and posisjon (for geometry)
            schema_quoted = quote_identifier(ROUTE_SCHEMA)
            table_quoted = quote_identifier('ruteinfopunkt')

            query = f"""
                SELECT
                    objid,
                    informasjon as navn,
                    tilrettelegging,
                    ST_Distance(
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                        ST_Transform(posisjon::geometry, 25833)
                    ) as distance_meters
                FROM {schema_quoted}.{table_quoted}
                WHERE ST_DWithin(
                    ST_Transform(posisjon::geometry, 25833),
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    %s
                )
                AND informasjon IS NOT NULL
                AND tilrettelegging = ANY(%s)
                ORDER BY
                    CASE
                        WHEN tilrettelegging IN ('12', '42', '43', '44') THEN 1  -- Hytter first
                        WHEN tilrettelegging = '22' THEN 2  -- Parkeringsplass last
                        ELSE 3
                    END,
                    distance_meters ASC
                LIMIT 1
            """

            # Filter values: '12' (Hytte), '42' (Hytte betjent), '43' (Hytte selvbetjent), '44' (Hytte ubetjent), '22' (Parkeringsplass)
            filter_values = ['12', '42', '43', '44', '22']
            cur.execute(query, (point_lon, point_lat, point_lon, point_lat, search_radius_meters, filter_values))
            result = cur.fetchone()

            if result and result.get('navn'):
                return {
                    'name': str(result['navn']),
                    'distance_meters': float(result['distance_meters']) if result.get('distance_meters') is not None else None,
                    'source': 'ruteinfopunkt',
                    'tilrettelegging': result.get('tilrettelegging')
                }
    except Exception as e:
        # Do not conn.rollback() here: callers (e.g. validators) may be inside a savepoint;
        # a full rollback would invalidate it and cause "savepoint does not exist".
        # Only log meaningful errors (not just "view doesn't exist")
        error_str = str(e)
        if error_str and error_str != "0" and "does not exist" not in error_str.lower():
            print(f"Error in lookup_name_in_ruteinfopunkt: {e}")
        return None

    return None


def list_ruteinfopunkt_facilities(
    conn,
    point_lon: float,
    point_lat: float,
    search_radius_meters: float = 500.0,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """List facility candidates from ruteinfopunkt near a point."""
    from .database import ROUTE_SCHEMA, quote_identifier, validate_schema_name

    if not validate_schema_name(ROUTE_SCHEMA):
        return []

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.views
                    WHERE table_schema = %s AND table_name = 'ruteinfopunkt'
                ) as exists
                """,
                (ROUTE_SCHEMA,),
            )
            result = cur.fetchone()
            view_exists = result.get("exists") if result else False
            if not view_exists:
                return []

            schema_quoted = quote_identifier(ROUTE_SCHEMA)
            table_quoted = quote_identifier("ruteinfopunkt")

            query = f"""
                SELECT
                    objid,
                    informasjon as navn,
                    tilrettelegging,
                    ST_Distance(
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                        ST_Transform(posisjon::geometry, 25833)
                    ) as distance_meters
                FROM {schema_quoted}.{table_quoted}
                WHERE ST_DWithin(
                    ST_Transform(posisjon::geometry, 25833),
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    %s
                )
                AND informasjon IS NOT NULL
                AND tilrettelegging = ANY(%s)
                ORDER BY distance_meters ASC
                LIMIT %s
            """
            filter_values = ["12", "42", "43", "44", "22"]
            cur.execute(
                query,
                (point_lon, point_lat, point_lon, point_lat, search_radius_meters, filter_values, limit),
            )
            results = cur.fetchall()
            return [
                {
                    "name": str(row["navn"]),
                    "source": "ruteinfopunkt",
                    "source_id": str(row.get("objid")) if row.get("objid") is not None else None,
                    "distance_meters": float(row["distance_meters"]) if row.get("distance_meters") is not None else None,
                    "tilrettelegging": row.get("tilrettelegging"),
                }
                for row in results
                if row.get("navn")
            ]
    except Exception:
        # Do not conn.rollback(): callers may be inside a savepoint.
        return []


def list_stedsnavn_candidates(
    conn,
    point_lon: float,
    point_lat: float,
    search_radius_meters: float = 500.0,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """List candidate names from stedsnavn near a point."""
    # Validate coordinates before attempting query
    if not (-180 <= point_lon <= 180) or not (-90 <= point_lat <= 90):
        # Invalid coordinates, skip query
        return []

    # Check if connection is closed
    try:
        if conn.closed:
            return []
    except (AttributeError, Exception):
        # Connection might not have 'closed' attribute, continue
        pass

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            query = """
                SELECT
                    sn.objid,
                    sm.komplettskrivemate AS navn,
                    ST_Distance(
                        ST_Transform(
                            COALESCE(
                                sp.geom,
                                smp.geom,
                                so.geom,
                                ssl.geom
                            ),
                            25833
                        ),
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833)
                    ) as distance_meters
                FROM public.stedsnavn sn
                JOIN public.skrivemate sm ON sn.objid = sm.stedsnavn_fk
                LEFT JOIN public.sted_posisjon sp ON sn.sted_fk = sp.stedsnummer
                LEFT JOIN public.sted_multipunkt smp ON sn.sted_fk = smp.stedsnummer
                LEFT JOIN public.sted_omrade so ON sn.sted_fk = so.stedsnummer
                LEFT JOIN public.sted_senterlinje ssl ON sn.sted_fk = ssl.stedsnummer
                WHERE ST_DWithin(
                    ST_Transform(
                        COALESCE(
                            sp.geom,
                            smp.geom,
                            so.geom,
                            ssl.geom
                        ),
                        25833
                    ),
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    %s
                )
                AND sm.komplettskrivemate IS NOT NULL
                ORDER BY distance_meters ASC
                LIMIT %s
            """
            cur.execute(query, (point_lon, point_lat, point_lon, point_lat, search_radius_meters, limit))
            results = cur.fetchall()
            return [
                {
                    "name": row.get("navn"),
                    "source": "stedsnavn",
                    "source_id": str(row.get("objid")) if row.get("objid") is not None else None,
                    "distance_meters": float(row["distance_meters"]) if row.get("distance_meters") is not None else None,
                }
                for row in results
                if row.get("navn")
            ]
    except Exception as e:
        error_str = str(e).lower()
        # Only log meaningful errors, not expected ones like invalid coordinates or closed connections
        if "connection is closed" in error_str or "invalid coordinate" in error_str or "transform" in error_str:
            # These are expected errors that can happen with invalid data, silently return empty list
            return []

        # Do not conn.rollback(): callers (e.g. validators) may be inside a savepoint.
        # Only print unexpected errors
        if "does not exist" not in error_str and "relation" not in error_str:
            print(f"Error querying stedsnavn: {e}")
        return []


def list_placename_candidates(
    conn,
    point_lon: float,
    point_lat: float,
    search_radius_meters: float = 500.0,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """List nearby placename candidates from stedsnavn."""
    candidates = list_stedsnavn_candidates(conn, point_lon, point_lat, search_radius_meters, limit)
    candidates.sort(key=lambda item: item.get("distance_meters") or 0)
    return candidates[:limit]


def lookup_name_in_stedsnavn(conn, point_lon: float, point_lat: float, search_radius_meters: float = 500.0) -> Optional[Dict[str, Any]]:
    """
    Look up a name for a point in the stedsnavn database.

    Uses the same structure as search_places: public.stedsnavn with skrivemate table.

    Args:
        conn: Database connection
        point_lon: Longitude of the point (WGS84)
        point_lat: Latitude of the point (WGS84)
        search_radius_meters: Search radius in meters (default: 500m)

    Returns:
        Dict with name, distance, and source, or None if not found
    """
    # Validate coordinates before attempting query
    if not (-180 <= point_lon <= 180) or not (-90 <= point_lat <= 90):
        # Invalid coordinates, skip query
        return None

    # Check if connection is closed
    try:
        if conn.closed:
            return None
    except (AttributeError, Exception):
        # Connection might not have 'closed' attribute, continue
        pass

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # Use the same structure as search_places: public.stedsnavn with skrivemate
            # Try the explicit public.stedsnavn structure first
            query = """
                SELECT
                    sm.komplettskrivemate AS navn,
                    ST_Distance(
                        ST_Transform(
                            COALESCE(
                                sp.geom,          -- punkt
                                smp.geom,         -- multipunkt
                                so.geom,          -- område
                                ssl.geom          -- senterlinje
                            ),
                            25833
                        ),
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833)
                    ) as distance_meters
                FROM public.stedsnavn sn
                JOIN public.skrivemate sm ON sn.objid = sm.stedsnavn_fk
                LEFT JOIN public.sted_posisjon   sp  ON sn.sted_fk = sp.stedsnummer
                LEFT JOIN public.sted_multipunkt smp ON sn.sted_fk = smp.stedsnummer
                LEFT JOIN public.sted_omrade    so  ON sn.sted_fk = so.stedsnummer
                LEFT JOIN public.sted_senterlinje ssl ON sn.sted_fk = ssl.stedsnummer
                WHERE ST_DWithin(
                    ST_Transform(
                        COALESCE(
                            sp.geom,
                            smp.geom,
                            so.geom,
                            ssl.geom
                        ),
                        25833
                    ),
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    %s
                )
                AND sm.komplettskrivemate IS NOT NULL
                ORDER BY distance_meters ASC
                LIMIT 1;
            """

            cur.execute(query, [point_lon, point_lat, point_lon, point_lat, search_radius_meters])
            result = cur.fetchone()

            if result and result.get('navn'):
                return {
                    'name': result['navn'],
                    'distance_meters': float(result['distance_meters']) if result.get('distance_meters') is not None else None,
                    'source': 'stedsnavn'
                }
    except Exception as e:
        error_str = str(e).lower()
        # Only log meaningful errors, not expected ones like invalid coordinates or closed connections
        if "connection is closed" in error_str or "invalid coordinate" in error_str or "transform" in error_str:
            # These are expected errors that can happen with invalid data, silently return None
            return None

        # Do not conn.rollback(): callers may be inside a savepoint.
        # Only print unexpected errors
        if "does not exist" not in error_str and "relation" not in error_str:
            print(f"Error querying stedsnavn: {e}")
        return None

    return None


def lookup_name_in_anchor_nodes(conn, point_lon: float, point_lat: float, search_radius_meters: float = 500.0) -> Optional[Dict[str, Any]]:
    """
    Look up a name for a point using anchor_nodes table.
    Anchor nodes already have names found via stedsnavn lookup.

    Args:
        conn: Database connection
        point_lon: Longitude of the point (WGS84)
        point_lat: Latitude of the point (WGS84)
        search_radius_meters: Search radius in meters (default: 500m)

    Returns:
        Dict with name, distance_meters, and source, or None if not found
    """
    from .database import ROUTE_SCHEMA, quote_identifier, validate_schema_name

    if not validate_schema_name(ROUTE_SCHEMA):
        return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # Check if anchor_nodes table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = 'anchor_nodes'
                )
            """, (ROUTE_SCHEMA,))
            result = cur.fetchone()
            table_exists = result[0] if result else False
            if not table_exists:
                return None

            schema_quoted = quote_identifier(ROUTE_SCHEMA)
            table_quoted = quote_identifier('anchor_nodes')

            # Find nearest anchor node with a name
            query = f"""
                SELECT
                    node_id,
                    navn,
                    navn_kilde,
                    navn_distance_m,
                    ST_Distance(
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                        ST_Transform(geom, 25833)
                    ) as distance_meters
                FROM {schema_quoted}.{table_quoted}
                WHERE navn IS NOT NULL
                  AND ST_DWithin(
                      ST_Transform(geom, 25833),
                      ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                      %s
                  )
                ORDER BY distance_meters ASC
                LIMIT 1
            """
            cur.execute(query, (point_lon, point_lat, point_lon, point_lat, search_radius_meters))
            result = cur.fetchone()

            if result and result.get('navn'):
                # Map navn_kilde to source format
                navn_kilde = result.get('navn_kilde', 'anchor_node')
                source_map = {
                    'ruteinfopunkt': 'ruteinfopunkt',
                    'stedsnavn': 'stedsnavn',
                }
                source = source_map.get(navn_kilde, 'anchor_node')

                return {
                    'name': format_utm_shortform(result['navn']),
                    'source': source,
                    'distance_meters': float(result['distance_meters']) if result.get('distance_meters') is not None else None,
                }
    except Exception as e:
        # Do not conn.rollback(): callers may be inside a savepoint.
        # Only log if it's a meaningful error (not just table doesn't exist or empty result)
        error_str = str(e)
        if error_str and error_str != "0" and "does not exist" not in error_str.lower():
            print(f"Error querying anchor_nodes: {e}")
        return None

    return None


def find_nearest_anchor_node(
    conn,
    point_lon: float,
    point_lat: float,
    search_radius_meters: float = 500.0,
) -> Optional[Dict[str, Any]]:
    """Find nearest anchor node by coordinates."""
    from .database import quote_identifier

    if not validate_schema_name(ROUTE_SCHEMA):
        return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = 'anchor_nodes'
                )
                """,
                (ROUTE_SCHEMA,),
            )
            result = cur.fetchone()
            table_exists = result[0] if result else False
            if not table_exists:
                return None

            schema_quoted = quote_identifier(ROUTE_SCHEMA)
            table_quoted = quote_identifier("anchor_nodes")
            query = f"""
                SELECT
                    node_id,
                    ST_X(ST_Transform(geom, 4326)) as lon,
                    ST_Y(ST_Transform(geom, 4326)) as lat,
                    ST_Distance(
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                        ST_Transform(geom, 25833)
                    ) as distance_meters
                FROM {schema_quoted}.{table_quoted}
                WHERE ST_DWithin(
                    ST_Transform(geom, 25833),
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    %s
                )
                  AND navn IS NOT NULL
                ORDER BY distance_meters ASC
                LIMIT 1
            """
            cur.execute(query, (point_lon, point_lat, point_lon, point_lat, search_radius_meters))
            row = cur.fetchone()
            if not row:
                return None
            if row.get("node_id") is None:
                return None
            return {
                "anchor_node_id": int(row["node_id"]),
                "lon": float(row["lon"]) if row.get("lon") is not None else None,
                "lat": float(row["lat"]) if row.get("lat") is not None else None,
                "distance_meters": float(row["distance_meters"]) if row.get("distance_meters") is not None else None,
            }
    except Exception:
        # Do not conn.rollback(): callers may be inside a savepoint.
        return None


def lookup_anchor_name_override(
    anchor_node_id: int,
    rutenummer: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Lookup validated anchor name from ops table."""
    if anchor_node_id is None:
        return None
    try:
        with op_db_connection() as op_conn:
            overrides = get_endpoint_names_for_anchors(
                op_conn,
                [anchor_node_id],
                rutenummer=rutenummer,
            )
        override = overrides.get(anchor_node_id)
        if override and override.get("name"):
            return {
                "name": override.get("name"),
                "source": override.get("source_type", "manual"),
                "source_id": override.get("source_id"),
                "distance_meters": override.get("distance_meters"),
            }
    except Exception:
        return None
    return None


def lookup_named_anchor_within_radius(
    conn,
    point_lon: float,
    point_lat: float,
    radius_meters: float = CLUSTER_RADIUS_METERS,
) -> Optional[Dict[str, Any]]:
    """Find nearest named anchor within radius (cluster fallback)."""
    from .database import quote_identifier

    if not validate_schema_name(ROUTE_SCHEMA):
        return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = 'anchor_nodes'
                )
                """,
                (ROUTE_SCHEMA,),
            )
            result = cur.fetchone()
            table_exists = result[0] if result else False
            if not table_exists:
                return None

            schema_quoted = quote_identifier(ROUTE_SCHEMA)
            table_quoted = quote_identifier("anchor_nodes")
            query = f"""
                SELECT
                    node_id,
                    ST_X(ST_Transform(geom, 4326)) as lon,
                    ST_Y(ST_Transform(geom, 4326)) as lat,
                    ST_Distance(
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                        ST_Transform(geom, 25833)
                    ) as distance_meters
                FROM {schema_quoted}.{table_quoted}
                WHERE ST_DWithin(
                    ST_Transform(geom, 25833),
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    %s
                )
                ORDER BY distance_meters ASC
                LIMIT 1
            """
            cur.execute(query, (point_lon, point_lat, point_lon, point_lat, radius_meters))
            row = cur.fetchone()
            if not row or row.get("node_id") is None:
                return None

        anchor_id = int(row["node_id"])
        override = lookup_anchor_name_override(anchor_id, rutenummer=None)
        if override:
            return {
                **override,
                "anchor_node_id": anchor_id,
                "distance_meters": float(row.get("distance_meters")) if row.get("distance_meters") is not None else None,
            }
        return None
    except Exception:
        # Do not conn.rollback(): callers may be inside a savepoint.
        return None


def lookup_name_in_stedsnavn_cached(
    conn,
    point_lon: float,
    point_lat: float,
    search_radius_meters: float = 500.0,
    anchor_node_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Lookup stedsnavn with a short TTL cache."""
    if anchor_node_id is None:
        cache_key = (None, round(point_lon, 6), round(point_lat, 6), float(search_radius_meters))
    else:
        cache_key = (anchor_node_id, float(search_radius_meters))
    now = time.time()
    cached = _STEDSNAVN_CACHE.get(cache_key)
    if cached:
        timestamp, value = cached
        if now - timestamp < STEDSNAVN_CACHE_TTL_SECONDS:
            return value

    result = lookup_name_in_stedsnavn(
        conn,
        point_lon,
        point_lat,
        search_radius_meters=search_radius_meters,
    )
    _STEDSNAVN_CACHE[cache_key] = (now, result)
    return result


def lookup_endpoint_name(conn, point_lon: float, point_lat: float, rutenummer: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Look up a name for a route endpoint using hierarchical lookup:
    1. Prefer validated anchor names from ops.endpoint_names
    2. Then check nearest named anchor within cluster radius
    3. Then check stedsnavn directly

    Args:
        conn: Database connection
        point_lon: Longitude of the point (WGS84)
        point_lat: Latitude of the point (WGS84)
        rutenummer: Optional route number for filtering ruteinfopunkt

    Returns:
        Dict with name, distance_meters, and source, or None if not found
    """
    # Use same search radius for all sources to allow fair comparison
    search_radius = 500.0

    anchor_node = find_nearest_anchor_node(conn, point_lon, point_lat, search_radius_meters=search_radius)
    if anchor_node:
        override = lookup_anchor_name_override(anchor_node["anchor_node_id"], rutenummer=rutenummer)
        if override:
            return override

    cluster_name = lookup_named_anchor_within_radius(
        conn,
        point_lon,
        point_lat,
        radius_meters=CLUSTER_RADIUS_METERS,
    )
    if cluster_name:
        return cluster_name

    stedsnavn_result = lookup_name_in_stedsnavn_cached(
        conn,
        point_lon,
        point_lat,
        search_radius_meters=search_radius,
        anchor_node_id=anchor_node.get("anchor_node_id") if anchor_node else None,
    )

    if stedsnavn_result:
        return stedsnavn_result

    return None


def get_route_endpoint_names(conn, route_geometry_geojson: Dict[str, Any], rutenummer: Optional[str] = None) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Get names for both start and end points of a route.

    Args:
        conn: Database connection
        route_geometry_geojson: GeoJSON geometry of the route
        rutenummer: Optional route number for filtering

    Returns:
        Dict with 'start_point' and 'end_point', each containing name info or None
    """
    start_point, end_point = extract_route_endpoints(route_geometry_geojson)

    result = {
        'start_point': None,
        'end_point': None
    }

    if start_point:
        start_lon, start_lat = start_point
        start_name = lookup_endpoint_name(conn, start_lon, start_lat, rutenummer)
        if start_name:
            result['start_point'] = {
                **start_name,
                'coordinates': [start_lon, start_lat]
            }

    if end_point:
        end_lon, end_lat = end_point
        end_name = lookup_endpoint_name(conn, end_lon, end_lat, rutenummer)
        if end_name:
            result['end_point'] = {
                **end_name,
                'coordinates': [end_lon, end_lat]
            }

    return result

