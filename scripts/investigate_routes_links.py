#!/usr/bin/env python3
"""Investigate routes and links relationship to find why routes are missing.

This script checks:
1. Routes materialized view definition
2. Routes with/without links
3. Routes missing from view
4. Bbox query comparison
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import services
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.database import db_connection
from psycopg.rows import dict_row


def print_section(title):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def run_query(conn, query, description, params=None):
    """Run a query and print results."""
    print(f"\n{description}:")
    print("-" * 80)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params or [])
            rows = cur.fetchall()

            if not rows:
                print("  (no results)")
                return rows

            # Print column headers
            if rows:
                headers = list(rows[0].keys())
                print("  " + " | ".join(f"{h:20}" for h in headers))
                print("  " + "-" * (len(headers) * 23))

                # Print rows (limit to 20)
                for i, row in enumerate(rows[:20]):
                    values = [str(row[h])[:20] for h in headers]
                    print("  " + " | ".join(f"{v:20}" for v in values))

                if len(rows) > 20:
                    print(f"\n  ... and {len(rows) - 20} more rows")

            return rows
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def main():
    """Main investigation."""
    print_section("Routes and Links Investigation")

    with db_connection() as conn:
        # 1. Check routes view definition
        print_section("1. Routes Materialized View Definition")
        query = """
            SELECT pg_get_viewdef('stiflyt.routes'::regclass, true) as definition;
        """
        rows = run_query(conn, query, "View definition")
        if rows:
            definition = rows[0]['definition']
            print("\nFull definition:")
            print(definition)

            # Check for suspicious JOINs
            if 'JOIN' in definition.upper() and 'link' in definition.lower():
                print("\n⚠️  WARNING: View definition contains JOIN to links table!")
                print("   This might filter out routes without links.")
            elif 'WHERE' in definition.upper() and 'link' in definition.lower():
                print("\n⚠️  WARNING: View definition contains WHERE clause with links!")
                print("   This might filter out routes without links.")
            else:
                print("\n✓ View definition doesn't appear to filter by links")

        # 2. Count routes
        print_section("2. Route Counts")
        query = """
            WITH routes_with_links AS (
                SELECT DISTINCT UNNEST(rutenummer_list) as rutenummer
                FROM stiflyt.links_with_routes
                WHERE rutenummer_list IS NOT NULL
            )
            SELECT
                (SELECT COUNT(*) FROM stiflyt.routes) as routes_in_view,
                (SELECT COUNT(*) FROM routes_with_links) as routes_with_links,
                (SELECT COUNT(DISTINCT rutenummer) FROM stiflyt.route_segments) as routes_from_segments;
        """
        run_query(conn, query, "Route counts comparison")

        # 3. Routes without links
        print_section("3. Routes WITHOUT Links (might be missing from view)")
        query = """
            SELECT
                r.rutenummer,
                r.rutenavn,
                r.segment_count,
                r.total_length_m,
                r.vedlikeholdsansvarlig
            FROM stiflyt.routes r
            WHERE NOT EXISTS (
                SELECT 1
                FROM stiflyt.links_with_routes lwr
                WHERE r.rutenummer = ANY(lwr.rutenummer_list)
            )
            ORDER BY r.segment_count DESC, r.rutenummer
            LIMIT 20;
        """
        rows = run_query(conn, query, "Routes without links")
        if rows:
            print(f"\n⚠️  Found {len(rows)} routes without links (showing first 20)")
            print("   These routes might not appear when 'Ankere' is not selected")

        # 4. Routes from segments but not in view
        print_section("4. Routes in route_segments but NOT in routes view")
        query = """
            SELECT DISTINCT
                rs.rutenummer,
                MAX(rs.rutenavn) as rutenavn,
                MAX(rs.vedlikeholdsansvarlig) as vedlikeholdsansvarlig
            FROM stiflyt.route_segments rs
            WHERE NOT EXISTS (
                SELECT 1 FROM stiflyt.routes r
                WHERE r.rutenummer = rs.rutenummer
            )
            GROUP BY rs.rutenummer
            ORDER BY rs.rutenummer
            LIMIT 20;
        """
        rows = run_query(conn, query, "Routes missing from materialized view")
        if rows:
            print(f"\n⚠️  Found {len(rows)} routes in route_segments but NOT in routes view")
            print("   These routes are completely missing from the materialized view!")

        # 5. Sample bbox query (you can modify coordinates)
        print_section("5. Sample Bbox Query (modify coordinates in script)")
        # Default bbox - replace with actual coordinates from your test
        bbox = [10.0, 59.0, 11.0, 60.0]  # xmin, ymin, xmax, ymax
        print(f"\nUsing bbox: {bbox}")
        print("(Modify bbox variable in script to test with actual coordinates)")

        query = """
            WITH bbox_routes AS (
                SELECT
                    r.rutenummer,
                    r.rutenavn,
                    r.segment_count,
                    r.total_length_m
                FROM stiflyt.routes r
                WHERE r.route_geometry && ST_Transform(
                    ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                    25833
                )
                AND ST_Intersects(
                    r.route_geometry,
                    ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), 25833)
                )
            )
            SELECT
                br.*,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM stiflyt.links_with_routes lwr
                        WHERE br.rutenummer = ANY(lwr.rutenummer_list)
                    ) THEN 'YES'
                    ELSE 'NO'
                END as has_links,
                (SELECT COUNT(*)
                 FROM stiflyt.links_with_routes lwr
                 WHERE br.rutenummer = ANY(lwr.rutenummer_list)
                ) as link_count
            FROM bbox_routes br
            ORDER BY br.rutenummer
            LIMIT 50;
        """
        params = bbox + bbox  # Need bbox twice for the query
        rows = run_query(conn, query, f"Routes in bbox {bbox} with link status", params)

        if rows:
            with_links = sum(1 for r in rows if r['has_links'] == 'YES')
            without_links = sum(1 for r in rows if r['has_links'] == 'NO')
            print(f"\nSummary:")
            print(f"  Routes with links: {with_links}")
            print(f"  Routes without links: {without_links}")
            if without_links > 0:
                print(f"\n⚠️  {without_links} routes in this bbox don't have links!")
                print("   These might be missing when 'Ankere' is not selected")

        # 6. Check view refresh status
        print_section("6. Materialized View Status")
        query = """
            SELECT
                schemaname,
                matviewname,
                hasindexes,
                ispopulated
            FROM pg_matviews
            WHERE schemaname = 'stiflyt' AND matviewname = 'routes';
        """
        run_query(conn, query, "View status")

        print_section("Investigation Complete")
        print("\nNext steps:")
        print("1. If routes view definition JOINs to links, that's the bug!")
        print("2. If routes without links exist, they should still appear in the view")
        print("3. Modify bbox coordinates in the script to test with your actual area")
        print("4. Check if routes view needs to be refreshed: REFRESH MATERIALIZED VIEW stiflyt.routes;")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
