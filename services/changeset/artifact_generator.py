"""Generate artifacts for changeset publish."""
import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from .materializer import Materializer
from .changeset_service import ChangesetService
from .event_store import EventStore


class ArtifactGenerator:
    """Generate artifacts for changeset publish."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.materializer = Materializer()

    def generate_all(
        self,
        changeset_id: str,
        base_url: str = "http://localhost:8002",
    ) -> Dict[str, Path]:
        """Generate all artifacts. Returns dict of artifact_name -> file_path."""
        changeset = ChangesetService.get(changeset_id)
        if not changeset:
            raise ValueError(f"Changeset {changeset_id} not found")
        
        events = EventStore.get_events(changeset_id)
        effective = self.materializer.materialize_effective(changeset_id)
        diff = self.materializer.materialize_diff(changeset_id)
        
        artifacts_dir = self.output_dir / "changesets" / changeset_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        artifacts = {}
        
        # meta.yaml
        meta_path = artifacts_dir / "meta.yaml"
        self._generate_meta(meta_path, changeset, base_url)
        artifacts["meta.yaml"] = meta_path
        
        # report.md
        report_path = artifacts_dir / "report.md"
        self._generate_report(report_path, changeset, events, effective, diff)
        artifacts["report.md"] = report_path
        
        # diff.json
        diff_json_path = artifacts_dir / "diff.json"
        self._generate_diff_json(diff_json_path, events)
        artifacts["diff.json"] = diff_json_path
        
        # diff.geojson
        diff_geojson_path = artifacts_dir / "diff.geojson"
        self._save_geojson(diff_geojson_path, diff)
        artifacts["diff.geojson"] = diff_geojson_path
        
        # effective.geojson
        effective_geojson_path = artifacts_dir / "effective.geojson"
        self._save_geojson(effective_geojson_path, effective)
        artifacts["effective.geojson"] = effective_geojson_path
        
        return artifacts

    def _generate_meta(self, path: Path, changeset, base_url: str) -> None:
        """Generate meta.yaml."""
        meta = {
            "changeset_id": changeset.id,
            "title": changeset.title,
            "description": changeset.description,
            "area": changeset.area,
            "status": changeset.status,
            "created_by": changeset.created_by,
            "created_at": changeset.created_at.isoformat(),
            "updated_at": changeset.updated_at.isoformat(),
            "base_snapshot": changeset.base_snapshot,
            "linked_issue_url": changeset.linked_issue_url,
            "pr_url": changeset.pr_url,
            "map_url": f"{base_url}/map?changeset={changeset.id}",
        }
        
        with open(path, "w") as f:
            yaml.dump(meta, f, default_flow_style=False, sort_keys=False)

    def _generate_report(
        self,
        path: Path,
        changeset,
        events: List[Dict],
        effective: Dict,
        diff: Dict,
    ) -> None:
        """Generate report.md."""
        # Count operations
        op_counts = {"add": 0, "update": 0, "retire": 0, "delete_new": 0}
        for event in events:
            event_type = event["event"].get("type", "")
            if "add" in event_type:
                op_counts["add"] += 1
            elif "update" in event_type:
                op_counts["update"] += 1
            elif "retire" in event_type:
                op_counts["retire"] += 1
            elif "delete_new" in event_type:
                op_counts["delete_new"] += 1
        
        report = f"""# Changeset: {changeset.title}

**ID:** `{changeset.id}`  
**Status:** {changeset.status}  
**Created:** {changeset.created_at.isoformat()}  
**Created by:** {changeset.created_by}

## Description

{changeset.description or '*No description provided*'}

## Area

{changeset.area or '*Not specified*'}

## Statistics

- **Add:** {op_counts['add']} segments
- **Update:** {op_counts['update']} segments
- **Retire:** {op_counts['retire']} segments
- **Delete (new):** {op_counts['delete_new']} segments
- **Total events:** {len(events)}
- **Effective segments:** {len(effective.get('features', []))}

## Linked Issue

{changeset.linked_issue_url or '*No linked issue*'}

## Map View

View this changeset on the map: {changeset.pr_url or '*Not published*'}

## Files

- `diff.geojson` - GeoJSON showing all changes
- `effective.geojson` - Complete effective state after changes
- `diff.json` - Machine-readable change log
- `meta.yaml` - Changeset metadata

## Validation

Run validation to see errors and warnings.

---
*Generated at {datetime.utcnow().isoformat()}*
"""
        
        with open(path, "w") as f:
            f.write(report)

    def _generate_diff_json(self, path: Path, events: List[Dict]) -> None:
        """Generate diff.json."""
        diff_data = {
            "events": [
                {
                    "event_id": str(e["event_id"]),
                    "ts": e["ts"].isoformat(),
                    "user_id": e["user_id"],
                    "event": e["event"],
                }
                for e in events
            ]
        }
        
        with open(path, "w") as f:
            json.dump(diff_data, f, indent=2)

    def _save_geojson(self, path: Path, geojson: Dict) -> None:
        """Save GeoJSON to file."""
        with open(path, "w") as f:
            json.dump(geojson, f, indent=2)
