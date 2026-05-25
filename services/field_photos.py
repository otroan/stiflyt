"""Field-photo service: storage, EXIF extraction, thumbnail pipeline.

Photos are independent of sign_sites — they live as their own map layer
keyed on (area_code, lon, lat). Files are stored under data/photos/<area>/
with three variants per upload:

  * original  — the bytes the user uploaded (often HEIC from iPhone)
  * display   — long-edge 1600 px JPEG, browser-renderable (lightbox)
  * thumb     — 200 px square JPEG, used as a map marker

HEIC support comes from `pillow-heif`, which registers itself as a Pillow
plugin at import time. We register once at module load.

The database row sits in `ops.field_photos`; see stiflyt-db migration 017.
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps, ExifTags

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIC_OK = True
except Exception:  # pragma: no cover — only relevant in environments missing the dep
    _HEIC_OK = False


# Repo-relative data root. Keeping it next to data/route_errata.yaml means
# the whole tool's mutable state lives under data/ and is one rsync away
# from backed up. Override with FIELD_PHOTOS_ROOT for tests.
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "photos"
PHOTOS_ROOT = Path(os.getenv("FIELD_PHOTOS_ROOT", str(_DEFAULT_ROOT)))

# Constrained tag vocabulary — keep alphabetical, extend deliberately.
ALLOWED_TAGS = frozenset({
    "bridge",
    "cairn",
    "damage",
    "general",
    "panel",
    "route-condition",
    "sign",
    "signpost",
})

DISPLAY_MAX_PX = 1600
THUMB_PX = 200

# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------

_EXIF_TAG_ID = {name: tag for tag, name in ExifTags.TAGS.items()}
_GPS_TAG_ID = {name: tag for tag, name in ExifTags.GPSTAGS.items()}


def _gps_to_decimal(coord: Tuple, ref: str) -> Optional[float]:
    """Convert EXIF GPS (deg, min, sec) + N/S/E/W ref to a signed decimal."""
    try:
        d, m, s = (float(x) for x in coord)
    except Exception:
        return None
    dec = d + m / 60.0 + s / 3600.0
    if ref in ("S", "W"):
        dec = -dec
    return dec


def extract_exif(image: Image.Image) -> Dict[str, Any]:
    """Return {lon, lat, heading_deg, taken_at} (any may be None) from EXIF."""
    out: Dict[str, Any] = {"lon": None, "lat": None, "heading_deg": None, "taken_at": None}
    exif = image.getexif()
    if not exif:
        return out

    # DateTimeOriginal lives under the EXIF IFD, not the main one. Pillow
    # exposes it via get_ifd(_EXIF_TAG_ID["ExifOffset"]).
    try:
        ifd = exif.get_ifd(_EXIF_TAG_ID.get("ExifOffset", 0x8769))
    except Exception:
        ifd = {}
    dto = (ifd or {}).get(_EXIF_TAG_ID.get("DateTimeOriginal", 0x9003))
    if isinstance(dto, str):
        # EXIF format: 'YYYY:MM:DD HH:MM:SS'
        try:
            out["taken_at"] = datetime.strptime(dto, "%Y:%m:%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass

    # GPS lives in its own IFD.
    try:
        gps = exif.get_ifd(_EXIF_TAG_ID.get("GPSInfo", 0x8825))
    except Exception:
        gps = {}
    if gps:
        lat = gps.get(_GPS_TAG_ID["GPSLatitude"])
        lat_ref = gps.get(_GPS_TAG_ID["GPSLatitudeRef"])
        lon = gps.get(_GPS_TAG_ID["GPSLongitude"])
        lon_ref = gps.get(_GPS_TAG_ID["GPSLongitudeRef"])
        if lat and lat_ref and lon and lon_ref:
            out["lat"] = _gps_to_decimal(lat, lat_ref)
            out["lon"] = _gps_to_decimal(lon, lon_ref)
        heading = gps.get(_GPS_TAG_ID.get("GPSImgDirection", 17))
        if heading is not None:
            try:
                out["heading_deg"] = int(round(float(heading))) % 360
            except Exception:
                pass
    return out


# ---------------------------------------------------------------------------
# Storage pipeline
# ---------------------------------------------------------------------------


def _ensure_area_dir(area_code: str) -> Path:
    p = PHOTOS_ROOT / area_code
    p.mkdir(parents=True, exist_ok=True)
    return p


def _detect_orig_extension(filename: Optional[str], mime: Optional[str]) -> str:
    name = (filename or "").lower()
    for ext in (".heic", ".heif", ".jpg", ".jpeg", ".png"):
        if name.endswith(ext):
            return ext
    if mime == "image/heic" or mime == "image/heif":
        return ".heic"
    if mime == "image/png":
        return ".png"
    return ".jpg"


def store_upload(
    *,
    area_code: str,
    raw_bytes: bytes,
    filename: Optional[str],
    mime_type: Optional[str],
) -> Dict[str, Any]:
    """Save the original + generate display + thumb. Return the metadata dict
    the caller persists in `ops.field_photos`.

    Raises ValueError if the bytes don't open as an image.
    """
    if not raw_bytes:
        raise ValueError("empty upload")

    # Decode (HEIC works because pillow-heif registered above).
    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()  # force decode now so we can fail early on bad files
    except Exception as e:
        raise ValueError(f"unsupported image format: {e}") from e

    # Apply EXIF orientation so the display + thumb match how the user took it.
    oriented = ImageOps.exif_transpose(image) or image

    exif = extract_exif(image)

    area_dir = _ensure_area_dir(area_code)
    base_id = uuid.uuid4().hex
    orig_ext = _detect_orig_extension(filename, mime_type)
    orig_path = area_dir / f"{base_id}{orig_ext}"
    display_path = area_dir / f"{base_id}-1600.jpg"
    thumb_path = area_dir / f"{base_id}-thumb.jpg"

    # Write original bytes as-is so HEIC stays HEIC etc.
    orig_path.write_bytes(raw_bytes)

    rgb = oriented.convert("RGB")

    # Display: long-edge resize, 85% JPEG quality.
    disp = rgb.copy()
    disp.thumbnail((DISPLAY_MAX_PX, DISPLAY_MAX_PX), Image.LANCZOS)
    disp.save(display_path, "JPEG", quality=85, optimize=True)

    # Thumb: 200×200 center-crop square.
    thumb = ImageOps.fit(rgb, (THUMB_PX, THUMB_PX), Image.LANCZOS)
    thumb.save(thumb_path, "JPEG", quality=82, optimize=True)

    return {
        "file_path": str(orig_path.relative_to(PHOTOS_ROOT.parent)),
        "display_path": str(display_path.relative_to(PHOTOS_ROOT.parent)),
        "thumb_path": str(thumb_path.relative_to(PHOTOS_ROOT.parent)),
        "mime_type": mime_type or "application/octet-stream",
        "bytes": len(raw_bytes),
        "lon": exif["lon"],
        "lat": exif["lat"],
        "exif_heading_deg": exif["heading_deg"],
        "taken_at": exif["taken_at"],
    }


def resolve_path(stored_path: str) -> Path:
    """Map a stored relative path (e.g. 'photos/bre/xxx.jpg') to an absolute
    path on disk. Raises ValueError on path traversal attempts."""
    p = (PHOTOS_ROOT.parent / stored_path).resolve()
    # Resolve PHOTOS_ROOT.parent (the data/ root) and confirm `p` is inside.
    data_root = PHOTOS_ROOT.parent.resolve()
    if not str(p).startswith(str(data_root) + os.sep):
        raise ValueError(f"path escapes data root: {stored_path}")
    return p


def delete_files(file_path: str, display_path: str, thumb_path: str) -> None:
    """Best-effort delete of the three on-disk artifacts for a photo row."""
    for rel in (file_path, display_path, thumb_path):
        try:
            resolve_path(rel).unlink(missing_ok=True)
        except Exception:
            # Cleanup is best-effort; orphaned files are a known cost.
            pass


# ---------------------------------------------------------------------------
# DB helpers (thin — keep SQL local to the service)
# ---------------------------------------------------------------------------


def _row_to_api(r: Dict[str, Any]) -> Dict[str, Any]:
    """Map a DB row dict to the JSON shape the frontend expects."""
    return {
        "id": r["id"],
        "area_code": r["area_code"],
        "lon": r.get("lon"),
        "lat": r.get("lat"),
        "thumb_url": f"/api/v1/photos/{r['id']}/file?size=thumb",
        "display_url": f"/api/v1/photos/{r['id']}/file?size=display",
        "original_url": f"/api/v1/photos/{r['id']}/file?size=original",
        "mime_type": r.get("mime_type"),
        "bytes": r.get("bytes"),
        "taken_at": r["taken_at"].isoformat() if r.get("taken_at") else None,
        "exif_heading_deg": r.get("exif_heading_deg"),
        "tags": list(r.get("tags") or []),
        "caption": r.get("caption"),
        "uploaded_at": r["uploaded_at"].isoformat() if r.get("uploaded_at") else None,
        "uploaded_by": r.get("uploaded_by"),
        "needs_placement": r.get("lon") is None or r.get("lat") is None,
    }


def list_photos(
    op_conn, area_code: str, *, only_placed: Optional[bool] = None
) -> List[Dict[str, Any]]:
    """Return all photos for an area.

    only_placed=True  → only photos with lon/lat (map layer)
    only_placed=False → only photos waiting for manual placement (tray)
    only_placed=None  → both
    """
    from psycopg.rows import dict_row

    where = "WHERE area_code = %s"
    params: list = [area_code]
    if only_placed is True:
        where += " AND lon IS NOT NULL AND lat IS NOT NULL"
    elif only_placed is False:
        where += " AND lon IS NULL"
    sql = f"""
        SELECT id, area_code, lon, lat, file_path, display_path, thumb_path,
               mime_type, bytes, taken_at, exif_heading_deg, tags, caption,
               uploaded_at, uploaded_by
        FROM ops.field_photos
        {where}
        ORDER BY COALESCE(taken_at, uploaded_at) DESC
    """
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [_row_to_api(r) for r in cur.fetchall()]


def get_photo(op_conn, photo_id: int) -> Optional[Dict[str, Any]]:
    """Return one row including the on-disk paths (for the file-serve endpoint)."""
    from psycopg.rows import dict_row

    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, area_code, lon, lat, file_path, display_path, thumb_path,
                   mime_type, bytes, taken_at, exif_heading_deg, tags, caption,
                   uploaded_at, uploaded_by
            FROM ops.field_photos
            WHERE id = %s
            """,
            (photo_id,),
        )
        r = cur.fetchone()
        return dict(r) if r else None


