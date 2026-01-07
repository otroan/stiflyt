#!/usr/bin/env python3
"""CLI tool for querying route segments from the Stiflyt backend API.

This CLI tool provides a command-line interface to query route segments
filtered by rutenummer prefix and/or vedlikeholdsansvarlig.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from .api_client import RouteSegmentsClient, APIError, ConnectionError, AuthenticationError, APIResponseError
from .config import CLIConfig
from .formatters import format_json, format_table, format_csv, format_text_summary, format_complete_route_table, format_complete_route_csv
from .find_available_numbers import analyze_available_numbers, format_available_numbers


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Query route segments from Stiflyt backend API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
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

  # Test ruteinfopunkt lookup (debug)
  %(prog)s --test-ruteinfopunkt 7.710764899 61.809237843 --rutenummer bre9
        """
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
        choices=['json', 'table', 'csv'],
        default='table',
        help='Output format (default: table)'
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

