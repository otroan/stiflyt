"""Lightweight phase-timer for serving Server-Timing headers.

Usage:
    timings = []
    with phase_timer(timings, "links_query"):
        links = _fetch_links_for_prefix_fast(conn, area)
    with phase_timer(timings, "panels_compute"):
        ...
    response.headers["Server-Timing"] = format_server_timing(timings)

`Server-Timing` is rendered natively in Chrome / Firefox / Safari DevTools
under the Network → request → Timing tab, so there's no frontend code needed
to view the breakdown. Per RFC 8673 / Server-Timing spec: metric names are
ASCII, no spaces or special chars; we coerce snake_case to keep it valid.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Iterator, List, Tuple


_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _safe_name(name: str) -> str:
    return _NAME_RE.sub("_", name) or "phase"


@contextmanager
def phase_timer(timings: List[Tuple[str, float]], name: str) -> Iterator[None]:
    """Append (name, duration_ms) to `timings` on exit. Reentrant-safe."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        timings.append((_safe_name(name), (time.perf_counter() - t0) * 1000.0))


def format_server_timing(timings: List[Tuple[str, float]]) -> str:
    """RFC 8673 Server-Timing header value. Each metric: name;dur=ms_with_one_decimal."""
    return ", ".join(f"{name};dur={ms:.1f}" for name, ms in timings)
