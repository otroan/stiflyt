#!/usr/bin/env bash
# Run Stiflyt MCP server. Finds project root from this script's path so Cursor
# can start it regardless of working directory. Use full path to this script
# in Cursor MCP config if relative "venv/bin/stiflyt-mcp" does not work.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/venv/bin/stiflyt-mcp"
