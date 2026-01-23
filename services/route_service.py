"""Route service for processing routes and matrikkelenhet."""
import psycopg
import json
from typing import Optional, Dict, List
from psycopg.rows import dict_row
from .database import (
    db_connection,
    ROUTE_SCHEMA,
    TEIG_SCHEMA,
    validate_schema_name,
    get_route_schema,
    quote_identifier,
)
from .operational_database import op_db_connection
from .operational_store import get_endpoint_names_for_anchors, get_endpoint_names_for_anchor_routes


def format_matrikkelenhet(kommunenummer, gardsnummer, bruksnummer, festenummer=None):
    """Format matrikkelenhet as kommunenummer-gardsnummer/bruksnummer/festenummer."""
    if not kommunenummer:
        return None

    # Check if umatrikulert (gardsnummer=0 or bruksnummer=0)
    if gardsnummer == 0 or bruksnummer == 0:
        return f"{kommunenummer}-Umatrikulert"

    if gardsnummer is None or bruksnummer is None:
        return None

    # Format as kommunenummer-gardsnummer/bruksnummer/festenummer
    formatted = f"{kommunenummer}-{gardsnummer}/{bruksnummer}"
    if festenummer is not None and festenummer != 0:
        formatted += f"/{festenummer}"

    return formatted


def parse_geometry(geom_data) -> dict:
    """
    Parse geometry from PostGIS ST_AsGeoJSON result.
    Handles both string and already-parsed dict cases.

    Args:
        geom_data: Geometry data from database (string or dict)

    Returns:
        dict: Parsed geometry as dict
    """
    if isinstance(geom_data, str):
        return json.loads(geom_data)
    elif isinstance(geom_data, dict):
        return geom_data
    else:
        # Fallback: try to convert to dict
        return geom_data


def get_segment_uuid_column(conn, schema: str = ROUTE_SCHEMA, table: str = "fotrute") -> Optional[str]:
    """
    Resolve the preferred UUID column for segments, if present.

    Checks for common UUID-like column names and returns the first match.
    """
    if not validate_schema_name(schema):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {schema}")

    query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
          AND column_name IN ('object_uuid', 'uuid', 'global_id', 'lokalid')
        ORDER BY CASE column_name
            WHEN 'object_uuid' THEN 1
            WHEN 'uuid' THEN 2
            WHEN 'global_id' THEN 3
            WHEN 'lokalid' THEN 4
            ELSE 5
        END
        LIMIT 1
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (schema, table))
        row = cur.fetchone()
        return row["column_name"] if row else None


def get_segment_by_lokalid(conn, lokalid: str, include_geometry: bool = False) -> Optional[dict]:
    """
    Get a single segment by lokalid with all segment fields and fotruteinfo rows.

    Args:
        conn: Database connection
        lokalid: Segment lokalid (stable UUID from source data)
        include_geometry: If True, include GeoJSON geometry in senterlinje

    Returns:
        Dict with segment fields + fotruteinfo_rows, or None if not found.
    """
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'fotrute'
            ORDER BY ordinal_position
            """,
            (ROUTE_SCHEMA,),
        )
        columns = [row["column_name"] for row in cur.fetchall()]

    if not columns:
        return None

    select_parts = []
    for col in columns:
        if col == "senterlinje":
            if include_geometry:
                select_parts.append(
                    "ST_AsGeoJSON(ST_Transform(f.senterlinje::geometry, 4326))::json as senterlinje"
                )
            else:
                select_parts.append("NULL as senterlinje")
        else:
            select_parts.append(f"f.{col}")

    query = f"""
        SELECT
            {', '.join(select_parts)}
        FROM {ROUTE_SCHEMA}.fotrute f
        WHERE f.lokalid = %s
        LIMIT 1
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (lokalid,))
        segment_row = cur.fetchone()

    if not segment_row:
        return None

    fotruteinfo_query = f"""
        SELECT *
        FROM {ROUTE_SCHEMA}.fotruteinfo
        WHERE fotrute_fk = %s
        ORDER BY objid
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(fotruteinfo_query, (segment_row.get("objid"),))
        fotruteinfo_rows = cur.fetchall()

    segment_row["object_uuid"] = segment_row.get("lokalid")

    return {
        "segment": segment_row,
        "fotruteinfo_rows": fotruteinfo_rows,
    }


def get_route_segments(conn, rutenummer):
    """
    Get all segments for a route with basic metadata.

    Args:
        conn: Database connection
        rutenummer: Route identifier

    Returns:
        List of segment dicts with: objid, senterlinje, rutenummer, rutenavn, vedlikeholdsansvarlig
    """
    # Validate schema name (should always be valid, but check for safety)
    # Schema names are constants, but validation provides defense in depth
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    uuid_col = get_segment_uuid_column(conn)
    select_uuid = f", f.{uuid_col}::text as object_uuid" if uuid_col else ""

    query = f"""
        SELECT
            f.objid,
            f.senterlinje,
            fi.rutenummer,
            fi.rutenavn,
            fi.vedlikeholdsansvarlig
            {select_uuid}
        FROM {ROUTE_SCHEMA}.fotrute f
        JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE fi.rutenummer = %s
        ORDER BY f.objid;
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (rutenummer,))
        rows = cur.fetchall()

    if uuid_col:
        for row in rows:
            if not row.get("object_uuid"):
                raise ValueError(f"Missing object_uuid for segment objid {row.get('objid')}")

    return rows


def get_route_segments_with_geometry(conn, rutenummer, include_geojson=True):
    """
    Get route segments with geometry converted to GeoJSON and length.

    All user inputs are parameterized. Schema names are validated constants.

    Args:
        conn: Database connection
        rutenummer: Route identifier
        include_geojson: If True, include geometry as GeoJSON string (default: True)

    Returns:
        List of segment dicts with: objid, senterlinje, length_meters, geometry_geojson (if include_geojson=True)
    """
    # Validate schema name (defense in depth)
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    uuid_col = get_segment_uuid_column(conn)
    select_uuid = f", f.{uuid_col}::text as object_uuid" if uuid_col else ""

    if include_geojson:
        query = f"""
            SELECT
                f.objid,
                f.senterlinje,
                ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters,
                ST_AsGeoJSON(ST_Transform(f.senterlinje::geometry, 4326)) as geometry_geojson
                {select_uuid}
            FROM {ROUTE_SCHEMA}.fotrute f
            JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
            WHERE fi.rutenummer = %s
            ORDER BY f.objid;
        """
    else:
        query = f"""
            SELECT
                f.objid,
                f.senterlinje,
                ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
                {select_uuid}
            FROM {ROUTE_SCHEMA}.fotrute f
            JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
            WHERE fi.rutenummer = %s
            ORDER BY f.objid;
        """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (rutenummer,))
        rows = cur.fetchall()

    if uuid_col:
        for row in rows:
            if not row.get("object_uuid"):
                raise ValueError(f"Missing object_uuid for segment objid {row.get('objid')}")

    return rows


