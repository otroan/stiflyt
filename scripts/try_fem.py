"""Exercise the area-level pipeline for fem to see what breaks.

Run with: python -m scripts.try_fem
"""
from __future__ import annotations

import sys
import traceback

from services.database import get_db_connection
from services.operational_database import get_operational_db_connection
from services.sign_candidates import (
    get_area_stats,
    get_route_summary_for_area,
    get_sign_candidates_for_area,
)
from services.sign_excel import build_manufacturing_workbook
from services.sign_pdf import build_field_pdf


def _try(label: str, fn):
    print(f"\n=== {label} ===")
    try:
        result = fn()
        return result
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None


def summarize_route_summary(payload):
    if not payload:
        return
    routes = payload.get("routes") or payload.get("items") or []
    print(f"  routes returned: {len(routes)}")
    if routes:
        sample = routes[:3]
        for r in sample:
            print(
                f"    {r.get('rutenummer')}: "
                f"start={r.get('start_name')!r} end={r.get('end_name')!r} "
                f"km={r.get('length_km_displayed')} geom={'yes' if r.get('route_geometry') else 'no'}"
            )
        missing_names = sum(1 for r in routes if not r.get("start_name") or not r.get("end_name"))
        no_km = sum(1 for r in routes if not r.get("length_km_displayed"))
        no_geom = sum(1 for r in routes if not r.get("route_geometry"))
        no_anchors = sum(
            1 for r in routes
            if r.get("start_anchor_node_id") is None or r.get("end_anchor_node_id") is None
        )
        print(f"  missing start/end name: {missing_names}/{len(routes)}")
        print(f"  missing/zero length_km_displayed: {no_km}/{len(routes)}")
        print(f"  missing route_geometry: {no_geom}/{len(routes)}")
        print(f"  missing endpoint anchors: {no_anchors}/{len(routes)}")


def summarize_stats(payload):
    if not payload:
        return
    for k, v in payload.items():
        print(f"  {k}: {v}")


def summarize_candidates(payload):
    if not payload:
        return
    sites = payload.get("sites") or []
    print(f"  candidate sites: {len(sites)}")
    if sites:
        panel_counts = [len(s.get("panels", [])) for s in sites]
        print(f"  panels per site: min={min(panel_counts)} avg={sum(panel_counts)/len(panel_counts):.1f} max={max(panel_counts)}")
        names = [s.get("name") or s.get("anchor_name") for s in sites if (s.get("name") or s.get("anchor_name"))]
        print(f"  named sites: {len(names)}/{len(sites)}")
        unnamed = [s for s in sites if not (s.get("name") or s.get("anchor_name"))]
        if unnamed:
            print(f"  WARNING: {len(unnamed)} sites without names — first id={unnamed[0].get('anchor_node_id') or unnamed[0].get('id')}")


def main():
    area = "fem"
    with get_db_connection() as conn:
        summary = _try(
            f"get_route_summary_for_area({area})",
            lambda: get_route_summary_for_area(conn, area),
        )
        summarize_route_summary(summary)

        stats = _try(f"get_area_stats({area})", lambda: get_area_stats(conn, area))
        summarize_stats(stats)

        candidates = _try(
            f"get_sign_candidates_for_area({area})",
            lambda: get_sign_candidates_for_area(conn, area),
        )
        summarize_candidates(candidates)

        xlsx_bytes = _try(
            f"build_manufacturing_workbook({area})",
            lambda: build_manufacturing_workbook(conn, area),
        )
        if xlsx_bytes:
            print(f"  xlsx size: {len(xlsx_bytes)} bytes")
            out = f"/tmp/skilt-{area}.xlsx"
            with open(out, "wb") as fh:
                fh.write(xlsx_bytes)
            print(f"  wrote {out}")

        with get_operational_db_connection() as op_conn:
            pdf_bytes = _try(
                f"build_field_pdf({area})",
                lambda: build_field_pdf(conn, op_conn, area),
            )
        if pdf_bytes:
            print(f"  pdf size: {len(pdf_bytes)} bytes")
            out = f"/tmp/skilt-{area}.pdf"
            with open(out, "wb") as fh:
                fh.write(pdf_bytes)
            print(f"  wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
