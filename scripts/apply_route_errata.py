"""Sync data/route_errata.yaml into ops.rutenummer_remap.

Idempotent: deleting entries from the YAML and re-running this script removes
them from the database too. Run via `make sync-route-errata` after editing
the YAML.

Schema (created by stiflyt-db migration 015):
    ops.rutenummer_remap(from_rutenummer PK, to_rutenummer, comment,
                         reported_at, updated_by, updated_at)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

# Path bootstrap so we can import the services/* helpers when run as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.operational_database import op_db_connection  # noqa: E402

ERRATA_FILE = ROOT / "data" / "route_errata.yaml"


def load_remaps() -> dict[str, dict]:
    if not ERRATA_FILE.exists():
        return {}
    raw = yaml.safe_load(ERRATA_FILE.read_text(encoding="utf-8")) or {}
    items = raw.get("rutenummer_remaps") or {}
    out: dict[str, dict] = {}
    for src, val in items.items():
        if isinstance(val, str):
            # Shorthand: src -> "bre26" — remap.
            out[str(src)] = {"to": val, "delete": False}
        elif isinstance(val, dict):
            has_to = "to" in val and val["to"] is not None
            is_delete = bool(val.get("delete"))
            if has_to == is_delete:
                # Both or neither — ambiguous.
                raise ValueError(
                    f"rutenummer_remap[{src!r}] must have exactly one of 'to' or 'delete: true'"
                )
            out[str(src)] = {
                "to": val.get("to") if has_to else None,
                "delete": is_delete,
                "comment": val.get("comment"),
                "reported_at": val.get("reported_at"),
            }
        else:
            raise ValueError(f"rutenummer_remap[{src!r}] must be a string or mapping")
    return out


def sync(updated_by: str = "apply_route_errata") -> None:
    remaps = load_remaps()
    with op_db_connection() as conn:
        with conn.cursor() as cur:
            # Replace the full set atomically: delete rows not in YAML, upsert the rest.
            yaml_keys = list(remaps.keys())
            cur.execute("SELECT from_rutenummer FROM ops.rutenummer_remap")
            existing = {r[0] for r in cur.fetchall()}
            to_delete = existing - set(yaml_keys)
            if to_delete:
                cur.execute(
                    "DELETE FROM ops.rutenummer_remap WHERE from_rutenummer = ANY(%s)",
                    (list(to_delete),),
                )
                print(f"removed {len(to_delete)} stale entries: {sorted(to_delete)}")
            for src, val in remaps.items():
                cur.execute(
                    """
                    INSERT INTO ops.rutenummer_remap
                        (from_rutenummer, to_rutenummer, deleted, comment, reported_at, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (from_rutenummer) DO UPDATE
                        SET to_rutenummer = EXCLUDED.to_rutenummer,
                            deleted = EXCLUDED.deleted,
                            comment = EXCLUDED.comment,
                            reported_at = EXCLUDED.reported_at,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW();
                    """,
                    (
                        src,
                        val.get("to"),
                        val.get("delete", False),
                        val.get("comment"),
                        val.get("reported_at"),
                        updated_by,
                    ),
                )
    n_remap = sum(1 for v in remaps.values() if not v.get("delete"))
    n_delete = sum(1 for v in remaps.values() if v.get("delete"))
    print(f"synced {n_remap} remap{'s' if n_remap != 1 else ''}, {n_delete} deletion{'s' if n_delete != 1 else ''}: {sorted(remaps.keys())}")


if __name__ == "__main__":
    sync(updated_by=os.environ.get("USER", "apply_route_errata"))
