"""API routes for changeset editor."""
import os
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Depends
from fastapi.responses import JSONResponse, FileResponse
from services.changeset.models import (
    CreateChangesetRequest,
    ChangesetResponse,
    AddEventRequest,
    EventResponse,
    ValidationResponse,
    PublishResponse,
)
from services.changeset.changeset_service import ChangesetService
from services.changeset.event_store import EventStore
from services.changeset.materializer import Materializer
from services.changeset.validator import Validator
from services.changeset.artifact_generator import ArtifactGenerator
from services.changeset.github_client import GitHubClient

router = APIRouter()

# Configuration
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "./artifacts"))
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "dnt")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "route-changes")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8001")


def get_user_id(x_user: Optional[str] = Header(None, alias="X-User")) -> str:
    """Get user ID from header or use default."""
    return x_user or "anonymous"


@router.post("/changesets", response_model=ChangesetResponse)
async def create_changeset(
    request: CreateChangesetRequest,
    user_id: str = Depends(get_user_id),
):
    """Create a new changeset."""
    try:
        changeset_id = ChangesetService.create(
            title=request.title,
            description=request.description,
            area=request.area,
            linked_issue_url=request.linked_issue_url,
            base_snapshot=request.base_snapshot,
            created_by=user_id,
        )
        changeset = ChangesetService.get(changeset_id)
        if not changeset:
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve created changeset {changeset_id}"
            )
        return changeset
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback.print_exc()  # Print to console for debugging
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create changeset: {error_detail}"
        )


@router.get("/changesets/{changeset_id}", response_model=ChangesetResponse)
async def get_changeset(changeset_id: str):
    """Get a changeset by ID."""
    changeset = ChangesetService.get(changeset_id)
    if not changeset:
        raise HTTPException(status_code=404, detail="Changeset not found")
    return changeset


@router.get("/changesets")
async def list_changesets(limit: int = 100, offset: int = 0):
    """List all changesets."""
    return ChangesetService.list_all(limit=limit, offset=offset)


@router.post("/changesets/{changeset_id}/events", response_model=EventResponse)
async def add_event(
    changeset_id: str,
    request: AddEventRequest,
    user_id: str = Depends(get_user_id),
):
    """Add an event to a changeset."""
    # Verify changeset exists
    changeset = ChangesetService.get(changeset_id)
    if not changeset:
        raise HTTPException(status_code=404, detail="Changeset not found")
    
    if changeset.status != "draft":
        raise HTTPException(
            status_code=400, detail=f"Cannot add events to changeset with status {changeset.status}"
        )
    
    # Add event
    event_id = EventStore.add_event(changeset_id, user_id, request.event)
    
    # Get event back
    event_data = EventStore.get_event(event_id)
    if not event_data:
        raise HTTPException(status_code=500, detail="Failed to retrieve event")
    
    return EventResponse(**event_data)


@router.get("/changesets/{changeset_id}/events")
async def get_events(changeset_id: str):
    """Get all events for a changeset."""
    # Verify changeset exists
    changeset = ChangesetService.get(changeset_id)
    if not changeset:
        raise HTTPException(status_code=404, detail="Changeset not found")
    
    events = EventStore.get_events(changeset_id)
    return {"events": events}


@router.post("/changesets/{changeset_id}/validate", response_model=ValidationResponse)
async def validate_changeset(changeset_id: str):
    """Validate a changeset."""
    # Verify changeset exists
    changeset = ChangesetService.get(changeset_id)
    if not changeset:
        raise HTTPException(status_code=404, detail="Changeset not found")
    
    validator = Validator()
    errors, warnings = validator.validate(changeset_id)
    
    return ValidationResponse(errors=errors, warnings=warnings)


@router.get("/changesets/{changeset_id}/diff.geojson")
async def get_diff_geojson(changeset_id: str):
    """Get diff GeoJSON for a changeset."""
    # Verify changeset exists
    changeset = ChangesetService.get(changeset_id)
    if not changeset:
        raise HTTPException(status_code=404, detail="Changeset not found")
    
    materializer = Materializer()
    diff = materializer.materialize_diff(changeset_id)
    return JSONResponse(content=diff)


@router.get("/changesets/{changeset_id}/effective.geojson")
async def get_effective_geojson(changeset_id: str):
    """Get effective GeoJSON for a changeset."""
    # Verify changeset exists
    changeset = ChangesetService.get(changeset_id)
    if not changeset:
        raise HTTPException(status_code=404, detail="Changeset not found")
    
    materializer = Materializer()
    effective = materializer.materialize_effective(changeset_id)
    return JSONResponse(content=effective)


