"""
Geometric route reconstruction - finds the actual geographic order of route segments
by following connections between segments.
"""
import json
from psycopg.rows import dict_row
from .database import get_db_connection, ROUTE_SCHEMA
from .route_connections import find_segment_connections
from .route_service import parse_geojson_string, get_route_segments_with_points, get_segments_by_objids


def find_geographic_order(conn, rutenummer):
    """
    Find the actual geographic order of segments by following connections.

    Returns:
        List of segment objids in geographic order
    """
    # Get all segments with start/end points (use shared function)
    segments = get_route_segments_with_points(conn, rutenummer)

    if not segments:
        return []

    # Build a graph of connections between segments
    # Use shared module to find connections
    segment_objids = [seg['objid'] for seg in segments]
    connections = find_segment_connections(conn, segment_objids, ROUTE_SCHEMA)

    # Find the start segment (the segment that has no connection to its start)
    # This is the segment that has a start point that is not an endpoint for any other segment
    all_end_points = set()
    for seg in segments:
        all_end_points.add(seg['end_point_wkt'])

    start_segment = None
    for seg in segments:
        if seg['start_point_wkt'] not in all_end_points:
            # This could be the start segment, but also check if it has a normal end_to_start connection
            # Prefer segments with end_to_start connections
            has_end_to_start = any(
                conn['type'] == 'end_to_start'
                for conn in connections.get(seg['objid'], [])
            )
            if not has_end_to_start or start_segment is None:
                start_segment = seg
                if has_end_to_start:
                    break

    # If we didn't find a clear start segment, use the first one
    if start_segment is None:
        start_segment = segments[0]

    # Follow connections to build the geographic order
    ordered_segments = []
    visited = set()
    current_segment_objid = start_segment['objid']

    while current_segment_objid and current_segment_objid not in visited:
        visited.add(current_segment_objid)

        # Find the segment
        current_segment = next(s for s in segments if s['objid'] == current_segment_objid)
        ordered_segments.append(current_segment['objid'])

        # Find next segment by following the best connection
        # Prioritize connection types in this order:
        # 1. end_to_start (normal connection: end → start) - BEST
        # 2. start_to_end (start → end) - next segment must be reversed
        # 3. end_to_end (end → end) - next segment must be reversed
        # 4. start_to_start (start → start) - both must be reversed
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
                # Prefer higher priority (lower number), or if same priority, shortest distance
                if conn_priority < best_priority or (conn_priority == best_priority and conn['distance'] < best_connection['distance']):
                    next_segment = conn['target']
                    best_connection = conn

        current_segment_objid = next_segment

    # Add any segments that were not visited (isolated or loose ends)
    for seg in segments:
        if seg['objid'] not in visited:
            ordered_segments.append(seg['objid'])

    return ordered_segments