def get_route_segments_with_points(conn, rutenummer):
    """
    Get route segments with start/end points as WKT and length.
    Useful for connection analysis.

    All user inputs are parameterized. Schema names are validated constants.

    Args:
        conn: Database connection
        rutenummer: Route identifier

    Returns:
        List of segment dicts with: objid, start_point_wkt, end_point_wkt, length_meters
    """
    # Validate schema name (defense in depth)
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    query = f"""
        SELECT
            f.objid,
            ST_AsText(ST_Transform(ST_StartPoint(f.senterlinje::geometry), 4326)) as start_point_wkt,
            ST_AsText(ST_Transform(ST_EndPoint(f.senterlinje::geometry), 4326)) as end_point_wkt,
            ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
        FROM {ROUTE_SCHEMA}.fotrute f
        JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE fi.rutenummer = %s
        ORDER BY f.objid;
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (rutenummer,))
        return cur.fetchall()


def get_anchor_node_coords(conn, anchor_node_id: int) -> Optional[Dict[str, float]]:
    """Get anchor node coordinates (lon/lat) for a node ID."""
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = 'anchor_nodes'
            ) as table_exists
            """,
            (ROUTE_SCHEMA,),
        )
        exists_row = cur.fetchone()
        if not exists_row or not exists_row.get("table_exists"):
            return None

        query = f"""
            SELECT
                ST_X(ST_Transform(geom, 4326)) as lon,
                ST_Y(ST_Transform(geom, 4326)) as lat
            FROM {ROUTE_SCHEMA}.anchor_nodes
            WHERE node_id = %s
            LIMIT 1
        """
        cur.execute(query, (anchor_node_id,))
        row = cur.fetchone()
        if not row or row.get("lon") is None or row.get("lat") is None:
            return None
        return {"lon": float(row["lon"]), "lat": float(row["lat"])}


