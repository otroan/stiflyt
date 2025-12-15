"""Startup checks for backend – validate database structure before serving requests."""

from typing import Any

from services.database import db_connection
from scripts.validate_database_structure import (  # type: ignore
    ValidationResult,
    validate_schema,
    validate_postgis_extension,
    validate_foreign_keys,
    REQUIRED_ROUTE_TABLES,
    REQUIRED_TEIG_TABLES,
    ROUTE_SCHEMA_PREFIX,
    TEIG_SCHEMA_PREFIX,
)


def run_startup_checks() -> None:
    """
    Run critical startup checks.

    - Validates that required schemas, tables and columns exist.
    - Fails fast (raises RuntimeError) if validation has any errors.
    """
    result = ValidationResult()

    with db_connection() as conn:
        # PostGIS must be present
        validate_postgis_extension(conn, result)

        # Required schemas and tables
        route_schema = validate_schema(conn, result, ROUTE_SCHEMA_PREFIX, REQUIRED_ROUTE_TABLES)
        teig_schema = validate_schema(conn, result, TEIG_SCHEMA_PREFIX, REQUIRED_TEIG_TABLES)

        # FK checks (only if route schema exists)
        if route_schema:
            validate_foreign_keys(conn, result)

    if not result.is_valid():
        # Build a compact error summary for logs / crash message
        summary_lines = ["Database startup validation failed – fix DB import before starting API.", ""]
        for err in result.errors:
            summary_lines.append(f"- {err.get('category')}: {err.get('message')} ({err.get('details')})")
        message = "\n".join(summary_lines)
        raise RuntimeError(message)


