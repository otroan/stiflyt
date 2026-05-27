"""Field-PDF for the signs_app: one A4 page per sign site, with a centred
map snippet, route memberships + endpoint distances, the panel table, and
nearby field photos. Used by the trail crew when they go to install / inspect
signs in the field.

This shares its data source with :mod:`sign_excel` (``get_sign_candidates_for_area``)
so any correction or override that shows up in the Excel manufacturing list
also shows up here. Routes/photos/snippet rendering are unique to this module.
"""
from __future__ import annotations

import io
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Table, TableStyle

from . import field_photos as fp_svc
from .operational_store import get_distance_correction_factor
from .sign_candidates import (
    _route_endpoints_bulk,
    _route_geometries_for_rutenummers,
    _route_total_lengths_and_names,
    correct_distance_km,
    get_sign_candidates_for_area,
)


def format_km_for_display(km: Optional[float]) -> str:
    """Manufacturing display: 1 decimal under 10 km, whole km at and above.
    Mirrors `sign_excel._format_km` so the PDF and Excel show the same value."""
    if km is None:
        return ""
    try:
        f = float(km)
    except (TypeError, ValueError):
        return ""
    return f"{f:.1f} km" if f < 10 else f"{int(round(f))} km"


# ---------------------------------------------------------------------------
# Page geometry
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm
HEADER_H = 18 * mm
MAP_SIZE = 84 * mm
PHOTO_ROW_H = 38 * mm
PHOTO_MAX_PER_PAGE = 3

# How far from the post a photo must be to be considered "for this sign".
# Generous — field staff often place the marker a few metres off from where
# they shot the photo so the marker is visible against the map background.
PHOTO_PROXIMITY_M = 50.0


def _selection_key(sign_site_id: int, panel: Dict[str, Any]) -> str:
    """Matches the key shape used by `sign_excel._selection_key` (sign_site_id:
    destination_anchor_node_id:first_link_id) so the same selection set drives
    both exports."""
    aid = panel.get("destination_anchor_node_id")
    fl = panel.get("first_link_id")
    return f"{sign_site_id}:{aid if aid is not None else ''}:{fl if fl is not None else ''}"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres. Used to associate photos with a post."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _wrap_text(c: pdfcanvas.Canvas, text: str, font: str, size: float, max_w: float) -> List[str]:
    """Naive word-wrap returning the lines that fit `max_w`. Sufficient for the
    field PDF — names are short and single-line in practice."""
    if not text:
        return [""]
    words = text.split()
    lines: List[str] = []
    current = ""
    for w in words:
        candidate = (current + " " + w).strip()
        if stringWidth(candidate, font, size) <= max_w:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines or [""]


# ---------------------------------------------------------------------------
# Per-site data assembly
# ---------------------------------------------------------------------------


def _photos_for_site(
    placed_photos: List[Dict[str, Any]],
    site_lon: float,
    site_lat: float,
    *,
    radius_m: float = PHOTO_PROXIMITY_M,
    max_count: int = PHOTO_MAX_PER_PAGE,
) -> List[Dict[str, Any]]:
    """Return up to `max_count` photos within `radius_m` of the post, nearest
    first. Photos with no geotag are silently skipped."""
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for p in placed_photos:
        lon = p.get("lon")
        lat = p.get("lat")
        if lon is None or lat is None:
            continue
        d = _haversine_m(site_lat, site_lon, lat, lon)
        if d <= radius_m:
            scored.append((d, p))
    scored.sort(key=lambda x: x[0])
    return [p for _d, p in scored[:max_count]]


