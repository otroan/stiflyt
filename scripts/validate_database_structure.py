#!/usr/bin/env python3
"""
Validate database structure - check that all required tables, columns, and indexes exist.

This script validates that the database has all the tables, columns, and indexes
that the backend requires. If anything is missing, it reports what needs to be fixed
in the database import repository.

Usage:
    # Activate virtual environment first:
    source venv/bin/activate  # or: . venv/bin/activate

    # Then run the script:
    python scripts/validate_database_structure.py
    python scripts/validate_database_structure.py --verbose
    python scripts/validate_database_structure.py --output report.json

Prerequisites:
    - Virtual environment must be activated
    - Database connection must be configured (via .env or environment variables)
"""
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from services.database import (
        get_db_connection,
        db_connection,
        get_route_schema,
        get_teig_schema,
        ROUTE_SCHEMA_PREFIX,
        TEIG_SCHEMA_PREFIX,
    )
    from psycopg.rows import dict_row
except ImportError as e:
    print("Error: Failed to import required modules.")
    print(f"   {e}")
    print("\nPlease ensure:")
    print("   1. Virtual environment is activated: source venv/bin/activate")
    print("   2. Dependencies are installed: pip install -r requirements.txt")
    sys.exit(1)


class ValidationResult:
    """Container for validation results."""
    def __init__(self):
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []
        self.info: List[Dict] = []
        self.schemas_found: Dict[str, str] = {}
        self.tables_found: Dict[str, List[str]] = {}
        self.columns_found: Dict[str, Dict[str, List[str]]] = {}
        self.indexes_found: Dict[str, Dict[str, List[str]]] = {}

    def add_error(self, category: str, message: str, details: Optional[Dict] = None):
        """Add an error."""
        error = {
            'category': category,
            'message': message,
            'details': details or {}
        }
        self.errors.append(error)

    def add_warning(self, category: str, message: str, details: Optional[Dict] = None):
        """Add a warning."""
        warning = {
            'category': category,
            'message': message,
            'details': details or {}
        }
        self.warnings.append(warning)

    def add_info(self, message: str, details: Optional[Dict] = None):
        """Add an info message."""
        info = {
            'message': message,
            'details': details or {}
        }
        self.info.append(info)

    def is_valid(self) -> bool:
        """Check if validation passed (no errors)."""
        return len(self.errors) == 0


# Required tables and their columns
REQUIRED_ROUTE_TABLES = {
    'fotrute': {
        'required_columns': [
            'objid',
            'senterlinje',  # Geometry column
        ],
        'optional_columns': [],
    },
    'fotruteinfo': {
        'required_columns': [
            'objid',
            'rutenummer',
            'rutenavn',
            'vedlikeholdsansvarlig',
            'fotrute_fk',  # Foreign key to fotrute.objid
        ],
        'optional_columns': [],
    },
    'ruteinfopunkt': {
        'required_columns': [],  # Optional table
        'optional_columns': [
            'objid',
            'navn',
            'geom',  # Geometry column
        ],
    },
    'links': {
        'required_columns': [
            'link_id',
            'a_node',
            'b_node',
            'length_m',
            'geom',  # Geometry column
        ],
        'optional_columns': [
            'rutenavn_list',
            'rutenummer_list',
            'rutetype_list',
            'vedlikeholdsansvarlig_list',
        ],
    },
    'links_with_routes': {
        'required_columns': [
            'link_id',
            'a_node',
            'b_node',
            'length_m',
            'geom',  # Geometry column
            'rutenavn_list',
            'rutenummer_list',
            'rutetype_list',
            'vedlikeholdsansvarlig_list',
        ],
        'optional_columns': [],
    },
    'anchor_nodes': {
        'required_columns': [
            'node_id',
            'geom',  # Geometry column
        ],
        'optional_columns': [
            'navn',
            'navn_kilde',
            'navn_distance_m',
        ],
        # Anchor nodes are required for backend – if missing, validation must fail
    },
}

REQUIRED_TEIG_TABLES = {
    'teig': {
        'required_columns': [
            'objid',
            'omrade',  # Geometry column (POLYGON)
            'matrikkelnummertekst',
            'teigid',
        ],
        'optional_columns': [
            'representasjonspunkt',  # Geometry column (POINT)
            'kommunenummer',
            'kommunenavn',
        ],
    },
    'matrikkelenhet': {
        'required_columns': [],  # Optional table
        'optional_columns': [
            'teig_fk',  # Foreign key to teig.teigid
            'kommunenummer',
            'gardsnummer',
            'bruksnummer',
            'festenummer',
        ],
    },
}

