"""Database connection module."""
import psycopg2
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

# Schema names
ROUTE_SCHEMA = "turogfriluftsruter_b9b25c7668da494b9894d492fc35290d"
TEIG_SCHEMA = "matrikkeleneiendomskartteig_d56c3a44c39b43ae8081f08a97a28c7d"


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


def quote_identifier(identifier):
    """
    Safely quote a SQL identifier (table name, schema name, etc.).
    Uses psycopg2's identifier quoting.

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
    """Get database connection."""
    if USE_UNIX_SOCKET:
        conn_params = {
            'host': SOCKET_DIR,
            'database': DB_NAME,
            'user': DB_USER,
        }
    else:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        conn_params = {
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'database': parsed.path.lstrip('/'),
            'user': parsed.username,
            'password': parsed.password
        }

    # Remove None values
    conn_params = {k: v for k, v in conn_params.items() if v is not None}
    return psycopg2.connect(**conn_params)


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

