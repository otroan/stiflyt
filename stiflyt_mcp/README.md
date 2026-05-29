# Stiflyt MCP Server

MCP (Model Context Protocol) server that exposes the Stiflyt backend API as tools for Cursor, Claude Code, and other MCP clients.

## Requirements

- The **Stiflyt backend** must be running (e.g. `make backend` or `uvicorn main:app --port 8001`).
- Python 3.9+ with the project installed (`pip install -e .` in the repo venv).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STIFLYT_BASE_URL` | `http://localhost:8001` | Backend API base URL |
| `STIFLYT_API_KEY` | — | Side-door key sent as `X-API-Key`. Must match `STIFLYT_API_KEY` on the **backend** side; both must be set to bypass Google OAuth. |
| `STIFLYT_X_USER` | — | Default `X-User` header for mutation attribution (`recorded_by`, `updated_by`, `uploaded_by`). Tools may override per-call via `x_user`. |
| `STIFLYT_MCP_ARTIFACTS_DIR` | `/tmp/stiflyt-mcp` | Where binary downloads (xlsx, pdf, photo files) land. |
| `STIFLYT_USERNAME` | — | Legacy Basic auth (only `/owners.xlsx` uses it). |
| `STIFLYT_PASSWORD` | — | Legacy Basic auth. |

## Auth model

`/api/v1/*` (except `/api/v1/auth/*`) is gated by [`require_user_or_api_key`](../api/auth.py). It accepts **either**:

1. A Google OAuth session cookie (what the browser app uses), **or**
2. An `X-API-Key` header matching the backend's `STIFLYT_API_KEY` env var (what this MCP server uses).

To enable the side door, set the **same** value for `STIFLYT_API_KEY` on both ends:

```bash
# Backend (cloud host):
export STIFLYT_API_KEY="$(openssl rand -hex 32)"
make backend

# MCP server (same host if running over SSH; laptop if local):
export STIFLYT_API_KEY="<the same value>"
export STIFLYT_X_USER="ole@meter.com"   # attribute mutations to a real person
```

If `STIFLYT_API_KEY` is unset on the backend, the side door is **closed** and every MCP tool call returns 401.

## Running the server

```bash
source venv/bin/activate
stiflyt-mcp
# or: python -m stiflyt_mcp
```

The server uses **stdio** transport (reads/writes stdin/stdout).

## Claude Code (local)

Project scope — visible in the repo, easy to demo. From the project root:

```bash
claude mcp add --scope project stiflyt \
  -e STIFLYT_BASE_URL=http://localhost:8001 \
  -e STIFLYT_API_KEY="$STIFLYT_API_KEY" \
  -e STIFLYT_X_USER="$USER@meter.com" \
  -- /home/otroan/stiflyt/scripts/stiflyt-mcp.sh
```

User scope (`--scope user`) puts it in `~/.claude.json` so every session sees it. Local scope (`--scope local`, the default) is the same file but project-keyed.

## Claude Code (laptop) + MCP on a cloud host

For a demo where Claude Code runs on a laptop and the backend + MCP server live in the cloud, hand SSH the stdio:

`.mcp.json` (on the laptop, repo root):

```json
{
  "mcpServers": {
    "stiflyt": {
      "command": "ssh",
      "args": [
        "-T",
        "demo@cloud-host",
        "STIFLYT_API_KEY=<key> STIFLYT_X_USER=ole@meter.com STIFLYT_BASE_URL=http://localhost:8001 /home/otroan/stiflyt/scripts/stiflyt-mcp.sh"
      ]
    }
  }
}
```

- `-T` disables pty allocation — required for clean binary stdio.
- The backend stays on the cloud host; the MCP server reaches it via localhost there. **No port forwarding needed.**
- Use key-based SSH (no password prompt) or Claude Code will hang on connect.
- Add `ControlMaster auto` / `ControlPersist 60s` to `~/.ssh/config` to reuse one SSH connection across MCP reconnects.