def get_route_anchor_nodes(conn, rutenummer: str) -> List[Dict[str, Optional[float]]]:
    """List anchor nodes for a route with coordinates and link counts."""
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = 'anchor_nodes'
            ) as table_exists
            """,
            (ROUTE_SCHEMA,),
        )
        exists_row = cur.fetchone()
        if not exists_row or not exists_row.get("table_exists"):
            return []

        query = f"""
            WITH route_links AS (
                SELECT link_id, a_node, b_node
                FROM {ROUTE_SCHEMA}.links_with_routes
                WHERE %s = ANY(rutenummer_list)
            ),
            node_counts AS (
                SELECT node_id, COUNT(*) as link_count
                FROM (
                    SELECT a_node as node_id FROM route_links
                    UNION ALL
                    SELECT b_node as node_id FROM route_links
                ) nodes
                GROUP BY node_id
            )
            SELECT
                n.node_id,
                ST_X(ST_Transform(a.geom, 4326)) as lon,
                ST_Y(ST_Transform(a.geom, 4326)) as lat,
                n.link_count
            FROM node_counts n
            JOIN {ROUTE_SCHEMA}.anchor_nodes a ON a.node_id = n.node_id
            ORDER BY n.link_count DESC, n.node_id
        """
        cur.execute(query, (rutenummer,))
        rows = cur.fetchall()

    results = []
    for row in rows:
        if row.get("lon") is None or row.get("lat") is None:
            continue
        results.append(
            {
                "anchor_node_id": int(row["node_id"]),
                "lon": float(row["lon"]),
                "lat": float(row["lat"]),
                "link_count": int(row.get("link_count") or 0),
            }
        )
    return results


def get_segments_by_objids(conn, segment_objids, include_geojson=True):
    """
    Get segments by their objids with geometry and length.

    Args:
        conn: Database connection
        segment_objids: List of segment objids
        include_geojson: If True, include geometry as GeoJSON string (default: True)

    Returns:
        List of segment dicts with: objid, geometry_geojson (if include_geojson=True), length_meters
    """
    if not segment_objids:
        return []

    # Validate segment_objids are integers (prevent injection)
    validated_objids = []
    for objid in segment_objids:
        try:
            objid_int = int(objid)
            if objid_int > 0:
                validated_objids.append(objid_int)
            else:
                raise ValueError(f"Invalid segment objid: {objid} (must be positive)")
        except (ValueError, TypeError):
            raise ValueError(f"Invalid segment objid: {objid} (must be an integer)")

    if not validated_objids:
        return []

    placeholders = ','.join(['%s'] * len(validated_objids))

    # Validate schema name (defense in depth)
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    if include_geojson:
        query = f"""
            SELECT
                f.objid,
                ST_AsGeoJSON(ST_Transform(f.senterlinje::geometry, 4326)) as geometry_geojson,
                ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
            FROM {ROUTE_SCHEMA}.fotrute f
            WHERE f.objid IN ({placeholders});
        """
    else:
        query = f"""
            SELECT
                f.objid,
                ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
            FROM {ROUTE_SCHEMA}.fotrute f
            WHERE f.objid IN ({placeholders});
        """

    with conn.cursor(row_factory=dict_row) as cur:
        # Use validated_objids (all values are parameterized, safe from injection)
        cur.execute(query, validated_objids)
        return cur.fetchall()


def combine_route_geometry(conn, segments):
    """
    Combine route segments into a single geometry (LineString or MultiLineString).

    Handles edge cases:
    - Empty segment list
    - Segments that cannot be merged (returns MultiLineString)
    - NULL geometries in segments
    - Single segment (returns as-is)
    """
    if not segments:
        return None

    # Validate schema name (defense in depth)
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    segment_ids = [seg['objid'] for seg in segments]
    if not segment_ids:
        return None

    # Collect all geometries and attempt to merge
    # ST_LineMerge will return MultiLineString if segments cannot be merged
    query = f"""
        SELECT
            ST_LineMerge(ST_Collect(senterlinje::geometry))::geometry as combined_geom,
            ST_GeometryType(ST_LineMerge(ST_Collect(senterlinje::geometry))::geometry) as geom_type
        FROM {ROUTE_SCHEMA}.fotrute
        WHERE objid = ANY(%s)
          AND senterlinje IS NOT NULL;
    """

    with conn.cursor() as cur:
        cur.execute(query, (segment_ids,))
        result = cur.fetchone()

        if not result or not result[0]:
            # No valid geometries found
            return None

        combined_geom = result[0]
        geom_type = result[1] if len(result) > 1 else None

        # Validate geometry type
        if geom_type and geom_type not in ('ST_LineString', 'ST_MultiLineString'):
            # Unexpected geometry type - log warning but return geometry anyway
            # This handles edge cases like Point, Polygon, etc.
            return combined_geom

        return combined_geom


def get_route_length(conn, route_geom):
    """
    Get route length in meters.

    Uses geography (spherical) calculation for accurate distance measurements.
    Handles both LineString and MultiLineString geometries.
    For MultiLineString, sums the length of all constituent lines.

    Edge cases handled:
    - NULL or empty geometries
    - Invalid geometry types
    - MultiLineString with NULL constituent geometries
    - Empty MultiLineString (no geometries)
    """
    if route_geom is None:
        return 0.0

    # Check geometry type and calculate length accordingly
    check_type_query = """
        SELECT ST_GeometryType(%s::geometry) as geom_type,
               ST_IsEmpty(%s::geometry) as is_empty;
    """

    with conn.cursor() as cur:
        cur.execute(check_type_query, (route_geom, route_geom))
        result = cur.fetchone()

        if not result:
            return 0.0

        geom_type = result[0]
        is_empty = result[1] if len(result) > 1 else False

        if is_empty:
            return 0.0

        if geom_type == 'ST_MultiLineString':
            # For MultiLineString, get number of geometries and validate
            num_query = """
                SELECT ST_NumGeometries(%s::geometry) as num,
                       ST_IsEmpty(%s::geometry) as is_empty;
            """
            cur.execute(num_query, (route_geom, route_geom))
            num_result = cur.fetchone()

            if not num_result:
                return 0.0

            num_geoms = num_result[0]
            is_empty = num_result[1] if len(num_result) > 1 else False

            if num_geoms is None or num_geoms < 1 or is_empty:
                return 0.0

            # Sum lengths using loop - handle NULL geometries gracefully
            total_length = 0.0
            for i in range(1, num_geoms + 1):
                length_query = """
                    SELECT ST_Length(
                        ST_Transform(
                            ST_GeometryN(%s::geometry, %s),
                            4326
                        )::geography
                    ) as length
                    WHERE ST_GeometryN(%s::geometry, %s) IS NOT NULL;
                """
                cur.execute(length_query, (route_geom, i, route_geom, i))
                length_result = cur.fetchone()
                if length_result and length_result[0] is not None:
                    total_length += float(length_result[0])

            return total_length
        elif geom_type == 'ST_LineString':
            # For LineString, use geography for accurate spherical distance calculation
            # Transform to WGS84 (4326) first, then cast to geography
            length_query = """
                SELECT ST_Length(ST_Transform(%s::geometry, 4326)::geography) as length_meters;
            """
            cur.execute(length_query, (route_geom,))
            result = cur.fetchone()
            return float(result[0]) if result and result[0] is not None else 0.0
        else:
            # Unexpected geometry type - try to calculate length anyway
            # This handles edge cases like Point, Polygon, etc.
            length_query = """
                SELECT ST_Length(ST_Transform(%s::geometry, 4326)::geography) as length_meters;
            """
            cur.execute(length_query, (route_geom,))
            result = cur.fetchone()
            return float(result[0]) if result and result[0] is not None else 0.0


def geometry_to_geojson(conn, geom):
    """
    Convert PostGIS geometry to GeoJSON.

    Handles edge cases:
    - NULL geometries
    - Empty geometries
    - Invalid geometry types
    - MultiLineString with empty constituent geometries

    Args:
        conn: Database connection
        geom: PostGIS geometry object

    Returns:
        dict: GeoJSON geometry object, or None if conversion fails
    """
    if geom is None:
        return None

    # Check if geometry is empty before conversion
    check_query = """
        SELECT ST_IsEmpty(%s::geometry) as is_empty,
               ST_GeometryType(%s::geometry) as geom_type;
    """

    with conn.cursor() as cur:
        cur.execute(check_query, (geom, geom))
        check_result = cur.fetchone()

        if not check_result:
            return None

        is_empty = check_result[0] if len(check_result) > 0 else True
        geom_type = check_result[1] if len(check_result) > 1 else None

        if is_empty:
            # Return appropriate empty geometry based on type
            if geom_type == 'ST_MultiLineString':
                return {'type': 'MultiLineString', 'coordinates': []}
            elif geom_type == 'ST_LineString':
                return {'type': 'LineString', 'coordinates': []}
            else:
                return None

        # Convert to GeoJSON
        query = """
            SELECT ST_AsGeoJSON(ST_Transform(%s::geometry, 4326)) as geojson;
        """
        cur.execute(query, (geom,))
        result = cur.fetchone()

        if result and result[0]:
            import json
            try:
                geojson_dict = json.loads(result[0])
                # Validate GeoJSON structure
                if isinstance(geojson_dict, dict) and 'type' in geojson_dict:
                    return geojson_dict
                return None
            except (json.JSONDecodeError, TypeError):
                return None
        return None


def parse_geojson_string(geojson_str):
    """
    Parse a GeoJSON string from SQL query results.
    Helper function to avoid duplicate json.loads() calls.

    Args:
        geojson_str: GeoJSON string from database (or None)

    Returns:
        dict: Parsed GeoJSON object, or None if input is None/empty
    """
    if not geojson_str:
        return None
    import json
    try:
        return json.loads(geojson_str)
    except (json.JSONDecodeError, TypeError):
        return None


def find_matrikkelenhet_intersections(conn, route_geom):
    """
    Find all intersections between route and teig polygons.

    Limits results to first 100 matrikkelenheter and returns total count
    to detect overflow.

    All schema names are validated constants. Route geometry is parameterized.

    Optimized to calculate ST_Intersection only once per row using CTE,
    and uses bounding box filter (&&) for faster initial filtering.

    Returns:
        tuple: (results, total_count) where:
            - results: List of intersection dicts (max 100)
            - total_count: Total number of intersections found (may be > 100)
    """
    # Validate schema names (should always be valid, but check for safety)
    if not validate_schema_name(TEIG_SCHEMA):
        raise ValueError(f"Invalid TEIG_SCHEMA: {TEIG_SCHEMA}")

    # Optimized query: Calculate ST_Intersection once using CTE
    # Use bounding box filter (&&) first for faster filtering
    # Use window function COUNT(*) OVER() to get total count before LIMIT
    query = f"""
        WITH intersections AS (
            SELECT
                t.matrikkelnummertekst,
                t.kommunenummer,
                t.kommunenavn,
                t.arealmerknadtekst,
                t.lagretberegnetareal,
                t.teigid,
                m.bruksnavn,
                m.gardsnummer,
                m.bruksnummer,
                m.festenummer,
                ST_Intersection(t.omrade::geometry, %s::geometry) as intersection_geom
            FROM {TEIG_SCHEMA}.teig t
            LEFT JOIN {TEIG_SCHEMA}.matrikkelenhet m ON m.teig_fk = t.teigid
            WHERE t.omrade::geometry && %s::geometry  -- Fast bounding box filter first
            AND ST_Intersects(t.omrade::geometry, %s::geometry)  -- Precise intersection check
        )
        SELECT
            matrikkelnummertekst,
            kommunenummer,
            kommunenavn,
            arealmerknadtekst,
            lagretberegnetareal,
            teigid,
            bruksnavn,
            gardsnummer,
            bruksnummer,
            festenummer,
            intersection_geom,
            CASE
                WHEN intersection_geom IS NOT NULL
                THEN ST_Length(ST_Transform(intersection_geom, 4326)::geography)
                ELSE 0
            END as length_meters,
            COUNT(*) OVER() as total_count
        FROM intersections
        WHERE intersection_geom IS NOT NULL
        AND ST_GeometryType(intersection_geom) IN ('ST_LineString', 'ST_MultiLineString')
        LIMIT 100;
    """

    with conn.cursor(row_factory=dict_row) as cur:
        # Only need route_geom 3 times now (was 4): &&, ST_Intersects, and ST_Intersection
        cur.execute(query, (route_geom, route_geom, route_geom))
        results = cur.fetchall()

        # Extract total_count from first row (all rows have same value due to window function)
        # If no results, total_count is 0
        total_count = results[0]['total_count'] if results else 0

        # Remove total_count from result rows before returning
        for row in results:
            row.pop('total_count', None)

        return results, total_count


def calculate_offsets(conn, route_geom, intersections, total_length):
    """
    Calculate offset from start for each intersection.

    Args:
        conn: Database connection
        route_geom: Route geometry
        intersections: List of intersection data
        total_length: Total length of route in meters

    Returns:
        list: List of offset dictionaries

    Raises:
        ValueError: If total_length is zero or negative
    """
    # Validate total_length to prevent division by zero or invalid calculations
    if total_length is None or total_length <= 0:
        # If route has zero or negative length, offsets cannot be calculated meaningfully
        # Return empty list rather than raising error, as this might be a valid edge case
        # (e.g., route with no length due to data issues)
        return []

    results = []

    # Check if route_geom is MultiLineString and convert to single LineString if needed
    # ST_LineLocatePoint requires a LineString, not MultiLineString
    check_route_type_query = """
        SELECT ST_GeometryType(%s::geometry) as geom_type;
    """

    with conn.cursor() as cur:
        cur.execute(check_route_type_query, (route_geom,))
        route_type = cur.fetchone()[0]

    # If route is MultiLineString, we need to handle it differently
    # For MultiLineString, we'll use ST_LineMerge to try to merge, or use the first line
    if route_type == 'ST_MultiLineString':
        # Check if MultiLineString is empty
        check_empty_query = """
            SELECT ST_IsEmpty(%s::geometry) as is_empty,
                   ST_NumGeometries(%s::geometry) as num_geoms;
        """
        with conn.cursor() as cur:
            cur.execute(check_empty_query, (route_geom, route_geom))
            empty_result = cur.fetchone()

            if not empty_result or empty_result[0] or (empty_result[1] if len(empty_result) > 1 else 0) < 1:
                # Empty MultiLineString - cannot calculate offsets
                return results

            # Attempt to merge MultiLineString
            merge_query = """
                SELECT ST_LineMerge(%s::geometry)::geometry as merged_geom,
                       ST_GeometryType(ST_LineMerge(%s::geometry)::geometry) as merged_type,
                       ST_IsEmpty(ST_LineMerge(%s::geometry)::geometry) as merged_empty;
            """
            cur.execute(merge_query, (route_geom, route_geom, route_geom))
            merge_result = cur.fetchone()

            if merge_result and merge_result[1] == 'ST_LineString' and not (merge_result[2] if len(merge_result) > 2 else False):
                # Successfully merged to LineString
                route_geom = merge_result[0]
            else:
                # Merge failed or still MultiLineString - use first non-empty line
                first_line_query = """
                    SELECT ST_GeometryN(%s::geometry, 1)::geometry as first_line
                    WHERE ST_NumGeometries(%s::geometry) >= 1
                      AND ST_GeometryN(%s::geometry, 1) IS NOT NULL
                      AND NOT ST_IsEmpty(ST_GeometryN(%s::geometry, 1)::geometry);
                """
                cur.execute(first_line_query, (route_geom, route_geom, route_geom, route_geom))
                first_line_result = cur.fetchone()
                if first_line_result and first_line_result[0]:
                    route_geom = first_line_result[0]
                else:
                    # No valid first line - cannot calculate offsets
                    return results

    for intersection in intersections:
        # Handle both LineString and MultiLineString for intersection
        # For MultiLineString, get the start point of the first line
        query = """
            SELECT ST_LineLocatePoint(
                %s::geometry,
                ST_StartPoint(
                    CASE
                        WHEN ST_GeometryType(%s::geometry) = 'ST_MultiLineString'
                        THEN ST_GeometryN(%s::geometry, 1)
                        ELSE %s::geometry
                    END
                )
            ) as fraction;
        """

        with conn.cursor() as cur:
            cur.execute(query, (route_geom, intersection['intersection_geom'],
                              intersection['intersection_geom'], intersection['intersection_geom']))
            result = cur.fetchone()
            fraction = result[0] if result else 0.0

        offset_meters = fraction * total_length
        offset_km = offset_meters / 1000.0

        # Format matrikkelenhet
        formatted_matrikkel = format_matrikkelenhet(
            intersection['kommunenummer'],
            intersection.get('gardsnummer'),
            intersection.get('bruksnummer'),
            intersection.get('festenummer')
        )

        # Convert intersection geometry to GeoJSON
        intersection_geom = intersection['intersection_geom']
        intersection_geojson = geometry_to_geojson(conn, intersection_geom)

        # Handle potential None or zero length_meters
        length_meters = intersection.get('length_meters') or 0.0
        length_km = length_meters / 1000.0 if length_meters else 0.0

        results.append({
            'matrikkelenhet': formatted_matrikkel or intersection['matrikkelnummertekst'],
            'bruksnavn': intersection.get('bruksnavn'),
            'kommunenummer': intersection['kommunenummer'],
            'kommunenavn': intersection['kommunenavn'],
            'offset_meters': offset_meters,
            'offset_km': offset_km,
            'length_meters': length_meters,
            'length_km': length_km,
            'geometry': intersection_geojson
        })

    # Sort by offset
    results.sort(key=lambda x: x['offset_meters'])
    return results


def _choose_first_available(columns, candidates):
    """Return the first column from candidates that exists in columns."""
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def search_places(query: str, limit: int = 20):
    """
    Search across ruteinfopunkt, stedsnavn and routes to support map zoom.

    Returns items with coordinates so the frontend can pan/zoom immediately.
    """
    if not isinstance(limit, int) or limit < 1 or limit > 200:
        raise ValueError(f"Invalid limit: {limit}. Must be between 1 and 200.")

    if not query or not isinstance(query, str):
        return []

    results = []
    seen_ids = set()

    with db_connection() as conn:
        route_schema = get_route_schema(conn)
        if not validate_schema_name(route_schema):
            raise ValueError(f"Invalid ROUTE_SCHEMA: {route_schema}")

        # 1) Search ruteinfopunkt (names stored with geometry)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = 'ruteinfopunkt'
                    """,
                    (route_schema,),
                )
                columns = [row[0] for row in cur.fetchall()]

            name_col = _choose_first_available(
                columns, ['navn', 'name', 'stedsnavn', 'punktnavn', 'beskrivelse', 'tekst']
            )
            geom_col = _choose_first_available(
                columns, ['geom', 'geometry', 'posisjon', 'location', 'punkt']
            )

            if name_col and geom_col:
                sub_limit = max(5, min(limit, 10))
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"""
                            SELECT
                                objid,
                                {name_col} AS name,
                                ST_X(ST_Centroid(ST_Transform({geom_col}::geometry, 4326))) AS lon,
                                ST_Y(ST_Centroid(ST_Transform({geom_col}::geometry, 4326))) AS lat
                            FROM {route_schema}.ruteinfopunkt
                            WHERE {name_col} ILIKE %s
                            ORDER BY {name_col}
                            LIMIT %s
                        """,
                        (f"%{query}%", sub_limit),
                    )
                    for row in cur.fetchall():
                        if row['objid'] in seen_ids:
                            continue
                        seen_ids.add(row['objid'])
                        if row['lon'] is None or row['lat'] is None:
                            continue
                        results.append(
                            {
                                'id': f"ruteinfopunkt-{row['objid']}",
                                'type': 'ruteinfopunkt',
                                'title': str(row['name']) if row['name'] else 'Uten navn',
                                'lon': float(row['lon']),
                                'lat': float(row['lat']),
                            }
                        )
        except Exception as e:
            print(f"Ruteinfopunkt search failed: {e}")

        # 2) Search stedsnavn
        #
        # Uses explicit query against public.stedsnavn / public.skrivemate +
        # sted_* geometry tables and kommune, and exposes kommunenavn/fylkesnavn
        # in the result (frontend shows as subtitle).
        #
        # Geometry strategy:
        #   - Prefer punkt (sted_posisjon)
        #   - Fallback til multipunkt, område, senterlinje via COALESCE
        try:
            sub_limit = max(5, min(limit, 10))
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                        SELECT
                            sn.objid,
                            sm.komplettskrivemate AS navn,
                            k.kommunenavn,
                            k.kommunenummer,
                            k.fylkesnavn,
                            k.fylkesnummer,
                            ST_X(
                                ST_Centroid(
                                    ST_Transform(
                                        COALESCE(
                                            sp.geom,          -- punkt
                                            smp.geom,         -- multipunkt
                                            so.geom,          -- område
                                            ssl.geom          -- senterlinje
                                        ),
                                        4326
                                    )
                                )
                            ) AS lon,
                            ST_Y(
                                ST_Centroid(
                                    ST_Transform(
                                        COALESCE(
                                            sp.geom,
                                            smp.geom,
                                            so.geom,
                                            ssl.geom
                                        ),
                                        4326
                                    )
                                )
                            ) AS lat
                        FROM public.stedsnavn sn
                        JOIN public.skrivemate sm ON sn.objid = sm.stedsnavn_fk
                        LEFT JOIN public.sted_posisjon   sp  ON sn.sted_fk = sp.stedsnummer
                        LEFT JOIN public.sted_multipunkt smp ON sn.sted_fk = smp.stedsnummer
                        LEFT JOIN public.sted_omrade    so  ON sn.sted_fk = so.stedsnummer
                        LEFT JOIN public.sted_senterlinje ssl ON sn.sted_fk = ssl.stedsnummer
                        LEFT JOIN public.kommune k ON sn.sted_fk = k.sted_fk
                        WHERE sm.komplettskrivemate ILIKE %s
                        ORDER BY
                            CASE
                                WHEN LOWER(sm.komplettskrivemate) = LOWER(%s) THEN 0
                                WHEN sm.komplettskrivemate ILIKE %s THEN 1
                                ELSE 2
                            END,
                            sm.komplettskrivemate
                        LIMIT %s;
                    """,
                    (f"%{query}%", query, f"{query}%", sub_limit),
                )
                for row in cur.fetchall():
                    objid = row.get('objid')
                    if objid in seen_ids:
                        continue
                    lon = row.get('lon')
                    lat = row.get('lat')
                    if lon is None or lat is None:
                        continue
                    seen_ids.add(objid)
                    title = row.get('navn') or 'Uten navn'
                    kommunenavn = row.get('kommunenavn')
                    fylkesnavn = row.get('fylkesnavn')
                    subtitle_parts = []
                    if kommunenavn:
                        subtitle_parts.append(str(kommunenavn))
                    if fylkesnavn:
                        subtitle_parts.append(str(fylkesnavn))
                    subtitle = ", ".join(subtitle_parts) if subtitle_parts else None

                    results.append(
                        {
                            'id': f"stedsnavn-{objid}",
                            'type': 'stedsnavn',
                            'title': str(title),
                            'subtitle': subtitle,
                            'lon': float(lon),
                            'lat': float(lat),
                        }
                    )
        except Exception as e:
            # Fallback: try to find stedsnavn table in any schema (stedsnavn may be in a different schema than stiflyt)
            print(f"Explicit stedsnavn search in stiflyt schema failed, trying dynamic discovery: {e}")
            try:
                stedsnavn_schema = None
                stedsnavn_table = None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                            SELECT table_schema, table_name
                            FROM information_schema.tables
                            WHERE (table_schema LIKE '%stedsnavn%' OR table_name LIKE '%stedsnavn%' OR table_name LIKE '%place%name%')
                            AND table_type = 'BASE TABLE'
                            ORDER BY table_schema, table_name
                            LIMIT 1;
                        """
                    )
                    result = cur.fetchone()
                    if result:
                        stedsnavn_schema, stedsnavn_table = result

                if stedsnavn_schema and stedsnavn_table and validate_schema_name(stedsnavn_schema) and validate_schema_name(stedsnavn_table):
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                                SELECT column_name
                                FROM information_schema.columns
                                WHERE table_schema = %s AND table_name = %s
                            """,
                            (stedsnavn_schema, stedsnavn_table),
                        )
                        columns = [row[0] for row in cur.fetchall()]

                    name_col = _choose_first_available(columns, ['navn', 'name', 'stedsnavn'])
                    geom_col = _choose_first_available(columns, ['geom', 'geometry', 'posisjon', 'punkt'])

                    if name_col and geom_col:
                        with conn.cursor(row_factory=dict_row) as cur:
                            cur.execute(
                                f"""
                                    SELECT
                                        objid,
                                        {name_col} AS name,
                                        ST_X(ST_Centroid(ST_Transform({geom_col}::geometry, 4326))) AS lon,
                                        ST_Y(ST_Centroid(ST_Transform({geom_col}::geometry, 4326))) AS lat
                                    FROM "{stedsnavn_schema}"."{stedsnavn_table}"
                                    WHERE {name_col} ILIKE %s
                                    ORDER BY {name_col}
                                    LIMIT %s
                                """,
                                (f"%{query}%", sub_limit),
                            )
                            for row in cur.fetchall():
                                if row['objid'] in seen_ids:
                                    continue
                                seen_ids.add(row['objid'])
                                if row['lon'] is None or row['lat'] is None:
                                    continue
                                results.append(
                                    {
                                        'id': f"stedsnavn-{row['objid']}",
                                        'type': 'stedsnavn',
                                        'title': str(row['name']) if row['name'] else 'Uten navn',
                                        'lon': float(row['lon']),
                                        'lat': float(row['lat']),
                                    }
                                )
            except Exception as e2:
                print(f"Stedsnavn dynamic search failed: {e2}")

        # 3) Search routes (by rutenummer or name) and return centroid
        try:
            sub_limit = max(5, min(limit, 10))
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                        SELECT
                            fi.rutenummer,
                            fi.rutenavn,
                            ST_X(ST_Centroid(ST_Transform(f.senterlinje::geometry, 4326))) AS lon,
                            ST_Y(ST_Centroid(ST_Transform(f.senterlinje::geometry, 4326))) AS lat
                        FROM {route_schema}.fotrute f
                        JOIN {route_schema}.fotruteinfo fi ON fi.fotrute_fk = f.objid
                        WHERE fi.rutenummer ILIKE %s OR fi.rutenavn ILIKE %s
                        ORDER BY fi.rutenummer
                        LIMIT %s
                    """,
                    (f"%{query}%", f"%{query}%", sub_limit),
                )
                for row in cur.fetchall():
                    result_id = f"rute-{row['rutenummer']}"
                    if result_id in seen_ids:
                        continue
                    seen_ids.add(result_id)
                    if row['lon'] is None or row['lat'] is None:
                        continue
                    results.append(
                        {
                            'id': result_id,
                            'type': 'rute',
                            'title': row['rutenavn'] or row['rutenummer'],
                            'subtitle': row['rutenummer'],
                            'lon': float(row['lon']),
                            'lat': float(row['lat']),
                            'rutenummer': row['rutenummer'],
                        }
                    )
        except Exception as e:
            print(f"Route centroid search failed: {e}")

    # Preserve insertion order, respect limit
    return results[:limit]


