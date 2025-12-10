"""Debugging utilities for route data quality issues."""
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from .database import get_db_connection, db_connection, ROUTE_SCHEMA
from .route_connections import find_segment_connections, find_sequential_connections
from .route_service import parse_geojson_string, get_route_segments_with_geometry


def analyze_route_segments(conn, rutenummer):
    """Analyze segments for a route and identify problems."""
    issues = []
    segments_info = []

    query = f"""
        SELECT
            f.objid,
            f.senterlinje,
            ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters,
            ST_StartPoint(f.senterlinje::geometry) as start_point,
            ST_EndPoint(f.senterlinje::geometry) as end_point,
            ST_NumPoints(f.senterlinje::geometry) as num_points
        FROM {ROUTE_SCHEMA}.fotrute f
        JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE fi.rutenummer = %s
        ORDER BY f.objid;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (rutenummer,))
        segments = cur.fetchall()

    if not segments:
        return {
            'segments': [],
            'issues': [{'type': 'NO_SEGMENTS', 'message': 'Ingen segmenter funnet'}],
            'connections': []
        }

    # Analyze each segment
    for i, seg in enumerate(segments):
        seg_info = {
            'objid': seg['objid'],
            'length_meters': float(seg['length_meters']) if seg['length_meters'] else 0,
            'num_points': seg['num_points'],
            'issues': []
        }

        # Check for zero length
        if seg['length_meters'] == 0:
            seg_info['issues'].append({
                'type': 'ZERO_LENGTH',
                'severity': 'WARNING',
                'message': 'Segment har lengde 0'
            })

        # Check for very few points
        if seg['num_points'] < 2:
            seg_info['issues'].append({
                'type': 'INSUFFICIENT_POINTS',
                'severity': 'ERROR',
                'message': f'Segment har kun {seg["num_points"]} punkt(er)'
            })

        segments_info.append(seg_info)

    # Check connections between segments
    # Use shared module to find connections
    connection_info = []

    # First: Check sequential order (use shared function)
    # We need segments with end_point for sequential check
    segments_with_points = []
    for seg in segments:
        # Get start and end points
        points_query = """
            SELECT
                ST_StartPoint(%s::geometry) as start_point,
                ST_EndPoint(%s::geometry) as end_point;
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(points_query, (seg['senterlinje'], seg['senterlinje']))
            points = cur.fetchone()
            seg_with_points = seg.copy()
            seg_with_points['start_point'] = points['start_point']
            seg_with_points['end_point'] = points['end_point']
            segments_with_points.append(seg_with_points)

    # Find sequential connections with GeoJSON (for visualization)
    sequential_connections = find_sequential_connections(conn, segments_with_points, include_geo_json=True)
    connection_info.extend(sequential_connections)

    # Then: Find actual connections between non-sequential segments
    # Use shared module for efficient SQL-based search
    segment_objids = [seg['objid'] for seg in segments]
    all_connections = find_segment_connections(conn, segment_objids, ROUTE_SCHEMA)

    # Convert to connection_info format and filter out sequential ones
    for seg1_objid, conn_list in all_connections.items():
        for conn in conn_list:
            seg2_objid = conn['target']
            conn_type = conn['type']
            distance = conn['distance']

            # Find indices to check if they are neighbors
            seg1_idx = next((i for i, s in enumerate(segments) if s['objid'] == seg1_objid), None)
            seg2_idx = next((i for i, s in enumerate(segments) if s['objid'] == seg2_objid), None)

            # Skip sequential connections (they are already added)
            if seg1_idx is not None and seg2_idx is not None and abs(seg1_idx - seg2_idx) == 1:
                continue

            # Get GeoJSON points for visualization (only if necessary)
            # For non-sequential connections, we can skip GeoJSON for performance
            # But if needed, we can fetch it here
            connection_info.append({
                'segment1_objid': seg1_objid,
                'segment2_objid': seg2_objid,
                'distance_meters': distance,
                'connection_type': conn_type,
                'is_connected': True
            })

    # Add issues for sequential connections that are not connected
    for conn in connection_info:
        if conn['connection_type'] == 'sequential' and not conn['is_connected']:
            # Find segment index to add issue
            for i, seg in enumerate(segments):
                if seg['objid'] == conn['segment1_objid']:
                    issues.append({
                        'type': 'DISCONNECTED_SEGMENTS_SEQUENTIAL',
                        'severity': 'INFO',  # INFO since order may be wrong
                        'message': f'Sekvensielle segmenter {conn["segment1_objid"]} og {conn["segment2_objid"]} er ikke koblet sammen',
                        'distance_meters': conn['distance_meters'],
                        'segment1_objid': conn['segment1_objid'],
                        'segment2_objid': conn['segment2_objid']
                    })

                    segments_info[i]['issues'].append({
                        'type': 'DISCONNECTED_TO_NEXT_SEQUENTIAL',
                        'severity': 'INFO',
                        'message': f'Sekvensiell rekkefølge: Ikke koblet til neste segment (avstand: {conn["distance_meters"]:.2f} m)',
                        'distance_meters': conn['distance_meters']
                    })
                    break

    # Check for overlap between segments
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            seg1 = segments[i]
            seg2 = segments[j]

            # Check if segments overlap
            overlap_query = """
                SELECT
                    ST_Length(ST_Transform(ST_Intersection(%s::geometry, %s::geometry), 4326)::geography) as overlap_length,
                    ST_Intersects(%s::geometry, %s::geometry) as intersects
                WHERE ST_Intersects(%s::geometry, %s::geometry);
            """

            try:
                with conn.cursor() as cur:
                    cur.execute(overlap_query, (seg1['senterlinje'], seg2['senterlinje'],
                                               seg1['senterlinje'], seg2['senterlinje'],
                                               seg1['senterlinje'], seg2['senterlinje']))
                    result = cur.fetchone()

                    if result and result[1]:  # intersects
                        overlap_length = result[0] if result[0] else 0
                        if overlap_length > 10:  # More than 10 meters overlap
                            issues.append({
                                'type': 'OVERLAPPING_SEGMENTS',
                                'severity': 'WARNING',
                                'message': f'Segmenter {seg1["objid"]} og {seg2["objid"]} overlapper',
                                'overlap_length_meters': float(overlap_length),
                                'segment1_objid': seg1['objid'],
                                'segment2_objid': seg2['objid']
                            })

                            segments_info[i]['issues'].append({
                                'type': 'OVERLAPS_WITH',
                                'severity': 'WARNING',
                                'message': f'Overlapper med segment {seg2["objid"]} ({overlap_length:.2f} m)',
                                'overlap_length_meters': float(overlap_length),
                                'other_segment_objid': seg2['objid']
                            })
            except Exception as e:
                # Ignore errors in overlap check
                pass

    return {
        'segments': segments_info,
        'issues': issues,
        'connections': connection_info  # Include connection information
    }


