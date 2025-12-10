"""
Geometric route reconstruction - finds the actual geographic order of route segments
by following connections between segments.
"""
from psycopg2.extras import RealDictCursor
from .database import get_db_connection, ROUTE_SCHEMA


def find_geographic_order(conn, rutenummer):
    """
    Finner den faktiske geografiske rekkefølgen av segmenter ved å følge koblingene.

    Returns:
        List of segment objids in geographic order
    """
    # Hent alle segmenter med start/end punkter
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
        segments = cur.fetchall()

    if not segments:
        return []

    # Bygg en graf av koblinger mellom segmenter
    # Bruk direkte SQL for bedre ytelse
    connections = {}  # segment_objid -> list of (connected_segment_objid, connection_type, distance)

    # Initialiser connections for alle segmenter
    for seg in segments:
        connections[seg['objid']] = []

    # Hent alle koblinger direkte fra databasen
    segment_objids = [seg['objid'] for seg in segments]
    placeholders = ','.join(['%s'] * len(segment_objids))

    # Sjekk alle mulige koblingstyper
    connection_queries = [
        ('end_to_start', f"""
            SELECT
                f1.objid as seg1_objid,
                f2.objid as seg2_objid,
                ST_Distance(
                    ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)
                ) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1
            CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders})
              AND f2.objid IN ({placeholders})
              AND f1.objid != f2.objid
              AND ST_Distance(
                    ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)
                  ) <= 1.0
        """),
        ('end_to_end', f"""
            SELECT
                f1.objid as seg1_objid,
                f2.objid as seg2_objid,
                ST_Distance(
                    ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)
                ) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1
            CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders})
              AND f2.objid IN ({placeholders})
              AND f1.objid != f2.objid
              AND ST_Distance(
                    ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)
                  ) <= 1.0
        """),
        ('start_to_start', f"""
            SELECT
                f1.objid as seg1_objid,
                f2.objid as seg2_objid,
                ST_Distance(
                    ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)
                ) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1
            CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders})
              AND f2.objid IN ({placeholders})
              AND f1.objid != f2.objid
              AND ST_Distance(
                    ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)
                  ) <= 1.0
        """),
        ('start_to_end', f"""
            SELECT
                f1.objid as seg1_objid,
                f2.objid as seg2_objid,
                ST_Distance(
                    ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)
                ) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1
            CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders})
              AND f2.objid IN ({placeholders})
              AND f1.objid != f2.objid
              AND ST_Distance(
                    ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                    ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)
                  ) <= 1.0
        """),
    ]

    for conn_type, query in connection_queries:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, segment_objids + segment_objids)
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

    # Finn startsegmentet (segmentet som ikke har noen som kobler til starten)
    # Dette er segmentet som har en start som ikke er endepunkt for noen annen
    all_end_points = set()
    for seg in segments:
        all_end_points.add(seg['end_point_wkt'])

    start_segment = None
    for seg in segments:
        if seg['start_point_wkt'] not in all_end_points:
            # Dette kan være startsegmentet, men sjekk også om det har en normal end_to_start kobling
            # Preferer segmenter med end_to_start koblinger
            has_end_to_start = any(
                conn['type'] == 'end_to_start'
                for conn in connections.get(seg['objid'], [])
            )
            if not has_end_to_start or start_segment is None:
                start_segment = seg
                if has_end_to_start:
                    break

    # Hvis vi ikke fant et klart startsegment, bruk det første
    if start_segment is None:
        start_segment = segments[0]

    # Følg koblingene for å bygge den geografiske rekkefølgen
    ordered_segments = []
    visited = set()
    current_segment_objid = start_segment['objid']

    while current_segment_objid and current_segment_objid not in visited:
        visited.add(current_segment_objid)

        # Finn segmentet
        current_segment = next(s for s in segments if s['objid'] == current_segment_objid)
        ordered_segments.append(current_segment['objid'])

        # Finn neste segment ved å følge den beste koblingen
        # Prioriterer koblingstyper i denne rekkefølgen:
        # 1. end_to_start (normal kobling: slutt → start) - BEST
        # 2. start_to_end (start → slutt) - neste segment må reverseres
        # 3. end_to_end (slutt → slutt) - neste segment må reverseres
        # 4. start_to_start (start → start) - begge må reverseres
        next_segment = None
        best_connection = None
        connection_priority = {'end_to_start': 1, 'start_to_end': 2, 'end_to_end': 3, 'start_to_start': 4}

        for conn in connections.get(current_segment_objid, []):
            if conn['target'] in visited:
                continue

            conn_priority = connection_priority.get(conn['type'], 99)

            if best_connection is None:
                next_segment = conn['target']
                best_connection = conn
            else:
                best_priority = connection_priority.get(best_connection['type'], 99)
                # Preferer høyere prioritet (lavere tall), eller hvis samme prioritet, kortest avstand
                if conn_priority < best_priority or (conn_priority == best_priority and conn['distance'] < best_connection['distance']):
                    next_segment = conn['target']
                    best_connection = conn

        current_segment_objid = next_segment

    # Legg til eventuelle segmenter som ikke ble besøkt (isolert eller løse ender)
    for seg in segments:
        if seg['objid'] not in visited:
            ordered_segments.append(seg['objid'])

    return ordered_segments


