"""Pydantic models for changeset editor."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# Event types
EventType = Literal[
    "segment.update_attrs",
    "segment.update_geom",
    "segment.retire",
    "segment.add",
    "segment.delete_new",
]


class SegmentTarget(BaseModel):
    """Target reference for segment operations."""
    kind: Literal["segment"] = "segment"
    id: str


class TempTarget(BaseModel):
    """Temporary target for new segments."""
    kind: Literal["segment"] = "segment"
    temp_id: str


# Event payloads
class SegmentUpdateAttrsEvent(BaseModel):
    """Update segment attributes."""
    type: Literal["segment.update_attrs"] = "segment.update_attrs"
    target: SegmentTarget
    patch: List[Dict[str, Any]]  # JSON Patch format
    comment: Optional[str] = None


class SegmentUpdateGeomEvent(BaseModel):
    """Update segment geometry."""
    type: Literal["segment.update_geom"] = "segment.update_geom"
    target: SegmentTarget
    geometry: Dict[str, Any]  # GeoJSON geometry
    srid: int = 4326
    comment: Optional[str] = None


class SegmentRetireEvent(BaseModel):
    """Retire a segment."""
    type: Literal["segment.retire"] = "segment.retire"
    target: SegmentTarget
    comment: Optional[str] = None


class SegmentAddEvent(BaseModel):
    """Add a new segment."""
    type: Literal["segment.add"] = "segment.add"
    temp_id: str = Field(..., pattern=r"^tmp_[a-f0-9-]+$")
    geometry: Dict[str, Any]  # GeoJSON geometry
    srid: int = 4326
    attrs: Dict[str, Any] = Field(default_factory=dict)
    comment: Optional[str] = None


class SegmentDeleteNewEvent(BaseModel):
    """Delete a newly added segment."""
    type: Literal["segment.delete_new"] = "segment.delete_new"
    target: TempTarget
    comment: Optional[str] = None


# Union type for all events
ChangeEvent = (
    SegmentUpdateAttrsEvent
    | SegmentUpdateGeomEvent
    | SegmentRetireEvent
    | SegmentAddEvent
    | SegmentDeleteNewEvent
)


# API request/response models
class CreateChangesetRequest(BaseModel):
    """Request to create a new changeset."""
    title: str
    description: Optional[str] = None
    area: Optional[str] = None
    linked_issue_url: Optional[str] = None
    base_snapshot: str = "default"  # Default snapshot identifier


class ChangesetResponse(BaseModel):
    """Changeset response."""
    id: str
    title: str
    description: Optional[str]
    area: Optional[str]
    status: Literal["draft", "review", "approved", "exported"]
    created_by: str
    created_at: datetime
    updated_at: datetime
    base_snapshot: str
    linked_issue_url: Optional[str]
    pr_url: Optional[str]


class AddEventRequest(BaseModel):
    """Request to add an event to a changeset."""
    event: Dict[str, Any]  # Will be validated against event types


class EventResponse(BaseModel):
    """Event response."""
    event_id: str
    changeset_id: str
    ts: datetime
    user_id: str
    event: Dict[str, Any]


class ValidationIssue(BaseModel):
    """Validation issue."""
    severity: Literal["error", "warn"]
    code: str
    message: str
    feature_ref: Dict[str, str]  # {kind: "segment", id: "..."}
    location: Optional[Dict[str, float]] = None  # {lon, lat}


class ValidationResponse(BaseModel):
    """Validation response."""
    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)


class PublishResponse(BaseModel):
    """Publish response."""
    changeset_id: str
    status: str
    pr_url: str
    artifacts: Dict[str, str]  # Paths to generated artifacts