Binary downloads (xlsx, pdf, photos) land in `STIFLYT_MCP_ARTIFACTS_DIR` on the **cloud host** — `scp` to fetch.

## Cursor

Project-level `.cursor/mcp.json` runs `scripts/stiflyt-mcp.sh`. If Stiflyt doesn't appear in Cursor's tool list, add it explicitly in Cursor Settings → MCP using the full path to `scripts/stiflyt-mcp.sh` and set `STIFLYT_BASE_URL` / `STIFLYT_API_KEY` in the Env field.

## Tools overview

The tool surface mirrors the backend endpoints used by `signs_app`.

### Health & session
- `health`, `get_me`

### Search & routes
- `search_places`
- `list_routes`, `get_route`, `get_route_complete`, `get_routes_bulk`
- `get_route_segments`, `get_route_links`, `get_route_areas`, `get_routes_statistics`
- `validate_route` (legacy), `get_area_route_validation` (new area-aware)

### Segments & links
- `list_route_segments`, `get_segment_routes`, `get_segment_by_lokalid`
- `get_links`, `get_anchor_nodes`

### Route anchors
- `get_route_anchors`, `get_anchor_placenames`, `upsert_anchor_name`

### Signs — legacy reports
- `get_route_signs`, `get_signs_by_prefix`, `get_signs_missing`,
  `get_signs_production`, `get_route_signs_production`

### Signs — signs_app workflow
- Candidates: `get_signs_candidates`, `accept_sign_candidate`, `reject_sign_candidate`, `create_manual_sign`
- Area: `get_signs_area_routes`, `get_signs_area_stats`, `get_signs_area_validation`
- Sites: `update_sign_site_name`, `update_sign_site_status`, `delete_sign_site`
- Panels: `patch_sign_panel`, `get_sign_site_destinations`, `set_sign_site_destinations`, `patch_sign_destination_skilt`
- Names: `upsert_signs_anchor_name`, `get_signs_placenames`
- Exports: `download_signs_manufacturing_xlsx`, `download_signs_field_pdf`, `download_signs_validation_xlsx`

### Route annotations (rutebok / inspeksjon / dugnad / arbeid)
- `list_route_annotations`, `create_route_annotation`, `update_route_annotation`, `delete_route_annotation`
- `list_work_markers`, `download_route_dagbok_xlsx`

### Route correction (link exclusions + bridges)
- `list_link_exclusions`, `add_link_exclusions`, `clear_link_exclusions`
- `list_link_bridges`, `add_link_bridge`, `clear_link_bridges`

### Photos
- `list_photos`, `get_photo_thumbnails`, `get_route_photos`
- `upload_photo`, `patch_photo`, `delete_photo`, `download_photo_file`

### GPX
- `list_gpx_tracks`, `upload_gpx`, `delete_gpx`, `get_route_gpx_comparison`

### Elevation
- `get_route_elevation`

### Metadata override (errata)
- `get_metadata_override`, `put_metadata_override`, `clear_metadata_override`

### Geometry / matrikkel
- `get_geometry_owners`, `get_point_matrikkelenhet`

### Changesets
- `list_changesets`, `create_changeset`, `get_changeset`,
  `add_changeset_event`, `get_changeset_events`,
  `validate_changeset`, `get_changeset_diff_geojson`,
  `get_changeset_effective_geojson`, `get_changeset_artifact`,
  `publish_changeset`

### Editor
- `get_snap_targets`

## Testing

**1. Backend + client (no MCP host)**  
With backend running:

```bash
source venv/bin/activate
python -m stiflyt_mcp.check
```

**2. MCP server starts**  
Should block on stdin without crashing:

```bash
make mcp
# Ctrl+C to stop
```

**3. End-to-end via Claude Code / Cursor**  
After wiring `.mcp.json` (laptop) or `.cursor/mcp.json`, ask:

> "Use Stiflyt's `health` tool, then list candidates in area `bre` and tell me how many are unaccepted."

The model should call `health`, then `get_signs_candidates`, and answer from the result.
