"""
Shared module for finding connections between route segments.
"""
import json
from psycopg2.extras import RealDictCursor
from .database import ROUTE_SCHEMA, validate_schema_name
from .route_service import parse_geojson_string


def _build_connection_query(connection_type, placeholders, route_schema):
    """
    Build SQL query for finding connections between route segments.

    Args:
        connection_type: One of 'end_to_start', 'end_to_end', 'start_to_start', 'start_to_end'
        placeholders: SQL placeholder string (e.g., '%s,%s,%s')
        route_schema: Schema name for the route table

    Returns:
        SQL query string
    """
    # Validate schema name to prevent SQL injection
    if not validate_schema_name(route_schema):
        raise ValueError(f"Invalid schema name: {route_schema}")

    # Map connection types to PostGIS point extraction functions
    point_mapping = {
        'end_to_start': ('ST_EndPoint', 'ST_StartPoint'),
        'end_to_end': ('ST_EndPoint', 'ST_EndPoint'),
        'start_to_start': ('ST_StartPoint', 'ST_StartPoint'),
        'start_to_end': ('ST_StartPoint', 'ST_EndPoint'),
    }

    if connection_type not in point_mapping:
        raise ValueError(f"Invalid connection_type: {connection_type}")

    point1_func, point2_func = point_mapping[connection_type]

    # Validate SQL function names (should be safe as they're from controlled mapping)
    valid_functions = {'ST_EndPoint', 'ST_StartPoint'}
    if point1_func not in valid_functions or point2_func not in valid_functions:
        raise ValueError(f"Invalid point function: {point1_func} or {point2_func}")

    query = f"""
        SELECT
            f1.objid as seg1_objid,
            f2.objid as seg2_objid,
            ST_Distance(
                ST_Transform({point1_func}(f1.senterlinje::geometry), 25833),
                ST_Transform({point2_func}(f2.senterlinje::geometry), 25833)
            ) as distance
        FROM {route_schema}.fotrute f1
        CROSS JOIN {route_schema}.fotrute f2
        WHERE f1.objid IN ({placeholders})
          AND f2.objid IN ({placeholders})
          AND f1.objid != f2.objid
          AND ST_Distance(
                ST_Transform({point1_func}(f1.senterlinje::geometry), 25833),
                ST_Transform({point2_func}(f2.senterlinje::geometry), 25833)
              ) <= 1.0
    """
    return query


def find_segment_connections(conn, segment_objids, route_schema=ROUTE_SCHEMA):
    """
    Find all connections between route segments using efficient SQL queries.

    Args:
        conn: Database connection
        segment_objids: List of segment objids to find connections for
        route_schema: Schema name for the route table (default: ROUTE_SCHEMA)

    Returns:
        dict: Mapping from segment_objid -> list of connection dicts
              Each connection dict contains:
              - 'target': connected segment objid
              - 'type': connection type ('end_to_start', 'end_to_end', etc.)
              - 'distance': distance in meters
    """
    if not segment_objids:
        return {}

    # Validate schema name
    if not validate_schema_name(route_schema):
        raise ValueError(f"Invalid schema name: {route_schema}")

    # Validate segment_objids are integers (prevent injection)
    validated_objids = []
    for objid in segment_objids:
        try:
            # Convert to int and validate it's positive
            objid_int = int(objid)
            if objid_int > 0:
                validated_objids.append(objid_int)
            else:
                raise ValueError(f"Invalid segment objid: {objid} (must be positive)")
        except (ValueError, TypeError):
            raise ValueError(f"Invalid segment objid: {objid} (must be an integer)")

    if not validated_objids:
        return {}

    # Initialize connections dict
    connections = {}
    for objid in validated_objids:
        connections[objid] = []

    # Build placeholders for SQL IN clause (all values are parameterized)
    placeholders = ','.join(['%s'] * len(validated_objids))

    # Check all possible connection types
    connection_types = ['end_to_start', 'end_to_end', 'start_to_start', 'start_to_end']

    for conn_type in connection_types:
        query = _build_connection_query(conn_type, placeholders, route_schema)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Use validated_objids (all values are parameterized, safe from injection)
            cur.execute(query, validated_objids + validated_objids)
            results = cur.fetchall()

            for result in results:
                seg1_objid = result['seg1_objid']
                seg2_objid = result['seg2_objid']
                distance = float(result['distance'])

                connections[seg1_objid].append({
                    'target': seg2_objid,
                    'type': conn_type,
                    'distance': distance
                })

    return connections


def find_sequential_connections(conn, segments, include_geo_json=False):
    """
    Find sequential connections between adjacent segments in the provided order.
    Useful for debugging to check if database order matches geographic order.

    Args:
        conn: Database connection
        segments: List of segment dicts with 'objid' and 'senterlinje' keys
        include_geo_json: If True, include GeoJSON points in result (slower)

    Returns:
        list: List of connection info dicts with:
              - 'segment1_objid': First segment objid
              - 'segment2_objid': Second segment objid
              - 'distance_meters': Distance between segments
              - 'connection_type': 'sequential'
              - 'is_connected': True if distance <= 1.0
              - 'end_point', 'start_point': GeoJSON points (if include_geo_json=True)
    """
    import json
    connection_info = []

    if len(segments) < 2:
        return connection_info

    # Check sequential connections (adjacent segments in order)
    for i in range(len(segments) - 1):
        seg1 = segments[i]
        seg2 = segments[i + 1]

        if include_geo_json:
            # Get GeoJSON points for visualization
            distance_query = """
                SELECT
                    ST_Distance(%s::geometry, %s::geometry) as distance,
                    ST_AsGeoJSON(ST_Transform(%s::geometry, 4326)) as end_point_geojson,
                    ST_AsGeoJSON(ST_Transform(%s::geometry, 4326)) as start_point_geojson;
            """
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(distance_query, (
                    seg1['end_point'], seg2['start_point'],
                    seg1['end_point'], seg2['start_point']
                ))
                result = cur.fetchone()
                distance = result['distance']
                end_point_geojson = result['end_point_geojson']
                start_point_geojson = result['start_point_geojson']

            connection_info.append({
                'segment1_objid': seg1['objid'],
                'segment2_objid': seg2['objid'],
                'distance_meters': float(distance),
                'end_point': parse_geojson_string(end_point_geojson),
                'start_point': parse_geojson_string(start_point_geojson),
                'connection_type': 'sequential',
                'is_connected': distance <= 1.0
            })
        else:
            # Faster version without GeoJSON
            distance_query = "SELECT ST_Distance(%s::geometry, %s::geometry) as distance;"
            with conn.cursor() as cur:
                cur.execute(distance_query, (seg1['end_point'], seg2['start_point']))
                distance = cur.fetchone()[0]

            connection_info.append({
                'segment1_objid': seg1['objid'],
                'segment2_objid': seg2['objid'],
                'distance_meters': float(distance),
                'connection_type': 'sequential',
                'is_connected': distance <= 1.0
            })

    return connection_info