def get_complete_route(conn, rutenummer, include_geometry=True, include_segments=False, include_endpoint_names=True):
    """
    Get a complete route using the route_geometries column from links_with_routes.
    The geometry is already ordered and oriented in one direction.

    Args:
        conn: Database connection
        rutenummer: Route number
        include_geometry: If True, include GeoJSON geometry (default: True)
        include_segments: If True, include individual segment details (default: False)
        include_endpoint_names: If True, lookup and include from/to names (default: True)

    Returns:
        dict with complete route information, or None if route not found
    """
    from .route_endpoints import get_route_endpoint_names, extract_route_endpoints

    # Validate schema name
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    # Get route metadata and geometry from links_with_routes
    route_query = f"""
        SELECT DISTINCT
            fi.rutenummer,
            fi.rutenavn,
            fi.vedlikeholdsansvarlig,
            lwr.route_geometries->>%s as route_geometry_json,
            ST_Length(ST_Transform(ST_GeomFromGeoJSON(lwr.route_geometries->>%s), 4326)::geography) as length_meters
        FROM {ROUTE_SCHEMA}.fotruteinfo fi
        JOIN {ROUTE_SCHEMA}.links_with_routes lwr ON %s = ANY(lwr.rutenummer_list)
        WHERE fi.rutenummer = %s
          AND lwr.route_geometries->>%s IS NOT NULL
        LIMIT 1
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(route_query, (rutenummer, rutenummer, rutenummer, rutenummer, rutenummer))
        route_row = cur.fetchone()

        if not route_row:
            return None  # Route not found

        rutenavn = route_row.get('rutenavn')
        vedlikeholdsansvarlig = route_row.get('vedlikeholdsansvarlig')
        route_geometry_json = route_row.get('route_geometry_json')
        total_length_meters = float(route_row.get('length_meters', 0)) if route_row.get('length_meters') is not None else 0.0

    # Parse geometry if available
    geometry = None
    if include_geometry and route_geometry_json:
        try:
            import json
            # route_geometry_json is already a GeoJSON string from the database
            geometry = json.loads(route_geometry_json)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            # If geometry parsing fails, continue without geometry
            geometry = None

    total_length_km = total_length_meters / 1000.0 if total_length_meters else 0.0

    # Get segment count
    segment_count_query = f"""
        SELECT COUNT(DISTINCT f.objid) as segment_count
        FROM {ROUTE_SCHEMA}.fotrute f
        JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE fi.rutenummer = %s
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(segment_count_query, (rutenummer,))
        segment_row = cur.fetchone()
        segment_count = int(segment_row['segment_count']) if segment_row else 0

    # Geometry from route_geometries is already connected and ordered
    is_connected = geometry is not None
    component_count = 1 if is_connected else 0

    # Get endpoint names if requested
    from_name = None
    to_name = None
    if include_endpoint_names:
        from .route_endpoints import extract_route_endpoints, lookup_endpoint_name

        # Try operational overrides using anchor nodes from links_with_routes
        anchor_ids = {}
        anchor_query = f"""
            WITH route_links AS (
                SELECT link_id, a_node, b_node
                FROM {ROUTE_SCHEMA}.links_with_routes
                WHERE %s = ANY(rutenummer_list)
            )
            SELECT
                (SELECT a_node FROM route_links ORDER BY link_id ASC LIMIT 1) as first_a_node,
                (SELECT b_node FROM route_links ORDER BY link_id DESC LIMIT 1) as last_b_node
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(anchor_query, (rutenummer,))
            anchor_row = cur.fetchone()
        if anchor_row:
            if anchor_row.get("first_a_node") is not None:
                anchor_ids["from"] = int(anchor_row["first_a_node"])
            if anchor_row.get("last_b_node") is not None:
                anchor_ids["to"] = int(anchor_row["last_b_node"])

        overrides = {}
        if anchor_ids:
            with op_db_connection() as op_conn:
                overrides = get_endpoint_names_for_anchors(
                    op_conn,
                    list(anchor_ids.values()),
                    rutenummer=rutenummer,
                )

        if anchor_ids.get("from") and overrides.get(anchor_ids.get("from")):
            override = overrides.get(anchor_ids["from"])
            coords = get_anchor_node_coords(conn, anchor_ids["from"])
            from_name = {
                "name": override.get("name"),
                "source": override.get("source_type", "manual"),
                "distance_meters": override.get("distance_meters"),
                "coordinates": [coords["lon"], coords["lat"]] if coords else None,
                "is_validated": True,
            }

        if anchor_ids.get("to") and overrides.get(anchor_ids.get("to")):
            override = overrides.get(anchor_ids["to"])
            coords = get_anchor_node_coords(conn, anchor_ids["to"])
            to_name = {
                "name": override.get("name"),
                "source": override.get("source_type", "manual"),
                "distance_meters": override.get("distance_meters"),
                "coordinates": [coords["lon"], coords["lat"]] if coords else None,
                "is_validated": True,
            }

        # Fallback to lookup by geometry if overrides not present
        if geometry:
            start_point, end_point = extract_route_endpoints(geometry)

            if start_point and not from_name:
                start_name_info = lookup_endpoint_name(conn, start_point[0], start_point[1], rutenummer)
                if start_name_info and start_name_info.get('name'):
                    from_name = {
                        'name': start_name_info.get('name'),
                        'source': start_name_info.get('source', 'unknown'),
                        'distance_meters': start_name_info.get('distance_meters'),
                        'coordinates': [start_point[0], start_point[1]],
                        'is_validated': False,
                    }

            if end_point and not to_name:
                end_name_info = lookup_endpoint_name(conn, end_point[0], end_point[1], rutenummer)
                if end_name_info and end_name_info.get('name'):
                    to_name = {
                        'name': end_name_info.get('name'),
                        'source': end_name_info.get('source', 'unknown'),
                        'distance_meters': end_name_info.get('distance_meters'),
                        'coordinates': [end_point[0], end_point[1]],
                        'is_validated': False,
                    }

    # Build segments list if requested
    segments = None
    if include_segments:
        uuid_col = get_segment_uuid_column(conn)
        select_uuid = f", f.{uuid_col}::text as object_uuid" if uuid_col else ""
        segments = []
        # Get all segments for this route
        segments_query = f"""
            SELECT
                f.objid,
                ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters,
                CASE WHEN %s THEN ST_AsGeoJSON(ST_Transform(f.senterlinje::geometry, 4326))::json ELSE NULL END as geometry
                {select_uuid}
            FROM {ROUTE_SCHEMA}.fotrute f
            JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
            WHERE fi.rutenummer = %s
            ORDER BY f.objid
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(segments_query, (include_geometry, rutenummer))
            segment_rows = cur.fetchall()

        for seg_row in segment_rows:
            objid = seg_row['objid']
            if uuid_col and not seg_row.get('object_uuid'):
                raise ValueError(f"Missing object_uuid for segment objid {objid}")
            # Get route info for this segment
            segment_routes_query = f"""
                SELECT DISTINCT
                    fi.rutenummer,
                    fi.rutenavn,
                    fi.vedlikeholdsansvarlig
                FROM {ROUTE_SCHEMA}.fotruteinfo fi
                WHERE fi.fotrute_fk = %s
            """
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(segment_routes_query, (objid,))
                route_rows = cur.fetchall()

            route_infos = []
            for route_row in route_rows:
                route_infos.append({
                    'rutenummer': route_row['rutenummer'],
                    'rutenavn': route_row.get('rutenavn'),
                    'vedlikeholdsansvarlig': route_row.get('vedlikeholdsansvarlig')
                })

            segment_geom = parse_geometry(seg_row.get('geometry')) if include_geometry and seg_row.get('geometry') else None
            segments.append({
                'objid': objid,
                'object_uuid': seg_row.get('object_uuid'),
                'routes': route_infos,
                'length_meters': float(seg_row['length_meters']) if seg_row.get('length_meters') is not None else 0.0,
                'geometry': segment_geom
            })

    # Build result
    result = {
        'rutenummer': rutenummer,
        'rutenavn': rutenavn,
        'vedlikeholdsansvarlig': vedlikeholdsansvarlig,
        'total_length_meters': total_length_meters,
        'total_length_km': total_length_km,
        'from_name': from_name,
        'to_name': to_name,
        'is_connected': is_connected,
        'segment_count': segment_count,
        'component_count': component_count
    }

    if include_geometry:
        result['geometry'] = geometry

    if include_segments and segments:
        result['segments'] = segments

    return result