def get_corrected_route_geometry(conn, rutenummer):
    """
    Returnerer en korrigert geografisk representasjon av ruten.
    Hvis segmenter ikke kan kobles sammen, returneres de som separate komponenter.

    Returns:
        dict with:
            - ordered_segment_objids: List of objids in geographic order (or list of lists if disconnected)
            - geometry: Combined GeoJSON geometry (MultiLineString with separate components)
            - segments_info: List of segment info in geographic order
            - components: List of separate route components if segments cannot be connected
            - is_connected: Boolean indicating if all segments form a single connected route
    """
    # Bruk samme metode som find_geographic_order for å finne koblinger
    # Hent alle segmenter først
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
        segments = cur.fetchall()

    if not segments:
        return None

    # Bygg koblinger ved å bruke samme metode som find_geographic_order
    segment_objids = [seg['objid'] for seg in segments]
    placeholders = ','.join(['%s'] * len(segment_objids))

    # Hent alle koblinger direkte fra databasen (samme metode som find_geographic_order)
    connections = {}
    for seg in segments:
        connections[seg['objid']] = []

    connection_queries = [
        ('end_to_start', f"""
            SELECT f1.objid as seg1_objid, f2.objid as seg2_objid,
                   ST_Distance(ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                              ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1 CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders}) AND f2.objid IN ({placeholders}) AND f1.objid != f2.objid
              AND ST_Distance(ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                             ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)) <= 1.0
        """),
        ('end_to_end', f"""
            SELECT f1.objid as seg1_objid, f2.objid as seg2_objid,
                   ST_Distance(ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                              ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1 CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders}) AND f2.objid IN ({placeholders}) AND f1.objid != f2.objid
              AND ST_Distance(ST_Transform(ST_EndPoint(f1.senterlinje::geometry), 25833),
                             ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)) <= 1.0
        """),
        ('start_to_start', f"""
            SELECT f1.objid as seg1_objid, f2.objid as seg2_objid,
                   ST_Distance(ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                              ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1 CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders}) AND f2.objid IN ({placeholders}) AND f1.objid != f2.objid
              AND ST_Distance(ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                             ST_Transform(ST_StartPoint(f2.senterlinje::geometry), 25833)) <= 1.0
        """),
        ('start_to_end', f"""
            SELECT f1.objid as seg1_objid, f2.objid as seg2_objid,
                   ST_Distance(ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                              ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)) as distance
            FROM {ROUTE_SCHEMA}.fotrute f1 CROSS JOIN {ROUTE_SCHEMA}.fotrute f2
            WHERE f1.objid IN ({placeholders}) AND f2.objid IN ({placeholders}) AND f1.objid != f2.objid
              AND ST_Distance(ST_Transform(ST_StartPoint(f1.senterlinje::geometry), 25833),
                             ST_Transform(ST_EndPoint(f2.senterlinje::geometry), 25833)) <= 1.0
        """),
    ]

    for conn_type, query_sql in connection_queries:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query_sql, segment_objids + segment_objids)
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

    # Finn sammenhengende komponenter ved å følge koblingene
    import json
    components = []
    visited = set()

    for start_objid in segment_objids:
        if start_objid in visited:
            continue

        # Bygg en komponent ved å følge koblingene fra dette segmentet
        component_objids = []
        current_objid = start_objid

        # Følg koblingene for å bygge komponenten
        while current_objid and current_objid not in visited:
            visited.add(current_objid)
            component_objids.append(current_objid)

            # Finn beste neste segment
            next_objid = None
            best_conn = None
            connection_priority = {'end_to_start': 1, 'start_to_end': 2, 'end_to_end': 3, 'start_to_start': 4}

            for connection in connections.get(current_objid, []):
                if connection['target'] in visited:
                    continue

                conn_priority = connection_priority.get(connection['type'], 99)
                if best_conn is None:
                    next_objid = connection['target']
                    best_conn = connection
                else:
                    best_priority = connection_priority.get(best_conn['type'], 99)
                    if conn_priority < best_priority or (conn_priority == best_priority and connection['distance'] < best_conn['distance']):
                        next_objid = connection['target']
                        best_conn = connection

            current_objid = next_objid

        if component_objids:
            components.append(component_objids)

    # Hent alle segmenter med geometri
    placeholders = ','.join(['%s'] * len(segment_objids))
    geom_query = f"""
        SELECT
            f.objid,
            ST_AsGeoJSON(ST_Transform(f.senterlinje::geometry, 4326)) as geometry_geojson,
            ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
        FROM {ROUTE_SCHEMA}.fotrute f
        WHERE f.objid IN ({placeholders});
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(geom_query, segment_objids)
        all_segments_with_geom = cur.fetchall()

    # Bygg dict for rask oppslag
    segment_dict = {seg['objid']: seg for seg in all_segments_with_geom}

    # Bygg geometrier for hver komponent
    component_geometries = []
    all_segments_info = []
    total_length = 0.0

    for component_objids in components:
        component_geoms = []
        component_length = 0.0

        for objid in component_objids:
            seg = segment_dict[objid]
            geom_json = json.loads(seg['geometry_geojson']) if seg['geometry_geojson'] else None
            length = float(seg['length_meters']) if seg['length_meters'] else 0.0

            all_segments_info.append({
                'objid': objid,
                'geometry': geom_json,
                'length_meters': length,
                'cumulative_length_meters': total_length,
                'component_index': len(component_geometries)
            })

            component_length += length
            total_length += length

            if geom_json:
                component_geoms.append(geom_json)

        # Kombiner komponenten til en LineString eller MultiLineString
        if len(component_geoms) == 1:
            component_geometry = component_geoms[0]
        else:
            component_geometry = {
                'type': 'MultiLineString',
                'coordinates': [geom['coordinates'] for geom in component_geoms if geom and geom.get('coordinates')]
            }

        component_geometries.append(component_geometry)

    # Kombiner alle komponenter til en MultiLineString
    if len(component_geometries) == 1:
        combined_geometry = component_geometries[0]
    else:
        # Flere komponenter - kombiner til MultiLineString
        all_coords = []
        for comp_geom in component_geometries:
            if comp_geom['type'] == 'LineString':
                all_coords.append(comp_geom['coordinates'])
            elif comp_geom['type'] == 'MultiLineString':
                all_coords.extend(comp_geom['coordinates'])

        combined_geometry = {
            'type': 'MultiLineString',
            'coordinates': all_coords
        }

    is_connected = len(components) == 1

    # Identifiser appendiks-segmenter (segmenter som ikke er koblet til hovedruten)
    # Dette er typisk segmenter som er isolerte eller kun koblet til andre appendiks-segmenter
    # Vi regner hovedruten som den største komponenten (mest segmenter eller lengste lengde)
    appendices = []
    main_component = None
    dead_end_segments = []

    if len(components) > 1:
        # Finn hovedkomponenten (største komponent)
        component_sizes = []
        for i, comp in enumerate(components):
            comp_length = sum(
                segment_dict[objid]['length_meters']
                for objid in comp
                if objid in segment_dict
            )
            component_sizes.append({
                'index': i,
                'component': comp,
                'segment_count': len(comp),
                'length': comp_length
            })

        # Sorter etter størrelse (segmenter først, deretter lengde)
        component_sizes.sort(key=lambda x: (x['segment_count'], x['length']), reverse=True)
        main_component = component_sizes[0]['component']
        main_component_index = component_sizes[0]['index']

        # Alle andre komponenter er appendiks
        appendices = [
            {
                'component': comp['component'],
                'segment_objids': comp['component'],
                'segment_count': comp['segment_count'],
                'length_meters': comp['length']
            }
            for comp in component_sizes[1:]
        ]

    # Hvis det ikke er flere komponenter, bruk første komponent som hovedkomponent
    if not main_component and len(components) == 1:
        main_component = components[0]

    # Identifiser dead-end segmenter (utstikkere) i hovedkomponenten
    # Dette er segmenter som kun er koblet på én side og ikke er nødvendige for å koble resten sammen
    if main_component and len(main_component) > 2:
        # Bygg en graf av koblinger i hovedkomponenten
        main_component_connections = {}
        for seg_objid in main_component:
            main_component_connections[seg_objid] = []
            for connection in connections.get(seg_objid, []):
                if connection['target'] in main_component:
                    main_component_connections[seg_objid].append(connection['target'])

        # Finn segmenter med kun én kobling (endepunkter)
        endpoints = [
            seg_objid for seg_objid in main_component
            if len(main_component_connections[seg_objid]) == 1
        ]

        # For hvert endepunkt, sjekk om det er nødvendig for å koble resten sammen
        # Vi gjør dette ved å fjerne segmentet og se om resten fortsatt er koblet sammen
        for endpoint in endpoints:
            # Bygg graf uten dette segmentet
            remaining_segments = [s for s in main_component if s != endpoint]

            if len(remaining_segments) < 2:
                # Kun ett segment igjen, ikke en dead-end
                continue

            # Sjekk om resten fortsatt er koblet sammen
            remaining_connections = {}
            for seg_objid in remaining_segments:
                remaining_connections[seg_objid] = []
                for connection in connections.get(seg_objid, []):
                    if connection['target'] in remaining_segments:
                        remaining_connections[seg_objid].append(connection['target'])

            # Sjekk om resten er sammenhengende ved å følge koblingene fra første segment
            visited = set()
            stack = [remaining_segments[0]]

            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                for neighbor in remaining_connections.get(current, []):
                    if neighbor not in visited:
                        stack.append(neighbor)

            # Hvis alle segmenter ble besøkt, er resten fortsatt sammenhengende
            # Dette betyr at endpoint-segmentet er en dead-end (utstikker)
            if len(visited) == len(remaining_segments):
                # Finn lengde av dette segmentet
                endpoint_length = 0.0
                if endpoint in segment_dict:
                    endpoint_length = segment_dict[endpoint]['length_meters']

                dead_end_segments.append({
                    'segment_objid': endpoint,
                    'length_meters': endpoint_length,
                    'connected_to': main_component_connections[endpoint][0] if main_component_connections[endpoint] else None
                })

    # Identifiser redundante segmenter (side-grener/løkker) i hovedkomponenten
    # Dette er segmenter som har flere koblinger, men som ikke er nødvendige for å koble resten sammen
    redundant_segments = []
    if main_component and len(main_component) > 3:
        for seg_objid in main_component:
            # Skip hvis allerede identifisert som dead-end
            if any(d['segment_objid'] == seg_objid for d in dead_end_segments):
                continue

            # Sjekk om segmentet er redundant ved å fjerne det og se om resten fortsatt er koblet sammen
            remaining_segments = [s for s in main_component if s != seg_objid]

            if len(remaining_segments) < 2:
                continue

            # Bygg graf uten dette segmentet
            remaining_connections = {}
            for seg in remaining_segments:
                remaining_connections[seg] = []
                for connection in connections.get(seg, []):
                    if connection['target'] in remaining_segments:
                        remaining_connections[seg].append(connection['target'])

            # Sjekk om resten er sammenhengende
            visited = set()
            stack = [remaining_segments[0]]

            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                for neighbor in remaining_connections.get(current, []):
                    if neighbor not in visited:
                        stack.append(neighbor)

            # Hvis alle segmenter ble besøkt, er segmentet redundant
            if len(visited) == len(remaining_segments):
                seg_length = 0.0
                if seg_objid in segment_dict:
                    seg_length = segment_dict[seg_objid]['length_meters']

                connected_to = []
                for connection in connections.get(seg_objid, []):
                    if connection['target'] in main_component:
                        connected_to.append(connection['target'])

                redundant_segments.append({
                    'segment_objid': seg_objid,
                    'length_meters': seg_length,
                    'connected_to': connected_to,
                    'is_redundant': True
                })

    # Legg til redundante segmenter i dead_end_segments for enkelhet (de er også "unødvendige")
    dead_end_segments.extend(redundant_segments)

    # Bygg rapport
    report = {
        'has_multiple_components': not is_connected,
        'component_count': len(components),
        'is_connected': is_connected,
        'components': [
            {
                'index': i,
                'segment_objids': comp,
                'segment_count': len(comp),
                'length_meters': sum(
                    segment_dict[objid]['length_meters']
                    for objid in comp
                    if objid in segment_dict
                ),
                'is_main': i == (main_component_index if main_component else 0)
            }
            for i, comp in enumerate(components)
        ],
        'appendices': appendices,
        'appendices_count': len(appendices),
        'dead_end_segments': dead_end_segments,
        'dead_end_count': len(dead_end_segments)
    }

    return {
        'rutenummer': rutenummer,
        'ordered_segment_objids': ordered_objids if is_connected else [comp for comp in components],
        'geometry': combined_geometry,
        'segments_info': all_segments_info,
        'total_length_meters': total_length,
        'components': components,
        'is_connected': is_connected,
        'component_count': len(components),
        'report': report
    }