def _endpoint_distances(
    site_pos_m_by_route: Dict[str, float],
    endpoints_by_route: Dict[str, Dict[str, Any]],
    correction_factor: float,
) -> Dict[str, Dict[str, Any]]:
    """For each route the post is on, the corrected distance from the post to
    each of the route's two endpoints (in km). Endpoints aren't named here —
    we just label them "start"/"slutt"; if a richer label is needed later we
    can resolve the anchor name via `_anchor_names_bulk`."""
    out: Dict[str, Dict[str, Any]] = {}
    for ruten, pos_m in site_pos_m_by_route.items():
        ep = endpoints_by_route.get(ruten)
        if not ep:
            continue
        length_m = float(ep.get("length_m") or 0.0)
        d_a = max(0.0, pos_m)
        d_b = max(0.0, length_m - pos_m)
        out[ruten] = {
            "to_start_km": correct_distance_km(d_a, correction_factor),
            "to_end_km": correct_distance_km(d_b, correction_factor),
            "total_km": correct_distance_km(length_m, correction_factor),
        }
    return out


def _site_pos_m_by_route_bulk(
    conn,
    sites: List[Dict[str, Any]],
) -> Dict[int, Dict[str, float]]:
    """For each sign_site whose anchor_node lies on a route, return the
    anchor's pos_m along that route. Sites without an anchor (manual signs
    snapped to a route position) are looked up by snapping the lon/lat onto
    the route geometry; we delegate that to the existing route_service helper.

    Result: {sign_site_id: {rutenummer: pos_m}}.
    """
    # For now we only handle anchor-backed sites (the common case). Manual
    # signs report distance to destinations via the existing panels — the
    # field PDF surfaces those in the panel table; endpoint distance is a
    # nice-to-have we can extend to manual signs later.
    by_anchor: Dict[int, int] = {}  # anchor_node_id -> sign_site_id
    rutenummers_by_anchor: Dict[int, List[str]] = {}
    for s in sites:
        sid = s.get("sign_site_id")
        anchor = s.get("anchor_node_id")
        if sid is None or anchor is None:
            continue
        by_anchor[anchor] = sid
        rutenummers_by_anchor[anchor] = list(s.get("route_numbers") or [])
    if not by_anchor:
        return {}

    sql = """
        WITH route_links AS (
            SELECT rutenummer, link_id, a_node, b_node, length_m
            FROM ops.route_link_graph
            WHERE rutenummer = ANY(%s)
        ),
        node_pos AS (
            -- BFS pos_m along each route from the min-degree-1 node. This
            -- mirrors `_build_route_chain` in sign_candidates but stays in
            -- SQL for speed (no per-site Python loop).
            SELECT rutenummer, node_id, pos_m FROM (
                WITH RECURSIVE
                degrees AS (
                    SELECT rutenummer, node_id, COUNT(*) AS deg
                    FROM (
                        SELECT rutenummer, a_node AS node_id FROM route_links
                        UNION ALL SELECT rutenummer, b_node FROM route_links
                    ) x GROUP BY rutenummer, node_id
                ),
                seeds AS (
                    SELECT DISTINCT ON (rutenummer) rutenummer, node_id
                    FROM degrees WHERE deg = 1 ORDER BY rutenummer, node_id
                ),
                walk AS (
                    SELECT s.rutenummer, s.node_id, 0::float AS pos_m,
                           ARRAY[s.node_id] AS visited
                    FROM seeds s
                    UNION ALL
                    SELECT w.rutenummer,
                           CASE WHEN l.a_node = w.node_id THEN l.b_node ELSE l.a_node END AS node_id,
                           w.pos_m + l.length_m AS pos_m,
                           w.visited || (CASE WHEN l.a_node = w.node_id THEN l.b_node ELSE l.a_node END)
                    FROM walk w
                    JOIN route_links l ON l.rutenummer = w.rutenummer
                                     AND (l.a_node = w.node_id OR l.b_node = w.node_id)
                    WHERE NOT (
                        (CASE WHEN l.a_node = w.node_id THEN l.b_node ELSE l.a_node END)
                        = ANY (w.visited)
                    )
                )
                SELECT rutenummer, node_id,
                       MIN(pos_m) AS pos_m
                FROM walk
                GROUP BY rutenummer, node_id
            ) t
        )
        SELECT rutenummer, node_id, pos_m FROM node_pos
        WHERE node_id = ANY(%s);
    """
    rutenummers = sorted({r for rs in rutenummers_by_anchor.values() for r in rs})
    anchor_ids = list(by_anchor.keys())
    pos_by_anchor_and_route: Dict[Tuple[int, str], float] = {}
    try:
        from psycopg.rows import dict_row
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (rutenummers, anchor_ids))
            for r in cur.fetchall():
                node_id = int(r["node_id"])
                ruten = r["rutenummer"]
                pos_m = float(r["pos_m"] or 0.0)
                pos_by_anchor_and_route[(node_id, ruten)] = pos_m
    except Exception as e:
        # Recursive walk can be expensive; if it falls over for any reason
        # we silently degrade — the panel table still has useful distances.
        print(f"[sign_pdf] route-position bulk query failed: {e}")
        return {}

    out: Dict[int, Dict[str, float]] = {}
    for anchor, sid in by_anchor.items():
        per_route: Dict[str, float] = {}
        for ruten in rutenummers_by_anchor.get(anchor, []):
            pos = pos_by_anchor_and_route.get((anchor, ruten))
            if pos is not None:
                per_route[ruten] = pos
        if per_route:
            out[sid] = per_route
    return out


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------