def insert_photo(
    op_conn,
    *,
    area_code: str,
    storage: Dict[str, Any],
    caption: Optional[str],
    tags: List[str],
    uploaded_by: Optional[str],
) -> Dict[str, Any]:
    """Persist a photo row. `storage` is the dict returned by store_upload()."""
    from psycopg.rows import dict_row

    sanitized_tags = sorted({t for t in tags if t in ALLOWED_TAGS})
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO ops.field_photos
                (area_code, lon, lat, file_path, display_path, thumb_path,
                 mime_type, bytes, taken_at, exif_heading_deg, tags, caption,
                 uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, area_code, lon, lat, file_path, display_path,
                      thumb_path, mime_type, bytes, taken_at,
                      exif_heading_deg, tags, caption, uploaded_at, uploaded_by
            """,
            (
                area_code,
                storage.get("lon"),
                storage.get("lat"),
                storage["file_path"],
                storage["display_path"],
                storage["thumb_path"],
                storage["mime_type"],
                storage["bytes"],
                storage.get("taken_at"),
                storage.get("exif_heading_deg"),
                sanitized_tags,
                caption,
                uploaded_by,
            ),
        )
        r = cur.fetchone()
    return _row_to_api(dict(r)) if r else {}


def update_photo(
    op_conn,
    photo_id: int,
    *,
    lon: Optional[float] = None,
    lat: Optional[float] = None,
    caption: Optional[str] = None,
    tags: Optional[List[str]] = None,
    clear_caption: bool = False,
) -> Optional[Dict[str, Any]]:
    """Patch a photo row. Only fields you pass are updated.

    Pass lon AND lat together to manually geotag (or correct) a photo.
    Pass clear_caption=True to explicitly NULL the caption.
    """
    from psycopg.rows import dict_row

    sets: List[str] = []
    params: List[Any] = []
    if lon is not None and lat is not None:
        sets.append("lon = %s")
        sets.append("lat = %s")
        params.extend([lon, lat])
    if tags is not None:
        sanitized = sorted({t for t in tags if t in ALLOWED_TAGS})
        sets.append("tags = %s")
        params.append(sanitized)
    if clear_caption:
        sets.append("caption = NULL")
    elif caption is not None:
        sets.append("caption = %s")
        params.append(caption)

    if not sets:
        return get_photo_for_api(op_conn, photo_id)

    params.append(photo_id)
    sql = f"""
        UPDATE ops.field_photos
        SET {", ".join(sets)}
        WHERE id = %s
        RETURNING id, area_code, lon, lat, file_path, display_path,
                  thumb_path, mime_type, bytes, taken_at,
                  exif_heading_deg, tags, caption, uploaded_at, uploaded_by
    """
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        r = cur.fetchone()
        return _row_to_api(dict(r)) if r else None


def get_photo_for_api(op_conn, photo_id: int) -> Optional[Dict[str, Any]]:
    r = get_photo(op_conn, photo_id)
    return _row_to_api(r) if r else None


def delete_photo(op_conn, photo_id: int) -> bool:
    """Delete the DB row AND best-effort delete the three on-disk artifacts."""
    row = get_photo(op_conn, photo_id)
    if not row:
        return False
    with op_conn.cursor() as cur:
        cur.execute("DELETE FROM ops.field_photos WHERE id = %s", (photo_id,))
    delete_files(row["file_path"], row["display_path"], row["thumb_path"])
    return True
