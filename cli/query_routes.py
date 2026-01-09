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

  # Query segments with rutenummer starting with "bre" and vedlikeholdsansvarlig "DNT Oslo"
  %(prog)s --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo"

  # Query with just rutenummer prefix
  %(prog)s --rutenummer-prefix bre

  # Get complete route (combines all segments)
  %(prog)s --complete-route bre10

  # Complete route with JSON output
  %(prog)s --complete-route bre10 --format json

  # Complete route without geometry
  %(prog)s --complete-route bre10 --no-geometry

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
        '--no-geometry',
        action='store_true',
        help='Exclude GeoJSON geometry from response (for complete route mode)'
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

    # Handle validation mode
    if args.validate:
        from services.database import db_connection, ROUTE_SCHEMA, quote_identifier, validate_schema_name
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

                # Validate metadata consistency
                errors = []
                warnings = []

                # First, dump all segment metadata
                segment_metadata_dump = []
                for segment_objid, fotruteinfo_rows in sorted(segments_dict.items()):
                    # Get length from first row (should be same for all rows of same segment)
                    segment_length = fotruteinfo_rows[0].get('length_meters') if fotruteinfo_rows else None

                    segment_metadata_dump.append({
                        'segment_objid': segment_objid,
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

                # Collect all values across all segments and fotruteinfo rows
                all_rutenummer = []
                all_rutenavn = []
                all_vedlikeholdsansvarlig = []
                all_rutetype = []
                all_gradering = []

                # Track segments missing fields for summary warnings
                segments_missing_rutenavn = []
                segments_missing_vedlikeholdsansvarlig = []

                # Track which segments have which values (for inconsistency warnings)
                rutenavn_by_segment = {}  # value -> [segment_objids]
                vedlikeholdsansvarlig_by_segment = {}  # value -> [segment_objids]
                rutetype_by_segment = {}  # value -> [segment_objids]
                gradering_by_segment = {}  # value -> [segment_objids]

                # Check for duplicates WITHIN each segment and collect values
                for segment_objid, fotruteinfo_rows in segments_dict.items():
                    # Check for duplicate values within each field for this segment
                    segment_rutenavn = [r.get('rutenavn') for r in fotruteinfo_rows if r.get('rutenavn')]
                    segment_vedlikeholdsansvarlig = [r.get('vedlikeholdsansvarlig') for r in fotruteinfo_rows if r.get('vedlikeholdsansvarlig')]
                    segment_rutetype = [r.get('rutetype') for r in fotruteinfo_rows if r.get('rutetype')]
                    segment_gradering = [r.get('gradering') for r in fotruteinfo_rows if r.get('gradering')]

                    # Track missing fields for this segment
                    has_rutenavn = len(segment_rutenavn) > 0
                    has_vedlikeholdsansvarlig = len(segment_vedlikeholdsansvarlig) > 0

                    if not has_rutenavn:
                        segments_missing_rutenavn.append(segment_objid)
                    if not has_vedlikeholdsansvarlig:
                        segments_missing_vedlikeholdsansvarlig.append(segment_objid)

                    # Track which segments have which values (use first non-null value if multiple)
                    if segment_rutenavn:
                        val = segment_rutenavn[0]  # Use first value if multiple
                        if val not in rutenavn_by_segment:
                            rutenavn_by_segment[val] = []
                        rutenavn_by_segment[val].append(segment_objid)

                    if segment_vedlikeholdsansvarlig:
                        val = segment_vedlikeholdsansvarlig[0]
                        if val not in vedlikeholdsansvarlig_by_segment:
                            vedlikeholdsansvarlig_by_segment[val] = []
                        vedlikeholdsansvarlig_by_segment[val].append(segment_objid)

                    if segment_rutetype:
                        val = segment_rutetype[0]
                        if val not in rutetype_by_segment:
                            rutetype_by_segment[val] = []
                        rutetype_by_segment[val].append(segment_objid)

                    if segment_gradering:
                        val = segment_gradering[0]
                        if val not in gradering_by_segment:
                            gradering_by_segment[val] = []
                        gradering_by_segment[val].append(segment_objid)

                    # Check for duplicates in rutenavn within this segment (only if multiple rows)
                    if len(fotruteinfo_rows) > 1:
                        rutenavn_counts = {}
                        for val in segment_rutenavn:
                            rutenavn_counts[val] = rutenavn_counts.get(val, 0) + 1
                        for val, count in rutenavn_counts.items():
                            if count > 1:
                                errors.append({
                                    'type': 'DUPLICATE_RUTENAVN_IN_SEGMENT',
                                    'message': f'Segment {segment_objid} has duplicate rutenavn "{val}" ({count} times) in its fotruteinfo rows',
                                    'severity': 'error',
                                    'segment_objid': segment_objid,
                                    'value': val,
                                    'count': count
                                })

                        # Check for duplicates in vedlikeholdsansvarlig within this segment
                        vedlikeholdsansvarlig_counts = {}
                        for val in segment_vedlikeholdsansvarlig:
                            vedlikeholdsansvarlig_counts[val] = vedlikeholdsansvarlig_counts.get(val, 0) + 1
                        for val, count in vedlikeholdsansvarlig_counts.items():
                            if count > 1:
                                errors.append({
                                    'type': 'DUPLICATE_VEDLIKEHOLDSANSVARLIG_IN_SEGMENT',
                                    'message': f'Segment {segment_objid} has duplicate vedlikeholdsansvarlig "{val}" ({count} times) in its fotruteinfo rows',
                                    'severity': 'error',
                                    'segment_objid': segment_objid,
                                    'value': val,
                                    'count': count
                                })

                        # Check for duplicates in rutetype within this segment
                        rutetype_counts = {}
                        for val in segment_rutetype:
                            rutetype_counts[val] = rutetype_counts.get(val, 0) + 1
                        for val, count in rutetype_counts.items():
                            if count > 1:
                                warnings.append({
                                    'type': 'DUPLICATE_RUTETYPE_IN_SEGMENT',
                                    'message': f'Segment {segment_objid} has duplicate rutetype "{val}" ({count} times) in its fotruteinfo rows',
                                    'severity': 'warning',
                                    'segment_objid': segment_objid,
                                    'value': val,
                                    'count': count
                                })

                        # Check for duplicates in gradering within this segment
                        gradering_counts = {}
                        for val in segment_gradering:
                            gradering_counts[val] = gradering_counts.get(val, 0) + 1
                        for val, count in gradering_counts.items():
                            if count > 1:
                                warnings.append({
                                    'type': 'DUPLICATE_GRADERING_IN_SEGMENT',
                                    'message': f'Segment {segment_objid} has duplicate gradering "{val}" ({count} times) in its fotruteinfo rows',
                                    'severity': 'warning',
                                    'segment_objid': segment_objid,
                                    'value': val,
                                    'count': count
                                })

                    # Collect values for cross-segment consistency checks
                    for row in fotruteinfo_rows:
                        if row['rutenummer']:
                            all_rutenummer.append(row['rutenummer'])
                        if row.get('rutenavn'):
                            all_rutenavn.append(row.get('rutenavn'))
                        if row.get('vedlikeholdsansvarlig'):
                            all_vedlikeholdsansvarlig.append(row.get('vedlikeholdsansvarlig'))
                        if row.get('rutetype'):
                            all_rutetype.append(row.get('rutetype'))
                        if row.get('gradering'):
                            all_gradering.append(row.get('gradering'))

                    # Check for missing required fields (rutenummer is always required)
                    has_rutenummer = any(r['rutenummer'] for r in fotruteinfo_rows)

                    if not has_rutenummer:
                        errors.append({
                            'type': 'MISSING_REQUIRED_FIELDS',
                            'message': f'Segment {segment_objid} is missing required field: rutenummer',
                            'severity': 'error',
                            'segment_objid': segment_objid,
                            'missing_fields': ['rutenummer']
                        })

                # Check 2: rutenummer consistency (all should be the same)
                rutenummer_values = set(all_rutenummer)
                if len(rutenummer_values) > 1:
                    errors.append({
                        'type': 'INCONSISTENT_RUTENUMMER',
                        'message': f'Route has segments with different rutenummer values: {sorted(rutenummer_values)}',
                        'severity': 'error',
                        'values': sorted(rutenummer_values)
                    })

                # Check 3: rutenavn consistency across segments (it's EXPECTED to be the same)
                rutenavn_values = set(all_rutenavn)

                if len(rutenavn_values) > 1:
                    # Build detailed message with segment IDs
                    value_details = []
                    for val in sorted(rutenavn_values):
                        segment_ids = sorted(rutenavn_by_segment.get(val, []))
                        value_details.append(f'"{val}" (segments: {segment_ids})')

                    warnings.append({
                        'type': 'INCONSISTENT_RUTENAVN',
                        'message': f'Route has segments with different rutenavn values: {sorted(rutenavn_values)} (Expected: all segments should have the same rutenavn)',
                        'severity': 'warning',
                        'values': sorted(rutenavn_values),
                        'value_by_segment': rutenavn_by_segment
                    })

                # Check for missing rutenavn (regardless of consistency)
                if segments_missing_rutenavn:
                    if len(rutenavn_values) == 0:
                        # All segments are missing rutenavn
                        warnings.append({
                            'type': 'MISSING_RUTENAVN',
                            'message': f'No segments have rutenavn set. Affected segments: {sorted(segments_missing_rutenavn)}',
                            'severity': 'warning',
                            'segment_objids': sorted(segments_missing_rutenavn)
                        })
                    else:
                        # Some segments are missing rutenavn
                        warnings.append({
                            'type': 'MISSING_RUTENAVN_SOME_SEGMENTS',
                            'message': f'Some segments are missing rutenavn. Affected segments: {sorted(segments_missing_rutenavn)}',
                            'severity': 'warning',
                            'segment_objids': sorted(segments_missing_rutenavn)
                        })
                elif len(rutenavn_values) == 0:
                    # Edge case: no rutenavn values found but segments_missing_rutenavn is empty (shouldn't happen, but handle it)
                    all_segment_objids = sorted(segments_dict.keys())
                    warnings.append({
                        'type': 'MISSING_RUTENAVN',
                        'message': f'No segments have rutenavn set. All segments: {all_segment_objids}',
                        'severity': 'warning',
                        'segment_objids': all_segment_objids
                    })

                # Check 4: vedlikeholdsansvarlig consistency across segments
                # Note: Different organizations for different segments might be OK, but we still report it
                vedlikeholdsansvarlig_values = set(all_vedlikeholdsansvarlig)

                if len(vedlikeholdsansvarlig_values) > 1:
                    warnings.append({
                        'type': 'INCONSISTENT_VEDLIKEHOLDSANSVARLIG',
                        'message': f'Route has segments with different vedlikeholdsansvarlig values: {sorted(vedlikeholdsansvarlig_values)} (Note: Different organizations may be responsible for different segments - this may be expected)',
                        'severity': 'warning',
                        'values': sorted(vedlikeholdsansvarlig_values),
                        'value_by_segment': vedlikeholdsansvarlig_by_segment
                    })

                # Check for missing vedlikeholdsansvarlig (regardless of consistency)
                if segments_missing_vedlikeholdsansvarlig:
                    if len(vedlikeholdsansvarlig_values) == 0:
                        # All segments are missing vedlikeholdsansvarlig
                        warnings.append({
                            'type': 'MISSING_VEDLIKEHOLDSANSVARLIG',
                            'message': f'No segments have vedlikeholdsansvarlig set. Affected segments: {sorted(segments_missing_vedlikeholdsansvarlig)}',
                            'severity': 'warning',
                            'segment_objids': sorted(segments_missing_vedlikeholdsansvarlig)
                        })
                    else:
                        # Some segments are missing vedlikeholdsansvarlig
                        warnings.append({
                            'type': 'MISSING_VEDLIKEHOLDSANSVARLIG_SOME_SEGMENTS',
                            'message': f'Some segments are missing vedlikeholdsansvarlig. Affected segments: {sorted(segments_missing_vedlikeholdsansvarlig)}',
                            'severity': 'warning',
                            'segment_objids': sorted(segments_missing_vedlikeholdsansvarlig)
                        })
                elif len(vedlikeholdsansvarlig_values) == 0:
                    # Edge case: no vedlikeholdsansvarlig values found but segments_missing_vedlikeholdsansvarlig is empty
                    all_segment_objids = sorted(segments_dict.keys())
                    warnings.append({
                        'type': 'MISSING_VEDLIKEHOLDSANSVARLIG',
                        'message': f'No segments have vedlikeholdsansvarlig set. All segments: {all_segment_objids}',
                        'severity': 'warning',
                        'segment_objids': all_segment_objids
                    })

                # Check 5: rutetype consistency across segments (expected to be the same)
                rutetype_values = set(all_rutetype)

                if len(rutetype_values) > 1:
                    warnings.append({
                        'type': 'INCONSISTENT_RUTETYPE',
                        'message': f'Route has segments with different rutetype values: {sorted(rutetype_values)} (Expected: all segments should have the same rutetype)',
                        'severity': 'warning',
                        'values': sorted(rutetype_values),
                        'value_by_segment': rutetype_by_segment
                    })

                # Check 6: gradering consistency across segments (expected to be the same)
                gradering_values = set(all_gradering)

                if len(gradering_values) > 1:
                    warnings.append({
                        'type': 'INCONSISTENT_GRADERING',
                        'message': f'Route has segments with different gradering values: {sorted(gradering_values)} (Expected: all segments should have the same gradering)',
                        'severity': 'warning',
                        'values': sorted(gradering_values),
                        'value_by_segment': gradering_by_segment
                    })

                # ====================================================================
                # GEOMETRY VALIDATION USING route_geometries
                # ====================================================================

                geometry_errors = []
                geometry_warnings = []
                geometry_info = []

                # Get route geometry from route_geometries column in links_with_routes
                route_geometry_query = f"""
                    SELECT
                        lwr.route_geometries->>%s as route_geometry_json,
                        ST_Length(ST_Transform(ST_GeomFromGeoJSON(lwr.route_geometries->>%s), 4326)::geography) as length_meters,
                        (SELECT COUNT(DISTINCT lwr2.link_id)
                         FROM {schema_quoted}.links_with_routes lwr2
                         WHERE %s = ANY(lwr2.rutenummer_list)) as link_count
                    FROM {schema_quoted}.links_with_routes lwr
                    WHERE %s = ANY(lwr.rutenummer_list)
                      AND lwr.route_geometries->>%s IS NOT NULL
                    LIMIT 1
                """

                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(route_geometry_query, (rutenummer, rutenummer, rutenummer, rutenummer, rutenummer))
                    route_geom_row = cur.fetchone()

                    if not route_geom_row or not route_geom_row.get('route_geometry_json'):
                        geometry_warnings.append({
                            'type': 'NO_ROUTE_GEOMETRY',
                            'message': f'No route_geometries found for route {rutenummer} in links_with_routes. This may mean the route could not be made continuous (e.g., disconnected components) or build-links has not run yet.',
                            'severity': 'warning'
                        })
                        links = []
                    else:
                        route_geometry_json = route_geom_row['route_geometry_json']
                        link_count = route_geom_row.get('link_count', 0)

                        # Validate route geometry
                        geom_validation_query = """
                            SELECT
                                ST_IsValid(ST_GeomFromGeoJSON(%s)::geometry) as is_valid,
                                ST_IsSimple(ST_GeomFromGeoJSON(%s)::geometry) as is_simple,
                                ST_Length(ST_Transform(ST_GeomFromGeoJSON(%s)::geometry, 4326)::geography) as length_meters,
                                ST_GeometryType(ST_GeomFromGeoJSON(%s)::geometry) as geom_type
                        """
                        cur.execute(geom_validation_query, (route_geometry_json, route_geometry_json, route_geometry_json, route_geometry_json))
                        geom_validation = cur.fetchone()

                        if geom_validation:
                            is_valid = geom_validation['is_valid']
                            is_simple = geom_validation['is_simple']
                            length_meters = geom_validation.get('length_meters')
                            geom_type = geom_validation.get('geom_type')

                            if not is_valid:
                                geometry_errors.append({
                                    'type': 'INVALID_ROUTE_GEOMETRY',
                                    'message': f'Route geometry is invalid',
                                    'severity': 'error'
                                })

                            if not is_simple:
                                geometry_warnings.append({
                                    'type': 'NON_SIMPLE_ROUTE_GEOMETRY',
                                    'message': f'Route geometry has self-intersections or is not simple',
                                    'severity': 'warning'
                                })

                            if length_meters is None or length_meters == 0:
                                geometry_errors.append({
                                    'type': 'ZERO_LENGTH_ROUTE',
                                    'message': f'Route has zero or null length',
                                    'severity': 'error'
                                })

                            if geom_type:
                                geometry_info.append({
                                    'type': 'ROUTE_GEOMETRY_TYPE',
                                    'message': f'Route geometry type: {geom_type}',
                                    'severity': 'info',
                                    'geom_type': geom_type,
                                    'length_meters': float(length_meters) if length_meters else None
                                })

                        # Get links for additional validation (node connectivity, etc.)
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
                        cur.execute(links_query, (rutenummer,))
                        links = cur.fetchall()

                        if links:
                            # Validate individual links (for node connectivity checks)
                            for link in links:
                                link_id = link['link_id']
                                length_m = link.get('length_m')

                                # Check length
                                if length_m is None or length_m == 0:
                                    geometry_errors.append({
                                        'type': 'ZERO_LENGTH_LINK',
                                        'message': f'Link {link_id} has zero or null length',
                                        'severity': 'error',
                                        'link_id': link_id
                                    })
                                elif length_m < 1.0:
                                    geometry_warnings.append({
                                        'type': 'VERY_SHORT_LINK',
                                        'message': f'Link {link_id} is very short ({length_m:.2f} m)',
                                        'severity': 'warning',
                                        'link_id': link_id,
                                        'length_m': length_m
                                    })

                        # Build link graph for node connectivity analysis
                        link_graph = {}  # node -> [links where this is a_node or b_node]
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

                        # Check node connectivity (route_geometries should already be continuous, but check node structure)
                        if len(links) > 1:
                            # Find endpoints (nodes with degree 1)
                            endpoint_nodes = []
                            for node, link_refs in link_graph.items():
                                if len(link_refs) == 1:
                                    endpoint_nodes.append(node)

                            if len(endpoint_nodes) != 2:
                                geometry_warnings.append({
                                    'type': 'UNEXPECTED_ENDPOINT_COUNT',
                                    'message': f'Route has {len(endpoint_nodes)} endpoint node(s) (expected 2 for a continuous route). Endpoints: {endpoint_nodes}',
                                    'severity': 'warning',
                                    'endpoint_count': len(endpoint_nodes),
                                    'endpoint_nodes': endpoint_nodes
                                })

                            # Check for nodes with degree 2 (should be intermediate nodes, not endpoints)
                            degree_2_nodes = []
                            for node, link_refs in link_graph.items():
                                if len(link_refs) == 2:
                                    degree_2_nodes.append(node)

                            # Check endpoints have correct degree
                            for link in links:
                                a_degree = link.get('a_node_degree')
                                b_degree = link.get('b_node_degree')

                                # Check if a_node is an endpoint but has wrong degree
                                if link['a_node'] in endpoint_nodes and a_degree is not None and a_degree != 1:
                                    geometry_warnings.append({
                                        'type': 'ENDPOINT_NODE_WRONG_DEGREE',
                                        'message': f'Link {link["link_id"]} has a_node {link["a_node"]} marked as endpoint but has degree={a_degree} (expected 1)',
                                        'severity': 'warning',
                                        'link_id': link['link_id'],
                                        'node_id': link['a_node'],
                                        'degree': a_degree
                                    })

                                # Check if b_node is an endpoint but has wrong degree
                                if link['b_node'] in endpoint_nodes and b_degree is not None and b_degree != 1:
                                    geometry_warnings.append({
                                        'type': 'ENDPOINT_NODE_WRONG_DEGREE',
                                        'message': f'Link {link["link_id"]} has b_node {link["b_node"]} marked as endpoint but has degree={b_degree} (expected 1)',
                                        'severity': 'warning',
                                        'link_id': link['link_id'],
                                        'node_id': link['b_node'],
                                        'degree': b_degree
                                    })

                        # Check for multiple components (disconnected link groups)
                        # Note: route_geometries should already be continuous, but we check node connectivity
                        if len(links) > 1:
                            components = []
                            visited_components = set()

                            def dfs_component(link_id, component):
                                if link_id in visited_components:
                                    return
                                visited_components.add(link_id)
                                component.append(link_id)

                                link = link_by_id[link_id]
                                # Find connected links
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
                                # Multiple components - identify main component (largest)
                                components.sort(key=len, reverse=True)
                                main_component = components[0]
                                appendix_components = components[1:]

                                geometry_info.append({
                                    'type': 'MULTIPLE_LINK_COMPONENTS',
                                    'message': f'Route has {len(components)} disconnected link component(s). Main component: {len(main_component)} links, Appendix components: {[len(c) for c in appendix_components]} links. Note: route_geometries should still provide continuous geometry.',
                                    'severity': 'info',
                                    'component_count': len(components),
                                    'main_component_link_ids': main_component,
                                    'appendix_component_link_ids': [c for c in appendix_components]
                                })

                # Add geometry errors and warnings to main lists
                errors.extend(geometry_errors)
                warnings.extend(geometry_warnings)
                # Info items can be added to a separate list or included in warnings

                # Build validation report
                validation_result = {
                    'rutenummer': rutenummer,
                    'segment_count': len(segments_dict),
                    'link_count': len(links) if links else 0,
                    'status': 'OK' if not errors else ('ERROR' if errors else 'WARNING'),
                    'errors': errors,
                    'warnings': warnings,
                    'geometry_info': geometry_info,
                    'segment_metadata': segment_metadata_dump,
                    'summary': {
                        'total_segments': len(segments_dict),
                        'total_fotruteinfo_rows': len(all_rows),
                        'total_links': len(links) if links else 0,
                        'error_count': len(errors),
                        'warning_count': len(warnings),
                        'geometry_error_count': len(geometry_errors),
                        'geometry_warning_count': len(geometry_warnings),
                        'rutenavn_values': sorted(rutenavn_values) if rutenavn_values else None,
                        'vedlikeholdsansvarlig_values': sorted(vedlikeholdsansvarlig_values) if vedlikeholdsansvarlig_values else None,
                        'rutetype_values': sorted(rutetype_values) if rutetype_values else None,
                        'gradering_values': sorted(gradering_values) if gradering_values else None,
                    }
                }

                # Output results
                if args.format == 'json':
                    print(format_json(validation_result))
                else:
                    # Human-readable table format
                    print("=" * 80)
                    print(f"VALIDATION REPORT: {rutenummer}")
                    print("=" * 80)
                    print(f"Total segments: {len(segments_dict)}")
                    print(f"Total fotruteinfo rows: {len(all_rows)}")
                    print(f"Total links: {len(links) if links else 0}")
                    print(f"Status: {validation_result['status']}")
                    print()

                    # Dump all segment metadata first
                    print("SEGMENT METADATA DUMP:")
                    print("-" * 80)
                    for seg_meta in segment_metadata_dump:
                        length_str = f"{seg_meta['length_meters']:.1f} m" if seg_meta.get('length_meters') is not None else "N/A"
                        print(f"Segment {seg_meta['segment_objid']} (length: {length_str}, {seg_meta['fotruteinfo_count']} fotruteinfo row(s)):")
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
                        print()

                    if not errors and not warnings:
                        print("✓ All metadata is consistent across all segments")
                        if not geometry_errors and not geometry_warnings:
                            print("✓ All geometry validation passed")
                        print()

                    # Show summary
                    print("SUMMARY:")
                    print("-" * 80)
                    summary = validation_result['summary']
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
    if args.list_routes or args.get_route or args.get_route_segments or args.get_route_links:
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
                include_geometry=not args.no_geometry,
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