def _draw_header(c: pdfcanvas.Canvas, site: Dict[str, Any], y_top: float) -> float:
    """Draw the sign title + route list at the top of the page. Returns the
    y-coordinate of the bottom of the header (= top of the next region)."""
    title = site.get("name") or "(uten navn)"
    code = site.get("site_code") or (f"@{site.get('anchor_node_id')}" if site.get("anchor_node_id") else "")
    routes = ", ".join(site.get("route_numbers") or []) or "—"

    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, y_top - 14, title)
    if code:
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#666"))
        c.drawRightString(PAGE_W - MARGIN, y_top - 14, code)
        c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    c.drawString(MARGIN, y_top - 30, f"Ruter: {routes}")
    return y_top - HEADER_H


def _draw_info_box(
    c: pdfcanvas.Canvas,
    site: Dict[str, Any],
    endpoint_dist: Dict[str, Dict[str, Any]],
    route_names: Dict[str, str],
    x: float, y: float, w: float, h: float,
) -> None:
    """Right of the map: UTM coords + endpoint distances per route."""
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, 3, stroke=1, fill=0)

    cur_y = y + h - 14
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + 8, cur_y, "Posisjon")
    cur_y -= 12
    c.setFont("Helvetica", 9)
    utm = site.get("utm_coords") or "—"
    c.drawString(x + 8, cur_y, f"UTM 32V: {utm}")
    cur_y -= 11
    if site.get("lon") is not None and site.get("lat") is not None:
        c.drawString(x + 8, cur_y, f"Lon/Lat: {site['lon']:.5f}, {site['lat']:.5f}")
        cur_y -= 11

    if endpoint_dist:
        cur_y -= 6
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 8, cur_y, "Avstand til rute-endepunkter")
        cur_y -= 12
        c.setFont("Helvetica", 9)
        for ruten in sorted(endpoint_dist.keys()):
            d = endpoint_dist[ruten]
            label = ruten
            rn = route_names.get(ruten)
            if rn:
                label = f"{ruten} — {rn}"
            c.drawString(x + 8, cur_y, label)
            cur_y -= 10
            c.setFillColor(colors.HexColor("#444"))
            c.drawString(
                x + 18, cur_y,
                f"◀ {format_km_for_display(d['to_start_km'])} · "
                f"{format_km_for_display(d['to_end_km'])} ▶ "
                f"(av {format_km_for_display(d['total_km'])})",
            )
            c.setFillColor(colors.black)
            cur_y -= 12
            if cur_y < y + 20:
                break

    if site.get("back_text"):
        cur_y -= 4
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 8, cur_y, "Baksidetekst")
        cur_y -= 12
        c.setFont("Helvetica", 9)
        for line in _wrap_text(c, site["back_text"], "Helvetica", 9, w - 16):
            if cur_y < y + 8:
                break
            c.drawString(x + 8, cur_y, line)
            cur_y -= 11


