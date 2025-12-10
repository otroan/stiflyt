"""Route service for processing routes and matrikkelenhet."""
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from .database import get_db_connection, db_connection, ROUTE_SCHEMA, TEIG_SCHEMA, validate_schema_name


class RouteNotFoundError(Exception):
    """Exception raised when a route is not found."""
    pass


class RouteDataError(Exception):
    """Exception raised when route data cannot be processed."""
    pass


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

    query = f"""
        SELECT
            f.objid,
            f.senterlinje,
            fi.rutenummer,
            fi.rutenavn,
            fi.vedlikeholdsansvarlig
        FROM {ROUTE_SCHEMA}.fotrute f
        JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE fi.rutenummer = %s
        ORDER BY f.objid;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (rutenummer,))
        return cur.fetchall()


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

    if include_geojson:
        query = f"""
            SELECT
                f.objid,
                f.senterlinje,
                ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters,
                ST_AsGeoJSON(ST_Transform(f.senterlinje::geometry, 4326)) as geometry_geojson
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
            FROM {ROUTE_SCHEMA}.fotrute f
            JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
            WHERE fi.rutenummer = %s
            ORDER BY f.objid;
        """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (rutenummer,))
        return cur.fetchall()


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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (rutenummer,))
        return cur.fetchall()


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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
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

    All schema names are validated constants. Route geometry is parameterized.
    """
    # Validate schema names (should always be valid, but check for safety)
    if not validate_schema_name(TEIG_SCHEMA):
        raise ValueError(f"Invalid TEIG_SCHEMA: {TEIG_SCHEMA}")

    query = f"""
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
            ST_Intersection(t.omrade::geometry, %s::geometry) as intersection_geom,
            ST_Length(ST_Transform(ST_Intersection(t.omrade::geometry, %s::geometry), 4326)::geography) as length_meters
        FROM {TEIG_SCHEMA}.teig t
        LEFT JOIN {TEIG_SCHEMA}.matrikkelenhet m ON m.teig_fk = t.teigid
        WHERE ST_Intersects(t.omrade::geometry, %s::geometry)
        AND ST_GeometryType(ST_Intersection(t.omrade::geometry, %s::geometry)) IN ('ST_LineString', 'ST_MultiLineString');
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (route_geom, route_geom, route_geom, route_geom))
        return cur.fetchall()


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


def search_routes(rutenummer_prefix=None, rutenavn_search=None, organization=None, limit=100):
    """
    Search for routes by various criteria.

    All user inputs are parameterized to prevent SQL injection.
    Schema names are validated constants.
    """
    # Validate limit to prevent injection via integer overflow
    if not isinstance(limit, int) or limit < 1 or limit > 10000:
        raise ValueError(f"Invalid limit: {limit}. Must be between 1 and 10000.")

    # Validate schema name (should always be valid, but check for safety)
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    with db_connection() as conn:
        # Schema name is a validated constant, safe to use in f-string
        query = f"""
            SELECT DISTINCT
                fi.rutenummer,
                fi.rutenavn,
                fi.vedlikeholdsansvarlig,
                COUNT(DISTINCT f.objid) as segment_count
            FROM {ROUTE_SCHEMA}.fotruteinfo fi
            JOIN {ROUTE_SCHEMA}.fotrute f ON f.objid = fi.fotrute_fk
            WHERE 1=1
        """

        params = []

        # All user inputs are parameterized (safe from SQL injection)
        if rutenummer_prefix:
            query += " AND fi.rutenummer ILIKE %s"
            params.append(f"{rutenummer_prefix}%")

        if rutenavn_search:
            query += " AND fi.rutenavn ILIKE %s"
            params.append(f"%{rutenavn_search}%")

        if organization:
            query += " AND fi.vedlikeholdsansvarlig ILIKE %s"
            params.append(f"%{organization}%")

        query += " GROUP BY fi.rutenummer, fi.rutenavn, fi.vedlikeholdsansvarlig"
        query += " ORDER BY fi.rutenummer"
        # LIMIT value is parameterized (safe)
        query += " LIMIT %s"
        params.append(limit)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            results = cur.fetchall()

            # Additional deduplication by rutenummer as a safety measure
            # This ensures no duplicates even if GROUP BY doesn't catch everything
            seen_rutenummer = set()
            unique_results = []
            for row in results:
                rutenummer = row['rutenummer']
                if rutenummer not in seen_rutenummer:
                    seen_rutenummer.add(rutenummer)
                    unique_results.append(row)

            return unique_results


def get_route_list(limit=1000):
    """Get list of all routes with basic metadata."""
    return search_routes(limit=limit)


def get_routes_in_bbox(min_lat, min_lng, max_lat, max_lng, rutenummer_prefix=None, organization=None, limit=100, zoom_level=None):
    """
    Get routes that intersect with a bounding box.

    Args:
        min_lat: Minimum latitude (south)
        min_lng: Minimum longitude (west)
        max_lat: Maximum latitude (north)
        max_lng: Maximum longitude (east)
        rutenummer_prefix: Optional filter for route prefix (e.g., 'bre')
        organization: Optional filter for organization (e.g., 'DNT')
        limit: Maximum number of results (default: 1000, max: 1000)
        zoom_level: Optional map zoom level for adaptive simplification (higher = more detail)

    Returns:
        List of route dicts with: rutenummer, rutenavn, vedlikeholdsansvarlig, geometry (GeoJSON), segment_count

    Raises:
        ValueError: If bounding box is invalid or limit is out of range
    """
    # Validate bounding box
    if not all(isinstance(coord, (int, float)) for coord in [min_lat, min_lng, max_lat, max_lng]):
        raise ValueError("All bounding box coordinates must be numbers")

    if min_lat >= max_lat:
        raise ValueError(f"min_lat ({min_lat}) must be less than max_lat ({max_lat})")

    if min_lng >= max_lng:
        raise ValueError(f"min_lng ({min_lng}) must be less than max_lng ({max_lng})")

    # Validate latitude range
    if not (-90 <= min_lat <= 90) or not (-90 <= max_lat <= 90):
        raise ValueError("Latitude must be between -90 and 90")

    # Validate longitude range
    if not (-180 <= min_lng <= 180) or not (-180 <= max_lng <= 180):
        raise ValueError("Longitude must be between -180 and 180")

    # Validate limit
    if not isinstance(limit, int) or limit < 1 or limit > 1000:
        raise ValueError(f"Invalid limit: {limit}. Must be between 1 and 1000.")

    # Validate schema name
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    # Adaptive simplification based on zoom level
    # Higher zoom = less simplification (more detail)
    # Lower zoom = more simplification (faster loading, smaller data)
    use_simplification = True
    if zoom_level is not None:
        # Zoom levels: 0-7 (country/region) = high simplification
        #              8-11 (city/area) = medium simplification
        #              12-13 (street level) = low simplification
        #              14+ (very high zoom) = no simplification (full detail)
        if zoom_level >= 14:
            use_simplification = False  # No simplification - show every detail
        elif zoom_level >= 12:
            simplify_tolerance = 0.0001  # Very detailed for street level
        elif zoom_level >= 8:
            simplify_tolerance = 0.0003  # Medium detail for city level
        else:
            simplify_tolerance = 0.0005  # High simplification for overview
    else:
        # Default to medium simplification if zoom not provided
        simplify_tolerance = 0.0003

    with db_connection() as conn:
        # Create bounding box geometry in WGS84 (4326)
        # ST_MakeEnvelope(xmin, ymin, xmax, ymax, srid)
        # Build geometry expression with or without simplification
        if use_simplification:
            geometry_expr = f"""
                ST_AsGeoJSON(
                    ST_Simplify(
                        ST_Transform(
                            ST_Collect(f.senterlinje::geometry),
                            4326
                        ),
                        %s
                    )
                ) as geometry
            """
        else:
            # No simplification - show every detail
            geometry_expr = """
                ST_AsGeoJSON(
                    ST_Transform(
                        ST_Collect(f.senterlinje::geometry),
                        4326
                    )
                ) as geometry
            """

        query = f"""
            SELECT DISTINCT
                fi.rutenummer,
                fi.rutenavn,
                fi.vedlikeholdsansvarlig,
                {geometry_expr},
                COUNT(DISTINCT f.objid) as segment_count
            FROM {ROUTE_SCHEMA}.fotrute f
            JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
            WHERE ST_Intersects(
                f.senterlinje::geometry,
                ST_Transform(
                    ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                    25833
                )
            )
        """

        # Build params list - only include simplify_tolerance if using simplification
        if use_simplification:
            params = [simplify_tolerance, min_lng, min_lat, max_lng, max_lat]
        else:
            params = [min_lng, min_lat, max_lng, max_lat]

        # Add optional filters (all parameterized for safety)
        if rutenummer_prefix:
            query += " AND fi.rutenummer ILIKE %s"
            params.append(f"{rutenummer_prefix}%")

        if organization:
            query += " AND fi.vedlikeholdsansvarlig ILIKE %s"
            params.append(f"%{organization}%")

        query += " GROUP BY fi.rutenummer, fi.rutenavn, fi.vedlikeholdsansvarlig"
        query += " ORDER BY fi.rutenummer"
        query += " LIMIT %s"
        params.append(limit)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            results = cur.fetchall()

            # Parse GeoJSON strings to dicts
            route_items = []
            seen_rutenummer = set()

            for row in results:
                rutenummer = row['rutenummer']
                if rutenummer in seen_rutenummer:
                    continue
                seen_rutenummer.add(rutenummer)

                # Parse geometry GeoJSON string
                geometry = None
                if row['geometry']:
                    try:
                        geometry = json.loads(row['geometry'])
                    except (json.JSONDecodeError, TypeError):
                        # Skip routes with invalid geometry
                        continue

                route_items.append({
                    'rutenummer': rutenummer,
                    'rutenavn': row['rutenavn'],
                    'vedlikeholdsansvarlig': row.get('vedlikeholdsansvarlig'),
                    'geometry': geometry,
                    'segment_count': row['segment_count']
                })

            return route_items


def get_route_data(rutenummer, use_corrected_geometry=True):
    """
    Get complete route data including geometry, metadata, and matrikkelenhet vector.

    Args:
        rutenummer: Route identifier
        use_corrected_geometry: If True, use corrected geographic order instead of database order.
                                If segments cannot be connected, they are shown as separate components.

    Returns:
        dict: Route data with geometry, metadata, and matrikkelenhet vector

    Raises:
        RouteNotFoundError: If the route is not found or has no segments
        RouteDataError: If route data cannot be processed (e.g., geometry issues)
    """
    with db_connection() as conn:
        if use_corrected_geometry:
            # Use corrected geographic geometry
            from .route_geometry import get_corrected_route_geometry

            corrected = get_corrected_route_geometry(conn, rutenummer)
            if not corrected:
                raise RouteNotFoundError(f"Route '{rutenummer}' not found or has no valid geometry")

            # Use corrected geometry
            route_geom_geojson = corrected['geometry']
            total_length = corrected['total_length_meters']
            total_length_km = total_length / 1000.0

            # Convert GeoJSON back to PostGIS geometry for matrikkelenhet calculations
            # We need to work with the combined geometry and set SRID to 4326 (WGS84) then transform to 25833
            geom_wkt_query = """
                SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s)::geometry, 4326), 25833) as geom;
            """
            with conn.cursor() as cur:
                cur.execute(geom_wkt_query, (json.dumps(route_geom_geojson),))
                result = cur.fetchone()
                if not result or not result[0]:
                    raise RouteDataError(f"Failed to convert geometry for route '{rutenummer}'")
                route_geom = result[0]

            # Get metadata from first segment
            segments = get_route_segments(conn, rutenummer)
            if not segments:
                raise RouteNotFoundError(f"Route '{rutenummer}' has no segments")

            metadata = {
                'rutenummer': segments[0]['rutenummer'],
                'rutenavn': segments[0]['rutenavn'],
                'vedlikeholdsansvarlig': segments[0]['vedlikeholdsansvarlig'],
                'total_length_meters': total_length,
                'total_length_km': total_length_km,
                'segment_count': len(segments),
                'is_connected': corrected.get('is_connected', True),
                'component_count': corrected.get('component_count', 1)
            }

            # Find matrikkelenhet intersections using corrected geometry
            intersections = find_matrikkelenhet_intersections(conn, route_geom)

            # Calculate offsets and create matrikkelenhet vector
            matrikkelenhet_vector = calculate_offsets(conn, route_geom, intersections, total_length)

            return {
                'geometry': route_geom_geojson,
                'metadata': metadata,
                'matrikkelenhet_vector': matrikkelenhet_vector,
                'components': corrected.get('components', []),
                'report': corrected.get('report')
            }
        else:
            # Original implementation using database order
            segments = get_route_segments(conn, rutenummer)
            if not segments:
                raise RouteNotFoundError(f"Route '{rutenummer}' not found or has no segments")

            # Combine geometry
            route_geom = combine_route_geometry(conn, segments)
            if not route_geom:
                raise RouteDataError(f"Failed to combine geometry for route '{rutenummer}'")

            # Get route length
            total_length = get_route_length(conn, route_geom)
            total_length_km = total_length / 1000.0

            # Convert geometry to GeoJSON
            geometry_geojson = geometry_to_geojson(conn, route_geom)
            if not geometry_geojson:
                raise RouteDataError(f"Failed to convert geometry to GeoJSON for route '{rutenummer}'")

            # Get metadata
            metadata = {
                'rutenummer': segments[0]['rutenummer'],
                'rutenavn': segments[0]['rutenavn'],
                'vedlikeholdsansvarlig': segments[0]['vedlikeholdsansvarlig'],
                'total_length_meters': total_length,
                'total_length_km': total_length_km,
                'segment_count': len(segments)
            }

            # Find matrikkelenhet intersections
            intersections = find_matrikkelenhet_intersections(conn, route_geom)

            # Calculate offsets and create matrikkelenhet vector
            matrikkelenhet_vector = calculate_offsets(conn, route_geom, intersections, total_length)

            return {
                'geometry': geometry_geojson,
                'metadata': metadata,
                'matrikkelenhet_vector': matrikkelenhet_vector
            }


def get_route_segments_data(rutenummer):
    """
    Get individual segments for a route with geometry and length.
    Uses shared segment fetching function.

    Args:
        rutenummer: Route identifier

    Returns:
        dict: Route segments data with rutenummer, rutenavn, and segments list

    Raises:
        RouteNotFoundError: If the route is not found or has no segments
    """
    with db_connection() as conn:
        # Get route segments with geometry (using shared function)
        segments = get_route_segments_with_geometry(conn, rutenummer, include_geojson=True)

        if not segments:
            raise RouteNotFoundError(f"Route '{rutenummer}' not found or has no segments")

        # Get route metadata (rutenummer, rutenavn) from first segment
        # We need to fetch this separately since get_route_segments_with_geometry doesn't include it
        basic_segments = get_route_segments(conn, rutenummer)
        if not basic_segments:
            raise RouteNotFoundError(f"Route '{rutenummer}' not found or has no segments")

        # Convert each segment geometry to GeoJSON
        segments_data = []
        for seg in segments:
            geom_json = parse_geojson_string(seg.get('geometry_geojson'))
            if geom_json:
                # Handle potential None or zero length_meters
                length_meters = seg.get('length_meters') or 0.0
                length_km = length_meters / 1000.0 if length_meters else 0.0

                segments_data.append({
                    'objid': seg['objid'],
                    'geometry': geom_json,
                    'length_meters': length_meters,
                    'length_km': length_km
                })

        return {
            'rutenummer': basic_segments[0]['rutenummer'],
            'rutenavn': basic_segments[0]['rutenavn'],
            'segments': segments_data,
            'total_segments': len(segments_data)
        }