def get_route_debug_info(rutenummer):
    """Get complete debugging information for a route."""
    with db_connection() as conn:
        # Get segments with geometry (use shared function)
        segments = get_route_segments_with_geometry(conn, rutenummer, include_geojson=True)

        if not segments:
            return {
                'rutenummer': rutenummer,
                'segments': [],
                'analysis': {'segments': [], 'issues': []}
            }

        # Analyze segments
        analysis = analyze_route_segments(conn, rutenummer)

        # Convert geometries to GeoJSON
        segments_with_geom = []
        for seg in segments:
            geom_json = parse_geojson_string(seg['geometry_geojson'])

            # Find issues for this segment
            seg_issues = []
            for seg_info in analysis['segments']:
                if seg_info['objid'] == seg['objid']:
                    seg_issues = seg_info['issues']
                    break

            segments_with_geom.append({
                'objid': seg['objid'],
                'geometry': geom_json,
                'length_meters': float(seg['length_meters']) if seg['length_meters'] else 0,
                'length_km': float(seg['length_meters']) / 1000.0 if seg['length_meters'] else 0,
                'issues': seg_issues
            })

        return {
            'rutenummer': rutenummer,
            'segments': segments_with_geom,
            'analysis': analysis,
            'connections': analysis.get('connections', [])  # Include connection information
        }