# Recommended indexes (spatial indexes are usually auto-created by PostGIS)
RECOMMENDED_INDEXES = {
    'fotrute': [
        ('objid', 'PRIMARY KEY or UNIQUE'),
        ('senterlinje', 'SPATIAL INDEX (GIST)'),
    ],
    'fotruteinfo': [
        ('objid', 'PRIMARY KEY or UNIQUE'),
        ('fotrute_fk', 'INDEX (for JOIN performance)'),
        ('rutenummer', 'INDEX (for filtering)'),
    ],
    'links': [
        ('link_id', 'PRIMARY KEY or UNIQUE'),
        ('geom', 'SPATIAL INDEX (GIST)'),
    ],
    'links_with_routes': [
        ('link_id', 'PRIMARY KEY or UNIQUE'),
        ('geom', 'SPATIAL INDEX (GIST)'),
    ],
    'anchor_nodes': [
        ('node_id', 'PRIMARY KEY or UNIQUE'),
        ('geom', 'SPATIAL INDEX (GIST)'),
    ],
    'teig': [
        ('objid', 'PRIMARY KEY or UNIQUE'),
        ('teigid', 'INDEX or UNIQUE'),
        ('omrade', 'SPATIAL INDEX (GIST)'),
        ('matrikkelnummertekst', 'INDEX (for filtering)'),
    ],
}


def check_schema_exists(conn, prefix: str) -> Optional[str]:
    """Check if a schema with the given prefix exists."""
    query = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE %s
        ORDER BY schema_name
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(query, (f"{prefix}%",))
        result = cur.fetchone()
        return result[0] if result else None


def get_tables_in_schema(conn, schema: str) -> List[str]:
    """Get all tables in a schema."""
    query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (schema,))
        return [row['table_name'] for row in cur.fetchall()]


def get_views_in_schema(conn, schema: str) -> List[str]:
    """Get all views in a schema."""
    query = """
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = %s
        ORDER BY table_name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (schema,))
        return [row['table_name'] for row in cur.fetchall()]


def get_columns_in_table(conn, schema: str, table: str) -> List[str]:
    """
    Get all columns in a relation (table, view or materialized view).

    We use pg_class/pg_attribute instead of information_schema.columns so that
    materialized views are handled consistently.
    """
    query = """
        SELECT a.attname AS column_name
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (schema, table))
        return [row["column_name"] for row in cur.fetchall()]


def get_indexes_on_table(conn, schema: str, table: str) -> List[Dict]:
    """Get all indexes on a table."""
    query = """
        SELECT
            i.indexname,
            i.indexdef
        FROM pg_indexes i
        WHERE i.schemaname = %s
          AND i.tablename = %s
        ORDER BY i.indexname
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (schema, table))
        indexes = []
        for row in cur.fetchall():
            # Extract column names from index definition
            # This is a simple approach - indexdef contains column names
            idx_def = row['indexdef']
            # Try to extract column names from definition
            # Format is usually: CREATE [UNIQUE] INDEX ... ON ... (column1, column2)
            columns = []
            if '(' in idx_def and ')' in idx_def:
                cols_part = idx_def[idx_def.index('(')+1:idx_def.index(')')]
                # Split by comma and clean up
                for col in cols_part.split(','):
                    col = col.strip().strip('"')
                    if col:
                        columns.append(col)

            indexes.append({
                'name': row['indexname'],
                'definition': idx_def,
                'columns': columns
            })
        return indexes


def check_geometry_column(conn, schema: str, table: str, column: str) -> bool:
    """Check if a column is a PostGIS geometry column."""
    query = """
        SELECT f_table_schema, f_table_name, f_geometry_column
        FROM geometry_columns
        WHERE f_table_schema = %s
          AND f_table_name = %s
          AND f_geometry_column = %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (schema, table, column))
        return cur.fetchone() is not None


