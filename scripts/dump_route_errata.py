"""Dump the ops errata tables back to data/route_errata.yaml.

The signs_app UI writes corrections (link exclusions in particular) directly to
the ops tables, so the database is the runtime source of truth. This script
exports that state to the version-controlled YAML for review, git history, and
disaster recovery. Run via `make dump-route-errata` and commit the result.

The inverse, `make sync-route-errata` (scripts/apply_route_errata.py), applies
YAML → DB and is for bootstrapping/restoring a fresh environment.

Per-entry `comment` / `reported_at` survive the round-trip because they live in
the table columns. File-level prose comments do not — this script regenerates a
fixed header instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.operational_database import op_db_connection  # noqa: E402

ERRATA_FILE = ROOT / "data" / "route_errata.yaml"

HEADER = """\
# Local errata for Kartverket turrutebasen data.
#
# GENERATED FILE — the database is the source of truth. This file is a
# version-controlled snapshot produced by `make dump-route-errata`. Edit
# corrections in the signs_app UI (or the DB), then re-dump and commit.
#
# To bootstrap/restore a fresh environment from this snapshot, apply it with
# `make sync-route-errata` (that direction OVERWRITES the DB to match the file).
#
# Sections:
#   rutenummer_remaps:    rename/hide a Kartverket rutenummer (string-keyed)
#   unmarked_segments:    flag a fotrute_fk as boat/glacier/other (int-keyed)
#   link_exclusions:      drop link(s) from one route's graph (rutenummer-keyed)
#   bridges:              connect parts of a disconnected route (rutenummer-keyed)
"""


def _clean(d: dict) -> dict:
    """Drop None values so the YAML stays terse."""
    return {k: v for k, v in d.items() if v is not None}


def dump() -> None:
    with op_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT from_rutenummer, to_rutenummer, deleted, comment, reported_at "
                "FROM ops.rutenummer_remap ORDER BY from_rutenummer"
            )
            remap_rows = cur.fetchall()
            cur.execute(
                "SELECT fotrute_fk, kind, label, lokalid, comment, reported_at "
                "FROM ops.unmarked_segment ORDER BY fotrute_fk"
            )
            unmarked_rows = cur.fetchall()
            cur.execute(
                "SELECT rutenummer, link_id, reason, comment, reported_at "
                "FROM ops.route_link_exclusion ORDER BY rutenummer, link_id"
            )
            excl_rows = cur.fetchall()
            cur.execute(
                "SELECT rutenummer, a_node, b_node, reason, comment, reported_at "
                "FROM ops.route_link_bridge ORDER BY rutenummer, a_node, b_node"
            )
            bridge_rows = cur.fetchall()

    remaps: dict = {}
    for r in remap_rows:
        entry: dict = {}
        if r["deleted"]:
            entry["delete"] = True
        else:
            entry["to"] = r["to_rutenummer"]
        entry["comment"] = r["comment"]
        entry["reported_at"] = r["reported_at"]
        remaps[r["from_rutenummer"]] = _clean(entry)

    unmarked: dict = {}
    for r in unmarked_rows:
        unmarked[int(r["fotrute_fk"])] = _clean({
            "kind": r["kind"],
            "label": r["label"],
            "lokalid": r["lokalid"],
            "comment": r["comment"],
            "reported_at": r["reported_at"],
        })

    link_exclusions: dict = {}
    for r in excl_rows:
        link_exclusions.setdefault(r["rutenummer"], []).append(_clean({
            "link_id": int(r["link_id"]),
            "reason": r["reason"],
            "comment": r["comment"],
            "reported_at": r["reported_at"],
        }))

    bridges: dict = {}
    for r in bridge_rows:
        bridges.setdefault(r["rutenummer"], []).append(_clean({
            "a_node": int(r["a_node"]),
            "b_node": int(r["b_node"]),
            "reason": r["reason"],
            "comment": r["comment"],
            "reported_at": r["reported_at"],
        }))

    data: dict = {}
    if remaps:
        data["rutenummer_remaps"] = remaps
    if unmarked:
        data["unmarked_segments"] = unmarked
    if link_exclusions:
        data["link_exclusions"] = link_exclusions
    if bridges:
        data["bridges"] = bridges

    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    ERRATA_FILE.write_text(HEADER + "\n" + body, encoding="utf-8")
    print(
        f"dumped {len(remaps)} remap(s), {len(unmarked)} unmarked, "
        f"{sum(len(v) for v in link_exclusions.values())} link exclusion(s), "
        f"{sum(len(v) for v in bridges.values())} bridge(s) -> {ERRATA_FILE.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    dump()
