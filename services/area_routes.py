"""Per-area route membership for the signs_app.

By default, an area's routes are anything whose rutenummer matches
`<area_code>%`. data/area_routes.yaml lets us extend or trim that set
per area (DNT chapter responsibility shifts over time and doesn't always
match the Kartverket prefix).

Use this for editorial chapter-responsibility decisions; use
data/route_errata.yaml for actual data corrections.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

import yaml

AREA_ROUTES_FILE = Path(__file__).resolve().parent.parent / "data" / "area_routes.yaml"

_cache: dict = {"mtime": -1.0, "data": {}, "include_inverse": {}}

_RUTENUMMER_PREFIX_RE = re.compile(r"^[a-z]+")


def _load() -> dict:
    try:
        mtime = AREA_ROUTES_FILE.stat().st_mtime
    except FileNotFoundError:
        _cache["data"] = {}
        _cache["include_inverse"] = {}
        _cache["mtime"] = -1.0
        return _cache["data"]
    if mtime != _cache["mtime"]:
        raw = yaml.safe_load(AREA_ROUTES_FILE.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("area_routes.yaml must be a mapping at the top level")
        _cache["data"] = raw
        inverse: dict = {}
        for area_code, cfg in raw.items():
            for r in (cfg or {}).get("include") or []:
                inverse[str(r)] = str(area_code)
        _cache["include_inverse"] = inverse
        _cache["mtime"] = mtime
    return _cache["data"]


def owner_area_for_rutenummer(rutenummer: Optional[str]) -> Optional[str]:
    """Map a rutenummer to its likely owner area_code.

    Resolution order:
      1. Explicit `include` override in data/area_routes.yaml.
      2. Alphabetic prefix of the rutenummer (e.g. "bre6" -> "bre").
      3. None when neither applies (numeric-only or empty rutenummer).
    """
    if not rutenummer:
        return None
    _load()
    inverse = _cache.get("include_inverse") or {}
    if rutenummer in inverse:
        return inverse[rutenummer]
    m = _RUTENUMMER_PREFIX_RE.match(rutenummer.lower())
    return m.group(0) if m else None


def area_membership(area_code: str) -> Tuple[List[str], List[str]]:
    """Return (include, exclude) explicit rutenummer lists for area_code."""
    cfg = _load().get(area_code) or {}
    include = [str(r) for r in (cfg.get("include") or [])]
    exclude = [str(r) for r in (cfg.get("exclude") or [])]
    return include, exclude


def area_route_filter_sql(area_code: str, column: str) -> Tuple[str, List[Any]]:
    """SQL predicate matching rows whose `column` belongs to `area_code`.

    Membership = (rutenummer LIKE <area_code>% OR rutenummer IN <include>)
                 AND rutenummer NOT IN <exclude>.

    `column` is interpolated as raw SQL — pass a trusted, fully-qualified
    column reference (e.g. "fi.rutenummer"). Never pass user input.
    """
    include, exclude = area_membership(area_code)
    parts = [f"{column} LIKE %s"]
    params: List[Any] = [f"{area_code}%"]
    if include:
        parts.append(f"{column} = ANY(%s)")
        params.append(include)
    sql = "(" + " OR ".join(parts) + ")"
    if exclude:
        sql += f" AND {column} <> ALL(%s)"
        params.append(exclude)
    return sql, params