def get_routes_from_view(
    conn,
    rutenummer: Optional[str] = None,
    prefix: Optional[str] = None,
    vedlikeholdsansvarlig: Optional[str] = None,
    bbox: Optional[tuple[float, float, float, float]] = None,
    limit: int = 100,
    offset: int = 0,
    include_geometry: bool = False
):
    """
    Get routes from stiflyt.routes materialized view with optional filters.

    Args:
        conn: Database connection
        rutenummer: Exact route number (e.g., "bre10")
        prefix: Route number prefix (e.g., "bre", "jot", "ron")
        vedlikeholdsansvarlig: Organization filter (pattern match)
        bbox: Bounding box as (xmin, ymin, xmax, ymax) in WGS84 (4326)
        limit: Maximum number of results
        offset: Pagination offset
        include_geometry: If True, include GeoJSON geometry

    Returns:
        tuple: (routes_list, total_count) where routes_list is list of route dicts
    """
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    # Build WHERE clause
    where_conditions = []
    params = []

    if rutenummer:
        where_conditions.append("rutenummer = %s")
        params.append(rutenummer)
    elif prefix:
        where_conditions.append("rutenummer LIKE %s")
        params.append(f"{prefix}%")

    if vedlikeholdsansvarlig:
        where_conditions.append("vedlikeholdsansvarlig ILIKE %s")
        params.append(f"%{vedlikeholdsansvarlig}%")

    if bbox:
        xmin, ymin, xmax, ymax = bbox
        # Transform bbox from WGS84 (4326) to UTM 33N (25833) for spatial query
        where_conditions.append(
            "route_geometry && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), 25833) "
            "AND ST_Intersects(route_geometry, ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), 25833))"
        )
        params.extend([xmin, ymin, xmax, ymax, xmin, ymin, xmax, ymax])

    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

    # Build SELECT clause
    select_parts = [
        "rutenummer",
        "rutenavn",
        "vedlikeholdsansvarlig",
        "rutetype",
        "total_length_m",
        "segment_count",
        "segment_objids"
    ]

    if include_geometry:
        select_parts.append("ST_AsGeoJSON(ST_Transform(route_geometry, 4326))::json as route_geometry")

    # Build query with count for total
    query = f"""
        WITH filtered_routes AS (
            SELECT
                {', '.join(select_parts)}
            FROM {ROUTE_SCHEMA}.routes
            {where_clause}
        )
        SELECT
            *,
            COUNT(*) OVER() as total_count
        FROM filtered_routes
        ORDER BY rutenummer
        LIMIT %s
        OFFSET %s
    """

    params.extend([limit, offset])

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    # Extract total count from first row
    total_count = rows[0]['total_count'] if rows else 0

    # Build results
    routes = []
    for row in rows:
        route = {
            'rutenummer': row['rutenummer'],
            'rutenavn': row.get('rutenavn'),
            'vedlikeholdsansvarlig': row.get('vedlikeholdsansvarlig'),
            'rutetype': row.get('rutetype'),
            'total_length_m': float(row['total_length_m']) if row.get('total_length_m') is not None else 0.0,
            'segment_count': int(row['segment_count']) if row.get('segment_count') is not None else 0,
            'segment_objids': row.get('segment_objids')
        }

        if include_geometry and row.get('route_geometry'):
            route['route_geometry'] = parse_geometry(row['route_geometry'])

        routes.append(route)

    # Get endpoint names for routes: first link's a_node and last link's b_node
    if routes:
        # Query endpoint names for all routes at once
        rutenummer_list = [r['rutenummer'] for r in routes]
        placeholders = ','.join(['%s'] * len(rutenummer_list))

        endpoint_query = f"""
            WITH route_links_expanded AS (
                SELECT
                    UNNEST(lwr.rutenummer_list) as rutenummer,
                    lwr.link_id,
                    lwr.a_node,
                    lwr.b_node
                FROM {ROUTE_SCHEMA}.links_with_routes lwr
                WHERE lwr.rutenummer_list && ARRAY[{placeholders}]
            ),
            first_last_links AS (
                SELECT
                    rutenummer,
                    (SELECT a_node FROM route_links_expanded rle2
                     WHERE rle2.rutenummer = rle.rutenummer
                     ORDER BY link_id ASC LIMIT 1) as first_a_node,
                    (SELECT b_node FROM route_links_expanded rle2
                     WHERE rle2.rutenummer = rle.rutenummer
                     ORDER BY link_id DESC LIMIT 1) as last_b_node
                FROM route_links_expanded rle
                GROUP BY rutenummer
            )
            SELECT
                fll.rutenummer,
                fll.first_a_node,
                fll.last_b_node,
                an_a.navn as from_name,
                an_b.navn as to_name
            FROM first_last_links fll
            LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_a ON an_a.node_id = fll.first_a_node
            LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_b ON an_b.node_id = fll.last_b_node
        """

        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(endpoint_query, rutenummer_list)
                endpoint_rows = cur.fetchall()

            # Map endpoint names to routes
            endpoint_map = {row['rutenummer']: row for row in endpoint_rows}
            anchor_ids = []
            for row in endpoint_rows:
                if row.get("first_a_node") is not None:
                    anchor_ids.append(int(row["first_a_node"]))
                if row.get("last_b_node") is not None:
                    anchor_ids.append(int(row["last_b_node"]))

            endpoint_overrides = {}
            if anchor_ids:
                with op_db_connection() as op_conn:
                    endpoint_overrides = get_endpoint_names_for_anchor_routes(
                        op_conn,
                        anchor_ids,
                        rutenummer_list,
                    )

            from .route_endpoints import format_utm_shortform
            for route in routes:
                endpoint_info = endpoint_map.get(route['rutenummer'])
                override_map = endpoint_overrides.get(route["rutenummer"], {}) if endpoint_overrides else {}
                if endpoint_info:
                    from_override = override_map.get(endpoint_info.get("first_a_node"))
                    to_override = override_map.get(endpoint_info.get("last_b_node"))
                    if from_override and from_override.get("name"):
                        route["from_name"] = from_override.get("name")
                    else:
                        route['from_name'] = format_utm_shortform(endpoint_info.get('from_name'))
                    if to_override and to_override.get("name"):
                        route["to_name"] = to_override.get("name")
                    else:
                        route['to_name'] = format_utm_shortform(endpoint_info.get('to_name'))
        except Exception as e:
            # Silently fail if query doesn't work (anchor_nodes might not exist)
            pass

    return routes, total_count


