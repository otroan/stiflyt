#!/usr/bin/env python3
"""
Analyze query performance for bounding box route queries.

This script helps identify performance bottlenecks by:
1. Checking for spatial indexes
2. Analyzing query execution plans
3. Testing different query approaches
"""

import sys
from pathlib import Path

# Add project root to path so we can import services
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.database import get_db_connection, validate_schema_name
from psycopg2.extras import RealDictCursor


def discover_route_schema(conn):
    """
    Dynamically discover the route schema name.
    The schema name contains a hash that can change.
    """
    query = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE %s
        ORDER BY schema_name
        LIMIT 1;
    """

    with conn.cursor() as cur:
        cur.execute(query, ('turogfriluftsruter_%',))
        result = cur.fetchone()
        if result:
            schema_name = result[0]
            # Validate schema name for safety
            if validate_schema_name(schema_name):
                return schema_name
        # Fallback to hardcoded value if not found
        return "turogfriluftsruter_b9b25c7668da494b9894d492fc35290d"


def check_indexes(conn):
    """Check if spatial indexes exist on fotrute table."""
    print("=" * 60)
    print("Checking for spatial indexes...")
    print("=" * 60)

    route_schema = discover_route_schema(conn)
    print(f"Using route schema: {route_schema}")

    if not route_schema:
        print("⚠️  Could not discover route schema")
        return False, None

    # First, let's see ALL indexes on the fotrute table for debugging
    debug_query = """
        SELECT
            indexname,
            indexdef
        FROM pg_indexes
        WHERE schemaname = %s
        AND tablename = 'fotrute'
        ORDER BY indexname;
    """

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(debug_query, (route_schema,))
            all_indexes = cur.fetchall()

            print(f"\n  All indexes on fotrute table ({len(all_indexes)} total):")
            for idx in all_indexes:
                print(f"    - {idx['indexname']}")
                if 'GIST' in idx['indexdef'] or 'gist' in idx['indexdef'].lower():
                    print(f"      ✓ GIST index: {idx['indexdef'][:100]}...")

            # Now check specifically for GIST indexes
            query = """
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = %s
                AND tablename = 'fotrute'
                AND (indexdef LIKE '%%GIST%%' OR indexdef LIKE '%%gist%%')
                ORDER BY indexname;
            """

            cur.execute(query, (route_schema,))
            indexes = cur.fetchall()

    except Exception as e:
        print(f"Error executing query: {e}")
        print(f"Query: {query}")
        print(f"Parameters: ({route_schema},)")
        raise

    if indexes:
        print(f"\n✓ Found {len(indexes)} spatial index(es):")
        for idx in indexes:
            print(f"  - {idx['indexname']}")
            print(f"    {idx['indexdef']}")
    else:
        print("\n✗ No spatial indexes found on fotrute.senterlinje")
        print("  This is likely a major performance issue!")
        print(f"\n  To create one, run:")
        print(f"  CREATE INDEX idx_fotrute_senterlinje_gist")
        print(f"  ON {route_schema}.fotrute USING GIST (senterlinje);")

    return len(indexes) > 0, route_schema


def analyze_query_plan(conn, route_schema, min_lat, min_lng, max_lat, max_lng, organization=None):
    """Analyze the execution plan for the bounding box query."""
    print("\n" + "=" * 60)
    print("Analyzing query execution plan...")
    print("=" * 60)

    # Current query (inefficient - transforms in WHERE)
    query_current = f"""
        EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
        SELECT DISTINCT
            fi.rutenummer,
            fi.rutenavn,
            fi.vedlikeholdsansvarlig,
            ST_AsGeoJSON(
                ST_Simplify(
                    ST_Transform(
                        ST_Collect(f.senterlinje::geometry),
                        4326
                    ),
                    0.0005
                )
            ) as geometry,
            COUNT(DISTINCT f.objid) as segment_count
        FROM {route_schema}.fotrute f
        JOIN {route_schema}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE ST_Intersects(
            ST_Transform(f.senterlinje::geometry, 4326),
            ST_MakeEnvelope(%s, %s, %s, %s, 4326)
        )
    """

    params = [min_lng, min_lat, max_lng, max_lat]

    if organization:
        query_current += " AND fi.vedlikeholdsansvarlig ILIKE %s"
        params.append(f"%{organization}%")

    query_current += " GROUP BY fi.rutenummer, fi.rutenavn, fi.vedlikeholdsansvarlig"
    query_current += " LIMIT 100"

    print("\n--- Current Query (transforms in WHERE clause) ---")
    with conn.cursor() as cur:
        cur.execute(query_current, params)
        plan = cur.fetchall()
        for row in plan:
            print(row[0])

    # Optimized query (transforms bbox to native SRID)
    print("\n--- Optimized Query (transforms bbox to native SRID) ---")
    query_optimized = f"""
        EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
        SELECT DISTINCT
            fi.rutenummer,
            fi.rutenavn,
            fi.vedlikeholdsansvarlig,
            ST_AsGeoJSON(
                ST_Simplify(
                    ST_Transform(
                        ST_Collect(f.senterlinje::geometry),
                        4326
                    ),
                    0.0005
                )
            ) as geometry,
            COUNT(DISTINCT f.objid) as segment_count
        FROM {route_schema}.fotrute f
        JOIN {route_schema}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE ST_Intersects(
            f.senterlinje::geometry,
            ST_Transform(
                ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                25833
            )
        )
    """

    if organization:
        query_optimized += " AND fi.vedlikeholdsansvarlig ILIKE %s"

    query_optimized += " GROUP BY fi.rutenummer, fi.rutenavn, fi.vedlikeholdsansvarlig"
    query_optimized += " LIMIT 100"

    with conn.cursor() as cur:
        cur.execute(query_optimized, params)
        plan = cur.fetchall()
        for row in plan:
            print(row[0])


def check_table_stats(conn, route_schema):
    """Check table statistics."""
    print("\n" + "=" * 60)
    print("Table Statistics")
    print("=" * 60)

    # schemaname in pg_stat_user_tables is a text column, so we use parameterized query
    query = """
        SELECT
            schemaname,
            relname as tablename,
            n_live_tup as row_count,
            n_dead_tup as dead_rows,
            last_vacuum,
            last_autovacuum,
            last_analyze,
            last_autoanalyze
        FROM pg_stat_user_tables
        WHERE schemaname = %s
        AND relname IN ('fotrute', 'fotruteinfo')
        ORDER BY relname;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (route_schema,))
        stats = cur.fetchall()

        for stat in stats:
            print(f"\n{stat['tablename']}:")
            print(f"  Rows: {stat['row_count']:,}")
            print(f"  Dead rows: {stat['dead_rows']:,}")
            if stat['last_analyze']:
                print(f"  Last analyzed: {stat['last_analyze']}")
            elif stat['last_autoanalyze']:
                print(f"  Last auto-analyzed: {stat['last_autoanalyze']}")
            else:
                print(f"  ⚠️  Never analyzed - statistics may be outdated")


def main():
    """Main function."""
    print("Query Performance Analysis")
    print("=" * 60)

    try:
        conn = get_db_connection()

        # Check indexes (also returns the discovered schema name)
        has_index, route_schema = check_indexes(conn)

        # Check table stats
        check_table_stats(conn, route_schema)

        # Analyze query plan (using test coordinates)
        if has_index:
            print("\n" + "=" * 60)
            print("Note: Running query plan analysis...")
            print("This may take a moment...")
            analyze_query_plan(conn, route_schema, 61.0, 8.0, 61.5, 8.5, organization="DNT")
        else:
            print("\n⚠️  Skipping query plan analysis - no spatial index found")
            print("   Create the index first for accurate analysis")

        conn.close()

        print("\n" + "=" * 60)
        print("Analysis complete!")
        print("=" * 60)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
