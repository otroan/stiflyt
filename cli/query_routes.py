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
from .formatters import format_json, format_table, format_csv, format_text_summary


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

  # JSON output
  %(prog)s --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo" --format json

  # CSV output with geometry
  %(prog)s --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo" --format csv --include-geometry --output results.csv

  # Custom API URL
  %(prog)s --rutenummer-prefix bre --api-url http://production.example.com/api/v1

  # Pagination
  %(prog)s --rutenummer-prefix bre --limit 50 --offset 100
        """
    )

    # Filters (at least one required)
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

    args = parser.parse_args()

    # Validate that at least one filter is provided
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

