"""Render a small map image centred on a sign-site, with route lines + a
marker for the post and dots for nearby sign sites.

Pure Pillow — fetches Web Mercator tiles from Kartverket's WMTS cache, mosaics
them, projects WGS84 geometry onto pixel coords, and writes a PNG suitable for
embedding into a reportlab field-PDF page.

Tile fetching is cached per-process via the shared `tile_cache` dict the caller
threads through. Adjacent signs share tiles, so for a multi-page PDF the cost
collapses from ~9N fetches to ~9 + neighbouring overlap.
"""
from __future__ import annotations

import io
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw

# Concurrency for tile fetching. Kartverket's WMTS cache handles parallel
# requests fine; serial fetching was the dominant cost of a multi-site PDF
# (~30 s for 100 unique tiles vs. ~4 s with 8 workers).
TILE_FETCH_WORKERS = 8

# Kartverket's open WMTS cache. {z}/{y}/{x} maps directly to
# {TileMatrix}/{TileRow}/{TileCol}. Topo for legible terrain in the field.
KARTVERKET_TOPO = "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
TILE_PX = 256
USER_AGENT = "stiflyt-signs-pdf/1.0"
HTTP_TIMEOUT_S = 8


def _lonlat_to_global_pixel(lon: float, lat: float, zoom: int) -> Tuple[float, float]:
    """WGS84 → global Web-Mercator pixel coords at the given zoom."""
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n * TILE_PX
    lat_rad = math.radians(max(-85.0511, min(85.0511, lat)))
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * TILE_PX
    return x, y


def _iter_linestrings(geom: Dict) -> Iterable[List[Tuple[float, float]]]:
    """Yield list-of-(lon,lat) for each LineString in a GeoJSON geometry."""
    if not geom:
        return
    t = geom.get("type")
    coords = geom.get("coordinates") or []
    if t == "LineString":
        yield [(c[0], c[1]) for c in coords if len(c) >= 2]
    elif t == "MultiLineString":
        for line in coords:
            yield [(c[0], c[1]) for c in line if len(c) >= 2]


def _fetch_tile(z: int, x: int, y: int, cache: Dict) -> Optional[Image.Image]:
    """Return a tile image or None on failure (which we paint as the placeholder
    background colour — better than crashing the whole PDF)."""
    key = (z, x, y)
    if key in cache:
        return cache[key]
    url = KARTVERKET_TOPO.replace("{z}", str(z)).replace("{y}", str(y)).replace("{x}", str(x))
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT})
        if resp.ok and resp.content:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            cache[key] = img
            return img
    except Exception as e:
        print(f"[map_snippet] tile fetch failed for {z}/{x}/{y}: {e}")
    cache[key] = None
    return None


