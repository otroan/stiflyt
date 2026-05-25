"""Render the sign-back-text (baksidetekst) template from data/sign_export.yaml.

The template uses ``{placeholder}`` syntax (Python ``str.format``). Lines whose
placeholders all resolve to empty are dropped, so anchor-less manual sites
don't emit blank lines for ``{name}``.

Known placeholders:
    {name}                — anchor / placename
    {easting} {northing}  — UTM 32V coordinates, rounded to 10 m
"""
from __future__ import annotations

import os
import re
from typing import Dict


_SIGN_EXPORT_YAML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "sign_export.yaml",
)

_FALLBACK_TEMPLATE = "Stier er ryddet og merket av DNT Oslo og Omegn"


def _load_template() -> str:
    try:
        import yaml  # local import: yaml is an optional runtime dep here
        with open(_SIGN_EXPORT_YAML, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get("baksidetekst")
        if not raw:
            return _FALLBACK_TEMPLATE
        return raw.rstrip("\n")
    except (OSError, ImportError, Exception):
        return _FALLBACK_TEMPLATE


BAKSIDETEKST_TEMPLATE = _load_template()


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class _SafeDict(dict):
    def __missing__(self, key):  # noqa: D401
        return ""


def render(values: Dict[str, str]) -> str:
    """Substitute placeholders; drop lines whose placeholders are all empty."""
    safe = _SafeDict(values)
    out = []
    for line in BAKSIDETEKST_TEMPLATE.splitlines():
        placeholders = _PLACEHOLDER_RE.findall(line)
        if placeholders and all(not values.get(p) for p in placeholders):
            continue
        out.append(line.format_map(safe))
    return "\n".join(out)


# The static parts of the template — used as a fallback where per-site
# values aren't available (older signs.py flows that don't carry name/coords).
DEFAULT_BACK_TEXT = render({})
