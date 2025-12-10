"""Database connection module."""
import psycopg2
import os
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

