"""Operational database connection module (mutable data)."""
import os
from contextlib import contextmanager
import psycopg

from .database import USE_UNIX_SOCKET as IMPORT_USE_UNIX_SOCKET
from .database import SOCKET_DIR as IMPORT_SOCKET_DIR
from .database import DB_NAME as IMPORT_DB_NAME
from .database import DB_USER as IMPORT_DB_USER
from .database import DB_PASSWORD as IMPORT_DB_PASSWORD


# Operational database connection parameters (fall back to import DB if unset)
OP_DATABASE_URL = os.getenv("OP_DATABASE_URL")
OP_USE_UNIX_SOCKET = os.getenv("OP_USE_UNIX_SOCKET")
if OP_USE_UNIX_SOCKET is None:
    OP_USE_UNIX_SOCKET = IMPORT_USE_UNIX_SOCKET
else:
    OP_USE_UNIX_SOCKET = OP_USE_UNIX_SOCKET.lower() == "true"

OP_SOCKET_DIR = os.getenv("OP_DB_SOCKET_DIR", IMPORT_SOCKET_DIR)
OP_DB_NAME = os.getenv("OP_DB_NAME", IMPORT_DB_NAME)
OP_DB_USER = os.getenv("OP_DB_USER", IMPORT_DB_USER)
OP_DB_PASSWORD = os.getenv("OP_DB_PASSWORD", IMPORT_DB_PASSWORD)


def get_operational_db_connection():
    """Get operational database connection using psycopg3."""
    if OP_DATABASE_URL:
        return psycopg.connect(OP_DATABASE_URL)

    if OP_USE_UNIX_SOCKET:
        conn_params = {
            "host": OP_SOCKET_DIR,
            "dbname": OP_DB_NAME,
            "user": OP_DB_USER,
        }
        if OP_DB_PASSWORD:
            conn_params["password"] = OP_DB_PASSWORD
    else:
        from urllib.parse import urlparse

        parsed = urlparse(os.getenv("DATABASE_URL", ""))
        conn_params = {
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "dbname": parsed.path.lstrip("/") or OP_DB_NAME,
            "user": parsed.username or OP_DB_USER,
            "password": parsed.password or OP_DB_PASSWORD,
        }

    conn_params = {k: v for k, v in conn_params.items() if v is not None}
    return psycopg.connect(**conn_params)


@contextmanager
def op_db_connection():
    """
    Context manager for operational database connections.
    Ensures connections are always closed and transactions are committed.
    Commits on success, rolls back on exception.
    """
    conn = None
    try:
        conn = get_operational_db_connection()
        yield conn
        # Commit transaction if no exception occurred
        conn.commit()
    except Exception:
        # Rollback transaction on error
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
