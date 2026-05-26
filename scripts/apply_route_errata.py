"""Sync data/route_errata.yaml into ops.rutenummer_remap + ops.unmarked_segment.

Idempotent: deleting entries from the YAML and re-running this script removes
them from the database too. Run via `make sync-route-errata` after editing
the YAML.

Schemas:
    ops.rutenummer_remap   — migration 015 / 016
        (from_rutenummer PK, to_rutenummer, deleted, comment, reported_at, …)
    ops.unmarked_segment   — migration 017
        (fotrute_fk PK, kind, label, lokalid, comment, reported_at, …)
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


VALID_UNMARKED_KINDS = {"boat", "glacier", "other"}


def load_unmarked() -> dict[int, dict]:
    if not ERRATA_FILE.exists():
        return {}
    raw = yaml.safe_load(ERRATA_FILE.read_text(encoding="utf-8")) or {}
    items = raw.get("unmarked_segments") or {}
    out: dict[int, dict] = {}
    for fk, val in items.items():
        try:
            fk_int = int(fk)
        except (TypeError, ValueError) as e:
            raise ValueError(f"unmarked_segments key {fk!r} must be an integer fotrute_fk") from e
        if not isinstance(val, dict):
            raise ValueError(f"unmarked_segments[{fk_int}] must be a mapping")
        kind = val.get("kind")
        if kind not in VALID_UNMARKED_KINDS:
            raise ValueError(
                f"unmarked_segments[{fk_int}].kind must be one of {sorted(VALID_UNMARKED_KINDS)}, got {kind!r}"
            )
        out[fk_int] = {
            "kind": kind,
            "label": val.get("label"),
            "lokalid": val.get("lokalid"),
            "comment": val.get("comment"),
            "reported_at": val.get("reported_at"),
        }
    return out


def sync(updated_by: str = "apply_route_errata") -> None:
    remaps = load_remaps()
    unmarked = load_unmarked()
    with op_db_connection() as conn:
        with conn.cursor() as cur:
            # --- rutenummer_remap ---
            yaml_keys = list(remaps.keys())
            cur.execute("SELECT from_rutenummer FROM ops.rutenummer_remap")
            existing = {r[0] for r in cur.fetchall()}
            to_delete = existing - set(yaml_keys)
            if to_delete:
                cur.execute(
                    "DELETE FROM ops.rutenummer_remap WHERE from_rutenummer = ANY(%s)",
                    (list(to_delete),),
                )
                print(f"removed {len(to_delete)} stale remap entries: {sorted(to_delete)}")
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

            # --- unmarked_segment ---
            yaml_fks = list(unmarked.keys())
            cur.execute("SELECT fotrute_fk FROM ops.unmarked_segment")
            existing_fks = {r[0] for r in cur.fetchall()}
            stale_fks = existing_fks - set(yaml_fks)
            if stale_fks:
                cur.execute(
                    "DELETE FROM ops.unmarked_segment WHERE fotrute_fk = ANY(%s)",
                    (list(stale_fks),),
                )
                print(f"removed {len(stale_fks)} stale unmarked entries: {sorted(stale_fks)}")
            for fk, val in unmarked.items():
                cur.execute(
                    """
                    INSERT INTO ops.unmarked_segment
                        (fotrute_fk, kind, label, lokalid, comment, reported_at, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (fotrute_fk) DO UPDATE
                        SET kind = EXCLUDED.kind,
                            label = EXCLUDED.label,
                            lokalid = EXCLUDED.lokalid,
                            comment = EXCLUDED.comment,
                            reported_at = EXCLUDED.reported_at,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW();
                    """,
                    (
                        fk,
                        val["kind"],
                        val.get("label"),
                        val.get("lokalid"),
                        val.get("comment"),
                        val.get("reported_at"),
                        updated_by,
                    ),
                )

    n_remap = sum(1 for v in remaps.values() if not v.get("delete"))
    n_delete = sum(1 for v in remaps.values() if v.get("delete"))
    by_kind: dict[str, int] = {}
    for v in unmarked.values():
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    unmarked_summary = ", ".join(f"{k}={n}" for k, n in sorted(by_kind.items())) or "none"
    print(
        f"synced {n_remap} remap{'s' if n_remap != 1 else ''}, "
        f"{n_delete} deletion{'s' if n_delete != 1 else ''}, "
        f"{len(unmarked)} unmarked ({unmarked_summary})"
    )


if __name__ == "__main__":
    sync(updated_by=os.environ.get("USER", "apply_route_errata"))
