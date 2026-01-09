"""
Geometry validators for route validation.
"""

from typing import Dict, List, Any
from .base import BaseValidator, ValidationResult, ValidationIssue, Severity
from ..database import ROUTE_SCHEMA, quote_identifier, validate_schema_name
from ..route_connections import find_segment_connections
from psycopg.rows import dict_row


class RouteGeometryValidator(BaseValidator):
    """Validates route geometry from route_geometries."""

    def get_name(self) -> str:
        return "route_geometry"

    def get_category(self) -> str:
        return "geometry"

    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """Validate route geometry."""
        rutenummer = route_data.get('rutenummer')
        result = ValidationResult(rutenummer)

        if not validate_schema_name(ROUTE_SCHEMA):
            result.add_issue(ValidationIssue(
                type='VALIDATION_ERROR',
                message=f'Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}',
                severity=Severity.ERROR
            ))
            return result

        schema_quoted = quote_identifier(ROUTE_SCHEMA)

        # Get route geometry from route_geometries column
        # Also check route_continuous_geometries for multilinestring_reason if table exists
        # First try with LEFT JOIN, fallback to simple query if table doesn't exist
        route_geometry_query = f"""
            SELECT
                lwr.route_geometries->>%s as route_geometry_json,
                ST_Length(ST_Transform(ST_GeomFromGeoJSON(lwr.route_geometries->>%s), 4326)::geography) as length_meters,
                ST_GeometryType(ST_GeomFromGeoJSON(lwr.route_geometries->>%s)) as geom_type,
                ST_NumGeometries(ST_GeomFromGeoJSON(lwr.route_geometries->>%s)) as num_geoms,
                (SELECT COUNT(DISTINCT lwr2.link_id)
                 FROM {schema_quoted}.links_with_routes lwr2
                 WHERE %s = ANY(lwr2.rutenummer_list)) as link_count
            FROM {schema_quoted}.links_with_routes lwr
            WHERE %s = ANY(lwr.rutenummer_list)
              AND lwr.route_geometries->>%s IS NOT NULL
            LIMIT 1
        """

        # Try to get multilinestring_reason from route_continuous_geometries if table exists
        # Use a savepoint to avoid breaking the main transaction if table doesn't exist
        multilinestring_reason = None
        column_exists = False  # Track if column exists for validation
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                # Check if table exists first
                table_check_query = """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = 'route_continuous_geometries'
                    ) as exists
                """
                cur.execute(table_check_query, (ROUTE_SCHEMA,))
                table_exists_row = cur.fetchone()
                table_exists = table_exists_row.get('exists') if table_exists_row else False

                if table_exists:
                    # Check if column exists (it might not exist if build-links hasn't run with latest version)
                    # Use dynamic schema check for turogfriluftsruter_* schemas
                    column_check_query = """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = %s
                              AND table_name = 'route_continuous_geometries'
                              AND column_name = 'multilinestring_reason'
                        ) as exists
                    """
                    cur.execute(column_check_query, (ROUTE_SCHEMA,))
                    column_exists_row = cur.fetchone()
                    column_exists = column_exists_row.get('exists') if column_exists_row else False

                    if column_exists:
                        reason_query = f"""
                            SELECT multilinestring_reason
                            FROM {schema_quoted}.route_continuous_geometries
                            WHERE rutenummer = %s
                            LIMIT 1
                        """
                        cur.execute(reason_query, (rutenummer,))
                        reason_row = cur.fetchone()
                        if reason_row:
                            multilinestring_reason = reason_row.get('multilinestring_reason')
                    else:
                        # Column doesn't exist - log warning
                        result.add_issue(ValidationIssue(
                            type='MULTILINESTRING_REASON_COLUMN_MISSING',
                            message=f'Column multilinestring_reason does not exist in route_continuous_geometries. This may indicate that build-links has not run with the latest version. Reason validation will be skipped.',
                            severity=Severity.WARNING,
                            metadata={'table': 'route_continuous_geometries', 'column': 'multilinestring_reason'}
                        ))
        except Exception:
            # Table might not exist yet or other error, ignore
            pass

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(route_geometry_query, (rutenummer, rutenummer, rutenummer, rutenummer, rutenummer, rutenummer, rutenummer))
            route_geom_row = cur.fetchone()

            if not route_geom_row or not route_geom_row.get('route_geometry_json'):
                result.add_issue(ValidationIssue(
                    type='NO_ROUTE_GEOMETRY',
                    message=f'No route_geometries found for route {rutenummer} in links_with_routes. This may mean the route could not be made continuous (e.g., disconnected components) or build-links has not run yet.',
                    severity=Severity.WARNING
                ))
                return result

            route_geometry_json = route_geom_row['route_geometry_json']
            link_count = route_geom_row.get('link_count', 0)
            geom_type = route_geom_row.get('geom_type')
            num_components = route_geom_row.get('num_geoms', 1) if geom_type == 'ST_MultiLineString' else 1
            # multilinestring_reason is fetched separately above

            # Validate route geometry
            geom_validation_query = """
                SELECT
                    ST_IsValid(ST_GeomFromGeoJSON(%s)::geometry) as is_valid,
                    ST_IsSimple(ST_GeomFromGeoJSON(%s)::geometry) as is_simple,
                    ST_Length(ST_Transform(ST_GeomFromGeoJSON(%s)::geometry, 4326)::geography) as length_meters
            """
            cur.execute(geom_validation_query, (route_geometry_json, route_geometry_json, route_geometry_json))
            geom_validation = cur.fetchone()

            if geom_validation:
                is_valid = geom_validation['is_valid']
                is_simple = geom_validation['is_simple']
                length_meters = geom_validation.get('length_meters')

                if not is_valid:
                    result.add_issue(ValidationIssue(
                        type='INVALID_ROUTE_GEOMETRY',
                        message='Route geometry is invalid',
                        severity=Severity.ERROR
                    ))

                if not is_simple:
                    result.add_issue(ValidationIssue(
                        type='NON_SIMPLE_ROUTE_GEOMETRY',
                        message='Route geometry has self-intersections or is not simple',
                        severity=Severity.WARNING
                    ))

                if length_meters is None or length_meters == 0:
                    result.add_issue(ValidationIssue(
                        type='ZERO_LENGTH_ROUTE',
                        message='Route has zero or null length',
                        severity=Severity.ERROR
                    ))

                if geom_type:
                    result.metadata['route_geometry_type'] = geom_type
                    result.metadata['route_length_meters'] = float(length_meters) if length_meters else None
                    if geom_type == 'ST_MultiLineString':
                        result.metadata['multilinestring_component_count'] = num_components
                    # Store multilinestring_reason in metadata if available (even for LineString, as it can be 'single_linestring')
                    if multilinestring_reason:
                        result.metadata['multilinestring_reason'] = multilinestring_reason

                    # Validate multilinestring_reason if it exists
                    if multilinestring_reason is not None:
                        # Valid values
                        valid_reasons = {
                            'single_linestring',
                            'link_is_multilinestring',
                            'loop_or_branch',
                            'precision_gap',
                            'disconnected_components',
                            'traversal_issue'
                        }

                        # Check if reason is valid
                        if multilinestring_reason not in valid_reasons:
                            result.add_issue(ValidationIssue(
                                type='INVALID_MULTILINESTRING_REASON',
                                message=f'Invalid multilinestring_reason value: "{multilinestring_reason}". Valid values are: {sorted(valid_reasons)}',
                                severity=Severity.ERROR,
                                metadata={
                                    'invalid_reason': multilinestring_reason,
                                    'valid_reasons': sorted(valid_reasons)
                                }
                            ))

                        # Check consistency with geometry type
                        is_linestring = geom_type == 'ST_LineString'
                        is_single_component_multilinestring = (geom_type == 'ST_MultiLineString' and num_components == 1)

                        if is_linestring or is_single_component_multilinestring:
                            # Should be 'single_linestring'
                            if multilinestring_reason != 'single_linestring':
                                result.add_issue(ValidationIssue(
                                    type='MULTILINESTRING_REASON_INCONSISTENT',
                                    message=f'Geometry is {geom_type} with {num_components} component(s) (should be LineString or single-component), but multilinestring_reason is "{multilinestring_reason}" (expected "single_linestring")',
                                    severity=Severity.ERROR,
                                    metadata={
                                        'geom_type': geom_type,
                                        'num_components': num_components,
                                        'actual_reason': multilinestring_reason,
                                        'expected_reason': 'single_linestring'
                                    }
                                ))
                        else:
                            # MultiLineString with multiple components - should NOT be 'single_linestring'
                            if multilinestring_reason == 'single_linestring':
                                result.add_issue(ValidationIssue(
                                    type='MULTILINESTRING_REASON_INCONSISTENT',
                                    message=f'Geometry is MultiLineString with {num_components} component(s), but multilinestring_reason is "single_linestring" (expected one of: link_is_multilinestring, loop_or_branch, precision_gap, disconnected_components, traversal_issue)',
                                    severity=Severity.ERROR,
                                    metadata={
                                        'geom_type': geom_type,
                                        'num_components': num_components,
                                        'actual_reason': multilinestring_reason,
                                        'expected_reasons': ['link_is_multilinestring', 'loop_or_branch', 'precision_gap', 'disconnected_components', 'traversal_issue']
                                    }
                                ))
                    else:
                        # multilinestring_reason is NULL - this is an error if column exists
                        # (We already checked if column exists above, so if we get here and reason is None,
                        # it means the column exists but the value is NULL)
                        if column_exists:
                            result.add_issue(ValidationIssue(
                                type='MULTILINESTRING_REASON_NULL',
                                message=f'multilinestring_reason is NULL for route {rutenummer}. All routes should have a reason value.',
                                severity=Severity.ERROR,
                                metadata={'rutenummer': rutenummer}
                            ))

                    # Build message with reason if available
                    message = f'Route geometry type: {geom_type}'
                    if geom_type == 'ST_MultiLineString' and num_components > 1:
                        message += f' with {num_components} component(s)'

                    # Show reason if available (for both LineString and MultiLineString)
                    if multilinestring_reason:
                        reason_descriptions = {
                            'single_linestring': 'Single LineString (perfect continuous geometry)',
                            'link_is_multilinestring': 'Individual link is already MultiLineString',
                            'loop_or_branch': 'Route has loops or branches (traversal found duplicates or incomplete)',
                            'precision_gap': 'Small gaps (< 1cm) between links due to floating point precision',
                            'disconnected_components': 'Large gaps between links (e.g., lakes, rivers)',
                            'traversal_issue': 'Traversal found all links in order, but still MultiLineString (unknown cause)'
                        }
                        reason_desc = reason_descriptions.get(multilinestring_reason, multilinestring_reason)
                        message += f'. Reason: {reason_desc}'

                    result.add_issue(ValidationIssue(
                        type='ROUTE_GEOMETRY_TYPE',
                        message=message,
                        severity=Severity.INFO,
                        metadata={
                            'geom_type': geom_type,
                            'length_meters': float(length_meters) if length_meters else None,
                            'num_components': num_components if geom_type == 'ST_MultiLineString' else 1,
                            'multilinestring_reason': multilinestring_reason if geom_type == 'ST_MultiLineString' else None
                        }
                    ))

        result.metadata['link_count'] = link_count
        return result