def get_corrected_route_geometry(conn, rutenummer):
    """
    Return a corrected geographic representation of the route.
    If segments cannot be connected, they are returned as separate components.

    Returns:
        dict with:
            - ordered_segment_objids: List of objids in geographic order (or list of lists if disconnected)
            - geometry: Combined GeoJSON geometry (MultiLineString with separate components)
            - segments_info: List of segment info in geographic order
            - components: List of separate route components if segments cannot be connected
            - is_connected: Boolean indicating if all segments form a single connected route
    """
    # Use same method as find_geographic_order to find connections
    # Get all segments first (use shared function)
    segments = get_route_segments_with_points(conn, rutenummer)

    if not segments:
        return None

    # Build connections using shared module
    segment_objids = [seg['objid'] for seg in segments]
    connections = find_segment_connections(conn, segment_objids, ROUTE_SCHEMA)

    # Find connected components by following connections
    components = []
    visited = set()

    for start_objid in segment_objids:
        if start_objid in visited:
            continue

        # Build a component by following connections from this segment
        component_objids = []
        current_objid = start_objid

        # Follow connections to build the component
        while current_objid and current_objid not in visited:
            visited.add(current_objid)
            component_objids.append(current_objid)

            # Find best next segment
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

    # Get all segments with geometry (use shared function)
    all_segments_with_geom = get_segments_by_objids(conn, segment_objids, include_geojson=True)

    # Build dict for fast lookup
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
            geom_json = parse_geojson_string(seg.get('geometry_geojson'))
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

        # Combine component into a LineString or MultiLineString
        if len(component_geoms) == 1:
            component_geometry = component_geoms[0]
        else:
            component_geometry = {
                'type': 'MultiLineString',
                'coordinates': [geom['coordinates'] for geom in component_geoms if geom and geom.get('coordinates')]
            }

        component_geometries.append(component_geometry)

    # Combine all components into a MultiLineString
    if len(component_geometries) == 1:
        combined_geometry = component_geometries[0]
    else:
        # Multiple components - combine into MultiLineString
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

    # Identify appendix segments (segments not connected to the main route)
    # These are typically segments that are isolated or only connected to other appendix segments
    # We consider the main route as the largest component (most segments or longest length)
    appendices = []
    main_component = None
    main_component_index = 0  # Initialize to 0 (first component)
    dead_end_segments = []

    if len(components) > 1:
        # Find main component (largest component)
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

        # Sort by size (segments first, then length)
        component_sizes.sort(key=lambda x: (x['segment_count'], x['length']), reverse=True)
        main_component = component_sizes[0]['component']
        main_component_index = component_sizes[0]['index']

        # All other components are appendices
        appendices = [
            {
                'component': comp['component'],
                'segment_objids': comp['component'],
                'segment_count': comp['segment_count'],
                'length_meters': comp['length']
            }
            for comp in component_sizes[1:]
        ]

    # If there are no more components, use first component as main component
    if not main_component and len(components) == 1:
        main_component = components[0]
        main_component_index = 0  # First (and only) component is the main one

    # Identify dead-end segments (spurs) in the main component
    # These are segments that are only connected on one side and are not necessary to connect the rest together
    if main_component and len(main_component) > 2:
        # Build a graph of connections in the main component
        main_component_connections = {}
        for seg_objid in main_component:
            main_component_connections[seg_objid] = []
            for connection in connections.get(seg_objid, []):
                if connection['target'] in main_component:
                    main_component_connections[seg_objid].append(connection['target'])

        # Find segments with only one connection (endpoints)
        endpoints = [
            seg_objid for seg_objid in main_component
            if len(main_component_connections[seg_objid]) == 1
        ]

        # For each endpoint, check if it is necessary to connect the rest together
        # We do this by removing the segment and seeing if the rest is still connected
        for endpoint in endpoints:
            # Bygg graf uten dette segmentet
            remaining_segments = [s for s in main_component if s != endpoint]

            if len(remaining_segments) < 2:
                # Kun ett segment igjen, ikke en dead-end
                continue

            # Check if the rest is still connected
            remaining_connections = {}
            for seg_objid in remaining_segments:
                remaining_connections[seg_objid] = []
                for connection in connections.get(seg_objid, []):
                    if connection['target'] in remaining_segments:
                        remaining_connections[seg_objid].append(connection['target'])

            # Check if the rest is connected by following connections from the first segment
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

            # If all segments were visited, the rest is still connected
            # This means the endpoint segment is a dead-end (spur)
            if len(visited) == len(remaining_segments):
                # Find length of this segment
                endpoint_length = 0.0
                if endpoint in segment_dict:
                    endpoint_length = segment_dict[endpoint]['length_meters']

                dead_end_segments.append({
                    'segment_objid': endpoint,
                    'length_meters': endpoint_length,
                    'connected_to': main_component_connections[endpoint][0] if main_component_connections[endpoint] else None
                })

    # Identify redundant segments (side branches/loops) in the main component
    # These are segments that have multiple connections, but are not necessary to connect the rest together
    redundant_segments = []
    if main_component and len(main_component) > 3:
        for seg_objid in main_component:
            # Skip if already identified as dead-end
            if any(d['segment_objid'] == seg_objid for d in dead_end_segments):
                continue

            # Check if segment is redundant by removing it and seeing if the rest is still connected
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

            # Check if the rest is connected
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

            # If all segments were visited, the segment is redundant
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

    # Add redundant segments to dead_end_segments for simplicity (they are also "unnecessary")
    dead_end_segments.extend(redundant_segments)

    # Build report
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

    # Build ordered segment objids: single list if connected, list of lists if disconnected
    if is_connected and components:
        ordered_segment_objids = components[0]  # Single component = ordered list
    else:
        ordered_segment_objids = components  # Multiple components = list of lists

    return {
        'rutenummer': rutenummer,
        'ordered_segment_objids': ordered_segment_objids,
        'geometry': combined_geometry,
        'segments_info': all_segments_info,
        'total_length_meters': total_length,
        'components': components,
        'is_connected': is_connected,
        'component_count': len(components),
        'report': report
    }