def validate_table(
    conn,
    result: ValidationResult,
    schema: str,
    table_name: str,
    table_def: Dict,
    is_required: bool = True,
):
    """Validate a single table (table, view or materialized view)."""
    # Check if relation exists (table, view or materialized view),
    # mirroring how the API discovers anchor_nodes.
    rel_query = """
        SELECT c.relname AS relname, c.relkind AS relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND c.relkind IN ('r', 'v', 'm')  -- table, view, materialized view
        LIMIT 1
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(rel_query, (schema, table_name))
        rel_info = cur.fetchone()

    # Also get all tables/views for reporting
    all_tables = get_tables_in_schema(conn, schema)
    all_views = get_views_in_schema(conn, schema)
    all_table_like = all_tables + all_views

    if not rel_info:
        if is_required:
            result.add_error(
                'MISSING_TABLE',
                f"Required table/view '{table_name}' not found in schema '{schema}'",
                {'schema': schema, 'table': table_name}
            )
        else:
            result.add_warning(
                'MISSING_OPTIONAL_TABLE',
                f"Optional table/view '{table_name}' not found in schema '{schema}'",
                {'schema': schema, 'table': table_name}
            )
        return

    # Map relkind to a human-readable type
    relkind = rel_info["relkind"]
    if relkind == "r":
        table_type = "TABLE"
    elif relkind == "v":
        table_type = "VIEW"
    elif relkind == "m":
        table_type = "MATERIALIZED VIEW"
    else:
        table_type = relkind

    is_view = relkind in ("v", "m")
    result.add_info(
        f"Found table/view '{table_name}' in schema '{schema}'",
        {
            "schema": schema,
            "table": table_name,
            "is_view": is_view,
            "table_type": table_type,
        },
    )

    # Get columns
    columns = get_columns_in_table(conn, schema, table_name)
    result.columns_found.setdefault(schema, {})[table_name] = columns

    # Check required columns
    required_cols = table_def.get('required_columns', [])
    for col in required_cols:
        if col not in columns:
            result.add_error(
                'MISSING_COLUMN',
                f"Required column '{col}' not found in table '{schema}.{table_name}'",
                {'schema': schema, 'table': table_name, 'column': col}
            )
        else:
            # Check if it's a geometry column
            if col in ['senterlinje', 'geom', 'omrade', 'representasjonspunkt']:
                if not check_geometry_column(conn, schema, table_name, col):
                    result.add_warning(
                        'GEOMETRY_COLUMN_NOT_REGISTERED',
                        f"Column '{col}' in '{schema}.{table_name}' is not registered in geometry_columns",
                        {'schema': schema, 'table': table_name, 'column': col}
                    )

    # Check optional columns (just report if missing)
    optional_cols = table_def.get('optional_columns', [])
    for col in optional_cols:
        if col not in columns:
            result.add_info(
                f"Optional column '{col}' not found in table '{schema}.{table_name}'",
                {'schema': schema, 'table': table_name, 'column': col}
            )

    # Check indexes
    if table_name in RECOMMENDED_INDEXES:
        indexes = get_indexes_on_table(conn, schema, table_name)
        result.indexes_found.setdefault(schema, {})[table_name] = [
            idx['name'] for idx in indexes
        ]

        recommended = RECOMMENDED_INDEXES[table_name]
        indexed_columns = set()
        for idx in indexes:
            indexed_columns.update(idx['columns'])

        for col, idx_type in recommended:
            if col not in indexed_columns:
                if 'PRIMARY KEY' in idx_type or 'UNIQUE' in idx_type:
                    result.add_warning(
                        'MISSING_PRIMARY_KEY',
                        f"Table '{schema}.{table_name}' may be missing PRIMARY KEY or UNIQUE constraint on '{col}'",
                        {'schema': schema, 'table': table_name, 'column': col, 'type': idx_type}
                    )
                elif 'SPATIAL' in idx_type:
                    result.add_warning(
                        'MISSING_SPATIAL_INDEX',
                        f"Table '{schema}.{table_name}' may be missing spatial index on '{col}'",
                        {'schema': schema, 'table': table_name, 'column': col}
                    )
                else:
                    result.add_info(
                        f"Table '{schema}.{table_name}' may benefit from index on '{col}'",
                        {'schema': schema, 'table': table_name, 'column': col, 'type': idx_type}
                    )


def validate_schema(conn, result: ValidationResult, prefix: str, required_tables: Dict):
    """Validate a schema and its tables."""
    schema = check_schema_exists(conn, prefix)
    if not schema:
        result.add_error(
            'MISSING_SCHEMA',
            f"Required schema with prefix '{prefix}' not found",
            {'prefix': prefix}
        )
        return None

    result.schemas_found[prefix] = schema
    result.add_info(
        f"Found schema '{schema}' with prefix '{prefix}'",
        {'prefix': prefix, 'schema': schema}
    )

    # Get all tables in schema
    all_tables = get_tables_in_schema(conn, schema)
    all_views = get_views_in_schema(conn, schema)
    result.tables_found[schema] = all_tables + all_views

    # Validate each required table
    for table_name, table_def in required_tables.items():
        # Check if this is a required table
        # A table is optional if explicitly marked, otherwise required if it has required columns
        is_optional_table = table_def.get('is_optional_table', False)
        has_required_columns = len(table_def.get('required_columns', [])) > 0
        is_required = not is_optional_table and has_required_columns
        validate_table(conn, result, schema, table_name, table_def, is_required)

    return schema


def validate_foreign_keys(conn, result: ValidationResult):
    """Validate foreign key relationships."""
    route_schema = result.schemas_found.get(ROUTE_SCHEMA_PREFIX)
    if not route_schema:
        return

    # Check fotruteinfo.fotrute_fk -> fotrute.objid
    query = """
        SELECT
            tc.constraint_name,
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = %s
          AND tc.table_name = 'fotruteinfo'
          AND kcu.column_name = 'fotrute_fk'
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (route_schema,))
        fk = cur.fetchone()
        if not fk:
            result.add_warning(
                'MISSING_FOREIGN_KEY',
                f"Foreign key from fotruteinfo.fotrute_fk to fotrute.objid not found",
                {'schema': route_schema, 'table': 'fotruteinfo', 'column': 'fotrute_fk'}
            )
        else:
            result.add_info(
                f"Foreign key found: fotruteinfo.fotrute_fk -> {fk['foreign_table_name']}.{fk['foreign_column_name']}",
                {'constraint': fk['constraint_name']}
            )


