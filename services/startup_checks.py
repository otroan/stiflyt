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
)


def run_startup_checks() -> None:
    """
    Run critical startup checks.

    - Validates that required schemas, tables/views and columns exist.
    - Fails fast (raises RuntimeError) if validation has any errors.
    - Aborts application startup if any required tables/views are missing.
    """
    result = ValidationResult()

    try:
        with db_connection() as conn:
            # PostGIS must be present
            validate_postgis_extension(conn, result)

            # Required schemas and tables/views (using fixed schema name 'stiflyt')
            route_schema = validate_schema(conn, result, 'stiflyt', REQUIRED_ROUTE_TABLES)
            teig_schema = validate_schema(conn, result, 'stiflyt', REQUIRED_TEIG_TABLES)

            # FK checks (only if route schema exists)
            if route_schema:
                validate_foreign_keys(conn, result)

        if not result.is_valid():
            # Build a comprehensive error summary for logs / crash message
            summary_lines = [
                "=" * 80,
                "DATABASE VALIDATION FAILED - Application startup aborted",
                "=" * 80,
                "",
                "The following required database objects are missing or invalid:",
                "",
            ]

            # Group errors by category
            missing_schemas = []
            missing_tables = []
            missing_columns = []
            other_errors = []

            for err in result.errors:
                category = err.get('category', 'UNKNOWN')
                message = err.get('message', 'Unknown error')
                details = err.get('details', {})

                if category == 'MISSING_SCHEMA':
                    missing_schemas.append(f"  - {message}")
                elif category == 'MISSING_TABLE':
                    table_name = details.get('table', 'unknown')
                    schema_name = details.get('schema', 'unknown')
                    missing_tables.append(f"  - {schema_name}.{table_name}")
                elif category == 'MISSING_COLUMN':
                    table_name = details.get('table', 'unknown')
                    column_name = details.get('column', 'unknown')
                    schema_name = details.get('schema', 'unknown')
                    missing_columns.append(f"  - {schema_name}.{table_name}.{column_name}")
                else:
                    other_errors.append(f"  - [{category}] {message}")

            if missing_schemas:
                summary_lines.append("Missing schemas:")
                summary_lines.extend(missing_schemas)
                summary_lines.append("")

            if missing_tables:
                summary_lines.append("Missing required tables/views:")
                summary_lines.extend(missing_tables)
                summary_lines.append("")

            if missing_columns:
                summary_lines.append("Missing required columns:")
                summary_lines.extend(missing_columns)
                summary_lines.append("")

            if other_errors:
                summary_lines.append("Other errors:")
                summary_lines.extend(other_errors)
                summary_lines.append("")

            summary_lines.extend([
                "=" * 80,
                "ACTION REQUIRED:",
                "  1. Ensure the database import has completed successfully",
                "  2. Verify that all required tables/views exist in the 'stiflyt' schema",
                "  3. Check database connection settings and permissions",
                "  4. Re-run database import if necessary",
                "=" * 80,
            ])

            message = "\n".join(summary_lines)
            raise RuntimeError(message)

    except RuntimeError:
        # Re-raise RuntimeError (validation failures)
        raise
    except Exception as e:
        # Wrap other exceptions (connection errors, etc.)
        error_msg = (
            f"Database connection failed during startup validation:\n"
            f"  {type(e).__name__}: {str(e)}\n\n"
            f"Please check:\n"
            f"  - Database is running and accessible\n"
            f"  - Connection settings in .env file are correct\n"
            f"  - Database user has required permissions\n"
            f"  - Schema 'stiflyt' exists in the database"
        )
        raise RuntimeError(error_msg) from e


