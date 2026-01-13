"""Materialize changeset events into effective/diff GeoJSON."""
import json
from typing import Dict, List, Tuple
from services.database import db_connection
from psycopg.rows import dict_row
from .event_store import EventStore


class Materializer:
    """Materialize events into effective and diff GeoJSON."""

    def __init__(self, base_schema: str = "base", base_table: str = "segment_base"):
        self.base_schema = base_schema
        self.base_table = base_table

    def materialize_effective(self, changeset_id: str) -> Dict:
        """Materialize effective GeoJSON from base + events."""
        events = EventStore.get_events(changeset_id)
        
        # Load base segments (simplified - in production, filter by bbox or affected IDs)
        base_segments = self._load_base_segments()
        
        # Apply events
        effective_map: Dict[str, Dict] = {}
        temp_id_map: Dict[str, str] = {}  # temp_id -> permanent_id
        
        # Initialize with base segments
        for seg in base_segments:
            effective_map[seg["id"]] = {
                "id": seg["id"],
                "geometry": seg["geometry"],
                "properties": seg.get("attrs", {}),
                "retired": False,
            }
        
        # Process events
        for event_data in events:
            event = event_data["event"]
            event_type = event.get("type")
            
            if event_type == "segment.update_attrs":
                target_id = event["target"]["id"]
                if target_id in effective_map:
                    self._apply_patch(
                        effective_map[target_id]["properties"],
                        event["patch"],
                    )
            
            elif event_type == "segment.update_geom":
                target_id = event["target"]["id"]
                if target_id in effective_map:
                    effective_map[target_id]["geometry"] = event["geometry"]
            
            elif event_type == "segment.retire":
                target_id = event["target"]["id"]
                if target_id in effective_map:
                    effective_map[target_id]["retired"] = True
            
            elif event_type == "segment.add":
                temp_id = event["temp_id"]
                # Generate permanent ID (in production, backend should do this)
                permanent_id = f"new_{temp_id.replace('tmp_', '')}"
                temp_id_map[temp_id] = permanent_id
                effective_map[permanent_id] = {
                    "id": permanent_id,
                    "geometry": event["geometry"],
                    "properties": event.get("attrs", {}),
                    "retired": False,
                }
            
            elif event_type == "segment.delete_new":
                temp_id = event["target"]["temp_id"]
                permanent_id = temp_id_map.get(temp_id)
                if permanent_id and permanent_id in effective_map:
                    del effective_map[permanent_id]
        
        # Build GeoJSON FeatureCollection
        features = []
        for seg_id, seg_data in effective_map.items():
            if not seg_data["retired"]:
                features.append({
                    "type": "Feature",
                    "id": seg_id,
                    "geometry": seg_data["geometry"],
                    "properties": seg_data["properties"],
                })
        
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    def materialize_diff(self, changeset_id: str) -> Dict:
        """Materialize diff GeoJSON showing changes."""
        events = EventStore.get_events(changeset_id)
        base_segments = self._load_base_segments()
        
        base_map = {seg["id"]: seg for seg in base_segments}
        diff_features = []
        temp_id_map: Dict[str, str] = {}
        
        for event_data in events:
            event = event_data["event"]
            event_type = event.get("type")
            
            if event_type == "segment.update_attrs":
                target_id = event["target"]["id"]
                base_seg = base_map.get(target_id)
                if base_seg:
                    # Create diff feature showing update
                    new_props = base_seg.get("attrs", {}).copy()
                    self._apply_patch(new_props, event["patch"])
                    diff_features.append({
                        "type": "Feature",
                        "id": target_id,
                        "geometry": base_seg["geometry"],
                        "properties": {
                            "op": "update",
                            "before": base_seg.get("attrs", {}),
                            "after": new_props,
                        },
                    })
            
            elif event_type == "segment.update_geom":
                target_id = event["target"]["id"]
                base_seg = base_map.get(target_id)
                if base_seg:
                    diff_features.append({
                        "type": "Feature",
                        "id": target_id,
                        "geometry": event["geometry"],
                        "properties": {
                            "op": "update",
                            "before_geom": base_seg["geometry"],
                            "after_geom": event["geometry"],
                        },
                    })
            
            elif event_type == "segment.retire":
                target_id = event["target"]["id"]
                base_seg = base_map.get(target_id)
                if base_seg:
                    diff_features.append({
                        "type": "Feature",
                        "id": target_id,
                        "geometry": base_seg["geometry"],
                        "properties": {
                            "op": "retire",
                            "before": base_seg.get("attrs", {}),
                        },
                    })
            
            elif event_type == "segment.add":
                temp_id = event["temp_id"]
                permanent_id = f"new_{temp_id.replace('tmp_', '')}"
                temp_id_map[temp_id] = permanent_id
                diff_features.append({
                    "type": "Feature",
                    "id": permanent_id,
                    "geometry": event["geometry"],
                    "properties": {
                        "op": "add",
                        "after": event.get("attrs", {}),
                    },
                })
            
            elif event_type == "segment.delete_new":
                temp_id = event["target"]["temp_id"]
                permanent_id = temp_id_map.get(temp_id)
                if permanent_id:
                    # Find the add event to get geometry
                    for e in events:
                        if e["event"].get("temp_id") == temp_id:
                            diff_features.append({
                                "type": "Feature",
                                "id": permanent_id,
                                "geometry": e["event"]["geometry"],
                                "properties": {
                                    "op": "delete_new",
                                    "before": e["event"].get("attrs", {}),
                                },
                            })
                            break
        
        return {
            "type": "FeatureCollection",
            "features": diff_features,
        }

    def _load_base_segments(self) -> List[Dict]:
        """Load base segments from database."""
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Check if base schema/table exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = %s
                    )
                    """,
                    (self.base_schema, self.base_table),
                )
                if not cur.fetchone()[0]:
                    # Return empty list if base table doesn't exist
                    return []
                
                # Load segments (simplified - assumes geom column and attrs JSONB)
                cur.execute(
                    f"""
                    SELECT 
                        id,
                        ST_AsGeoJSON(geom)::json as geometry,
                        COALESCE(attrs, '{{}}'::jsonb) as attrs
                    FROM {self.base_schema}.{self.base_table}
                    LIMIT 1000
                    """
                )
                return [
                    {
                        "id": row["id"],
                        "geometry": row["geometry"],
                        "attrs": row["attrs"],
                    }
                    for row in cur.fetchall()
                ]

    def _apply_patch(self, target: Dict, patch: List[Dict]) -> None:
        """Apply JSON Patch operations to target dict."""
        for op in patch:
            op_type = op.get("op")
            path = op.get("path", "").lstrip("/")
            value = op.get("value")
            
            if op_type == "replace":
                self._set_nested(target, path, value)
            elif op_type == "add":
                self._set_nested(target, path, value)
            elif op_type == "remove":
                self._remove_nested(target, path)

    def _set_nested(self, obj: Dict, path: str, value: any) -> None:
        """Set nested value in dict using path."""
        parts = path.split("/")
        current = obj
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def _remove_nested(self, obj: Dict, path: str) -> None:
        """Remove nested value from dict using path."""
        parts = path.split("/")
        current = obj
        for part in parts[:-1]:
            if part not in current:
                return
            current = current[part]
        if parts[-1] in current:
            del current[parts[-1]]