def build_snippet(
    center_lon: float,
    center_lat: float,
    width_px: int = 800,
    height_px: int = 800,
    zoom: int = 14,
    route_geoms: Optional[Dict[str, Dict]] = None,
    other_sites: Optional[List[Tuple[float, float, str]]] = None,
    tile_cache: Optional[Dict] = None,
) -> bytes:
    """Render a PNG centered on (center_lon, center_lat).

    Args:
        width_px, height_px: output dimensions
        zoom: WMTS zoom level (14 ≈ 1.3 km across the snippet's width at lat 62°)
        route_geoms: {rutenummer: GeoJSON-MultiLineString} drawn underneath the post marker
        other_sites: [(lon, lat, hex_color), ...] — drawn as small dots
        tile_cache: optional shared dict {(z,x,y): PIL.Image | None}; pass one to
            amortise tile fetches over a batch of snippets.
    """
    if tile_cache is None:
        tile_cache = {}

    cx, cy = _lonlat_to_global_pixel(center_lon, center_lat, zoom)
    origin_x = cx - width_px / 2
    origin_y = cy - height_px / 2

    tile_x_min = int(math.floor(origin_x / TILE_PX))
    tile_y_min = int(math.floor(origin_y / TILE_PX))
    tile_x_max = int(math.floor((origin_x + width_px - 1) / TILE_PX))
    tile_y_max = int(math.floor((origin_y + height_px - 1) / TILE_PX))

    mosaic_w = (tile_x_max - tile_x_min + 1) * TILE_PX
    mosaic_h = (tile_y_max - tile_y_min + 1) * TILE_PX
    mosaic = Image.new("RGB", (mosaic_w, mosaic_h), "#dde6ee")

    # Fetch tiles in parallel. The cache prevents redundant fetches both across
    # snippets and within a single snippet (overlapping tile coordinates).
    coords = [(tx, ty) for tx in range(tile_x_min, tile_x_max + 1)
              for ty in range(tile_y_min, tile_y_max + 1)]
    missing = [(tx, ty) for tx, ty in coords if (zoom, tx, ty) not in tile_cache]
    if missing:
        with ThreadPoolExecutor(max_workers=TILE_FETCH_WORKERS) as ex:
            list(ex.map(lambda c: _fetch_tile(zoom, c[0], c[1], tile_cache), missing))
    for tx, ty in coords:
        tile = tile_cache.get((zoom, tx, ty))
        if tile is not None:
            mosaic.paste(tile, ((tx - tile_x_min) * TILE_PX, (ty - tile_y_min) * TILE_PX))

    crop_x = int(origin_x - tile_x_min * TILE_PX)
    crop_y = int(origin_y - tile_y_min * TILE_PX)
    snippet = mosaic.crop((crop_x, crop_y, crop_x + width_px, crop_y + height_px)).convert("RGBA")

    draw = ImageDraw.Draw(snippet, "RGBA")

    # Route lines first (under everything else).
    if route_geoms:
        for _ruten, geom in route_geoms.items():
            for line in _iter_linestrings(geom):
                pts: List[Tuple[float, float]] = []
                for lon, lat in line:
                    gx, gy = _lonlat_to_global_pixel(lon, lat, zoom)
                    pts.append((gx - origin_x, gy - origin_y))
                if len(pts) >= 2:
                    # Soft white halo under the red line to keep it legible
                    # over both terrain tiles and snow.
                    draw.line(pts, fill=(255, 255, 255, 200), width=7)
                    draw.line(pts, fill=(196, 61, 61, 235), width=3)

    # Neighbouring sites — small dots, drawn before the centre marker so the
    # post sits on top.
    if other_sites:
        for lon, lat, color in other_sites:
            gx, gy = _lonlat_to_global_pixel(lon, lat, zoom)
            sx, sy = gx - origin_x, gy - origin_y
            r = 5
            draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=color, outline=(0, 0, 0, 220), width=1)

    # Post marker — concentric circles for clear visibility on busy terrain.
    cx_snip, cy_snip = width_px / 2, height_px / 2
    draw.ellipse((cx_snip - 11, cy_snip - 11, cx_snip + 11, cy_snip + 11), fill=(255, 255, 255, 255))
    draw.ellipse((cx_snip - 8, cy_snip - 8, cx_snip + 8, cy_snip + 8), fill=(26, 127, 196, 255))
    draw.ellipse((cx_snip - 3, cy_snip - 3, cx_snip + 3, cy_snip + 3), fill=(255, 255, 255, 255))

    out = io.BytesIO()
    # JPEG at q=78 shrinks the snippet ~4× vs PNG with no perceptible quality
    # loss on terrain backgrounds. Critical for keeping a 60-page PDF under
    # 15 MB instead of 35 MB+.
    snippet.convert("RGB").save(out, "JPEG", quality=78, optimize=True)
    return out.getvalue()


def pick_zoom_for_radius_m(radius_m: float, lat: float, snippet_width_px: int) -> int:
    """Choose a tile zoom level so that the snippet width spans ~2 × radius.
    Helpful when you want the snippet to comfortably contain a given radius
    around the post (e.g. the 500 m matrikkel radius)."""
    # At zoom z, one tile is 256 px and the world is 256 * 2^z px around the
    # equator, mapped over 40075016 m. Latitude-corrected metres/pixel:
    #   res_m_per_px = (40075016 * cos(lat)) / (256 * 2^z)
    # Pick the z where snippet_width_px * res ≈ 2 * radius_m.
    if radius_m <= 0:
        return 14
    target_res = (2 * radius_m) / snippet_width_px
    for z in range(20, 4, -1):
        res = (40075016.0 * math.cos(math.radians(lat))) / (TILE_PX * (2 ** z))
        if res >= target_res:
            return z
    return 14