def get_route_segments_from_view(conn, rutenummer: str, include_geometry: bool = False):
    """
    Get route segments from stiflyt.route_segments view for a specific route.

    Args:
        conn: Database connection
        rutenummer: Route number
        include_geometry: If True, include GeoJSON geometry

    Returns:
        List of segment dicts
    """
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    uuid_col = get_segment_uuid_column(conn)
    select_parts = [
        "rs.rutenummer",
        "rs.segment_objid",
        "rs.source_node",
        "rs.target_node",
        "rs.rutenavn",
        "rs.vedlikeholdsansvarlig",
        "rs.rutetype",
        "rs.gradering",
        "ST_Length(ST_Transform(rs.senterlinje, 4326)::geography) as length_meters"
    ]

    if uuid_col:
        select_parts.append(f"f.{uuid_col}::text as object_uuid")

    if include_geometry:
        select_parts.append("ST_AsGeoJSON(ST_Transform(rs.senterlinje, 4326))::json as senterlinje")

    join_clause = f"LEFT JOIN {ROUTE_SCHEMA}.fotrute f ON f.objid = rs.segment_objid" if uuid_col else ""
    query = f"""
        SELECT
            {', '.join(select_parts)}
        FROM {ROUTE_SCHEMA}.route_segments rs
        {join_clause}
        WHERE rutenummer = %s
        ORDER BY segment_objid
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (rutenummer,))
        rows = cur.fetchall()

    segments = []
    if uuid_col:
        for row in rows:
            if not row.get("object_uuid"):
                raise ValueError(f"Missing object_uuid for segment objid {row.get('segment_objid')}")
    for row in rows:
        segment = {
            'rutenummer': row['rutenummer'],
            'segment_objid': int(row['segment_objid']),
            'object_uuid': row.get('object_uuid'),
            'source_node': row.get('source_node'),
            'target_node': row.get('target_node'),
            'rutenavn': row.get('rutenavn'),
            'vedlikeholdsansvarlig': row.get('vedlikeholdsansvarlig'),
            'rutetype': row.get('rutetype'),
            'gradering': row.get('gradering'),
            'length_meters': float(row['length_meters']) if row.get('length_meters') is not None else None
        }

        if include_geometry and row.get('senterlinje'):
            segment['senterlinje'] = parse_geometry(row['senterlinje'])

        segments.append(segment)

    return segments


def get_route_links(conn, rutenummer: str, include_geometry: bool = False):
    """
    Get routing links for a specific route from stiflyt.links_with_routes table.

    Uses links_with_routes table which is already aggregated and won't have duplicates.

    Links represent routing topology (segments between junctions) and may
    combine multiple segments. Useful for navigation/routing purposes.

    Args:
        conn: Database connection
        rutenummer: Route number
        include_geometry: If True, include GeoJSON geometry

    Returns:
        List of link dicts
    """
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    # Check if navn column exists in anchor_nodes
    schema_quoted = quote_identifier(ROUTE_SCHEMA)
    has_navn_column = False
    with conn.cursor() as check_cur:
        check_cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'anchor_nodes'
                  AND column_name = 'navn'
            )
        """, (ROUTE_SCHEMA,))
        has_navn_column = check_cur.fetchone()[0]

    select_parts = [
        "l.link_id",
        "l.a_node",
        "l.b_node",
        "l.length_m",
        "l.segment_objids",
        "l.rutenummer_list",
    ]

    # Only include navn columns if they exist
    if has_navn_column:
        select_parts.extend([
            "an_a.navn as a_node_name",
            "an_b.navn as b_node_name"
        ])
    else:
        select_parts.extend([
            "NULL as a_node_name",
            "NULL as b_node_name"
        ])

    if include_geometry:
        select_parts.append("ST_AsGeoJSON(ST_Transform(l.geom, 4326))::json as geom")

    # Use links_with_routes with JOIN to anchor_nodes for node names (if column exists)
    join_clause = ""
    if has_navn_column:
        join_clause = f"""
        LEFT JOIN {schema_quoted}.anchor_nodes an_a ON an_a.node_id = l.a_node
        LEFT JOIN {schema_quoted}.anchor_nodes an_b ON an_b.node_id = l.b_node
        """
    
    query = f"""
        SELECT
            {', '.join(select_parts)}
        FROM {schema_quoted}.links_with_routes l
        {join_clause}
        WHERE %s = ANY(l.rutenummer_list)
        ORDER BY l.link_id
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (rutenummer,))
        rows = cur.fetchall()

    anchor_ids = []
    for row in rows:
        if row.get("a_node") is not None:
            anchor_ids.append(int(row["a_node"]))
        if row.get("b_node") is not None:
            anchor_ids.append(int(row["b_node"]))

    endpoint_overrides = {}
    if anchor_ids:
        with op_db_connection() as op_conn:
            endpoint_overrides = get_endpoint_names_for_anchors(
                op_conn,
                anchor_ids,
                rutenummer=rutenummer,
            )

    links = []
    for row in rows:
        from .route_endpoints import format_utm_shortform
        a_override = endpoint_overrides.get(row.get("a_node")) if endpoint_overrides else None
        b_override = endpoint_overrides.get(row.get("b_node")) if endpoint_overrides else None
        link = {
            'link_id': int(row['link_id']),
            'a_node': row.get('a_node'),
            'b_node': row.get('b_node'),
            'a_node_name': a_override.get("name") if a_override else format_utm_shortform(row.get('a_node_name')),
            'b_node_name': b_override.get("name") if b_override else format_utm_shortform(row.get('b_node_name')),
            'length_m': float(row['length_m']) if row.get('length_m') is not None else None,
            'segment_objids': row.get('segment_objids')
        }

        if include_geometry and row.get('geom'):
            link['geom'] = parse_geometry(row['geom'])

        links.append(link)

    return links