def _draw_panel_table(
    c: pdfcanvas.Canvas,
    panels: List[Dict[str, Any]],
    x: float, y_top: float, w: float,
) -> float:
    """Render the panel destinations as a small Platypus Table at (x, y_top).
    Returns the y of the bottom of the table."""
    if not panels:
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(colors.HexColor("#888"))
        c.drawString(x, y_top - 10, "Ingen panel registrert.")
        c.setFillColor(colors.black)
        return y_top - 14

    header = ["Destinasjon", "Retning", "Ruter", "Km", "Farge"]
    body = []
    for p in panels:
        body.append([
            p.get("destination_name") or "—",
            (p.get("direction") or ""),
            ", ".join(p.get("route_numbers") or []),
            format_km_for_display(p.get("distance_km_displayed")),
            p.get("color") or "trehvit",
        ])
    data = [header] + body

    col_widths = [w * 0.36, w * 0.12, w * 0.16, w * 0.12, w * 0.16]
    # The 5 column widths should add to ~1.0 of w; trim slack to match exactly.
    total = sum(col_widths)
    if total != w:
        col_widths[-1] += (w - total)

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")]),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#ccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ddd")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    avail_h = y_top - MARGIN - PHOTO_ROW_H - 6 * mm
    tw, th = t.wrapOn(c, w, avail_h)
    t.drawOn(c, x, y_top - th)
    return y_top - th


def _draw_photos_row(
    c: pdfcanvas.Canvas,
    photos: List[Dict[str, Any]],
    x: float, y: float, w: float, h: float,
) -> None:
    """Draw up to `PHOTO_MAX_PER_PAGE` photo thumbnails along the bottom."""
    if not photos:
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(colors.HexColor("#888"))
        c.drawString(x, y + h / 2 - 4, f"Ingen bilder funnet innenfor {int(PHOTO_PROXIMITY_M)} m av stolpen.")
        c.setFillColor(colors.black)
        return

    gap = 4 * mm
    cell_w = (w - gap * (PHOTO_MAX_PER_PAGE - 1)) / PHOTO_MAX_PER_PAGE
    for i, p in enumerate(photos[:PHOTO_MAX_PER_PAGE]):
        cell_x = x + i * (cell_w + gap)
        # Prefer the display variant (1600 px) — better quality than the thumb
        # for the field-printed page.
        img_bytes = _read_photo_bytes(p)
        if not img_bytes:
            continue
        try:
            with Image.open(io.BytesIO(img_bytes)) as im:
                im = im.convert("RGB")
                # Fit while preserving aspect.
                im.thumbnail((int(cell_w * 4), int(h * 4)), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=80, optimize=True)
                buf.seek(0)
                # Centre the image in its cell.
                iw, ih = im.size
                scale = min(cell_w / iw, h / ih)
                dw, dh = iw * scale, ih * scale
                dx = cell_x + (cell_w - dw) / 2
                dy = y + (h - dh) / 2
                from reportlab.lib.utils import ImageReader
                c.drawImage(ImageReader(buf), dx, dy, dw, dh)
                # Optional caption underneath, truncated to fit.
                cap = (p.get("caption") or "").strip()
                if cap:
                    c.setFont("Helvetica", 7)
                    c.setFillColor(colors.HexColor("#444"))
                    lines = _wrap_text(c, cap, "Helvetica", 7, cell_w)
                    if lines:
                        c.drawString(cell_x, y - 4, lines[0][:80])
                    c.setFillColor(colors.black)
        except Exception as e:
            print(f"[sign_pdf] failed to embed photo {p.get('id')}: {e}")


