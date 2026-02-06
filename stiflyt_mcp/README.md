# Stiflyt MCP Server

MCP (Model Context Protocol) server that exposes the Stiflyt backend API as tools for Cursor and other MCP clients.

## Requirements

- The **Stiflyt backend** must be running (e.g. `uvicorn main:app --port 8001`).
- Python 3.9+ with the project installed (e.g. `pip install -e .` in the repo venv).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STIFLYT_BASE_URL` | `http://localhost:8001` | Backend API base URL |
| `STIFLYT_USERNAME` | — | Optional Basic auth username (for owners.xlsx and point/matrikkelenhet owner info) |
| `STIFLYT_PASSWORD` | — | Optional Basic auth password |

## Running the server

From the project root with the venv activated:

```bash
source venv/bin/activate
stiflyt-mcp
```

Or:

```bash
python -m stiflyt_mcp
```

The server uses **stdio** transport (reads/writes stdin/stdout).

## Cursor MCP integration

Project-level `.cursor/mcp.json` is configured to run `scripts/stiflyt-mcp.sh` (which finds the project and runs the venv). If **Stiflyt does not appear** in Cursor’s tool list:

1. **Add the server in Cursor Settings** (this is more reliable than project-level config):
   - Open **Cursor Settings → Features → MCP**.
   - Click **Add new MCP server** (or Edit existing).
   - **Name:** `stiflyt`.
   - **Command:** use the **full path** to one of:
     - `venv/bin/stiflyt-mcp` → e.g. `/home/otroan/stiflyt/venv/bin/stiflyt-mcp`
     - or the wrapper → e.g. `/home/otroan/stiflyt/scripts/stiflyt-mcp.sh` (works no matter what Cursor’s working directory is).
   - **Env** (optional): `STIFLYT_BASE_URL`: `http://localhost:8001`.
2. Save and **restart Cursor** or use **Refresh** in the MCP section so the server (and tools) reload.

If the command uses a relative path, Cursor may run it from a different directory and the server will fail to start; use the full path to `venv/bin/stiflyt-mcp` or to `scripts/stiflyt-mcp.sh`.

## Tools overview

- **Search**: `search_places`
- **Routes**: `list_routes`, `get_route`, `get_route_complete`, `get_route_segments`, `get_route_links`, `validate_route`, `get_routes_statistics`, `get_route_areas`, `get_routes_bulk`
- **Segments**: `list_route_segments`, `get_segment_routes`, `get_segment_by_lokalid`
- **Links / nodes**: `get_links`, `get_anchor_nodes`
- **Route anchors**: `get_route_anchors`, `get_anchor_placenames`, `upsert_anchor_name`
- **Signs**: `get_route_signs`, `get_signs_by_prefix`, `get_signs_missing`, `get_signs_production`, `get_route_signs_production`
- **Geometry / matrikkel**: `get_geometry_owners`, `get_point_matrikkelenhet`
- **Changesets**: `list_changesets`, `create_changeset`, `get_changeset`, `add_changeset_event`, `get_changeset_events`, `validate_changeset`, `get_changeset_diff_geojson`, `get_changeset_effective_geojson`, `get_changeset_artifact`, `publish_changeset`
- **Editor**: `get_snap_targets`
- **Health**: `health`

Excel owner reports (`POST /api/v1/owners.xlsx`) are not exposed as a tool (binary response); use `get_geometry_owners` and the backend API or frontend for Excel export.

## Testing

**1. Backend + client (no Cursor)**
With the backend running (`make backend` in another terminal):

```bash
source venv/bin/activate
python -m stiflyt_mcp.check
```

You should see `GET /health` and `GET /api/v1/search/places` succeed. If either fails, fix the backend URL or start the backend first.

**2. MCP server starts**
Run the server; it should block on stdin (no crash):

```bash
make mcp
# or: stiflyt-mcp
```

Press Ctrl+C to stop.

**3. Full MCP in Cursor**
- Open this project in Cursor and ensure `.cursor/mcp.json` is present (Cursor loads it automatically).
- Start the backend (`make backend`).
- In Cursor chat or Composer, ask: *"Use the Stiflyt health tool to check if the backend is up"* or *"Search for places named oslo using Stiflyt"*.
- The model should call the `health` or `search_places` MCP tool and show the result. If the tools do not appear, check Cursor Settings → MCP and refresh the server list.