@router.get("/changesets/{changeset_id}/artifacts/{filename}")
async def download_changeset_artifact(changeset_id: str, filename: str):
    """Download changeset artifact (JSON only)."""
    if not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON artifacts are supported")

    artifact_path = (ARTIFACTS_DIR / "changesets" / changeset_id / filename).resolve()
    artifacts_root = (ARTIFACTS_DIR / "changesets" / changeset_id).resolve()

    if not str(artifact_path).startswith(str(artifacts_root)):
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(
        path=str(artifact_path),
        media_type="application/json",
        filename=filename,
    )


@router.post("/changesets/{changeset_id}/publish", response_model=PublishResponse)
async def publish_changeset(
    changeset_id: str,
    user_id: str = Depends(get_user_id),
):
    """Publish a changeset (send to review)."""
    # Verify changeset exists
    changeset = ChangesetService.get(changeset_id)
    if not changeset:
        raise HTTPException(status_code=404, detail="Changeset not found")
    
    if changeset.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot publish changeset with status {changeset.status}",
        )
    
    # Validate
    validator = Validator()
    errors, warnings = validator.validate(changeset_id)
    
    if errors:
        return JSONResponse(
            status_code=400,
            content={
                "errors": [e.dict() for e in errors],
                "warnings": [w.dict() for w in warnings],
            },
        )
    
    # Generate artifacts
    generator = ArtifactGenerator(ARTIFACTS_DIR)
    artifacts = generator.generate_all(changeset_id, BASE_URL)
    
    # Create GitHub PR
    pr_url = None
    if GITHUB_TOKEN:
        github = GitHubClient(GITHUB_REPO_OWNER, GITHUB_REPO_NAME, GITHUB_TOKEN)
        
        # Generate PR body
        events = EventStore.get_events(changeset_id)
        op_counts = {"add": 0, "update": 0, "retire": 0}
        for event in events:
            event_type = event["event"].get("type", "")
            if "add" in event_type:
                op_counts["add"] += 1
            elif "update" in event_type:
                op_counts["update"] += 1
            elif "retire" in event_type:
                op_counts["retire"] += 1
        
        pr_body = f"""## Changeset: {changeset.title}

{changeset.description or ''}

**Map View:** {BASE_URL}/map?changeset={changeset_id}

**Statistics:**
- Add: {op_counts['add']} segments
- Update: {op_counts['update']} segments  
- Retire: {op_counts['retire']} segments

**Validation:**
- Errors: {len(errors)}
- Warnings: {len(warnings)}

{f'**Linked Issue:** {changeset.linked_issue_url}' if changeset.linked_issue_url else ''}
"""
        
        try:
            pr_url = github.create_pr(
                changeset_id,
                f"Changeset {changeset_id}: {changeset.title}",
                pr_body,
                artifacts["meta.yaml"].parent,
            )
        except Exception as e:
            # Log error but don't fail publish
            print(f"Failed to create GitHub PR: {e}")
    
    # Update changeset status
    ChangesetService.update_status(changeset_id, "review")
    if pr_url:
        ChangesetService.update_pr_url(changeset_id, pr_url)
    
    # Return artifact paths (relative)
    artifact_paths = {
        name: f"changesets/{changeset_id}/{Path(path).name}"
        for name, path in artifacts.items()
    }
    
    return PublishResponse(
        changeset_id=changeset_id,
        status="review",
        pr_url=pr_url or "",
        artifacts=artifact_paths,
    )


@router.get("/snap-targets")
async def get_snap_targets(bbox: str):
    """Get snap targets for a bounding box."""
    # Parse bbox: "min_lon,min_lat,max_lon,max_lat"
    try:
        coords = [float(x) for x in bbox.split(",")]
        if len(coords) != 4:
            raise ValueError
        min_lon, min_lat, max_lon, max_lat = coords
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid bbox format")
    
    # Load segments from base in bbox
    # This is simplified - in production, use spatial query
    materializer = Materializer()
    base_segments = materializer._load_base_segments()
    
    # Filter by bbox (simplified)
    snap_targets = []
    for seg in base_segments:
        geom = seg["geometry"]
        if geom.get("type") == "LineString":
            coords = geom.get("coordinates", [])
            # Check if any coordinate is in bbox
            in_bbox = any(
                min_lon <= c[0] <= max_lon and min_lat <= c[1] <= max_lat
                for c in coords
            )
            if in_bbox:
                snap_targets.append({
                    "id": seg["id"],
                    "geometry": geom,
                    "vertices": coords,  # All vertices for snapping
                })
    
    return {"targets": snap_targets}
