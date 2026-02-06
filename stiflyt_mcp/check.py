#!/usr/bin/env python3
"""Quick check that the Stiflyt backend is reachable and the MCP client works.
Run with: python -m stiflyt_mcp.check
Requires the backend to be running (e.g. make backend)."""
import sys
from .client import StiflytClient


def main() -> int:
    client = StiflytClient()
    print(f"Using backend: {client.base_url}")
    print()

    # 1. Health
    print("1. GET /health ...")
    health = client.health()
    if isinstance(health, dict) and health.get("error"):
        print(f"   FAIL: {health}")
        return 1
    print(f"   OK: {health}")
    print()

    # 2. Search (lightweight)
    print("2. GET /api/v1/search/places?q=oslo&limit=2 ...")
    search = client.search_places("oslo", limit=2)
    if isinstance(search, dict) and search.get("error"):
        print(f"   FAIL: {search}")
        return 1
    total = search.get("total", 0)
    results = search.get("results", [])
    print(f"   OK: total={total}, got {len(results)} result(s)")
    print()

    print("Backend is reachable and client works. MCP server should work when run via Cursor or make mcp.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
