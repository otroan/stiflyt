"""Route service for processing routes and matrikkelenhet."""
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from .database import get_db_connection, ROUTE_SCHEMA, TEIG_SCHEMA


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
    """Get all segments for a route."""
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


def combine_route_geometry(conn, segments):
    """Combine route segments into a single linestring."""
    if not segments:
        return None

    # Collect all geometries
    query = f"""
        SELECT ST_LineMerge(ST_Collect(senterlinje::geometry))::geometry as combined_geom
        FROM {ROUTE_SCHEMA}.fotrute
        WHERE objid = ANY(%s);
    """

    segment_ids = [seg['objid'] for seg in segments]

    with conn.cursor() as cur:
        cur.execute(query, (segment_ids,))
        result = cur.fetchone()
        return result[0] if result else None


def get_route_length(conn, route_geom):
    """Get route length in meters.

    Uses geography (spherical) calculation for accurate distance measurements.
    Handles both LineString and MultiLineString geometries.
    For MultiLineString, sums the length of all constituent lines.
    """
    # Check geometry type and calculate length accordingly
    check_type_query = """
        SELECT ST_GeometryType(%s::geometry) as geom_type;
    """

    with conn.cursor() as cur:
        cur.execute(check_type_query, (route_geom,))
        geom_type = cur.fetchone()[0]

        if geom_type == 'ST_MultiLineString':
            # For MultiLineString, use loop instead of generate_series in SUM (PostgreSQL doesn't allow set-returning functions in aggregates)
            # First get number of geometries
            num_query = "SELECT ST_NumGeometries(%s::geometry) as num;"
            cur.execute(num_query, (route_geom,))
            num_geoms = cur.fetchone()[0]

            # Sum lengths using loop
            total_length = 0.0
            for i in range(1, num_geoms + 1):
                length_query = "SELECT ST_Length(ST_Transform(ST_GeometryN(%s::geometry, %s), 4326)::geography) as length;"
                cur.execute(length_query, (route_geom, i))
                length = cur.fetchone()[0]
                if length:
                    total_length += length

            return total_length
        else:
            # For LineString, use geography for accurate spherical distance calculation
            # Transform to WGS84 (4326) first, then cast to geography
            length_query = """
                SELECT ST_Length(ST_Transform(%s::geometry, 4326)::geography) as length_meters;
            """
            cur.execute(length_query, (route_geom,))

        result = cur.fetchone()
        return result[0] if result else 0.0


def geometry_to_geojson(conn, geom):
    """Convert PostGIS geometry to GeoJSON."""
    query = """
        SELECT ST_AsGeoJSON(ST_Transform(%s::geometry, 4326)) as geojson;
    """

    with conn.cursor() as cur:
        cur.execute(query, (geom,))
        result = cur.fetchone()
        if result and result[0]:
            import json
            return json.loads(result[0])
        return None


def find_matrikkelenhet_intersections(conn, route_geom):
    """Find all intersections between route and teig polygons."""
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
    """Calculate offset from start for each intersection."""
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
        merge_query = """
            SELECT ST_LineMerge(%s::geometry)::geometry as merged_geom,
                   ST_GeometryType(ST_LineMerge(%s::geometry)::geometry) as merged_type;
        """
        with conn.cursor() as cur:
            cur.execute(merge_query, (route_geom, route_geom))
            merge_result = cur.fetchone()
            if merge_result and merge_result[1] == 'ST_LineString':
                route_geom = merge_result[0]  # Use merged LineString
            else:
                # If merge failed, use first line of MultiLineString
                first_line_query = "SELECT ST_GeometryN(%s::geometry, 1)::geometry as first_line;"
                cur.execute(first_line_query, (route_geom,))
                first_line_result = cur.fetchone()
                if first_line_result:
                    route_geom = first_line_result[0]

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

        results.append({
            'matrikkelenhet': formatted_matrikkel or intersection['matrikkelnummertekst'],
            'bruksnavn': intersection.get('bruksnavn'),
            'kommunenummer': intersection['kommunenummer'],
            'kommunenavn': intersection['kommunenavn'],
            'offset_meters': offset_meters,
            'offset_km': offset_km,
            'length_meters': intersection['length_meters'],
            'length_km': intersection['length_meters'] / 1000.0,
            'geometry': intersection_geojson
        })

    # Sort by offset
    results.sort(key=lambda x: x['offset_meters'])
    return results


def search_routes(rutenummer_prefix=None, rutenavn_search=None, organization=None, limit=100):
    """Search for routes by various criteria."""
    conn = get_db_connection()

    try:
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
        query += f" LIMIT %s"
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

    finally:
        conn.close()


def get_route_list(limit=1000):
    """Get list of all routes with basic metadata."""
    return search_routes(limit=limit)


def get_route_data(rutenummer, use_corrected_geometry=True):
    """
    Get complete route data including geometry, metadata, and matrikkelenhet vector.

    Args:
        use_corrected_geometry: If True, use corrected geographic order instead of database order.
                                If segments cannot be connected, they are shown as separate components.
    """
    conn = get_db_connection()

    try:
        if use_corrected_geometry:
            # Use corrected geographic geometry
            from .route_geometry import get_corrected_route_geometry

            corrected = get_corrected_route_geometry(conn, rutenummer)
            if not corrected:
                return None

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
                route_geom = cur.fetchone()[0]

            # Get metadata from first segment
            segments = get_route_segments(conn, rutenummer)
            if not segments:
                return None

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
                return None

            # Combine geometry
            route_geom = combine_route_geometry(conn, segments)
            if not route_geom:
                return None

            # Get route length
            total_length = get_route_length(conn, route_geom)
            total_length_km = total_length / 1000.0

            # Convert geometry to GeoJSON
            geometry_geojson = geometry_to_geojson(conn, route_geom)

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

    finally:
        conn.close()


def get_route_segments_data(rutenummer):
    """Get individual segments for a route with geometry and length."""
    conn = get_db_connection()

    try:
        # Get route segments with geometry and length
        # Use geography for accurate distance calculation (not Web Mercator which distorts at high latitudes)
        query = f"""
            SELECT
                f.objid,
                f.senterlinje,
                fi.rutenummer,
                fi.rutenavn,
                ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
            FROM {ROUTE_SCHEMA}.fotrute f
            JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
            WHERE fi.rutenummer = %s
            ORDER BY f.objid;
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (rutenummer,))
            segments = cur.fetchall()

        if not segments:
            return None

        # Convert each segment geometry to GeoJSON
        segments_data = []
        for seg in segments:
            geom_geojson = geometry_to_geojson(conn, seg['senterlinje'])
            if geom_geojson:
                segments_data.append({
                    'objid': seg['objid'],
                    'geometry': geom_geojson,
                    'length_meters': seg['length_meters'],
                    'length_km': seg['length_meters'] / 1000.0
                })

        return {
            'rutenummer': segments[0]['rutenummer'],
            'rutenavn': segments[0]['rutenavn'],
            'segments': segments_data,
            'total_segments': len(segments_data)
        }

    finally:
        conn.close()

