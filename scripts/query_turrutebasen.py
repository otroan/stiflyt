"""Simple script to query route and teig tables and inspect their structure."""
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database connection parameters
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/matrikkel")

# Fixed schema name - ALWAYS use 'stiflyt' schema
ROUTE_SCHEMA = os.getenv("ROUTE_SCHEMA", "stiflyt")
TEIG_SCHEMA = os.getenv("TEIG_SCHEMA", "stiflyt")


def check_table_exists(conn, table_name):
    """Check if a table exists."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = %s
            );
        """, (table_name,))
        return cur.fetchone()[0]


def list_tables(conn):
    """List all tables in the database."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = cur.fetchall()
        return [t['table_name'] for t in tables]


def check_table_in_schema(conn, schema, table):
    """Check if a table exists in a specific schema."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = %s
                AND table_name = %s
            );
        """, (schema, table))
        return cur.fetchone()[0]


def get_table_info(conn):
    """Get information about the fotrute table structure."""
    # Check if table exists in the route schema
    if not check_table_in_schema(conn, ROUTE_SCHEMA, 'fotrute'):
        print("=" * 80)
        print(f"ERROR: Table '{ROUTE_SCHEMA}.fotrute' does not exist!")
        print("=" * 80)
        print("\nAvailable tables in database:")
        tables = list_tables(conn)
        if tables:
            for table in tables:
                print(f"  - {table}")
        else:
            print("  (no tables found)")
        print(f"\nPlease check schema name. Current: {ROUTE_SCHEMA}")
        return False

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get column information
        cur.execute(f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'fotrute'
            ORDER BY ordinal_position;
        """, (ROUTE_SCHEMA,))

        columns = cur.fetchall()
        print("=" * 80)
        print(f"fotrute Table Structure (schema: {ROUTE_SCHEMA}):")
        print("=" * 80)
        for col in columns:
            print(f"  {col['column_name']:30} {col['data_type']:20} nullable={col['is_nullable']}")

        # Get row count
        cur.execute(f"SELECT COUNT(*) as count FROM {ROUTE_SCHEMA}.fotrute;")
        count = cur.fetchone()
        print(f"\nTotal rows: {count['count']}")

        # Check for route identifier fields
        cur.execute(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'fotrute'
            AND (column_name LIKE '%%rute%%' OR column_name LIKE '%%id%%');
        """, (ROUTE_SCHEMA,))
        id_columns = cur.fetchall()
        if id_columns:
            print("\nPotential route identifier columns:")
            for col in id_columns:
                print(f"  - {col['column_name']}")

        # Get sample route identifiers (try rutefolger or lokalid)
        for col_name in ['rutefolger', 'lokalid', 'anleggsnummer']:
            cur.execute(f"""
                SELECT COUNT(DISTINCT {col_name}) as unique_values
                FROM {ROUTE_SCHEMA}.fotrute
                WHERE {col_name} IS NOT NULL;
            """)
            result = cur.fetchone()
            if result and result['unique_values'] > 0:
                print(f"\nUnique {col_name} values: {result['unique_values']}")

                # Get sample values
                cur.execute(f"""
                    SELECT DISTINCT {col_name}, COUNT(*) as segment_count
                    FROM {ROUTE_SCHEMA}.fotrute
                    WHERE {col_name} IS NOT NULL
                    GROUP BY {col_name}
                    ORDER BY segment_count DESC
                    LIMIT 10;
                """)
                sample_routes = cur.fetchall()
                print(f"Top 10 {col_name} by segment count:")
                for route in sample_routes:
                    print(f"  {str(route[col_name]):30} {route['segment_count']:5} segments")
                break

    return True


def get_sample_data(conn, limit=5):
    """Get sample data from fotrute."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            SELECT *
            FROM {ROUTE_SCHEMA}.fotrute
            LIMIT {limit};
        """)

        rows = cur.fetchall()
        print("\n" + "=" * 80)
        print(f"Sample Data (first {limit} rows):")
        print("=" * 80)

        for i, row in enumerate(rows, 1):
            print(f"\nRow {i}:")
            for key, value in row.items():
                if key in ['senterlinje', 'omrade', 'representasjonspunkt', 'geom']:
                    # Get geometry info
                    cur.execute("""
                        SELECT
                            ST_GeometryType(%s::geometry) as geom_type,
                            ST_SRID(%s::geometry) as srid,
                            ST_Length(ST_Transform(%s::geometry, 3857)) as length_meters
                    """, (value, value, value))
                    geom_info = cur.fetchone()
                    if geom_info:
                        print(f"  {key:20} {geom_info['geom_type']} (SRID: {geom_info['srid']}, Length: {geom_info['length_meters']:.2f}m)")
                    else:
                        print(f"  {key:20} (geometry)")
                else:
                    print(f"  {key:20} {value}")


def get_route_example(conn, route_identifier=None):
    """Get example route data."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Try to find a route identifier column
        identifier_col = None
        for col_name in ['rutefolger', 'lokalid', 'anleggsnummer']:
            cur.execute(f"""
                SELECT COUNT(DISTINCT {col_name}) as cnt
                FROM {ROUTE_SCHEMA}.fotrute
                WHERE {col_name} IS NOT NULL;
            """)
            result = cur.fetchone()
            if result and result['cnt'] > 0:
                identifier_col = col_name
                break

        if not identifier_col:
            print("\nNo suitable route identifier column found.")
            return

        if route_identifier:
            cur.execute(f"""
                SELECT *
                FROM {ROUTE_SCHEMA}.fotrute
                WHERE {identifier_col} = %s
                ORDER BY objid
                LIMIT 5;
            """, (route_identifier,))
        else:
            # Get first route with multiple segments
            cur.execute(f"""
                SELECT {identifier_col}, COUNT(*) as cnt
                FROM {ROUTE_SCHEMA}.fotrute
                WHERE {identifier_col} IS NOT NULL
                GROUP BY {identifier_col}
                HAVING COUNT(*) > 1
                ORDER BY cnt DESC
                LIMIT 1;
            """)
            route_info = cur.fetchone()
            if route_info:
                route_id = route_info[identifier_col]
                print(f"\nExample route ({identifier_col}): {route_id} ({route_info['cnt']} segments)")
                cur.execute(f"""
                    SELECT *
                    FROM {ROUTE_SCHEMA}.fotrute
                    WHERE {identifier_col} = %s
                    ORDER BY objid
                    LIMIT 5;
                """, (route_id,))
            else:
                print("\nNo routes with multiple segments found.")
                return

        rows = cur.fetchall()
        print("\n" + "=" * 80)
        print(f"Example Route Segments:")
        print("=" * 80)

        for i, row in enumerate(rows, 1):
            print(f"\nSegment {i}:")
            for key, value in row.items():
                if key in ['senterlinje', 'omrade', 'representasjonspunkt', 'geom']:
                    cur.execute("""
                        SELECT
                            ST_AsText(ST_StartPoint(%s::geometry)) as start_point,
                            ST_AsText(ST_EndPoint(%s::geometry)) as end_point,
                            ST_Length(ST_Transform(%s::geometry, 3857)) as length_meters
                    """, (value, value, value))
                    geom_info = cur.fetchone()
                    if geom_info and geom_info.get('start_point'):
                        print(f"  {key:20} Start: {geom_info['start_point']}")
                        print(f"  {'':20} End: {geom_info['end_point']}")
                        print(f"  {'':20} Length: {geom_info['length_meters']:.2f}m")
                    elif geom_info:
                        print(f"  {key:20} Length: {geom_info['length_meters']:.2f}m")
                else:
                    print(f"  {key:20} {value}")


def main():
    """Main function."""
    try:
        # Check if using Unix domain socket
        use_unix_socket = os.getenv("USE_UNIX_SOCKET", "true").lower() == "true"
        socket_dir = os.getenv("DB_SOCKET_DIR", "/var/run/postgresql")

        # Get database name and user from environment variables (take precedence)
        db_name = os.getenv("DB_NAME")
        db_user = os.getenv("DB_USER")
        db_password = os.getenv("DB_PASSWORD")

        # Parse DATABASE_URL if it's a full URL
        if DATABASE_URL.startswith("postgresql://"):
            from urllib.parse import urlparse
            parsed = urlparse(DATABASE_URL)

            # Use environment variables if set, otherwise use parsed values
            db_name = db_name or parsed.path.lstrip('/')
            db_user = db_user or parsed.username
            db_password = db_password or parsed.password

            if use_unix_socket:
                # Use Unix domain socket
                conn_params = {
                    'host': socket_dir,  # Socket directory path
                    'database': db_name,
                    'user': db_user,
                }
                if db_password:
                    conn_params['password'] = db_password
            else:
                # Use TCP connection
                conn_params = {
                    'host': parsed.hostname,
                    'port': parsed.port or 5432,
                    'database': db_name,
                    'user': db_user,
                }
                if db_password:
                    conn_params['password'] = db_password
        else:
            # Use environment variables directly
            if use_unix_socket:
                conn_params = {
                    'host': socket_dir,
                    'database': db_name or os.getenv("DB_NAME", "matrikkel"),
                    'user': db_user or os.getenv("USER"),  # Default to current user
                }
                if db_password:
                    conn_params['password'] = db_password
            else:
                conn_params = {
                    'host': os.getenv("DB_HOST", "localhost"),
                    'port': os.getenv("DB_PORT", "5432"),
                    'database': db_name or os.getenv("DB_NAME", "matrikkel"),
                    'user': db_user or os.getenv("DB_USER", "user"),
                }
                if db_password:
                    conn_params['password'] = db_password

        # Remove None values (password might be None for socket auth)
        conn_params = {k: v for k, v in conn_params.items() if v is not None}

        print("Connecting to database...")
        if use_unix_socket:
            print(f"Using Unix domain socket: {conn_params.get('host', socket_dir)}")
        else:
            print(f"Host: {conn_params.get('host')}:{conn_params.get('port', 5432)}")
        print(f"Database: {conn_params.get('database')}")
        print(f"User: {conn_params.get('user')}")

        conn = psycopg2.connect(**conn_params)

        # Check if PostGIS is enabled
        with conn.cursor() as cur:
            cur.execute("SELECT PostGIS_version();")
            version = cur.fetchone()
            print(f"PostGIS version: {version[0]}\n")

        # Get table information
        if not get_table_info(conn):
            # Table doesn't exist, exit early
            conn.close()
            return

        # Get sample data
        get_sample_data(conn, limit=3)

        # Get route example
        get_route_example(conn)

        conn.close()
        print("\n" + "=" * 80)
        print("Query completed successfully!")
        print("=" * 80)

    except psycopg2.Error as e:
        print(f"\nDatabase error: {e}")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