def validate_postgis_extension(conn, result: ValidationResult):
    """Check if PostGIS extension is installed."""
    query = """
        SELECT EXISTS(
            SELECT 1
            FROM pg_extension
            WHERE extname = 'postgis'
        ) as postgis_installed
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        row = cur.fetchone()
        if not row['postgis_installed']:
            result.add_error(
                'MISSING_POSTGIS',
                "PostGIS extension is not installed",
                {}
            )
        else:
            result.add_info("PostGIS extension is installed", {})


def generate_report(result: ValidationResult, output_file: Optional[str] = None, verbose: bool = False):
    """Generate validation report."""
    report = {
        'validation_date': datetime.now().isoformat(),
        'summary': {
            'valid': result.is_valid(),
            'error_count': len(result.errors),
            'warning_count': len(result.warnings),
            'info_count': len(result.info),
        },
        'schemas_found': result.schemas_found,
        'tables_found': result.tables_found,
        'columns_found': result.columns_found,
        'indexes_found': result.indexes_found,
        'errors': result.errors,
        'warnings': result.warnings,
    }

    if verbose:
        report['info'] = result.info

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report saved to {output_file}")

    # Print summary
    print("\n" + "="*70)
    print("DATABASE STRUCTURE VALIDATION REPORT")
    print("="*70)
    print(f"Validation date: {report['validation_date']}")
    print(f"\nSummary:")
    print(f"  Status: {'✓ VALID' if result.is_valid() else '✗ INVALID'}")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")
    if verbose:
        print(f"  Info messages: {len(result.info)}")

    print(f"\nSchemas found:")
    for prefix, schema in result.schemas_found.items():
        print(f"  {prefix} -> {schema}")

    if result.errors:
        print(f"\n{'='*70}")
        print("ERRORS (must be fixed):")
        print("="*70)
        for i, error in enumerate(result.errors, 1):
            print(f"\n{i}. {error['category']}: {error['message']}")
            if error['details']:
                print(f"   Details: {error['details']}")

    if result.warnings:
        print(f"\n{'='*70}")
        print("WARNINGS (should be fixed):")
        print("="*70)
        for i, warning in enumerate(result.warnings, 1):
            print(f"\n{i}. {warning['category']}: {warning['message']}")
            if warning['details']:
                print(f"   Details: {warning['details']}")

    if verbose and result.info:
        print(f"\n{'='*70}")
        print("INFO MESSAGES:")
        print("="*70)
        for i, info in enumerate(result.info, 1):
            print(f"{i}. {info['message']}")
            if info['details']:
                print(f"   Details: {info['details']}")

    print("\n" + "="*70)
    if not result.is_valid():
        print("\n⚠️  Database structure validation FAILED!")
        print("   Please fix the errors above in the database import repository.")
        print("   Then re-run the database import and try again.")
    else:
        print("\n✓ Database structure validation PASSED!")
        if result.warnings:
            print("   Some warnings were found - consider fixing them for better performance.")
    print("="*70 + "\n")

    return report


def main():
    parser = argparse.ArgumentParser(
        description='Validate database structure - check tables, columns, and indexes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show info messages'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output file for report (JSON format)'
    )
    args = parser.parse_args()

    result = ValidationResult()

    print("Connecting to database...")
    with db_connection() as conn:
        # Check PostGIS
        print("Checking PostGIS extension...")
        validate_postgis_extension(conn, result)

        # Validate route schema
        print(f"Validating route schema (prefix: {ROUTE_SCHEMA_PREFIX})...")
        route_schema = validate_schema(conn, result, ROUTE_SCHEMA_PREFIX, REQUIRED_ROUTE_TABLES)

        # Validate teig schema
        print(f"Validating teig schema (prefix: {TEIG_SCHEMA_PREFIX})...")
        teig_schema = validate_schema(conn, result, TEIG_SCHEMA_PREFIX, REQUIRED_TEIG_TABLES)

        # Validate foreign keys
        if route_schema:
            print("Validating foreign keys...")
            validate_foreign_keys(conn, result)

    # Generate report
    generate_report(result, args.output, args.verbose)

    # Exit with error code if validation failed
    sys.exit(0 if result.is_valid() else 1)


if __name__ == '__main__':
    main()

