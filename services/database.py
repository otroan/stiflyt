"""Database connection module."""
import psycopg
import os
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

# Database connection parameters
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/matrikkel")
USE_UNIX_SOCKET = os.getenv("USE_UNIX_SOCKET", "true").lower() == "true"
SOCKET_DIR = os.getenv("DB_SOCKET_DIR", "/var/run/postgresql")
DB_NAME = os.getenv("DB_NAME", "matrikkel")
DB_USER = os.getenv("DB_USER", os.getenv("USER"))

# Schema name prefixes (hash suffix changes on each download)
ROUTE_SCHEMA_PREFIX = "turogfriluftsruter_"
TEIG_SCHEMA_PREFIX = "matrikkeleneiendomskartteig_"

# Cached schema names (will be discovered dynamically)
_ROUTE_SCHEMA_CACHE = None
_TEIG_SCHEMA_CACHE = None


def validate_schema_name(schema_name):
    """
    Validate that a schema name is safe for use in SQL queries.
    Schema names should only contain alphanumeric characters and underscores.

    Args:
        schema_name: Schema name to validate

    Returns:
        bool: True if valid, False otherwise
    """
    if not schema_name or not isinstance(schema_name, str):
        return False
    # Allow alphanumeric, underscores, and hyphens (common in schema names)
    import re
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', schema_name))


def discover_schema(conn, prefix):
    """
    Dynamically discover a schema name by prefix.
    The schema name contains a hash that can change on each download.

    Args:
        conn: Database connection
        prefix: Schema name prefix (e.g., "turogfriluftsruter_")

    Returns:
        str: Schema name if found, None otherwise
    """
    query = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE %s
        ORDER BY schema_name
        LIMIT 1;
    """

    try:
        with conn.cursor() as cur:
            cur.execute(query, (f"{prefix}%",))
            result = cur.fetchone()
            if result:
                schema_name = result[0]
                # Validate schema name for safety
                if validate_schema_name(schema_name):
                    return schema_name
    except Exception as e:
        print(f"Error discovering schema with prefix '{prefix}': {str(e)}")

    return None


def get_route_schema(conn=None):
    """
    Get the route schema name, discovering it dynamically if needed.
    Results are cached to avoid repeated database queries.

    Args:
        conn: Optional database connection. If None, a new connection is created.

    Returns:
        str: Route schema name
    """
    global _ROUTE_SCHEMA_CACHE

    if _ROUTE_SCHEMA_CACHE is not None:
        return _ROUTE_SCHEMA_CACHE

    # Try to get from environment variable first
    env_schema = os.getenv("ROUTE_SCHEMA")
    if env_schema and validate_schema_name(env_schema):
        _ROUTE_SCHEMA_CACHE = env_schema
        return _ROUTE_SCHEMA_CACHE

    # Discover dynamically
    if conn is None:
        with db_connection() as temp_conn:
            _ROUTE_SCHEMA_CACHE = discover_schema(temp_conn, ROUTE_SCHEMA_PREFIX)
    else:
        _ROUTE_SCHEMA_CACHE = discover_schema(conn, ROUTE_SCHEMA_PREFIX)

    if _ROUTE_SCHEMA_CACHE is None:
        raise ValueError(f"Could not discover route schema with prefix '{ROUTE_SCHEMA_PREFIX}'. "
                        "Please set ROUTE_SCHEMA environment variable or ensure schema exists.")

    return _ROUTE_SCHEMA_CACHE


def get_teig_schema(conn=None):
    """
    Get the teig schema name, discovering it dynamically if needed.
    Results are cached to avoid repeated database queries.

    Args:
        conn: Optional database connection. If None, a new connection is created.

    Returns:
        str: Teig schema name
    """
    global _TEIG_SCHEMA_CACHE

    if _TEIG_SCHEMA_CACHE is not None:
        return _TEIG_SCHEMA_CACHE

    # Try to get from environment variable first
    env_schema = os.getenv("TEIG_SCHEMA")
    if env_schema and validate_schema_name(env_schema):
        _TEIG_SCHEMA_CACHE = env_schema
        return _TEIG_SCHEMA_CACHE

    # Discover dynamically
    if conn is None:
        with db_connection() as temp_conn:
            _TEIG_SCHEMA_CACHE = discover_schema(temp_conn, TEIG_SCHEMA_PREFIX)
    else:
        _TEIG_SCHEMA_CACHE = discover_schema(conn, TEIG_SCHEMA_PREFIX)

    if _TEIG_SCHEMA_CACHE is None:
        raise ValueError(f"Could not discover teig schema with prefix '{TEIG_SCHEMA_PREFIX}'. "
                        "Please set TEIG_SCHEMA environment variable or ensure schema exists.")

    return _TEIG_SCHEMA_CACHE


# For backward compatibility: provide module-level variables
# These will be initialized lazily on first access using __getattr__
def __getattr__(name):
    """Lazy initialization of schema names for backward compatibility."""
    if name == 'ROUTE_SCHEMA':
        global _ROUTE_SCHEMA_CACHE
        if _ROUTE_SCHEMA_CACHE is None:
            _ROUTE_SCHEMA_CACHE = get_route_schema()
        return _ROUTE_SCHEMA_CACHE
    elif name == 'TEIG_SCHEMA':
        global _TEIG_SCHEMA_CACHE
        if _TEIG_SCHEMA_CACHE is None:
            _TEIG_SCHEMA_CACHE = get_teig_schema()
        return _TEIG_SCHEMA_CACHE
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def quote_identifier(identifier):
    """
    Safely quote a SQL identifier (table name, schema name, etc.).

    Args:
        identifier: Identifier to quote

    Returns:
        str: Quoted identifier
    """
    if not validate_schema_name(identifier):
        raise ValueError(f"Invalid identifier: {identifier}")
    # For PostgreSQL, identifiers are quoted with double quotes
    # But we validate first to ensure safety
    return f'"{identifier}"'


def get_db_connection():
    """Get database connection using psycopg3."""
    # Try DATABASE_URL first
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return psycopg.connect(database_url)

    # Fall back to individual connection parameters
    if USE_UNIX_SOCKET:
        conn_params = {
            'host': SOCKET_DIR,
            'dbname': DB_NAME,
            'user': DB_USER,
        }
    else:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        conn_params = {
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'dbname': parsed.path.lstrip('/'),
            'user': parsed.username,
            'password': parsed.password
        }

    # Remove None values
    conn_params = {k: v for k, v in conn_params.items() if v is not None}
    return psycopg.connect(**conn_params)


@contextmanager
def db_connection():
    """
    Context manager for database connections.
    Ensures connections are always closed, even if an exception occurs.

    Usage:
        with db_connection() as conn:
            # use conn
            pass
    """
    conn = None
    try:
        conn = get_db_connection()
        yield conn
    finally:
        if conn is not None:
            conn.close()