class LinkConnectivityValidator(BaseValidator):
    """Validates link connectivity and node structure."""

    def get_name(self) -> str:
        return "link_connectivity"

    def get_category(self) -> str:
        return "geometry"

    def get_dependencies(self) -> List[str]:
        return ["route_geometry"]  # Needs route geometry to be validated first

    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """Validate link connectivity."""
        rutenummer = route_data.get('rutenummer')
        result = ValidationResult(rutenummer)

        if not validate_schema_name(ROUTE_SCHEMA):
            return result

        schema_quoted = quote_identifier(ROUTE_SCHEMA)

        # Get links
        links_query = f"""
            SELECT
                l.link_id,
                l.a_node,
                l.b_node,
                l.length_m,
                l.segment_objids,
                an_a.degree as a_node_degree,
                an_b.degree as b_node_degree,
                an_a.navn as a_node_name,
                an_b.navn as b_node_name
            FROM {schema_quoted}.links_with_routes l
            LEFT JOIN {schema_quoted}.anchor_nodes an_a ON an_a.node_id = l.a_node
            LEFT JOIN {schema_quoted}.anchor_nodes an_b ON an_b.node_id = l.b_node
            WHERE %s = ANY(l.rutenummer_list)
            ORDER BY l.link_id
        """

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(links_query, (rutenummer,))
            links = cur.fetchall()

        if not links:
            return result

        # Validate individual links
        for link in links:
            link_id = link['link_id']
            length_m = link.get('length_m')

            if length_m is None or length_m == 0:
                result.add_issue(ValidationIssue(
                    type='ZERO_LENGTH_LINK',
                    message=f'Link {link_id} has zero or null length',
                    severity=Severity.ERROR,
                    affected_links=[link_id]
                ))
            elif length_m < 1.0:
                result.add_issue(ValidationIssue(
                    type='VERY_SHORT_LINK',
                    message=f'Link {link_id} is very short ({length_m:.2f} m)',
                    severity=Severity.WARNING,
                    affected_links=[link_id],
                    metadata={'length_m': length_m}
                ))

        # Build link graph
        link_graph = {}
        link_by_id = {}

        for link in links:
            link_id = link['link_id']
            a_node = link['a_node']
            b_node = link['b_node']
            link_by_id[link_id] = link

            if a_node not in link_graph:
                link_graph[a_node] = []
            link_graph[a_node].append(('a', link_id))

            if b_node not in link_graph:
                link_graph[b_node] = []
            link_graph[b_node].append(('b', link_id))

        # Check node connectivity
        if len(links) > 1:
            # Find endpoints
            endpoint_nodes = []
            for node, link_refs in link_graph.items():
                if len(link_refs) == 1:
                    endpoint_nodes.append(node)

            if len(endpoint_nodes) != 2:
                result.add_issue(ValidationIssue(
                    type='UNEXPECTED_ENDPOINT_COUNT',
                    message=f'Route has {len(endpoint_nodes)} endpoint node(s) (expected 2 for a continuous route). Endpoints: {endpoint_nodes}',
                    severity=Severity.WARNING,
                    metadata={'endpoint_count': len(endpoint_nodes), 'endpoint_nodes': endpoint_nodes}
                ))

            # Check endpoints have correct degree
            for link in links:
                a_degree = link.get('a_node_degree')
                b_degree = link.get('b_node_degree')

                if link['a_node'] in endpoint_nodes and a_degree is not None and a_degree != 1:
                    result.add_issue(ValidationIssue(
                        type='ENDPOINT_NODE_WRONG_DEGREE',
                        message=f'Link {link["link_id"]} has a_node {link["a_node"]} marked as endpoint but has degree={a_degree} (expected 1)',
                        severity=Severity.WARNING,
                        affected_links=[link['link_id']],
                        metadata={'node_id': link['a_node'], 'degree': a_degree}
                    ))

                if link['b_node'] in endpoint_nodes and b_degree is not None and b_degree != 1:
                    result.add_issue(ValidationIssue(
                        type='ENDPOINT_NODE_WRONG_DEGREE',
                        message=f'Link {link["link_id"]} has b_node {link["b_node"]} marked as endpoint but has degree={b_degree} (expected 1)',
                        severity=Severity.WARNING,
                        affected_links=[link['link_id']],
                        metadata={'node_id': link['b_node'], 'degree': b_degree}
                    ))

            # Check for multiple components
            components = []
            visited_components = set()

            def dfs_component(link_id, component):
                if link_id in visited_components:
                    return
                visited_components.add(link_id)
                component.append(link_id)

                link = link_by_id[link_id]
                b_node = link['b_node']
                if b_node in link_graph:
                    for node_type, connected_link_id in link_graph[b_node]:
                        if node_type == 'a' and connected_link_id not in visited_components:
                            dfs_component(connected_link_id, component)

            for link in links:
                link_id = link['link_id']
                if link_id not in visited_components:
                    component = []
                    dfs_component(link_id, component)
                    components.append(component)

            if len(components) > 1:
                components.sort(key=len, reverse=True)
                main_component = components[0]
                appendix_components = components[1:]

                result.add_issue(ValidationIssue(
                    type='MULTIPLE_LINK_COMPONENTS',
                    message=f'Route has {len(components)} disconnected link component(s). Main component: {len(main_component)} links, Appendix components: {[len(c) for c in appendix_components]} links. Note: route_geometries should still provide continuous geometry.',
                    severity=Severity.INFO,
                    metadata={
                        'component_count': len(components),
                        'main_component_link_ids': main_component,
                        'appendix_component_link_ids': [c for c in appendix_components]
                    }
                ))

        return result


