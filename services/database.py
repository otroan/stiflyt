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
DB_USER = os.getenv("DB_USER", "stiflyt_reader")

# Fixed schema name - ALWAYS use 'stiflyt' schema (never dynamic schema names)
# The schema name is fixed and does not change on each download
STIFLYT_SCHEMA = "stiflyt"

# Cached schema names (for backward compatibility)
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


def get_route_schema(conn=None):
    """
    Get the route schema name.

    ALWAYS returns 'stiflyt' - the fixed schema name.
    The schema name does not change on each download.

    Args:
        conn: Optional database connection (ignored, kept for backward compatibility).

    Returns:
        str: Route schema name (always 'stiflyt')
    """
    global _ROUTE_SCHEMA_CACHE

    if _ROUTE_SCHEMA_CACHE is not None:
        return _ROUTE_SCHEMA_CACHE

    # Try to get from environment variable first (for override if needed)
    env_schema = os.getenv("ROUTE_SCHEMA")
    if env_schema and validate_schema_name(env_schema):
        _ROUTE_SCHEMA_CACHE = env_schema
        return _ROUTE_SCHEMA_CACHE

    # Use fixed schema name
    _ROUTE_SCHEMA_CACHE = STIFLYT_SCHEMA
    return _ROUTE_SCHEMA_CACHE


def get_teig_schema(conn=None):
    """
    Get the teig schema name.

    ALWAYS returns 'stiflyt' - the fixed schema name.
    The schema name does not change on each download.

    Note: Teig/matrikkelenhet tables may or may not be in the stiflyt schema.
    This function is kept for backward compatibility.

    Args:
        conn: Optional database connection (ignored, kept for backward compatibility).

    Returns:
        str: Teig schema name (always 'stiflyt')
    """
    global _TEIG_SCHEMA_CACHE

    if _TEIG_SCHEMA_CACHE is not None:
        return _TEIG_SCHEMA_CACHE

    # Try to get from environment variable first (for override if needed)
    env_schema = os.getenv("TEIG_SCHEMA")
    if env_schema and validate_schema_name(env_schema):
        _TEIG_SCHEMA_CACHE = env_schema
        return _TEIG_SCHEMA_CACHE

    # Use fixed schema name
    _TEIG_SCHEMA_CACHE = STIFLYT_SCHEMA
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


# Schema name constants for backward compatibility (deprecated - use get_route_schema() instead)
# These are kept for scripts and legacy code
ROUTE_SCHEMA_PREFIX = None  # Deprecated - no longer used
TEIG_SCHEMA_PREFIX = None  # Deprecated - no longer used


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
