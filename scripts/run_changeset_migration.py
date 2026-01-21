#!/usr/bin/env python3
"""Run changeset editor database migrations using same connection as backend."""
import sys
from pathlib import Path
from services.database import USE_UNIX_SOCKET, SOCKET_DIR, DB_NAME, DB_USER, DB_PASSWORD
import subprocess
import os

def main():
    sql_file = Path('scripts/changeset_initial_schema.sql')
    if not sql_file.exists():
        print(f'Error: {sql_file} not found')
        sys.exit(1)

    cmd = ['psql']
    if USE_UNIX_SOCKET:
        cmd.extend(['-h', SOCKET_DIR])
    else:
        cmd.extend(['-h', 'localhost', '-p', '5432'])

    cmd.extend(['-U', DB_USER or os.getenv('USER', 'postgres')])

    if DB_PASSWORD:
        os.environ['PGPASSWORD'] = DB_PASSWORD

    # Use same database name as backend
    db_name = DB_NAME or os.getenv('DB_NAME', 'matrikkel')
    cmd.extend(['-d', db_name])
    cmd.extend(['-f', str(sql_file)])

    print(f"Running migration on database: {db_name}")
    print(f"Using {'Unix socket' if USE_UNIX_SOCKET else 'TCP'} connection")
    if USE_UNIX_SOCKET:
        print(f"Socket directory: {SOCKET_DIR}")
    print(f"User: {DB_USER or os.getenv('USER', 'postgres')}")

    result = subprocess.run(cmd)
    sys.exit(result.returncode)

if __name__ == '__main__':
    main()
