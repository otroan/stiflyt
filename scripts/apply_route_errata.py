"""Sync data/route_errata.yaml into the ops errata tables.

Idempotent: deleting entries from the YAML and re-running this script removes
them from the database too. Run via `make sync-route-errata`.

NOTE on direction: the signs_app UI writes corrections (link exclusions,
bridges, metadata overrides) directly to the database, so the DB is the runtime
source of truth. This script applies YAML → DB to bootstrap or restore a fresh
environment. The regular workflow is the inverse: `make dump-route-errata`
exports the DB to YAML for git (see scripts/dump_route_errata.py).

GUARD: because a sync deletes DB rows not present in the YAML, it would wipe
UI-authored corrections. So sync ABORTS if any DB correction is missing from the
file, listing what would be deleted, unless run with `--force`. Run
`make dump-route-errata` first to snapshot UI edits, then sync is safe.

Schemas:
    ops.rutenummer_remap     — migration 015 / 016
        (from_rutenummer PK, to_rutenummer, deleted, comment, reported_at, …)
    ops.unmarked_segment     — migration 017
        (fotrute_fk PK, kind, label, lokalid, comment, reported_at, …)
    ops.route_link_exclusion — migration 020
        ((rutenummer, link_id) PK, reason, comment, reported_at, …)
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


def load_link_exclusions() -> list[dict]:
    """YAML `link_exclusions:` is keyed by rutenummer with a list of entries:

        link_exclusions:
          fem30:
            - { link_id: 266, reason: wrong_arm, comment: "...", reported_at: 2026-05-27 }
    """
    if not ERRATA_FILE.exists():
        return []
    raw = yaml.safe_load(ERRATA_FILE.read_text(encoding="utf-8")) or {}
    items = raw.get("link_exclusions") or {}
    out: list[dict] = []
    for rutenummer, entries in items.items():
        if not isinstance(entries, list):
            raise ValueError(f"link_exclusions[{rutenummer!r}] must be a list of entries")
        for e in entries:
            if not isinstance(e, dict) or "link_id" not in e:
                raise ValueError(
                    f"link_exclusions[{rutenummer!r}] entries must be mappings with a link_id"
                )
            out.append({
                "rutenummer": str(rutenummer),
                "link_id": int(e["link_id"]),
                "reason": e.get("reason"),
                "comment": e.get("comment"),
                "reported_at": e.get("reported_at"),
            })
    return out


def load_bridges() -> list[dict]:
    """YAML `bridges:` is keyed by rutenummer with a list of entries:

        bridges:
          fem22:
            - { a_node: 25159, b_node: 93510, reason: digitizing_gap, reported_at: 2026-05-27 }

    The node pair is stored sorted (a_node < b_node) to match the table PK/CHECK.
    """
    if not ERRATA_FILE.exists():
        return []
    raw = yaml.safe_load(ERRATA_FILE.read_text(encoding="utf-8")) or {}
    items = raw.get("bridges") or {}
    out: list[dict] = []
    for rutenummer, entries in items.items():
        if not isinstance(entries, list):
            raise ValueError(f"bridges[{rutenummer!r}] must be a list of entries")
        for e in entries:
            if not isinstance(e, dict) or "a_node" not in e or "b_node" not in e:
                raise ValueError(
                    f"bridges[{rutenummer!r}] entries must be mappings with a_node and b_node"
                )
            a, b = sorted((int(e["a_node"]), int(e["b_node"])))
            if a == b:
                raise ValueError(f"bridges[{rutenummer!r}] a_node and b_node must differ")
            out.append({
                "rutenummer": str(rutenummer),
                "a_node": a,
                "b_node": b,
                "reason": e.get("reason"),
                "comment": e.get("comment"),
                "reported_at": e.get("reported_at"),
            })
    return out


_METADATA_OVERRIDE_FIELDS = ("rutenavn", "vedlikeholdsansvarlig", "rutetype", "gradering")


def load_metadata_overrides() -> dict[str, dict]:
    """YAML `metadata_overrides:` is keyed by rutenummer with a mapping of the
    canonical values to force across the route:

        metadata_overrides:
          fem22:
            rutenavn: "Synnervika - Svukuriset"
            reported_at: 2026-05-27
    """
    if not ERRATA_FILE.exists():
        return {}
    raw = yaml.safe_load(ERRATA_FILE.read_text(encoding="utf-8")) or {}
    items = raw.get("metadata_overrides") or {}
    out: dict[str, dict] = {}
    for rutenummer, val in items.items():
        if not isinstance(val, dict):
            raise ValueError(f"metadata_overrides[{rutenummer!r}] must be a mapping")
        if all(val.get(f) in (None, "") for f in _METADATA_OVERRIDE_FIELDS):
            raise ValueError(
                f"metadata_overrides[{rutenummer!r}] must set at least one of {_METADATA_OVERRIDE_FIELDS}"
            )
        out[str(rutenummer)] = {
            "rutenavn": val.get("rutenavn"),
            "vedlikeholdsansvarlig": val.get("vedlikeholdsansvarlig"),
            "rutetype": val.get("rutetype"),
            "gradering": val.get("gradering"),
            "comment": val.get("comment"),
            "reported_at": val.get("reported_at"),
        }
    return out


def _would_delete(conn, remaps, unmarked, link_exclusions, bridges, metadata_overrides) -> dict:
    """Corrections present in the DB but absent from the YAML — i.e. rows a sync
    would delete. Used to guard against wiping UI-authored corrections."""
    out: dict = {}
    with conn.cursor() as cur:
        cur.execute("SELECT from_rutenummer FROM ops.rutenummer_remap")
        s = {r[0] for r in cur.fetchall()} - set(remaps)
        if s:
            out["rutenummer_remap"] = sorted(s)
        cur.execute("SELECT fotrute_fk FROM ops.unmarked_segment")
        s = {int(r[0]) for r in cur.fetchall()} - set(unmarked)
        if s:
            out["unmarked_segment"] = sorted(s)
        cur.execute("SELECT rutenummer, link_id FROM ops.route_link_exclusion")
        s = {(r[0], int(r[1])) for r in cur.fetchall()} - {(x["rutenummer"], x["link_id"]) for x in link_exclusions}
        if s:
            out["route_link_exclusion"] = sorted(s)
        cur.execute("SELECT rutenummer, a_node, b_node FROM ops.route_link_bridge")
        s = {(r[0], int(r[1]), int(r[2])) for r in cur.fetchall()} - {(x["rutenummer"], x["a_node"], x["b_node"]) for x in bridges}
        if s:
            out["route_link_bridge"] = sorted(s)
        cur.execute("SELECT rutenummer FROM ops.route_metadata_override")
        s = {r[0] for r in cur.fetchall()} - set(metadata_overrides)
        if s:
            out["route_metadata_override"] = sorted(s)
    return out


def sync(updated_by: str = "apply_route_errata", force: bool = False) -> None:
    remaps = load_remaps()
    unmarked = load_unmarked()
    link_exclusions = load_link_exclusions()
    bridges = load_bridges()
    metadata_overrides = load_metadata_overrides()
    with op_db_connection() as conn:
        # Guard: applying the YAML deletes DB rows not in the file. With the UI
        # writing corrections straight to the DB, a blind sync would wipe them.
        # Abort if anything would be deleted, unless --force.
        stale = _would_delete(conn, remaps, unmarked, link_exclusions, bridges, metadata_overrides)
        if stale and not force:
            total = sum(len(v) for v in stale.values())
            print(
                f"ABORT: this sync would delete {total} DB correction(s) not present in "
                f"{ERRATA_FILE.name}:"
            )
            for table, items in stale.items():
                print(f"  {table}: {items}")
            print(
                "These are likely UI-authored corrections. Run `make dump-route-errata` to "
                "snapshot them into the YAML first, or re-run with --force to overwrite the DB."
            )
            raise SystemExit(2)
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

            # --- route_link_exclusion ---
            yaml_excl_keys = {(x["rutenummer"], x["link_id"]) for x in link_exclusions}
            cur.execute("SELECT rutenummer, link_id FROM ops.route_link_exclusion")
            existing_excl = {(r[0], int(r[1])) for r in cur.fetchall()}
            stale_excl = existing_excl - yaml_excl_keys
            if stale_excl:
                cur.executemany(
                    "DELETE FROM ops.route_link_exclusion WHERE rutenummer = %s AND link_id = %s",
                    [list(k) for k in stale_excl],
                )
                print(f"removed {len(stale_excl)} stale link exclusion(s): {sorted(stale_excl)}")
            for x in link_exclusions:
                cur.execute(
                    """
                    INSERT INTO ops.route_link_exclusion
                        (rutenummer, link_id, reason, comment, reported_at, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (rutenummer, link_id) DO UPDATE
                        SET reason = EXCLUDED.reason,
                            comment = EXCLUDED.comment,
                            reported_at = EXCLUDED.reported_at,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW();
                    """,
                    (
                        x["rutenummer"],
                        x["link_id"],
                        x.get("reason"),
                        x.get("comment"),
                        x.get("reported_at"),
                        updated_by,
                    ),
                )

            # --- route_link_bridge ---
            yaml_bridge_keys = {(x["rutenummer"], x["a_node"], x["b_node"]) for x in bridges}
            cur.execute("SELECT rutenummer, a_node, b_node FROM ops.route_link_bridge")
            existing_bridges = {(r[0], int(r[1]), int(r[2])) for r in cur.fetchall()}
            stale_bridges = existing_bridges - yaml_bridge_keys
            if stale_bridges:
                cur.executemany(
                    "DELETE FROM ops.route_link_bridge WHERE rutenummer = %s AND a_node = %s AND b_node = %s",
                    [list(k) for k in stale_bridges],
                )
                print(f"removed {len(stale_bridges)} stale bridge(s): {sorted(stale_bridges)}")
            for x in bridges:
                cur.execute(
                    """
                    INSERT INTO ops.route_link_bridge
                        (rutenummer, a_node, b_node, reason, comment, reported_at, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (rutenummer, a_node, b_node) DO UPDATE
                        SET reason = EXCLUDED.reason,
                            comment = EXCLUDED.comment,
                            reported_at = EXCLUDED.reported_at,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW();
                    """,
                    (
                        x["rutenummer"],
                        x["a_node"],
                        x["b_node"],
                        x.get("reason"),
                        x.get("comment"),
                        x.get("reported_at"),
                        updated_by,
                    ),
                )

            # --- route_metadata_override ---
            yaml_md_keys = list(metadata_overrides.keys())
            cur.execute("SELECT rutenummer FROM ops.route_metadata_override")
            existing_md = {r[0] for r in cur.fetchall()}
            stale_md = existing_md - set(yaml_md_keys)
            if stale_md:
                cur.execute(
                    "DELETE FROM ops.route_metadata_override WHERE rutenummer = ANY(%s)",
                    (list(stale_md),),
                )
                print(f"removed {len(stale_md)} stale metadata override(s): {sorted(stale_md)}")
            for rn, v in metadata_overrides.items():
                cur.execute(
                    """
                    INSERT INTO ops.route_metadata_override
                        (rutenummer, rutenavn, vedlikeholdsansvarlig, rutetype, gradering,
                         comment, reported_at, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (rutenummer) DO UPDATE
                        SET rutenavn = EXCLUDED.rutenavn,
                            vedlikeholdsansvarlig = EXCLUDED.vedlikeholdsansvarlig,
                            rutetype = EXCLUDED.rutetype,
                            gradering = EXCLUDED.gradering,
                            comment = EXCLUDED.comment,
                            reported_at = EXCLUDED.reported_at,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW();
                    """,
                    (
                        rn,
                        v.get("rutenavn"),
                        v.get("vedlikeholdsansvarlig"),
                        v.get("rutetype"),
                        v.get("gradering"),
                        v.get("comment"),
                        v.get("reported_at"),
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
        f"{len(unmarked)} unmarked ({unmarked_summary}), "
        f"{len(link_exclusions)} link exclusion{'s' if len(link_exclusions) != 1 else ''}, "
        f"{len(bridges)} bridge{'s' if len(bridges) != 1 else ''}, "
        f"{len(metadata_overrides)} metadata override{'s' if len(metadata_overrides) != 1 else ''}"
    )


if __name__ == "__main__":
    sync(
        updated_by=os.environ.get("USER", "apply_route_errata"),
        force="--force" in sys.argv,
    )
