#!/usr/bin/env python3
"""CLI tool for querying route segments from the Stiflyt backend API.

This CLI tool provides a command-line interface to query route segments
filtered by rutenummer prefix and/or vedlikeholdsansvarlig.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from .api_client import RouteSegmentsClient, RoutesClient, APIError, ConnectionError, AuthenticationError, APIResponseError
from .config import CLIConfig
from .formatters import format_json, format_table, format_csv, format_text_summary, format_complete_route_table, format_complete_route_csv, format_route_registry_yaml, format_routes_table, format_routes_csv, format_routes_summary
from .find_available_numbers import analyze_available_numbers, format_available_numbers, parse_rutenummer, get_existing_rutenummer


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Query routes and route segments from Stiflyt backend API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query routes (new routes API)
  %(prog)s --list-routes
  %(prog)s --list-routes --prefix bre
  %(prog)s --list-routes --prefix bre --format json
  %(prog)s --list-routes --bbox 10.0,59.0,11.0,60.0
  %(prog)s --get-route bre10
  %(prog)s --get-route bre10 --format json
  %(prog)s --get-route-segments bre10  # Physical route segments
  %(prog)s --get-route-links bre10      # Routing topology links
  %(prog)s --get-segment-lokalid 00661e35-bce5-4106-932f-48f6197dfb58

  # Query segments with rutenummer starting with "bre" and vedlikeholdsansvarlig "DNT Oslo"
  %(prog)s --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo"

  # Query with just rutenummer prefix
  %(prog)s --rutenummer-prefix bre

  # Get complete route (combines all segments)
  %(prog)s --complete-route bre10

  # Complete route with JSON output
  %(prog)s --complete-route bre10 --format json

  # Complete route with geometry
  %(prog)s --complete-route bre10 --include-geometry

  # Complete route with segment details
  %(prog)s --complete-route bre10 --include-segments

  # JSON output
  %(prog)s --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo" --format json

  # CSV output with geometry
  %(prog)s --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo" --format csv --include-geometry --output results.csv

  # Custom API URL
  %(prog)s --rutenummer-prefix bre --api-url http://production.example.com/api/v1

  # Pagination
  %(prog)s --rutenummer-prefix bre --limit 50 --offset 100

  # Find available route numbers
  %(prog)s --rutenummer-prefix bre --find-available

  # Validate route segment metadata
  %(prog)s --validate bre10
  %(prog)s --validate bre10 --format json

  # List routes with multilinestring_reason
  %(prog)s --list-multilinestring-reasons
  %(prog)s --list-multilinestring-reasons --reason-filter disconnected_components
  %(prog)s --list-multilinestring-reasons --format json

  # Test ruteinfopunkt lookup (debug)
  %(prog)s --test-ruteinfopunkt 7.710764899 61.809237843 --rutenummer bre9
        """
    )

    # Routes API commands (new)
    parser.add_argument(
        '--list-routes',
        action='store_true',
        help='List all routes (uses new routes API)'
    )
    parser.add_argument(
        '--get-route',
        type=str,
        metavar='RUTENUMMER',
        help='Get a single route by rutenummer (uses new routes API)'
    )
    parser.add_argument(
        '--get-route-segments',
        type=str,
        metavar='RUTENUMMER',
        help='Get physical route segments for a route (from route_segments view). Shows individual segments with geometry and length.'
    )
    parser.add_argument(
        '--get-route-links',
        type=str,
        metavar='RUTENUMMER',
        help='Get routing links for a route (from links table). Links represent routing topology between junctions and may combine multiple segments. Useful for navigation/routing.'
    )
    parser.add_argument(
        '--get-segment-lokalid',
        type=str,
        metavar='LOKALID',
        help='Get a single segment by lokalid (stable UUID) with all fields'
    )
    parser.add_argument(
        '--prefix',
        type=str,
        help='Filter routes by prefix (e.g., "bre", "jot", "ron") - used with --list-routes'
    )
    parser.add_argument(
        '--bbox',
        type=str,
        help='Bounding box as "xmin,ymin,xmax,ymax" in WGS84 - used with --list-routes'
    )

    # Complete route mode
    parser.add_argument(
        '--complete-route',
        type=str,
        metavar='RUTENUMMER',
        help='Get complete route by combining all segments with the same rutenummer (e.g., "bre10")'
    )

    # Filters (at least one required for segment query mode)
    parser.add_argument(
        '--rutenummer-prefix',
        type=str,
        help='Filter by route number prefix (e.g., "bre")'
    )
    parser.add_argument(
        '--vedlikeholdsansvarlig',
        type=str,
        help='Filter by organization (e.g., "DNT Oslo")'
    )

    # Output options
    parser.add_argument(
        '--format',
        choices=['json', 'table', 'csv', 'yaml'],
        default='table',
        help='Output format (default: table)'
    )
    parser.add_argument(
        '--export-registry',
        nargs='+',
        metavar='AREA',
        help='Export routes for given area(s) (e.g., bre jot ron) as YAML registry format. Queries database directly.'
    )
    parser.add_argument(
        '--include-geometry',
        action='store_true',
        help='Include GeoJSON geometry in response (only for JSON format)'
    )
    parser.add_argument(
        '--include-segments',
        action='store_true',
        help='Include individual segment details (for complete route mode)'
    )
    parser.add_argument(
        '--no-endpoint-names',
        action='store_true',
        help='Skip lookup of from/to place names (for complete route mode)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Write output to file instead of stdout'
    )
    parser.add_argument(
        '--no-summary',
        action='store_true',
        help='Do not show summary information (table format only)'
    )

    # Pagination
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of results (default: 100, max: 1000)'
    )
    parser.add_argument(
        '--offset',
        type=int,
        default=0,
        help='Offset for pagination (default: 0)'
    )

    # Configuration
    parser.add_argument(
        '--api-url',
        type=str,
        help='API base URL (default: http://localhost:8000/api/v1 or STIFLYT_API_URL env var)'
    )
    parser.add_argument(
        '--username',
        type=str,
        help='HTTP Basic Auth username (or STIFLYT_USERNAME env var)'
    )
    parser.add_argument(
        '--password',
        type=str,
        help='HTTP Basic Auth password (or STIFLYT_PASSWORD env var)'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='Request timeout in seconds (default: 30)'
    )

    # Verbosity
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show verbose error messages'
    )

    # Find available numbers
    parser.add_argument(
        '--find-available',
        action='store_true',
        help='Find available route numbers for the given prefix (requires --rutenummer-prefix)'
    )

    # Validation
    parser.add_argument(
        '--validate',
        type=str,
        metavar='RUTENUMMER',
        help='Validate route segment metadata for consistency and correctness'
    )
    parser.add_argument(
        '--list-multilinestring-reasons',
        action='store_true',
        help='List all routes with their multilinestring_reason values from route_continuous_geometries'
    )
    parser.add_argument(
        '--reason-filter',
        type=str,
        metavar='REASON',
        help='Filter routes by multilinestring_reason value (used with --list-multilinestring-reasons). Valid values: single_linestring, link_is_multilinestring, loop_or_branch, precision_gap, disconnected_components, traversal_issue'
    )

    # Debug/test options
    parser.add_argument(
        '--test-ruteinfopunkt',
        nargs=2,
        metavar=('LON', 'LAT'),
        help='Test ruteinfopunkt lookup for given coordinates (lon lat)'
    )
    parser.add_argument(
        '--test-radius',
        type=float,
        default=500.0,
        help='Search radius in meters for test-ruteinfopunkt (default: 500.0)'
    )

    args = parser.parse_args()

    # Handle test-ruteinfopunkt mode
    if args.test_ruteinfopunkt:
        try:
            lon = float(args.test_ruteinfopunkt[0])
            lat = float(args.test_ruteinfopunkt[1])
        except ValueError:
            parser.error("--test-ruteinfopunkt requires valid numeric coordinates (lon lat)")

        from services.database import db_connection
        from services.route_endpoints import lookup_name_in_ruteinfopunkt, lookup_name_in_stedsnavn, lookup_name_in_anchor_nodes
        import json

        print(f"Testing name lookup for point: ({lon}, {lat})")
        print(f"Search radius: {args.test_radius} m")
        if args.rutenummer_prefix:
            print(f"Filtering by rutenummer: {args.rutenummer_prefix}*")
        print("")

        with db_connection() as conn:
            # Test anchor nodes
            print("1. Checking anchor_nodes...")
            anchor_result = lookup_name_in_anchor_nodes(conn, lon, lat, search_radius_meters=args.test_radius)
            if anchor_result:
                print(f"   ✓ Found: {anchor_result.get('name')} (source: {anchor_result.get('source')}, distance: {anchor_result.get('distance_meters'):.2f} m)")
            else:
                print("   ✗ Not found")

            # Test ruteinfopunkt
            print("\n2. Checking ruteinfopunkt...")
            rutenummer = args.rutenummer_prefix if args.rutenummer_prefix else None
            # Check if view exists and has data
            from services.database import ROUTE_SCHEMA
            from psycopg.rows import dict_row
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.views
                        WHERE table_schema = %s AND table_name = 'ruteinfopunkt'
                    ) as exists
                """, (ROUTE_SCHEMA,))
                result = cur.fetchone()
                view_exists = result.get('exists') if result else False
                print(f"   View exists: {view_exists}")

                if view_exists:
                    # Count total ruteinfopunkt
                    cur.execute(f"SELECT COUNT(*) as count FROM {ROUTE_SCHEMA}.ruteinfopunkt")
                    result = cur.fetchone()
                    total_count = result['count'] if result else 0
                    print(f"   Total ruteinfopunkt in view: {total_count}")

                    # Count with names (using informasjon column)
                    cur.execute(f"SELECT COUNT(*) as count FROM {ROUTE_SCHEMA}.ruteinfopunkt WHERE informasjon IS NOT NULL")
                    result = cur.fetchone()
                    with_names = result['count'] if result else 0
                    print(f"   Ruteinfopunkt with informasjon: {with_names}")

                    # Try query (filtered to hytter and parkering only, prioritized)
                    filter_values = ['12', '42', '43', '44', '22']
                    cur.execute(f"""
                        SELECT
                            objid,
                            informasjon as navn,
                            tilrettelegging,
                            ST_Distance(
                                ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                                ST_Transform(posisjon::geometry, 25833)
                            ) as distance_meters
                        FROM {ROUTE_SCHEMA}.ruteinfopunkt
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
                        LIMIT 5
                    """, (lon, lat, lon, lat, args.test_radius, filter_values))
                    results = cur.fetchall()
                    print(f"   Found {len(results)} ruteinfopunkt (hytter/parkering only) within {args.test_radius}m:")
                    for r in results:
                        tilrettelegging = r.get('tilrettelegging', 'N/A')
                        print(f"     - objid: {r.get('objid')}, navn: {r.get('navn')}, tilrettelegging: {tilrettelegging}, distance: {r.get('distance_meters'):.2f} m")

            ruteinfopunkt_result = lookup_name_in_ruteinfopunkt(conn, lon, lat, rutenummer, search_radius_meters=args.test_radius)
            if ruteinfopunkt_result:
                print(f"   ✓ Found: {ruteinfopunkt_result.get('name')} (source: {ruteinfopunkt_result.get('source')}, distance: {ruteinfopunkt_result.get('distance_meters'):.2f} m)")
            else:
                print("   ✗ Not found")

            # Test stedsnavn
            print("\n3. Checking stedsnavn...")
            stedsnavn_result = lookup_name_in_stedsnavn(conn, lon, lat, search_radius_meters=args.test_radius)
            if stedsnavn_result:
                print(f"   ✓ Found: {stedsnavn_result.get('name')} (source: {stedsnavn_result.get('source')}, distance: {stedsnavn_result.get('distance_meters'):.2f} m)")
            else:
                print("   ✗ Not found")

            # Test combined lookup
            print("\n4. Combined lookup (lookup_endpoint_name)...")
            from services.route_endpoints import lookup_endpoint_name
            combined_result = lookup_endpoint_name(conn, lon, lat, rutenummer)
            if combined_result:
                print(f"   ✓ Result: {combined_result.get('name')} (source: {combined_result.get('source')}, distance: {combined_result.get('distance_meters'):.2f} m)")
            else:
                print("   ✗ Not found")

            if args.format == "json":
                result = {
                    "coordinates": [lon, lat],
                    "search_radius_meters": args.test_radius,
                    "rutenummer_filter": rutenummer,
                    "anchor_node": anchor_result,
                    "ruteinfopunkt": ruteinfopunkt_result,
                    "stedsnavn": stedsnavn_result,
                    "combined_result": combined_result
                }
                print("\n" + json.dumps(result, indent=2, ensure_ascii=False))

        sys.exit(0)

    # Handle list multilinestring reasons mode
    if args.list_multilinestring_reasons:
        from services.database import db_connection, ROUTE_SCHEMA, quote_identifier, validate_schema_name
        from psycopg.rows import dict_row

        try:
            with db_connection() as conn:
                if not validate_schema_name(ROUTE_SCHEMA):
                    print(f"Error: Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}", file=sys.stderr)
                    sys.exit(1)

                schema_quoted = quote_identifier(ROUTE_SCHEMA)

                # Check if table exists
                with conn.cursor(row_factory=dict_row) as cur:
                    table_check_query = """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s
                              AND table_name = 'route_continuous_geometries'
                        ) as table_exists
                    """
                    cur.execute(table_check_query, (ROUTE_SCHEMA,))
                    table_exists_row = cur.fetchone()
                    table_exists = table_exists_row.get('table_exists') if table_exists_row else False

                    if not table_exists:
                        print(f"Error: route_continuous_geometries table does not exist in schema {ROUTE_SCHEMA}.", file=sys.stderr)
                        print("       This table is created by build-links. Please run build-links first.", file=sys.stderr)
                        sys.exit(1)

                    # Check if column exists
                    column_check_query = """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = %s
                              AND table_name = 'route_continuous_geometries'
                              AND column_name = 'multilinestring_reason'
                        ) as column_exists
                    """
                    cur.execute(column_check_query, (ROUTE_SCHEMA,))
                    column_exists_row = cur.fetchone()
                    column_exists = column_exists_row.get('column_exists') if column_exists_row else False

                    if not column_exists:
                        print(f"Warning: multilinestring_reason column does not exist in route_continuous_geometries.", file=sys.stderr)
                        print("         This column was added in a recent version. Please run build-links with the latest version.", file=sys.stderr)
                        sys.exit(1)

                    # Build query - prioritize routes with non-single_linestring reasons
                    valid_reasons = {
                        'single_linestring',
                        'link_is_multilinestring',
                        'loop_or_branch',
                        'precision_gap',
                        'disconnected_components',
                        'traversal_issue'
                    }

                    if args.reason_filter:
                        if args.reason_filter not in valid_reasons:
                            print(f"Error: Invalid reason filter '{args.reason_filter}'. Valid values: {', '.join(sorted(valid_reasons))}", file=sys.stderr)
                            sys.exit(1)
                        reason_filter = args.reason_filter
                    else:
                        reason_filter = None

                    # Query routes - prioritize non-single_linestring if no filter
                    if reason_filter:
                        query = f"""
                            SELECT
                                rutenummer,
                                continuous_geometry,
                                multilinestring_reason,
                                ST_GeometryType(continuous_geometry) as geom_type,
                                ST_NumGeometries(continuous_geometry) as num_geoms
                            FROM {schema_quoted}.route_continuous_geometries
                            WHERE continuous_geometry IS NOT NULL
                              AND multilinestring_reason = %s
                            ORDER BY rutenummer
                        """
                        cur.execute(query, (reason_filter,))
                    else:
                        # Get routes with non-single_linestring first, then others
                        query = f"""
                            (
                                SELECT
                                    rutenummer,
                                    continuous_geometry,
                                    multilinestring_reason,
                                    ST_GeometryType(continuous_geometry) as geom_type,
                                    ST_NumGeometries(continuous_geometry) as num_geoms
                                FROM {schema_quoted}.route_continuous_geometries
                                WHERE continuous_geometry IS NOT NULL
                                  AND multilinestring_reason != 'single_linestring'
                                ORDER BY rutenummer
                            )
                            UNION ALL
                            (
                                SELECT
                                    rutenummer,
                                    continuous_geometry,
                                    multilinestring_reason,
                                    ST_GeometryType(continuous_geometry) as geom_type,
                                    ST_NumGeometries(continuous_geometry) as num_geoms
                                FROM {schema_quoted}.route_continuous_geometries
                                WHERE continuous_geometry IS NOT NULL
                                  AND multilinestring_reason = 'single_linestring'
                                ORDER BY rutenummer
                            )
                        """
                        cur.execute(query)

                    routes = cur.fetchall()

                    if not routes:
                        print("No routes found in route_continuous_geometries.")
                        if reason_filter:
                            print(f"  (filtered by reason: {reason_filter})")
                        sys.exit(0)

                    # Count reasons
                    reason_counts = {}
                    for route in routes:
                        reason = route.get('multilinestring_reason')
                        if reason:
                            reason_counts[reason] = reason_counts.get(reason, 0) + 1

                    # Output based on format
                    if args.format == 'json':
                        import json
                        output = {
                            'total_routes': len(routes),
                            'reason_distribution': reason_counts,
                            'routes': [
                                {
                                    'rutenummer': r['rutenummer'],
                                    'multilinestring_reason': r.get('multilinestring_reason'),
                                    'geom_type': r.get('geom_type'),
                                    'num_geoms': r.get('num_geoms')
                                }
                                for r in routes
                            ]
                        }
                        print(json.dumps(output, indent=2, ensure_ascii=False))
                    else:
                        # Human-readable format
                        print("=" * 80)
                        print("ROUTES WITH MULTILINESTRING REASON")
                        print("=" * 80)
                        print(f"Total routes: {len(routes)}")
                        if reason_filter:
                            print(f"Filtered by reason: {reason_filter}")
                        print()

                        print("Reason distribution:")
                        print("-" * 80)
                        for reason in sorted(valid_reasons):
                            count = reason_counts.get(reason, 0)
                            if count > 0:
                                percentage = (count / len(routes)) * 100
                                print(f"  {reason:30s}: {count:4d} route(s) ({percentage:5.1f}%)")
                        print()

                        print("Routes:")
                        print("-" * 80)
                        for route in routes:
                            reason = route.get('multilinestring_reason')
                            geom_type = route.get('geom_type')
                            num_geoms = route.get('num_geoms', 1)
                            print(f"  {route['rutenummer']:15s} | {reason:30s} | {geom_type:20s} | {num_geoms} part(s)")
                        print()

                        # Show all routes with issues
                        problematic_routes = [r for r in routes if r.get('multilinestring_reason') != 'single_linestring']
                        if problematic_routes:
                            print(f"Routes with issues (non-single_linestring): {len(problematic_routes)}")
                            print("-" * 80)
                            for route in problematic_routes:  # Show all
                                reason = route.get('multilinestring_reason')
                                geom_type = route.get('geom_type')
                                num_geoms = route.get('num_geoms', 1)
                                reason_descriptions = {
                                    'link_is_multilinestring': 'Individual link is already MultiLineString',
                                    'loop_or_branch': 'Route has loops or branches',
                                    'precision_gap': 'Small gaps (< 1cm) due to floating point precision',
                                    'disconnected_components': 'Large gaps (e.g., lakes, rivers)',
                                    'traversal_issue': 'Traversal issue (unknown cause)'
                                }
                                reason_desc = reason_descriptions.get(reason, reason)
                                print(f"  {route['rutenummer']:15s} | {reason:30s} | {reason_desc}")
                            print()

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

        sys.exit(0)

    # Handle validation mode
    if args.validate:
        from services.database import db_connection, ROUTE_SCHEMA, quote_identifier, validate_schema_name
        from services.validators import get_validator_registry
        from psycopg.rows import dict_row
        from collections import defaultdict

        rutenummer = args.validate

        try:
            with db_connection() as conn:
                if not validate_schema_name(ROUTE_SCHEMA):
                    print(f"Error: Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}", file=sys.stderr)
                    sys.exit(1)

                schema_quoted = quote_identifier(ROUTE_SCHEMA)

                # Get all segments for the route with all metadata including length
                # Note: A segment can have multiple fotruteinfo rows (if it's part of multiple routes)
                query = f"""
                    SELECT
                        f.objid as segment_objid,
                        f.lokalid as segment_lokalid,
                        fi.rutenummer,
                        fi.rutenavn,
                        fi.vedlikeholdsansvarlig,
                        fi.rutetype,
                        fi.gradering,
                        fi.objid as fotruteinfo_objid,
                        ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
                    FROM {schema_quoted}.fotrute f
                    JOIN {schema_quoted}.fotruteinfo fi ON fi.fotrute_fk = f.objid
                    WHERE fi.rutenummer = %s
                    ORDER BY f.objid, fi.objid
                """

                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (rutenummer,))
                    all_rows = cur.fetchall()

                if not all_rows:
                    print(f"Error: No segments found for route '{rutenummer}'", file=sys.stderr)
                    sys.exit(1)

                # Group by segment_objid to handle multiple fotruteinfo rows per segment
                segments_dict = defaultdict(list)
                for row in all_rows:
                    segments_dict[row['segment_objid']].append(row)

                segments = list(segments_dict.values())  # List of lists, each inner list is fotruteinfo rows for one segment

                # Prepare segment metadata dump for output
                segment_metadata_dump = []
                for segment_objid, fotruteinfo_rows in sorted(segments_dict.items()):
                    segment_length = fotruteinfo_rows[0].get('length_meters') if fotruteinfo_rows else None
                    segment_lokalid = fotruteinfo_rows[0].get('segment_lokalid') if fotruteinfo_rows else None
                    segment_metadata_dump.append({
                        'segment_objid': segment_objid,
                        'segment_lokalid': segment_lokalid,
                        'length_meters': float(segment_length) if segment_length is not None else None,
                        'fotruteinfo_count': len(fotruteinfo_rows),
                        'fotruteinfo_rows': [
                            {
                                'fotruteinfo_objid': row['fotruteinfo_objid'],
                                'rutenummer': row['rutenummer'],
                                'rutenavn': row.get('rutenavn'),
                                'vedlikeholdsansvarlig': row.get('vedlikeholdsansvarlig'),
                                'rutetype': row.get('rutetype'),
                                'gradering': row.get('gradering'),
                            }
                            for row in fotruteinfo_rows
                        ]
                    })

                # Prepare route data for validators
                route_data = {
                    'rutenummer': rutenummer,
                    'segments_dict': segments_dict,
                    'all_rows': all_rows,
                }

                # Run validators
                registry = get_validator_registry()
                validation_result = registry.run_validators(route_data, conn)

                # Convert ValidationResult to old format for compatibility
                errors = [issue.to_dict() for issue in validation_result.errors]
                warnings = [issue.to_dict() for issue in validation_result.warnings]
                geometry_info = [issue.to_dict() for issue in validation_result.info]

                # Get link count for summary (from validation result metadata if available)
                link_count = validation_result.metadata.get('link_count', 0)
                link_lengths = []
                if link_count == 0:
                    # Fallback: query directly
                    link_count_query = f"""
                        SELECT COUNT(DISTINCT lwr.link_id) as link_count
                        FROM {schema_quoted}.links_with_routes lwr
                        WHERE %s = ANY(lwr.rutenummer_list)
                    """
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(link_count_query, (rutenummer,))
                        link_count_row = cur.fetchone()
                        link_count = link_count_row.get('link_count', 0) if link_count_row else 0
                    # Load link lengths for reporting
                    link_lengths_query = f"""
                        SELECT lwr.link_id, lwr.length_m
                        FROM {schema_quoted}.links_with_routes lwr
                        WHERE %s = ANY(lwr.rutenummer_list)
                        ORDER BY lwr.link_id
                    """
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(link_lengths_query, (rutenummer,))
                        link_lengths = cur.fetchall()
                else:
                    link_lengths_query = f"""
                        SELECT lwr.link_id, lwr.length_m
                        FROM {schema_quoted}.links_with_routes lwr
                        WHERE %s = ANY(lwr.rutenummer_list)
                        ORDER BY lwr.link_id
                    """
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(link_lengths_query, (rutenummer,))
                        link_lengths = cur.fetchall()

                # Extract summary values from validation result metadata
                # Collect unique values for summary
                all_rutenavn = []
                all_vedlikeholdsansvarlig = []
                all_rutetype = []
                all_gradering = []

                for segment_objid, fotruteinfo_rows in segments_dict.items():
                    for row in fotruteinfo_rows:
                        if row.get('rutenavn'):
                            all_rutenavn.append(row.get('rutenavn'))
                        if row.get('vedlikeholdsansvarlig'):
                            all_vedlikeholdsansvarlig.append(row.get('vedlikeholdsansvarlig'))
                        if row.get('rutetype'):
                            all_rutetype.append(row.get('rutetype'))
                        if row.get('gradering'):
                            all_gradering.append(row.get('gradering'))

                # Build validation report (using ValidationResult status)
                validation_report = {
                    'rutenummer': rutenummer,
                    'segment_count': len(segments_dict),
                    'link_count': link_count,
                    'link_lengths': [
                        {
                            'link_id': row.get('link_id'),
                            'length_meters': float(row['length_m']) if row.get('length_m') is not None else None
                        }
                        for row in link_lengths
                    ],
                    'status': validation_result.get_status(),
                    'errors': errors,
                    'warnings': warnings,
                    'geometry_info': geometry_info,
                    'segment_metadata': segment_metadata_dump,
                    'summary': {
                        'total_segments': len(segments_dict),
                        'total_fotruteinfo_rows': len(all_rows),
                        'total_links': link_count,
                        'error_count': len(errors),
                        'warning_count': len(warnings),
                        'geometry_error_count': len([e for e in errors if 'geometry' in e.get('type', '').lower() or 'link' in e.get('type', '').lower()]),
                        'geometry_warning_count': len([w for w in warnings if 'geometry' in w.get('type', '').lower() or 'link' in w.get('type', '').lower()]),
                        'rutenavn_values': sorted(set(all_rutenavn)) if all_rutenavn else None,
                        'vedlikeholdsansvarlig_values': sorted(set(all_vedlikeholdsansvarlig)) if all_vedlikeholdsansvarlig else None,
                        'rutetype_values': sorted(set(all_rutetype)) if all_rutetype else None,
                        'gradering_values': sorted(set(all_gradering)) if all_gradering else None,
                    }
                }

                # Output results
                if args.format == 'json':
                    print(format_json(validation_report))
                else:
                    # Human-readable table format
                    print("=" * 80)
                    print(f"VALIDATION REPORT: {rutenummer}")
                    print("=" * 80)
                    print(f"Total segments: {len(segments_dict)}")
                    print(f"Total fotruteinfo rows: {len(all_rows)}")
                    print(f"Total links: {link_count}")
                    if link_lengths:
                        print("Link lengths:")
                        for row in link_lengths:
                            length_m = row.get('length_m')
                            length_str = f"{length_m:.1f} m" if length_m is not None else "N/A"
                            print(f"  Link {row.get('link_id')}: {length_str}")
                    print(f"Status: {validation_report['status']}")
                    print()

                    # Dump all segment metadata first
                    print("SEGMENT METADATA DUMP:")
                    print("-" * 80)
                    for seg_meta in segment_metadata_dump:
                        length_str = f"{seg_meta['length_meters']:.1f} m" if seg_meta.get('length_meters') is not None else "N/A"
                        lokalid = seg_meta.get('segment_lokalid') or '(null)'
                        print(f"Segment {seg_meta['segment_objid']} (lokalid: {lokalid}, length: {length_str}, {seg_meta['fotruteinfo_count']} fotruteinfo row(s)):")
                        for i, row in enumerate(seg_meta['fotruteinfo_rows'], 1):
                            print(f"  Row {i} (fotruteinfo_objid: {row['fotruteinfo_objid']}):")
                            print(f"    rutenummer: {row['rutenummer']}")
                            print(f"    rutenavn: {row['rutenavn'] or '(null)'}")
                            print(f"    vedlikeholdsansvarlig: {row['vedlikeholdsansvarlig'] or '(null)'}")
                            print(f"    rutetype: {row['rutetype'] or '(null)'}")
                            print(f"    gradering: {row['gradering'] or '(null)'}")
                        print()
                    print()

                    if errors:
                        print(f"ERRORS ({len(errors)}):")
                        print("-" * 80)
                        for i, err in enumerate(errors, 1):
                            print(f"{i}. [{err['type']}] {err['message']}")
                            if 'segment_objid' in err:
                                print(f"   Segment: {err['segment_objid']}")
                            if 'fotruteinfo_objids' in err:
                                print(f"   fotruteinfo_objids: {err['fotruteinfo_objids']}")
                            if 'values' in err:
                                print(f"   Values: {err['values']}")
                            if 'missing_fields' in err:
                                print(f"   Missing fields: {err['missing_fields']}")
                            if 'link_id' in err:
                                print(f"   Link ID: {err['link_id']}")
                        print()

                    if warnings:
                        print(f"WARNINGS ({len(warnings)}):")
                        print("-" * 80)
                        for i, warn in enumerate(warnings, 1):
                            print(f"{i}. [{warn['type']}] {warn['message']}")
                            if 'values' in warn:
                                print(f"   Values: {warn['values']}")
                            if 'value_by_segment' in warn:
                                print(f"   Segments by value:")
                                for val in sorted(warn['value_by_segment'].keys()):
                                    segment_ids = sorted(warn['value_by_segment'][val])
                                    print(f"     \"{val}\": {segment_ids}")
                            if 'value' in warn and 'count' in warn:
                                print(f"   Value: {warn['value']}, Count: {warn['count']}")
                            if 'segment_objid' in warn:
                                print(f"   Segment: {warn['segment_objid']}")
                            if 'segment_objids' in warn:
                                print(f"   Affected segments: {warn['segment_objids']}")
                            if 'link_id' in warn:
                                print(f"   Link ID: {warn['link_id']}")
                            if 'link1_id' in warn and 'link2_id' in warn:
                                print(f"   Links: {warn['link1_id']} -> {warn['link2_id']}")
                            if 'link_ids' in warn:
                                print(f"   Link IDs: {warn['link_ids']}")
                            if 'gap_meters' in warn:
                                print(f"   Gap: {warn['gap_meters']:.2f} m")
                            if 'node_id' in warn and 'degree' in warn:
                                print(f"   Node ID: {warn['node_id']}, Degree: {warn['degree']}")
                            if 'reversible_sequence_length' in warn:
                                print(f"   Reversible sequence length: {warn['reversible_sequence_length']}")
                                print(f"   Reversed links count: {warn['reversed_links_count']}")
                                if 'unvisited_links' in warn and warn['unvisited_links']:
                                    print(f"   Unvisited links: {warn['unvisited_links']}")
                            if 'reversed_connections' in warn:
                                print(f"   Reversed connections:")
                                for conn in warn['reversed_connections'][:5]:  # Show first 5
                                    print(f"     Link {conn['link1_id']} {conn['connection_type']} Link {conn['link2_id']} (node: {conn['node_id']})")
                                if len(warn['reversed_connections']) > 5:
                                    print(f"     ... and {len(warn['reversed_connections']) - 5} more")
                        print()

                    # Show geometry info
                    if geometry_info:
                        print(f"GEOMETRY INFO ({len(geometry_info)}):")
                        print("-" * 80)
                        for i, info in enumerate(geometry_info, 1):
                            print(f"{i}. [{info['type']}] {info['message']}")
                            if 'link_ids' in info:
                                print(f"   Link IDs: {info['link_ids']}")
                            if 'link1_id' in info and 'link2_id' in info:
                                print(f"   Links: {info['link1_id']} -> {info['link2_id']}")
                            if 'gap_meters' in info:
                                print(f"   Gap: {info['gap_meters']:.2f} m")
                            if 'component_count' in info:
                                print(f"   Components: {info['component_count']}")
                                if 'main_component_link_ids' in info:
                                    print(f"   Main component link IDs: {info['main_component_link_ids']}")
                                if 'appendix_component_link_ids' in info:
                                    for i, appendix in enumerate(info['appendix_component_link_ids'], 1):
                                        print(f"   Appendix {i} link IDs: {appendix}")
                            if 'reversible_sequence_length' in info:
                                print(f"   Reversible sequence length: {info['reversible_sequence_length']}")
                                print(f"   Reversed links count: {info['reversed_links_count']}")
                                if 'unvisited_links' in info and info['unvisited_links']:
                                    print(f"   Unvisited links: {info['unvisited_links']}")
                            if 'reversed_connections' in info:
                                print(f"   Reversed connections:")
                                for conn in info['reversed_connections'][:5]:  # Show first 5
                                    print(f"     Link {conn['link1_id']} {conn['connection_type']} Link {conn['link2_id']} (node: {conn['node_id']})")
                                if len(info['reversed_connections']) > 5:
                                    print(f"     ... and {len(info['reversed_connections']) - 5} more")
                            # Show multilinestring_reason if available
                            if 'multilinestring_reason' in info and info['multilinestring_reason']:
                                reason_descriptions = {
                                    'single_linestring': 'Single LineString (not MultiLineString)',
                                    'link_is_multilinestring': 'Individual link is already MultiLineString',
                                    'loop_or_branch': 'Route has loops or branches (traversal found duplicates or incomplete)',
                                    'precision_gap': 'Small gaps (< 1cm) between links due to floating point precision',
                                    'disconnected_components': 'Large gaps between links (e.g., lakes, rivers)',
                                    'traversal_issue': 'Traversal found all links in order, but still MultiLineString (unknown cause)'
                                }
                                reason = info['multilinestring_reason']
                                reason_desc = reason_descriptions.get(reason, reason)
                                print(f"   MultiLineString reason: {reason_desc} ({reason})")
                        print()

                    # Show multilinestring_reason from metadata if available
                    multilinestring_reason = validation_result.metadata.get('multilinestring_reason')
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
                        print("MULTILINESTRING REASON:")
                        print("-" * 80)
                        print(f"Reason: {reason_desc} ({multilinestring_reason})")
                        if multilinestring_reason == 'single_linestring':
                            print("Note: This indicates perfect continuous geometry (LineString, not MultiLineString)")
                        else:
                            print("Note: This explains why the route geometry is MultiLineString instead of LineString")
                        print()

                    if not errors and not warnings:
                        print("✓ All validation passed")
                        print()

                    # Show summary
                    print("SUMMARY:")
                    print("-" * 80)
                    summary = validation_report['summary']
                    print(f"Metadata errors: {summary['error_count'] - summary['geometry_error_count']}")
                    print(f"Metadata warnings: {summary['warning_count'] - summary['geometry_warning_count']}")
                    print(f"Geometry errors: {summary['geometry_error_count']}")
                    print(f"Geometry warnings: {summary['geometry_warning_count']}")
                    print()

                    if summary['rutenavn_values']:
                        print(f"rutenavn: {', '.join(summary['rutenavn_values'])}")
                    else:
                        print("rutenavn: (not set)")

                    if summary['vedlikeholdsansvarlig_values']:
                        print(f"vedlikeholdsansvarlig: {', '.join(summary['vedlikeholdsansvarlig_values'])}")
                    else:
                        print("vedlikeholdsansvarlig: (not set)")

                    if summary['rutetype_values']:
                        print(f"rutetype: {', '.join(summary['rutetype_values'])}")

                    if summary['gradering_values']:
                        print(f"gradering: {', '.join(summary['gradering_values'])}")

                    print("=" * 80)

        except Exception as e:
            print(f"Error during validation: {type(e).__name__}: {e}", file=sys.stderr)
            import traceback
            if args.verbose:
                traceback.print_exc()
            else:
                # Show traceback even without verbose for debugging
                print("Traceback:", file=sys.stderr)
                traceback.print_exc()
            sys.exit(1)

        sys.exit(0)

    # Handle export-registry mode
    if args.export_registry:
        from services.database import db_connection, get_route_schema, quote_identifier
        from services.route_endpoints import extract_route_endpoints, lookup_endpoint_name
        from collections import defaultdict
        from psycopg.rows import dict_row

        # Validate area prefixes
        areas = [area.lower() for area in args.export_registry]
        for area in areas:
            if len(area) != 3 or not area.isalpha():
                parser.error(f"Invalid area prefix: {area}. Must be exactly 3 letters (e.g., 'bre')")

        try:
            # Query database for all routes in each area
            all_routes_by_number = defaultdict(dict)  # number -> {rutenummer: route_data}

            with db_connection() as conn:
                route_schema = get_route_schema(conn)
                schema_quoted = quote_identifier(route_schema)

                for area in areas:
                    if args.verbose:
                        print(f"Querying routes for area: {area}", file=sys.stderr)

                    # Get all rutenummer for this area
                    rutenummer_list = get_existing_rutenummer(area)

                    if args.verbose:
                        print(f"Found {len(rutenummer_list)} routes for {area}", file=sys.stderr)

                    # Batch query: Get metadata for all routes in one query
                    if not rutenummer_list:
                        continue

                    placeholders = ','.join(['%s'] * len(rutenummer_list))
                    metadata_query = f"""
                        SELECT DISTINCT
                            fi.rutenummer,
                            fi.rutenavn,
                            fi.vedlikeholdsansvarlig,
                            f.objid as first_objid
                        FROM {schema_quoted}.fotruteinfo fi
                        JOIN {schema_quoted}.fotrute f ON fi.fotrute_fk = f.objid
                        WHERE fi.rutenummer IN ({placeholders})
                        ORDER BY fi.rutenummer, f.objid
                    """

                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(metadata_query, rutenummer_list)
                        metadata_rows = cur.fetchall()

                    # Group by rutenummer to get first segment for endpoint lookup
                    routes_metadata = {}
                    for row in metadata_rows:
                        rutenummer = row['rutenummer']
                        if rutenummer not in routes_metadata:
                            routes_metadata[rutenummer] = {
                                'rutenavn': row.get('rutenavn'),
                                'vedlikeholdsansvarlig': row.get('vedlikeholdsansvarlig'),
                                'first_objid': row['first_objid']
                            }

                    # Get endpoint coordinates for routes (lightweight - just first/last points)
                    if args.verbose:
                        print(f"Getting endpoint coordinates for {len(routes_metadata)} routes...", file=sys.stderr)

                    endpoint_query = f"""
                        WITH route_segments AS (
                            SELECT
                                fi.rutenummer,
                                f.objid,
                                ST_X(ST_Transform(ST_StartPoint(f.senterlinje::geometry), 4326)) as start_lon,
                                ST_Y(ST_Transform(ST_StartPoint(f.senterlinje::geometry), 4326)) as start_lat,
                                ST_X(ST_Transform(ST_EndPoint(f.senterlinje::geometry), 4326)) as end_lon,
                                ST_Y(ST_Transform(ST_EndPoint(f.senterlinje::geometry), 4326)) as end_lat,
                                ROW_NUMBER() OVER (PARTITION BY fi.rutenummer ORDER BY f.objid) as rn_start,
                                ROW_NUMBER() OVER (PARTITION BY fi.rutenummer ORDER BY f.objid DESC) as rn_end
                            FROM {schema_quoted}.fotruteinfo fi
                            JOIN {schema_quoted}.fotrute f ON fi.fotrute_fk = f.objid
                            WHERE fi.rutenummer IN ({placeholders})
                        )
                        SELECT
                            rutenummer,
                            MAX(CASE WHEN rn_start = 1 THEN start_lon END) as first_start_lon,
                            MAX(CASE WHEN rn_start = 1 THEN start_lat END) as first_start_lat,
                            MAX(CASE WHEN rn_end = 1 THEN end_lon END) as last_end_lon,
                            MAX(CASE WHEN rn_end = 1 THEN end_lat END) as last_end_lat
                        FROM route_segments
                        GROUP BY rutenummer
                    """

                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(endpoint_query, rutenummer_list)
                        endpoint_rows = cur.fetchall()

                    # Map endpoints to routes
                    endpoints_by_route = {}
                    for row in endpoint_rows:
                        rutenummer = row['rutenummer']
                        first_start_lon = row.get('first_start_lon')
                        first_start_lat = row.get('first_start_lat')
                        last_end_lon = row.get('last_end_lon')
                        last_end_lat = row.get('last_end_lat')
                        if first_start_lon is not None and first_start_lat is not None and last_end_lon is not None and last_end_lat is not None:
                            endpoints_by_route[rutenummer] = {
                                'start': [first_start_lon, first_start_lat],
                                'end': [last_end_lon, last_end_lat]
                            }

                    # Process each route (lightweight - only endpoint name lookups)
                    processed = 0
                    for rutenummer in rutenummer_list:
                        try:
                            metadata = routes_metadata.get(rutenummer, {})
                            route_data = {
                                'rutenummer': rutenummer,
                                'rutenavn': metadata.get('rutenavn'),
                                'vedlikeholdsansvarlig': metadata.get('vedlikeholdsansvarlig'),
                                'from_name': None,
                                'to_name': None
                            }

                            # Get endpoint names (only if coordinates available)
                            endpoints = endpoints_by_route.get(rutenummer)
                            if endpoints:
                                start_coords = endpoints.get('start')
                                end_coords = endpoints.get('end')

                                if start_coords and len(start_coords) >= 2:
                                    start_name_info = lookup_endpoint_name(conn, start_coords[0], start_coords[1], rutenummer)
                                    if start_name_info and start_name_info.get('name'):
                                        route_data['from_name'] = {
                                            'name': start_name_info.get('name'),
                                            'source': start_name_info.get('source', 'unknown'),
                                            'distance_meters': start_name_info.get('distance_meters')
                                        }

                                if end_coords and len(end_coords) >= 2:
                                    end_name_info = lookup_endpoint_name(conn, end_coords[0], end_coords[1], rutenummer)
                                    if end_name_info and end_name_info.get('name'):
                                        route_data['to_name'] = {
                                            'name': end_name_info.get('name'),
                                            'source': end_name_info.get('source', 'unknown'),
                                            'distance_meters': end_name_info.get('distance_meters')
                                        }

                            # Parse rutenummer to get number
                            parsed = parse_rutenummer(rutenummer)
                            if parsed:
                                prefix, number, letter = parsed
                                all_routes_by_number[number][rutenummer] = route_data
                                processed += 1

                                if args.verbose and processed % 10 == 0:
                                    print(f"Processed {processed}/{len(rutenummer_list)} routes...", file=sys.stderr)
                        except Exception as e:
                            if args.verbose:
                                print(f"Error getting route {rutenummer}: {e}", file=sys.stderr)
                            continue

                    if args.verbose:
                        print(f"Completed processing {processed} routes for area {area}", file=sys.stderr)

            # Format as YAML (output as list since we have multiple route numbers)
            yaml_output = format_route_registry_yaml(all_routes_by_number, as_list=True)

            # Write output
            if args.output:
                try:
                    with open(args.output, 'w', encoding='utf-8') as f:
                        f.write(yaml_output)
                    if not args.verbose:
                        print(f"Registry exported to {args.output}", file=sys.stderr)
                except Exception as e:
                    print(f"Error writing to file {args.output}: {e}", file=sys.stderr)
                    sys.exit(1)
            else:
                print(yaml_output)

            sys.exit(0)
        except Exception as e:
            print(f"Error exporting registry: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

    # Handle find-available mode
    if args.find_available:
        if not args.rutenummer_prefix:
            parser.error("--find-available requires --rutenummer-prefix")

        # Validate prefix format (3 letters)
        if len(args.rutenummer_prefix) != 3 or not args.rutenummer_prefix.isalpha():
            parser.error("--rutenummer-prefix must be exactly 3 letters (e.g., 'bre')")

        try:
            result = analyze_available_numbers(args.rutenummer_prefix.lower())
            output = format_available_numbers(result)

            if args.format == "json":
                import json
                output = json.dumps(result, indent=2, ensure_ascii=False)

            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(output)
            else:
                print(output)

            sys.exit(0)
        except Exception as e:
            print(f"Error finding available numbers: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

    # Handle routes API commands (new)
    if args.list_routes or args.get_route or args.get_route_segments or args.get_route_links or args.get_segment_lokalid:
        # Create configuration
        config = CLIConfig(
            api_url=args.api_url,
            username=args.username,
            password=args.password,
            timeout=args.timeout
        )

        # Create routes API client
        client = RoutesClient(config)

        try:
            if args.list_routes:
                # List routes
                response = client.get_routes(
                    prefix=args.prefix,
                    vedlikeholdsansvarlig=args.vedlikeholdsansvarlig,
                    bbox=args.bbox,
                    limit=args.limit,
                    offset=args.offset,
                    include_geometry=args.include_geometry
                )

                # Format output
                if args.format == "json":
                    output_text = format_json(response)
                elif args.format == "csv":
                    routes = response.get("routes", [])
                    output_text = format_routes_csv(routes, include_geometry=args.include_geometry)
                else:
                    # Table output (default)
                    output_lines = []
                    if not args.no_summary:
                        output_lines.append(format_routes_summary(response))
                    routes = response.get("routes", [])
                    output_lines.append(format_routes_table(routes, show_geometry=args.include_geometry))
                    output_text = "\n".join(output_lines)

            elif args.get_route:
                # Get single route
                route = client.get_route(
                    rutenummer=args.get_route,
                    include_geometry=args.include_geometry
                )

                # Format output
                if args.format == "json":
                    output_text = format_json(route)
                elif args.format == "csv":
                    output_text = format_routes_csv([route], include_geometry=args.include_geometry)
                else:
                    # Table output (default)
                    output_text = format_routes_table([route], show_geometry=args.include_geometry)

            elif args.get_route_segments:
                # Get route segments
                response = client.get_route_segments(
                    rutenummer=args.get_route_segments,
                    include_geometry=args.include_geometry
                )

                # Format output
                if args.format == "json":
                    output_text = format_json(response)
                else:
                    # For segments, use existing segment formatters
                    segments = response.get("segments", [])
                    # Convert to format expected by formatters
                    formatted_segments = []
                    for seg in segments:
                        formatted_segments.append({
                            "objid": seg.get("segment_objid"),
                            "routes": [{
                                "rutenummer": seg.get("rutenummer"),
                                "rutenavn": seg.get("rutenavn"),
                                "vedlikeholdsansvarlig": seg.get("vedlikeholdsansvarlig")
                            }],
                            "length_meters": seg.get("length_meters"),  # Now available!
                            "geometry": seg.get("senterlinje") if args.include_geometry else None
                        })

                    if args.format == "csv":
                        output_text = format_csv(formatted_segments, include_geometry=args.include_geometry)
                    else:
                        output_text = format_table(formatted_segments, show_geometry=args.include_geometry)

            elif args.get_route_links:
                # Get route links
                response = client.get_route_links(
                    rutenummer=args.get_route_links,
                    include_geometry=args.include_geometry
                )

                # Format output
                if args.format == "json":
                    output_text = format_json(response)
                else:
                    # For links, create a custom table format
                    links = response.get("links", [])
                    if args.format == "csv":
                        import csv
                        from io import StringIO
                        output = StringIO()
                        fieldnames = ["link_id", "a_node", "a_node_name", "b_node", "b_node_name", "length_m", "segment_objids"]
                        if args.include_geometry:
                            fieldnames.append("geom")
                        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
                        writer.writeheader()
                        for link in links:
                            row = {k: link.get(k) for k in fieldnames}
                            if "segment_objids" in row and row["segment_objids"]:
                                row["segment_objids"] = ",".join(map(str, row["segment_objids"]))
                            if "geom" in row and row["geom"]:
                                import json
                                row["geom"] = json.dumps(row["geom"])
                            writer.writerow(row)
                        output_text = output.getvalue()
                    else:
                        # Table format for links
                        lines = []
                        lines.append(f"Routing Links for Route: {response.get('rutenummer', args.get_route_links)}")
                        lines.append(f"Total: {response.get('total', len(links))} links")
                        lines.append("")

                        # Build table
                        col_widths = {
                            "link_id": max(len("link_id"), max(len(str(l.get("link_id", ""))) for l in links)),
                            "a_node": max(len("a_node"), max(len(str(l.get("a_node", "") or "")) for l in links)),
                            "a_node_name": max(len("a_name"), max(len(str(l.get("a_node_name", "") or "")) for l in links)),
                            "b_node": max(len("b_node"), max(len(str(l.get("b_node", "") or "")) for l in links)),
                            "b_node_name": max(len("b_name"), max(len(str(l.get("b_node_name", "") or "")) for l in links)),
                            "length_m": max(len("length (m)"), max(len(f"{l.get('length_m', 0):.1f}") if l.get('length_m') else len("N/A") for l in links)),
                            "segments": max(len("segments"), max(len(str(len(l.get("segment_objids", [])))) for l in links)),
                        }
                        for key in col_widths:
                            col_widths[key] = max(col_widths[key], 8)

                        header = (
                            f"{'link_id':<{col_widths['link_id']}} | "
                            f"{'a_node':<{col_widths['a_node']}} | "
                            f"{'a_name':<{col_widths['a_node_name']}} | "
                            f"{'b_node':<{col_widths['b_node']}} | "
                            f"{'b_name':<{col_widths['b_node_name']}} | "
                            f"{'length (m)':>{col_widths['length_m']}} | "
                            f"{'segments':>{col_widths['segments']}}"
                        )
                        lines.append(header)
                        lines.append("-" * len(header))

                        for link in links:
                            link_id = str(link.get("link_id", ""))
                            a_node = str(link.get("a_node") or "")
                            a_node_name = str(link.get("a_node_name") or "")
                            b_node = str(link.get("b_node") or "")
                            b_node_name = str(link.get("b_node_name") or "")
                            length_m = link.get("length_m")
                            length_str = f"{length_m:.1f}" if length_m is not None else "N/A"
                            segment_count = len(link.get("segment_objids", []))

                            row = (
                                f"{link_id:<{col_widths['link_id']}} | "
                                f"{a_node:<{col_widths['a_node']}} | "
                                f"{a_node_name:<{col_widths['a_node_name']}} | "
                                f"{b_node:<{col_widths['b_node']}} | "
                                f"{b_node_name:<{col_widths['b_node_name']}} | "
                                f"{length_str:>{col_widths['length_m']}} | "
                                f"{segment_count:>{col_widths['segments']}}"
                            )
                            lines.append(row)

                        output_text = "\n".join(lines)

            elif args.get_segment_lokalid:
                # Get segment by lokalid
                response = client.get_segment_by_lokalid(
                    lokalid=args.get_segment_lokalid,
                    include_geometry=args.include_geometry
                )

                # Format output (JSON only for complex response)
                output_text = format_json(response)

            # Write output
            if args.output:
                try:
                    with open(args.output, 'w', encoding='utf-8') as f:
                        f.write(output_text)
                    if args.format != "json" and not args.no_summary:
                        print(f"Results written to {args.output}", file=sys.stderr)
                except Exception as e:
                    print(f"Error writing to file {args.output}: {e}", file=sys.stderr)
                    sys.exit(1)
            else:
                print(output_text)

            sys.exit(0)

        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except ConnectionError as e:
            print(f"Connection error: {e}", file=sys.stderr)
            if args.verbose:
                print(f"API URL: {config.api_url}", file=sys.stderr)
            sys.exit(1)
        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            sys.exit(1)
        except APIResponseError as e:
            if e.status_code == 404:
                print(f"Route not found: {e}", file=sys.stderr)
            else:
                print(f"API error: {e}", file=sys.stderr)
            if args.verbose and e.response:
                print(f"Response: {e.response}", file=sys.stderr)
            sys.exit(1)
        except APIError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Handle complete route mode
    if args.complete_route:
        # Complete route mode - validate arguments
        if args.rutenummer_prefix or args.vedlikeholdsansvarlig:
            parser.error("--complete-route cannot be used with --rutenummer-prefix or --vedlikeholdsansvarlig")

        # Create configuration
        config = CLIConfig(
            api_url=args.api_url,
            username=args.username,
            password=args.password,
            timeout=args.timeout
        )

        # Create API client
        client = RouteSegmentsClient(config)

        # Query API for complete route
        try:
            route = client.get_complete_route(
                rutenummer=args.complete_route,
                include_geometry=args.include_geometry,
                include_segments=args.include_segments,
                include_endpoint_names=not args.no_endpoint_names
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except ConnectionError as e:
            print(f"Connection error: {e}", file=sys.stderr)
            if args.verbose:
                print(f"API URL: {config.api_url}", file=sys.stderr)
            sys.exit(1)
        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            sys.exit(1)
        except APIResponseError as e:
            if e.status_code == 404:
                print(f"Route not found: {e}", file=sys.stderr)
            else:
                print(f"API error: {e}", file=sys.stderr)
            if args.verbose and e.response:
                print(f"Response: {e.response}", file=sys.stderr)
            sys.exit(1)
        except APIError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        # Format output
        if args.format == "json":
            output_text = format_json(route)
        elif args.format == "csv":
            output_text = format_complete_route_csv(route)
        else:
            # Table output (default)
            output_text = format_complete_route_table(route)

        # Write output
        if args.output:
            try:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(output_text)
                if args.format != "json":
                    print(f"Results written to {args.output}", file=sys.stderr)
            except Exception as e:
                print(f"Error writing to file {args.output}: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            print(output_text)

        # Exit successfully
        sys.exit(0)

    # Segment query mode - validate that at least one filter is provided
    if not args.rutenummer_prefix and not args.vedlikeholdsansvarlig:
        parser.error("At least one filter must be provided: --rutenummer-prefix or --vedlikeholdsansvarlig")

    # Validate limit
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")

    # Validate offset
    if args.offset < 0:
        parser.error("--offset must be >= 0")

    # Create configuration
    config = CLIConfig(
        api_url=args.api_url,
        username=args.username,
        password=args.password,
        timeout=args.timeout
    )

    # Create API client
    client = RouteSegmentsClient(config)

    # Query API
    try:
        response = client.get_segments(
            rutenummer_prefix=args.rutenummer_prefix,
            vedlikeholdsansvarlig=args.vedlikeholdsansvarlig,
            limit=args.limit,
            offset=args.offset,
            include_geometry=args.include_geometry
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ConnectionError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        if args.verbose:
            print(f"API URL: {config.api_url}", file=sys.stderr)
        sys.exit(1)
    except AuthenticationError as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        sys.exit(1)
    except APIResponseError as e:
        print(f"API error: {e}", file=sys.stderr)
        if args.verbose and e.response:
            print(f"Response: {e.response}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Format output
    segments = response.get("segments", [])
    output_lines = []

    if args.format == "json":
        # JSON output
        output_lines.append(format_json(response))
    elif args.format == "csv":
        # CSV output
        output_lines.append(format_csv(segments, include_geometry=args.include_geometry))
    else:
        # Table output (default)
        if not args.no_summary:
            output_lines.append(format_text_summary(response))
        output_lines.append(format_table(segments, show_geometry=args.include_geometry))

    output_text = "\n".join(output_lines)

    # Write output
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output_text)
            if not args.format == "json" and not args.no_summary:
                print(f"Results written to {args.output}", file=sys.stderr)
        except Exception as e:
            print(f"Error writing to file {args.output}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output_text)

    # Exit successfully
    sys.exit(0)


if __name__ == '__main__':
    main()