def _read_photo_bytes(photo: Dict[str, Any]) -> Optional[bytes]:
    """Read the display variant from disk (or thumb as a fallback)."""
    for rel_key in ("display_path", "thumb_path", "file_path"):
        rel = photo.get(rel_key)
        if not rel:
            continue
        try:
            path = fp_svc.resolve_path(rel)
            if path.exists():
                return path.read_bytes()
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_field_pdf(
    conn,
    op_conn,
    area_code: str,
    selection: Any = None,
) -> bytes:
    """Render the field-PDF for one area as PDF bytes.

    Args:
        conn: connection to the routes schema (stiflyt)
        op_conn: connection to the ops schema (sign overrides, field photos)
        area_code: e.g. "bre"
        selection: same shape as sign_excel — iterable of
            "<sign_site_id>:<destination_anchor_node_id>:<first_link_id>" strings.
            When provided, only sites whose panels match are included; when
            omitted, every accepted + installed site is emitted.

    Returns:
        PDF bytes (single document, one page per sign site).
    """
    data = get_sign_candidates_for_area(conn, area_code)
    sites = data.get("sites") or []

    # Field-PDF is only for signs the trail crew is actually going to deploy.
    # Proposed candidates are pre-decision; rejected ones are out.
    field_statuses = {"accepted", "installed"}
    sites = [s for s in sites if (s.get("status") or "").lower() in field_statuses]

    selection_set: Optional[set] = None
    if selection:
        selection_set = {str(s) for s in selection if s}

    # Filter panels by selection (and drop sites with no remaining panels).
    filtered_sites: List[Dict[str, Any]] = []
    for s in sites:
        panels = s.get("panels") or []
        if selection_set is not None:
            sid = s.get("sign_site_id")
            if sid is None:
                continue
            panels = [p for p in panels if _selection_key(sid, p) in selection_set]
            if not panels:
                continue
        sc = dict(s)
        sc["panels"] = panels
        filtered_sites.append(sc)

    if not filtered_sites:
        return _empty_pdf(area_code)

    # Bulk lookups so a 100-sign export doesn't issue 300 round-trips.
    rutenummers = sorted({r for s in filtered_sites for r in (s.get("route_numbers") or [])})
    endpoints_by_route = _route_endpoints_bulk(conn, rutenummers) if rutenummers else {}
    geoms_by_route = _route_geometries_for_rutenummers(conn, rutenummers) if rutenummers else {}
    lengths_and_names = _route_total_lengths_and_names(conn, rutenummers) if rutenummers else {}
    route_names = {r: (v.get("rutenavn") or "") for r, v in lengths_and_names.items()}
    correction_factor = get_distance_correction_factor(op_conn, area_code) or 1.0
    site_pos_by_route = _site_pos_m_by_route_bulk(conn, filtered_sites)

    # Photo proximity match — fetch all placed photos once, filter per site.
    all_photos = fp_svc.list_photos(op_conn, area_code, only_placed=True)

    # Shared tile cache: adjacent signs share tiles, so this collapses tile
    # fetches dramatically across a multi-site export.
    tile_cache: Dict[Tuple[int, int, int], Any] = {}

    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Felt-PDF — {area_code}")

    for site in filtered_sites:
        _render_site_page(
            c, site,
            endpoints_by_route=endpoints_by_route,
            geoms_by_route=geoms_by_route,
            route_names=route_names,
            site_pos_by_route=site_pos_by_route,
            correction_factor=correction_factor,
            all_photos=all_photos,
            all_sites=filtered_sites,
            tile_cache=tile_cache,
        )
        c.showPage()

    c.save()
    return buf.getvalue()


def _empty_pdf(area_code: str) -> bytes:
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Felt-PDF — {area_code}")
    c.setFont("Helvetica", 12)
    c.drawString(MARGIN, PAGE_H - MARGIN - 20, f"Ingen skiltsteder å eksportere for {area_code}.")
    c.showPage()
    c.save()
    return buf.getvalue()


