#!/usr/bin/env python3
"""Remap endpoint_names to new anchor_node_id based on stored coordinates."""
import argparse
from typing import Optional

from psycopg.rows import dict_row

from services.database import db_connection, get_route_schema, validate_schema_name, quote_identifier
from services.operational_database import op_db_connection
from services.operational_store import OP_SCHEMA
from services.database import quote_identifier, validate_schema_name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remap endpoint names to new anchor nodes")
    parser.add_argument("--radius", type=float, default=50.0, help="Match radius in meters (default: 50)")
    parser.add_argument("--rutenummer", type=str, help="Limit to a single rutenummer")
    parser.add_argument("--dry-run", action="store_true", help="Only show proposed changes")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of rows processed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not validate_schema_name(OP_SCHEMA):
        raise ValueError(f"Invalid OP_SCHEMA: {OP_SCHEMA}")

    schema_quoted = quote_identifier(OP_SCHEMA)

    with op_db_connection() as op_conn:
        with op_conn.cursor(row_factory=dict_row) as cur:
            query = f"""
                SELECT id, anchor_node_id, rutenummer, name, anchor_lon, anchor_lat
                FROM {schema_quoted}.endpoint_names
                WHERE anchor_lon IS NOT NULL AND anchor_lat IS NOT NULL
            """
            params = []
            if args.rutenummer:
                query += " AND rutenummer = %s"
                params.append(args.rutenummer)
            if args.limit and args.limit > 0:
                query += " LIMIT %s"
                params.append(args.limit)
            cur.execute(query, params)
            rows = cur.fetchall()

    if not rows:
        print("No endpoint names with coordinates found.")
        return 0

    updates = 0
    skipped = 0
    conflicts = 0

    with db_connection() as import_conn, op_db_connection() as op_conn:
        route_schema = get_route_schema(import_conn)
        if not validate_schema_name(route_schema):
            raise ValueError(f"Invalid route schema: {route_schema}")
        anchor_table = f"{quote_identifier(route_schema)}.{quote_identifier('anchor_nodes')}"
        for row in rows:
            anchor_lon = row["anchor_lon"]
            anchor_lat = row["anchor_lat"]
            endpoint_id = row["id"]
            current_anchor = row["anchor_node_id"]

            with import_conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT node_id,
                           ST_Distance(
                               ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                               ST_Transform(geom, 25833)
                           ) as distance_m
                    FROM {anchor_table}
                    WHERE ST_DWithin(
                        ST_Transform(geom, 25833),
                        ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                        %s
                    )
                    ORDER BY distance_m ASC
                    LIMIT 1
                    """,
                    (anchor_lon, anchor_lat, anchor_lon, anchor_lat, args.radius),
                )
                match = cur.fetchone()

            if not match:
                skipped += 1
                continue

            new_anchor = match["node_id"]
            if new_anchor == current_anchor:
                continue

            if args.dry_run:
                print(
                    f"[dry-run] endpoint_names.id={endpoint_id} "
                    f"anchor {current_anchor} -> {new_anchor} "
                    f"(dist {match['distance_m']:.2f}m)"
                )
                continue

            try:
                with op_conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {schema_quoted}.endpoint_names
                        SET anchor_node_id = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (new_anchor, endpoint_id),
                    )
                updates += 1
            except Exception:
                conflicts += 1
                op_conn.rollback()

        if not args.dry_run:
            op_conn.commit()

    print(f"Remap complete: updated={updates}, skipped={skipped}, conflicts={conflicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
