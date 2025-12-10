"""Debugging utilities for route data quality issues."""
import psycopg2
from psycopg2.extras import RealDictCursor
from .database import get_db_connection, ROUTE_SCHEMA


def analyze_route_segments(conn, rutenummer):
    """Analyserer segmenter for en rute og identifiserer problemer."""
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

    # Analyser hvert segment
    for i, seg in enumerate(segments):
        seg_info = {
            'objid': seg['objid'],
            'length_meters': float(seg['length_meters']) if seg['length_meters'] else 0,
            'num_points': seg['num_points'],
            'issues': []
        }

        # Sjekk for null-lengde
        if seg['length_meters'] == 0:
            seg_info['issues'].append({
                'type': 'ZERO_LENGTH',
                'severity': 'WARNING',
                'message': 'Segment har lengde 0'
            })

        # Sjekk for veldig få punkter
        if seg['num_points'] < 2:
            seg_info['issues'].append({
                'type': 'INSUFFICIENT_POINTS',
                'severity': 'ERROR',
                'message': f'Segment har kun {seg["num_points"]} punkt(er)'
            })

        segments_info.append(seg_info)

    # Sjekk koblinger mellom segmenter
    # Fokuser på faktiske koblinger og sekvensiell rekkefølge
    connection_info = []
    import json

    # Først: Sjekk sekvensiell rekkefølge og faktiske koblinger mellom naboer
    for i in range(len(segments) - 1):
        seg1 = segments[i]
        seg2 = segments[i + 1]

        # Sjekk normal kobling (end_to_start)
        distance_query = """
            SELECT
                ST_Distance(%s::geometry, %s::geometry) as distance,
                ST_AsGeoJSON(ST_Transform(%s::geometry, 4326)) as end_point_geojson,
                ST_AsGeoJSON(ST_Transform(%s::geometry, 4326)) as start_point_geojson;
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(distance_query, (seg1['end_point'], seg2['start_point'],
                                        seg1['end_point'], seg2['start_point']))
            result = cur.fetchone()
            distance = result['distance']
            end_point_geojson = result['end_point_geojson']
            start_point_geojson = result['start_point_geojson']

        connection_info.append({
            'segment1_objid': seg1['objid'],
            'segment2_objid': seg2['objid'],
            'distance_meters': float(distance),
            'end_point': json.loads(end_point_geojson) if end_point_geojson else None,
            'start_point': json.loads(start_point_geojson) if start_point_geojson else None,
            'connection_type': 'sequential',
            'is_connected': distance <= 1.0
        })

    # Deretter: Finn faktiske koblinger mellom ikke-sekvensielle segmenter
    # (kun hvis de faktisk er koblet sammen, dvs. distance <= 1.0)
    for i in range(len(segments)):
        seg1 = segments[i]

        # Hent start- og endepunkt for seg1
        seg1_points_query = """
            SELECT
                ST_StartPoint(%s::geometry) as start_point,
                ST_EndPoint(%s::geometry) as end_point,
                ST_AsGeoJSON(ST_Transform(ST_StartPoint(%s::geometry), 4326)) as start_point_geojson,
                ST_AsGeoJSON(ST_Transform(ST_EndPoint(%s::geometry), 4326)) as end_point_geojson;
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(seg1_points_query, (seg1['senterlinje'], seg1['senterlinje'],
                                           seg1['senterlinje'], seg1['senterlinje']))
            seg1_points = cur.fetchone()
            seg1_start = seg1_points['start_point']
            seg1_end = seg1_points['end_point']
            seg1_start_geojson = seg1_points['start_point_geojson']
            seg1_end_geojson = seg1_points['end_point_geojson']

        # Sjekk kun faktiske koblinger til andre segmenter (ikke naboer, de er allerede sjekket)
        for j in range(len(segments)):
            if i == j or abs(i - j) == 1:  # Skip seg selv og naboer
                continue

            seg2 = segments[j]

            # Hent start- og endepunkt for seg2
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(seg1_points_query, (seg2['senterlinje'], seg2['senterlinje'],
                                               seg2['senterlinje'], seg2['senterlinje']))
                seg2_points = cur.fetchone()
                seg2_start = seg2_points['start_point']
                seg2_end = seg2_points['end_point']
                seg2_start_geojson = seg2_points['start_point_geojson']
                seg2_end_geojson = seg2_points['end_point_geojson']

            # Sjekk alle mulige koblinger mellom seg1 og seg2
            distance_query = "SELECT ST_Distance(%s::geometry, %s::geometry) as distance;"

            connections_to_check = [
                (seg1_end, seg2_start, seg1_end_geojson, seg2_start_geojson, 'end_to_start'),
                (seg1_end, seg2_end, seg1_end_geojson, seg2_end_geojson, 'end_to_end'),
                (seg1_start, seg2_start, seg1_start_geojson, seg2_start_geojson, 'start_to_start'),
                (seg1_start, seg2_end, seg1_start_geojson, seg2_end_geojson, 'start_to_end'),
            ]

            for point1, point2, geojson1, geojson2, connection_type in connections_to_check:
                with conn.cursor() as cur:
                    cur.execute(distance_query, (point1, point2))
                    distance = cur.fetchone()[0]

                # Kun lagre faktiske koblinger (distance <= 1.0)
                if distance <= 1.0:
                    # Sjekk om denne koblingen allerede finnes
                    exists = any(c['segment1_objid'] == seg1['objid'] and
                                c['segment2_objid'] == seg2['objid'] and
                                c.get('connection_type') == connection_type
                                for c in connection_info)
                    if not exists:
                        connection_info.append({
                            'segment1_objid': seg1['objid'],
                            'segment2_objid': seg2['objid'],
                            'distance_meters': float(distance),
                            'point1': json.loads(geojson1) if geojson1 else None,
                            'point2': json.loads(geojson2) if geojson2 else None,
                            'connection_type': connection_type,
                            'is_connected': True
                        })

    # Legg til issues for sekvensielle koblinger som ikke er koblet
    for conn in connection_info:
        if conn['connection_type'] == 'sequential' and not conn['is_connected']:
            # Finn segment-indeks for å legge til issue
            for i, seg in enumerate(segments):
                if seg['objid'] == conn['segment1_objid']:
                    issues.append({
                        'type': 'DISCONNECTED_SEGMENTS_SEQUENTIAL',
                        'severity': 'INFO',  # INFO siden rekkefølge kan være feil
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

    # Sjekk for overlapp mellom segmenter
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            seg1 = segments[i]
            seg2 = segments[j]

            # Sjekk om segmentene overlapper
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
                        if overlap_length > 10:  # Mer enn 10 meter overlapp
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
                # Ignorer feil ved overlap-sjekk
                pass

    return {
        'segments': segments_info,
        'issues': issues,
        'connections': connection_info  # Legg til koblingsinformasjon
    }


def get_route_debug_info(rutenummer):
    """Henter komplett debugging-informasjon for en rute."""
    conn = get_db_connection()

    try:
        # Hent segmenter med geometri
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

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (rutenummer,))
            segments = cur.fetchall()

        if not segments:
            return {
                'rutenummer': rutenummer,
                'segments': [],
                'analysis': {'segments': [], 'issues': []}
            }

        # Analyser segmenter
        analysis = analyze_route_segments(conn, rutenummer)

        # Konverter geometrier til GeoJSON
        segments_with_geom = []
        for seg in segments:
            import json
            geom_json = json.loads(seg['geometry_geojson']) if seg['geometry_geojson'] else None

            # Finn issues for dette segmentet
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
            'connections': analysis.get('connections', [])  # Inkluder koblingsinformasjon
        }
    finally:
        conn.close()