class SegmentGapValidator(BaseValidator):
    """Validates gaps between route segments."""

    def get_name(self) -> str:
        return "segment_gaps"

    def get_category(self) -> str:
        return "geometry"

    def get_dependencies(self) -> List[str]:
        return ["route_geometry"]  # Needs route geometry to be validated first

    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """
        Validate gaps between route segments.

        Checks for gaps between connected segments that might prevent
        ST_LineMerge from creating a single LineString.
        """
        rutenummer = route_data.get('rutenummer')
        result = ValidationResult(rutenummer)

        if not validate_schema_name(ROUTE_SCHEMA):
            return result

        # Get segment objids from route_data
        segments_dict = route_data.get('segments_dict', {})
        if not segments_dict:
            return result

        segment_objids = [int(objid) for objid in segments_dict.keys()]
        if len(segment_objids) < 2:
            # Need at least 2 segments to check for gaps
            return result

        # Find connections between segments
        # Note: find_segment_connections only finds connections within 1.0m
        # But we want to check ALL connections, so we need a different approach
        # Let's check the actual route_geometries geometry instead

        # First, try to get the route geometry from route_geometries
        schema_quoted = quote_identifier(ROUTE_SCHEMA)
        route_geom_query = f"""
            SELECT
                lwr.route_geometries->>%s as route_geometry_json,
                ST_GeometryType(ST_GeomFromGeoJSON(lwr.route_geometries->>%s)) as geom_type
            FROM {schema_quoted}.links_with_routes lwr
            WHERE %s = ANY(lwr.rutenummer_list)
              AND lwr.route_geometries->>%s IS NOT NULL
            LIMIT 1
        """

        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(route_geom_query, (rutenummer, rutenummer, rutenummer, rutenummer))
                route_geom_row = cur.fetchone()

                if route_geom_row and route_geom_row.get('route_geometry_json'):
                    geom_type = route_geom_row.get('geom_type')
                    # multilinestring_reason is fetched separately above
                    if geom_type == 'ST_MultiLineString':
                        # Check if MultiLineString has multiple components
                        # This means segments couldn't be merged
                        num_geoms_query = """
                            SELECT ST_NumGeometries(ST_GeomFromGeoJSON(%s)) as num_geoms
                        """
                        cur.execute(num_geoms_query, (route_geom_row['route_geometry_json'],))
                        num_result = cur.fetchone()
                        # With dict_row, fetchone() returns a dict, so get the first value
                        num_geoms = list(num_result.values())[0] if num_result else 1

                        if num_geoms > 1:
                            # MultiLineString with multiple components - analyze why
                            # Check: gaps, reversed segments, overlapping, etc.

                            # First, check if we can merge with ST_LineMerge
                            try:
                                merge_test_query = """
                                    SELECT
                                        ST_GeometryType(ST_LineMerge(ST_GeomFromGeoJSON(%s))) as merged_type,
                                        ST_NumGeometries(ST_LineMerge(ST_GeomFromGeoJSON(%s))) as merged_num_geoms
                                """
                                cur.execute(merge_test_query, (route_geom_row['route_geometry_json'], route_geom_row['route_geometry_json']))
                                merge_result = cur.fetchone()
                                merged_type = merge_result[0] if merge_result else None
                                merged_num_geoms = merge_result[1] if merge_result and len(merge_result) > 1 else num_geoms
                            except Exception as e:
                                # If merge test fails, continue with other checks
                                merged_type = None
                                merged_num_geoms = num_geoms

                            # Check distances between components
                            check_gaps_query = """
                            WITH geom AS (
                                SELECT ST_GeomFromGeoJSON(%s) as g
                            ),
                            components AS (
                                SELECT
                                    generate_series(1, ST_NumGeometries(g)) as idx,
                                    ST_GeometryN(g, generate_series(1, ST_NumGeometries(g))) as component
                                FROM geom
                            )
                            SELECT
                                c1.idx as comp1_idx,
                                c2.idx as comp2_idx,
                                ST_Distance(
                                    ST_Transform(ST_EndPoint(c1.component), 25833),
                                    ST_Transform(ST_StartPoint(c2.component), 25833)
                                ) as distance_end_to_start,
                                ST_Distance(
                                    ST_Transform(ST_EndPoint(c1.component), 25833),
                                    ST_Transform(ST_EndPoint(c2.component), 25833)
                                ) as distance_end_to_end,
                                ST_Distance(
                                    ST_Transform(ST_StartPoint(c1.component), 25833),
                                    ST_Transform(ST_StartPoint(c2.component), 25833)
                                ) as distance_start_to_start,
                                ST_Distance(
                                    ST_Transform(ST_StartPoint(c1.component), 25833),
                                    ST_Transform(ST_EndPoint(c2.component), 25833)
                                ) as distance_start_to_end
                            FROM components c1
                            CROSS JOIN components c2
                            WHERE c1.idx < c2.idx
                            ORDER BY
                                LEAST(
                                    COALESCE(ST_Distance(ST_Transform(ST_EndPoint(c1.component), 25833), ST_Transform(ST_StartPoint(c2.component), 25833)), 999999),
                                    COALESCE(ST_Distance(ST_Transform(ST_EndPoint(c1.component), 25833), ST_Transform(ST_EndPoint(c2.component), 25833)), 999999),
                                    COALESCE(ST_Distance(ST_Transform(ST_StartPoint(c1.component), 25833), ST_Transform(ST_StartPoint(c2.component), 25833)), 999999),
                                    COALESCE(ST_Distance(ST_Transform(ST_StartPoint(c1.component), 25833), ST_Transform(ST_EndPoint(c2.component), 25833)), 999999)
                                )
                            LIMIT 10
                            """
                            try:
                                cur.execute(check_gaps_query, (route_geom_row['route_geometry_json'],))
                                gap_results = cur.fetchall()
                            except Exception as e:
                                # If query fails, skip gap checking
                                gap_results = []

                            if gap_results:
                                for gap_row in gap_results:
                                    # Find minimum distance between components
                                    min_dist = min(
                                        gap_row.get('distance_end_to_start', float('inf')),
                                        gap_row.get('distance_end_to_end', float('inf')),
                                        gap_row.get('distance_start_to_start', float('inf')),
                                        gap_row.get('distance_start_to_end', float('inf'))
                                    )

                                    if min_dist < float('inf') and min_dist > 0.0:
                                        result.add_issue(ValidationIssue(
                                            type='SEGMENT_GAP',
                                            message=f"Gap between MultiLineString components {gap_row['comp1_idx']} and {gap_row['comp2_idx']}: {min_dist:.6f} m. Components should be perfectly connected (distance = 0.0).",
                                            severity=Severity.ERROR,
                                            metadata={
                                                'component1': gap_row['comp1_idx'],
                                                'component2': gap_row['comp2_idx'],
                                                'distance_meters': min_dist,
                                                'distance_end_to_start': gap_row.get('distance_end_to_start'),
                                                'distance_end_to_end': gap_row.get('distance_end_to_end'),
                                                'distance_start_to_start': gap_row.get('distance_start_to_start'),
                                                'distance_start_to_end': gap_row.get('distance_start_to_end')
                                            }
                                        ))
                            # Analyze why MultiLineString couldn't be merged
                            # First check if we have a reason from route_continuous_geometries
                            # Note: multilinestring_reason is from route_continuous_geometries
                            if multilinestring_reason:
                                reason_descriptions = {
                                    'single_linestring': 'Single LineString (not MultiLineString)',
                                    'link_is_multilinestring': 'Individual link is already MultiLineString',
                                    'loop_or_branch': 'Route has loops or branches (traversal found duplicates or incomplete)',
                                    'precision_gap': 'Small gaps (< 1cm) between links due to floating point precision',
                                    'disconnected_components': 'Large gaps between links (e.g., lakes, rivers)',
                                    'traversal_issue': 'Traversal found all links in order, but still MultiLineString (unknown cause)'
                                }
                                reason_desc = reason_descriptions.get(multilinestring_reason, multilinestring_reason)

                                # Map reasons to appropriate severity
                                if multilinestring_reason in ('loop_or_branch', 'disconnected_components'):
                                    severity = Severity.ERROR
                                elif multilinestring_reason in ('link_is_multilinestring', 'traversal_issue'):
                                    severity = Severity.WARNING
                                elif multilinestring_reason == 'precision_gap':
                                    severity = Severity.INFO
                                else:
                                    severity = Severity.WARNING

                                result.add_issue(ValidationIssue(
                                    type='MULTILINESTRING_REASON',
                                    message=f"Route geometry is MultiLineString with {num_geoms} component(s). Reason: {reason_desc}",
                                    severity=severity,
                                    metadata={
                                        'num_components': num_geoms,
                                        'multilinestring_reason': multilinestring_reason
                                    }
                                ))
                            elif merged_type == 'ST_LineString' and merged_num_geoms == 1:
                                # Can be merged - but wasn't in route_geometries
                                result.add_issue(ValidationIssue(
                                    type='MULTILINESTRING_MERGEABLE',
                                    message=f"Route geometry is MultiLineString with {num_geoms} component(s), but ST_LineMerge can merge them into a single LineString. This suggests the link-building process didn't merge them properly.",
                                    severity=Severity.WARNING,
                                    metadata={'num_components': num_geoms, 'can_merge': True}
                                ))
                            elif not gap_results or (gap_results and all(
                            min(
                                gap_row.get('distance_end_to_start', float('inf')),
                                gap_row.get('distance_end_to_end', float('inf')),
                                gap_row.get('distance_start_to_start', float('inf')),
                                gap_row.get('distance_start_to_end', float('inf'))
                            ) == 0.0
                                for gap_row in gap_results
                            )):
                                # No gaps found - check for other issues
                                # Check if segments might be reversed or overlapping
                                check_overlap_query = """
                                WITH geom AS (
                                    SELECT ST_GeomFromGeoJSON(%s) as g
                                ),
                                components AS (
                                    SELECT
                                        generate_series(1, ST_NumGeometries(g)) as idx,
                                        ST_GeometryN(g, generate_series(1, ST_NumGeometries(g))) as component
                                    FROM geom
                                )
                                SELECT
                                    c1.idx as comp1_idx,
                                    c2.idx as comp2_idx,
                                    ST_Overlaps(c1.component, c2.component) as overlaps,
                                    ST_Intersects(c1.component, c2.component) as intersects,
                                    ST_Touches(c1.component, c2.component) as touches
                                FROM components c1
                                CROSS JOIN components c2
                                WHERE c1.idx < c2.idx
                                LIMIT 10
                                """
                                try:
                                    cur.execute(check_overlap_query, (route_geom_row['route_geometry_json'],))
                                    overlap_results = cur.fetchall()

                                    has_overlap = any(row.get('overlaps', False) for row in overlap_results)
                                    has_intersect = any(row.get('intersects', False) for row in overlap_results)

                                    if has_overlap:
                                        result.add_issue(ValidationIssue(
                                            type='MULTILINESTRING_OVERLAPPING',
                                            message=f"Route geometry is MultiLineString with {num_geoms} component(s) that overlap. Overlapping segments prevent ST_LineMerge from creating a single LineString.",
                                            severity=Severity.ERROR,
                                            metadata={'num_components': num_geoms, 'has_overlap': True}
                                        ))
                                    elif has_intersect:
                                        result.add_issue(ValidationIssue(
                                            type='MULTILINESTRING_INTERSECTING',
                                            message=f"Route geometry is MultiLineString with {num_geoms} component(s) that intersect. Intersecting segments may prevent ST_LineMerge from creating a single LineString.",
                                            severity=Severity.WARNING,
                                            metadata={'num_components': num_geoms, 'has_intersect': True}
                                        ))
                                    else:
                                        # No gaps, no overlaps - check if segments are reversed
                                        # ST_LineMerge requires segments to be correctly oriented
                                        # If end of segment1 != start of segment2, they can't merge
                                        check_reversed_query = """
                                        WITH geom AS (
                                            SELECT ST_GeomFromGeoJSON(%s) as g
                                        ),
                                        components AS (
                                            SELECT
                                                generate_series(1, ST_NumGeometries(g)) as idx,
                                                ST_GeometryN(g, generate_series(1, ST_NumGeometries(g))) as component
                                            FROM geom
                                        )
                                        SELECT
                                            c1.idx as comp1_idx,
                                            c2.idx as comp2_idx,
                                            ST_Equals(ST_EndPoint(c1.component), ST_StartPoint(c2.component)) as end_equals_start,
                                            ST_Equals(ST_EndPoint(c1.component), ST_EndPoint(c2.component)) as end_equals_end,
                                            ST_Equals(ST_StartPoint(c1.component), ST_StartPoint(c2.component)) as start_equals_start,
                                            ST_Equals(ST_StartPoint(c1.component), ST_EndPoint(c2.component)) as start_equals_end,
                                            ST_Distance(
                                                ST_Transform(ST_EndPoint(c1.component), 25833),
                                                ST_Transform(ST_StartPoint(c2.component), 25833)
                                            ) as distance_end_to_start
                                        FROM components c1
                                        CROSS JOIN components c2
                                        WHERE c1.idx < c2.idx
                                        ORDER BY c1.idx, c2.idx
                                        LIMIT 10
                                        """
                                        try:
                                            cur.execute(check_reversed_query, (route_geom_row['route_geometry_json'],))
                                            reversed_results = cur.fetchall()
                                        except Exception as e:
                                            # If reversed check fails, skip it
                                            reversed_results = []

                                        # Check if components are touching but not correctly oriented
                                        incorrectly_oriented = []
                                        for rev_row in reversed_results:
                                            end_to_start_dist = rev_row.get('distance_end_to_start', float('inf'))
                                            end_equals_start = rev_row.get('end_equals_start', False)

                                            # If components are very close but end != start, they might be reversed
                                            if end_to_start_dist < 0.001 and not end_equals_start:
                                                incorrectly_oriented.append({
                                                    'comp1': rev_row['comp1_idx'],
                                                    'comp2': rev_row['comp2_idx'],
                                                    'distance': end_to_start_dist
                                                })

                                        if incorrectly_oriented:
                                            result.add_issue(ValidationIssue(
                                                type='MULTILINESTRING_REVERSED_SEGMENTS',
                                                message=f"Route geometry is MultiLineString with {num_geoms} component(s). Components are touching but incorrectly oriented (reversed segments). ST_LineMerge requires end of segment1 to equal start of segment2. Found {len(incorrectly_oriented)} incorrectly oriented component pair(s).",
                                                severity=Severity.ERROR,
                                                metadata={
                                                    'num_components': num_geoms,
                                                    'incorrectly_oriented_pairs': incorrectly_oriented
                                                }
                                            ))
                                        else:
                                            # No gaps, no overlaps, correctly oriented - check ordering
                                            # Check if components are in sequential order (end of comp1 should be near start of comp2)
                                            check_ordering_query = """
                                                WITH geom AS (
                                                    SELECT ST_GeomFromGeoJSON(%s) as g
                                                ),
                                                components AS (
                                                    SELECT
                                                        generate_series(1, ST_NumGeometries(g)) as idx,
                                                        ST_GeometryN(g, generate_series(1, ST_NumGeometries(g))) as component
                                                    FROM geom
                                                )
                                                SELECT
                                                    c1.idx as comp1_idx,
                                                    c2.idx as comp2_idx,
                                                    ST_Distance(
                                                        ST_Transform(ST_EndPoint(c1.component), 25833),
                                                        ST_Transform(ST_StartPoint(c2.component), 25833)
                                                    ) as distance_end_to_start,
                                                    ST_Distance(
                                                        ST_Transform(ST_EndPoint(c1.component), 25833),
                                                        ST_Transform(ST_EndPoint(c2.component), 25833)
                                                    ) as distance_end_to_end
                                                FROM components c1
                                                CROSS JOIN components c2
                                                WHERE c2.idx = c1.idx + 1
                                                ORDER BY c1.idx
                                            """
                                            try:
                                                cur.execute(check_ordering_query, (route_geom_row['route_geometry_json'],))
                                                ordering_results = cur.fetchall()

                                                # Check if sequential components are close
                                                sequential_issues = []
                                                for ord_row in ordering_results:
                                                    end_to_start = ord_row.get('distance_end_to_start', float('inf'))
                                                    end_to_end = ord_row.get('distance_end_to_end', float('inf'))

                                                    # If sequential components are far apart, they're in wrong order
                                                    if end_to_start > 1.0 and end_to_end > 1.0:
                                                        sequential_issues.append({
                                                            'comp1': ord_row['comp1_idx'],
                                                            'comp2': ord_row['comp2_idx'],
                                                            'end_to_start_dist': end_to_start,
                                                            'end_to_end_dist': end_to_end
                                                        })

                                                if sequential_issues:
                                                    result.add_issue(ValidationIssue(
                                                        type='MULTILINESTRING_WRONG_ORDER',
                                                        message=f"Route geometry is MultiLineString with {num_geoms} component(s). Sequential components are far apart, suggesting incorrect ordering. Components should be in geographic sequence. Found {len(sequential_issues)} ordering issue(s).",
                                                        severity=Severity.ERROR,
                                                        metadata={
                                                            'num_components': num_geoms,
                                                            'ordering_issues': sequential_issues
                                                        }
                                                    ))
                                                else:
                                                    # No gaps, no overlaps, correctly oriented, correct order - unknown issue
                                                    result.add_issue(ValidationIssue(
                                                        type='MULTILINESTRING_UNKNOWN_CAUSE',
                                                        message=f"Route geometry is MultiLineString with {num_geoms} component(s) but no obvious issues found (no gaps, no overlaps, correctly oriented, correct order). This may indicate a subtle geometry issue or link-building process problem.",
                                                        severity=Severity.WARNING,
                                                        metadata={'num_components': num_geoms}
                                                    ))
                                            except Exception:
                                                # If ordering check fails, report general issue
                                                result.add_issue(ValidationIssue(
                                                    type='MULTILINESTRING_NO_GAPS',
                                                    message=f"Route geometry is MultiLineString with {num_geoms} component(s) but no gaps found between them. Components may be in incorrect order, or link-building process didn't properly sequence segments.",
                                                    severity=Severity.WARNING,
                                                    metadata={'num_components': num_geoms, 'has_gaps': False}
                                                ))
                                except Exception:
                                    # If overlap check fails, just report general issue
                                    result.add_issue(ValidationIssue(
                                        type='MULTILINESTRING_UNKNOWN',
                                        message=f"Route geometry is MultiLineString with {num_geoms} component(s). Could not determine cause (no gaps found). May indicate reversed segments, overlapping, or ordering issues.",
                                        severity=Severity.WARNING,
                                        metadata={'num_components': num_geoms}
                                    ))
        except Exception as e:
            # If route geometry check fails, continue with segment checks
            route_geom_row = None

        # Also check if raw segments can be merged (to compare with route_geometries)
        # This helps identify if link-building process introduced the MultiLineString
        if segment_objids:
            try:
                raw_merge_query = f"""
                    SELECT
                        ST_GeometryType(ST_LineMerge(ST_Collect(senterlinje::geometry))) as merged_type,
                        ST_NumGeometries(ST_LineMerge(ST_Collect(senterlinje::geometry))) as merged_num_geoms
                    FROM {schema_quoted}.fotrute
                    WHERE objid = ANY(%s)
                      AND senterlinje IS NOT NULL
                """
                cur.execute(raw_merge_query, (segment_objids,))
                raw_merge_result = cur.fetchone()
                if raw_merge_result:
                    raw_merged_type = raw_merge_result[0] if raw_merge_result else None
                    raw_merged_num_geoms = raw_merge_result[1] if raw_merge_result and len(raw_merge_result) > 1 else None

                    # Compare raw segments with route_geometries
                    if route_geom_row and route_geom_row.get('route_geometry_json'):
                        route_geom_type = route_geom_row.get('geom_type')
                        if raw_merged_type == 'ST_LineString' and route_geom_type == 'ST_MultiLineString':
                            # Raw segments can merge, but route_geometries is MultiLineString
                            # This suggests link-building process didn't merge properly
                            result.add_issue(ValidationIssue(
                                type='LINK_BUILDING_MERGE_ISSUE',
                                message=f"Raw segments can be merged into LineString, but route_geometries is MultiLineString. This suggests the link-building process didn't properly merge or orient segments.",
                                severity=Severity.ERROR,
                                metadata={
                                    'raw_segments_type': raw_merged_type,
                                    'route_geometries_type': route_geom_type
                                }
                            ))
            except Exception:
                # If query fails, skip this check
                pass

        # Also check connections between individual segments (original approach)
        # This helps identify which specific segments have gaps
        try:
            connections = find_segment_connections(conn, segment_objids, ROUTE_SCHEMA)
        except Exception:
            connections = {}

        if not connections:
            return result

        # Check gaps in connections
        # Segments should have perfect mapping - any gap > 0 is an error
        # We're interested in 'end_to_start' connections (normal sequential connections)
        # which should have distance = 0.0 for perfect connection

        gaps_found = []
        total_connections_checked = 0
        max_gap = 0.0

        for seg1_objid, conn_list in connections.items():
            for conn in conn_list:
                distance = conn.get('distance', 0.0)
                conn_type = conn.get('type', '')
                seg2_objid = conn.get('target')

                # Only check connections that should be continuous
                # 'end_to_start' is the normal sequential connection
                if conn_type == 'end_to_start':
                    total_connections_checked += 1

                    # Any gap > 0 is an error (segments should be perfectly connected)
                    if distance > 0.0:
                        max_gap = max(max_gap, distance)
                        gaps_found.append({
                            'segment1': str(seg1_objid),
                            'segment2': str(seg2_objid),
                            'distance_m': distance,
                            'connection_type': conn_type
                        })

        # Report all gaps as errors (perfect mapping required)
        if gaps_found:
            for gap in gaps_found:
                result.add_issue(ValidationIssue(
                    type='SEGMENT_GAP',
                    message=f"Gap between segments {gap['segment1']} and {gap['segment2']}: {gap['distance_m']:.6f} m. Segments should be perfectly connected (distance = 0.0). This prevents ST_LineMerge from creating a single LineString.",
                    severity=Severity.ERROR,
                    affected_segments=[gap['segment1'], gap['segment2']],
                    metadata={
                        'distance_meters': gap['distance_m'],
                        'connection_type': gap['connection_type']
                    }
                ))

            # Add summary metadata
            result.metadata['segment_gap_count'] = len(gaps_found)
            result.metadata['segment_gap_max_meters'] = max_gap
            result.metadata['segment_gap_total_checked'] = total_connections_checked

        return result