def _render_site_page(
    c: pdfcanvas.Canvas,
    site: Dict[str, Any],
    *,
    endpoints_by_route: Dict[str, Dict[str, Any]],
    geoms_by_route: Dict[str, Dict],
    route_names: Dict[str, str],
    site_pos_by_route: Dict[int, Dict[str, float]],
    correction_factor: float,
    all_photos: List[Dict[str, Any]],
    all_sites: List[Dict[str, Any]],
    tile_cache: Dict,
) -> None:
    y = PAGE_H - MARGIN
    y_after_header = _draw_header(c, site, y)

    map_x = MARGIN
    map_y = y_after_header - MAP_SIZE
    map_w = MAP_SIZE

    # Map snippet
    from . import map_snippet as ms
    site_lon = site.get("lon")
    site_lat = site.get("lat")
    if site_lon is not None and site_lat is not None:
        # Surrounding-site dots: every other accepted site in this batch within
        # the snippet's footprint. Status colours match the on-screen map.
        other = [
            (s["lon"], s["lat"], _status_color(s.get("status")))
            for s in all_sites
            if s is not site
            and s.get("lon") is not None
            and s.get("lat") is not None
        ]
        site_routes = set(site.get("route_numbers") or [])
        route_geoms = {r: geoms_by_route[r] for r in site_routes if r in geoms_by_route}
        # 600 px at the rendered 84 mm = ~180 dpi; plenty for print and ~3×
        # smaller than 900 px at q=78 once JPEG-encoded.
        snippet_px = 600
        zoom = ms.pick_zoom_for_radius_m(700.0, site_lat, snippet_px)
        try:
            png = ms.build_snippet(
                center_lon=site_lon,
                center_lat=site_lat,
                width_px=snippet_px,
                height_px=snippet_px,
                zoom=zoom,
                route_geoms=route_geoms,
                other_sites=other,
                tile_cache=tile_cache,
            )
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(io.BytesIO(png)), map_x, map_y, map_w, MAP_SIZE)
            c.setStrokeColor(colors.HexColor("#888"))
            c.setLineWidth(0.6)
            c.rect(map_x, map_y, map_w, MAP_SIZE, stroke=1, fill=0)
        except Exception as e:
            print(f"[sign_pdf] map snippet failed for {site.get('sign_site_id')}: {e}")
            _draw_map_placeholder(c, map_x, map_y, map_w, MAP_SIZE)
    else:
        _draw_map_placeholder(c, map_x, map_y, map_w, MAP_SIZE)

    # Info box to the right
    info_x = MARGIN + MAP_SIZE + 6 * mm
    info_w = PAGE_W - info_x - MARGIN
    sid = site.get("sign_site_id")
    pos_for_routes = site_pos_by_route.get(sid, {}) if sid is not None else {}
    ep_dist = _endpoint_distances(pos_for_routes, endpoints_by_route, correction_factor)
    _draw_info_box(c, site, ep_dist, route_names, info_x, map_y, info_w, MAP_SIZE)

    # Panel table
    table_y_top = map_y - 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, table_y_top - 10, "Paneler")
    table_y_top -= 16
    _draw_panel_table(c, site.get("panels") or [], MARGIN, table_y_top, PAGE_W - 2 * MARGIN)

    # Photos along the bottom
    photo_y = MARGIN + 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, photo_y + PHOTO_ROW_H + 4, "Bilder")
    if site_lon is not None and site_lat is not None:
        photos = _photos_for_site(all_photos, site_lon, site_lat)
    else:
        photos = []
    _draw_photos_row(c, photos, MARGIN, photo_y, PAGE_W - 2 * MARGIN, PHOTO_ROW_H)


def _draw_map_placeholder(c: pdfcanvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setFillColor(colors.HexColor("#eef0f3"))
    c.rect(x, y, w, h, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#888"))
    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(x + w / 2, y + h / 2, "(kartutsnitt utilgjengelig)")
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.HexColor("#888"))
    c.rect(x, y, w, h, stroke=1, fill=0)


def _status_color(status: Optional[str]) -> str:
    s = (status or "").lower()
    if s == "accepted":
        return "#1a7f3a"
    if s == "installed":
        return "#0b4d7a"
    if s == "rejected":
        return "#888888"
    return "#cbcbcb"
