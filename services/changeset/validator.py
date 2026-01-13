"""Validator for changeset geometry and attributes."""
from typing import List, Dict, Any, Tuple
from services.database import db_connection
from psycopg.rows import dict_row
from .models import ValidationIssue
from .materializer import Materializer


class Validator:
    """Validate changeset geometry and attributes."""

    def __init__(self, base_schema: str = "base", base_table: str = "segment_base"):
        self.base_schema = base_schema
        self.base_table = base_table
        self.materializer = Materializer(base_schema, base_table)

    def validate(self, changeset_id: str) -> Tuple[List[ValidationIssue], List[ValidationIssue]]:
        """Validate a changeset. Returns (errors, warnings)."""
        errors: List[ValidationIssue] = []
        warnings: List[ValidationIssue] = []
        
        effective = self.materializer.materialize_effective(changeset_id)
        
        for feature in effective.get("features", []):
            feature_id = feature.get("id", "unknown")
            geometry = feature.get("geometry")
            properties = feature.get("properties", {})
            
            # Validate geometry
            geom_errors, geom_warnings = self._validate_geometry(feature_id, geometry)
            errors.extend(geom_errors)
            warnings.extend(geom_warnings)
            
            # Validate attributes
            attr_errors, attr_warnings = self._validate_attributes(feature_id, properties)
            errors.extend(attr_errors)
            warnings.extend(attr_warnings)
            
            # Validate endpoints (snap to network)
            endpoint_errors, endpoint_warnings = self._validate_endpoints(feature_id, geometry)
            errors.extend(endpoint_errors)
            warnings.extend(endpoint_warnings)
        
        return errors, warnings

    def _validate_geometry(
        self, feature_id: str, geometry: Dict[str, Any]
    ) -> Tuple[List[ValidationIssue], List[ValidationIssue]]:
        """Validate geometry."""
        errors: List[ValidationIssue] = []
        warnings: List[ValidationIssue] = []
        
        if not geometry or geometry.get("type") != "LineString":
            errors.append(
                ValidationIssue(
                    severity="error",
                    code="INVALID_GEOMETRY_TYPE",
                    message="Geometry must be a LineString",
                    feature_ref={"kind": "segment", "id": feature_id},
                )
            )
            return errors, warnings
        
        coords = geometry.get("coordinates", [])
        if len(coords) < 2:
            errors.append(
                ValidationIssue(
                    severity="error",
                    code="INSUFFICIENT_COORDINATES",
                    message="LineString must have at least 2 coordinates",
                    feature_ref={"kind": "segment", "id": feature_id},
                )
            )
            return errors, warnings
        
        # Check geometry validity using PostGIS
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Create temporary geometry
                import json
                geom_json = json.dumps(geometry)
                cur.execute(
                    """
                    SELECT 
                        ST_IsValid(ST_GeomFromGeoJSON(%s)) as is_valid,
                        ST_IsSimple(ST_GeomFromGeoJSON(%s)) as is_simple,
                        ST_Length(ST_GeomFromGeoJSON(%s)::geography) as length_m
                    """,
                    (geom_json, geom_json, geom_json),
                )
                result = cur.fetchone()
                
                if not result["is_valid"]:
                    errors.append(
                        ValidationIssue(
                            severity="error",
                            code="INVALID_GEOMETRY",
                            message="Geometry is not valid",
                            feature_ref={"kind": "segment", "id": feature_id},
                            location=self._get_centroid(geometry),
                        )
                    )
                
                if not result["is_simple"]:
                    warnings.append(
                        ValidationIssue(
                            severity="warn",
                            code="NON_SIMPLE_GEOMETRY",
                            message="Geometry has self-intersections",
                            feature_ref={"kind": "segment", "id": feature_id},
                            location=self._get_centroid(geometry),
                        )
                    )
                
                # Check minimum length (5 meters)
                if result["length_m"] and result["length_m"] < 5.0:
                    errors.append(
                        ValidationIssue(
                            severity="error",
                            code="SEGMENT_TOO_SHORT",
                            message=f"Segment is too short: {result['length_m']:.2f}m (minimum 5m)",
                            feature_ref={"kind": "segment", "id": feature_id},
                            location=self._get_centroid(geometry),
                        )
                    )
        
        return errors, warnings

    def _validate_attributes(
        self, feature_id: str, properties: Dict[str, Any]
    ) -> Tuple[List[ValidationIssue], List[ValidationIssue]]:
        """Validate attributes."""
        errors: List[ValidationIssue] = []
        warnings: List[ValidationIssue] = []
        
        # Validate route_ref format (if present)
        route_ref = properties.get("route_ref")
        if route_ref:
            import re
            # Simple validation: should match pattern like "BRE017" or "bre-1"
            if not re.match(r"^[A-Za-z0-9_-]+$", route_ref):
                errors.append(
                    ValidationIssue(
                        severity="error",
                        code="INVALID_ROUTE_REF",
                        message=f"Invalid route_ref format: {route_ref}",
                        feature_ref={"kind": "segment", "id": feature_id},
                    )
                )
        
        return errors, warnings

    def _validate_endpoints(
        self, feature_id: str, geometry: Dict[str, Any]
    ) -> Tuple[List[ValidationIssue], List[ValidationIssue]]:
        """Validate that endpoints snap to network."""
        errors: List[ValidationIssue] = []
        warnings: List[ValidationIssue] = []
        
        coords = geometry.get("coordinates", [])
        if len(coords) < 2:
            return errors, warnings
        
        start_point = coords[0]
        end_point = coords[-1]
        
        # Check distance to nearest segment in base + effective
        # This is simplified - in production, load all segments and check distance
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Check if base table exists
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
                    return errors, warnings
                
                # Find nearest point on network for start
                cur.execute(
                    f"""
                    SELECT 
                        ST_Distance(
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                            geom::geography
                        ) as distance_m
                    FROM {self.base_schema}.{self.base_table}
                    WHERE id != %s
                    ORDER BY ST_Distance(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        geom::geography
                    )
                    LIMIT 1
                    """,
                    (start_point[0], start_point[1], feature_id, start_point[0], start_point[1]),
                )
                result = cur.fetchone()
                if result and result["distance_m"]:
                    distance = result["distance_m"]
                    if distance > 5.0:
                        errors.append(
                            ValidationIssue(
                                severity="error",
                                code="DANGLE_ENDPOINT",
                                message=f"Start endpoint is too far from network: {distance:.2f}m",
                                feature_ref={"kind": "segment", "id": feature_id},
                                location={"lon": start_point[0], "lat": start_point[1]},
                            )
                        )
                    elif distance > 2.0:
                        warnings.append(
                            ValidationIssue(
                                severity="warn",
                                code="DANGLE_ENDPOINT",
                                message=f"Start endpoint is far from network: {distance:.2f}m",
                                feature_ref={"kind": "segment", "id": feature_id},
                                location={"lon": start_point[0], "lat": start_point[1]},
                            )
                        )
                
                # Check end point
                cur.execute(
                    f"""
                    SELECT 
                        ST_Distance(
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                            geom::geography
                        ) as distance_m
                    FROM {self.base_schema}.{self.base_table}
                    WHERE id != %s
                    ORDER BY ST_Distance(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        geom::geography
                    )
                    LIMIT 1
                    """,
                    (end_point[0], end_point[1], feature_id, end_point[0], end_point[1]),
                )
                result = cur.fetchone()
                if result and result["distance_m"]:
                    distance = result["distance_m"]
                    if distance > 5.0:
                        errors.append(
                            ValidationIssue(
                                severity="error",
                                code="DANGLE_ENDPOINT",
                                message=f"End endpoint is too far from network: {distance:.2f}m",
                                feature_ref={"kind": "segment", "id": feature_id},
                                location={"lon": end_point[0], "lat": end_point[1]},
                            )
                        )
                    elif distance > 2.0:
                        warnings.append(
                            ValidationIssue(
                                severity="warn",
                                code="DANGLE_ENDPOINT",
                                message=f"End endpoint is far from network: {distance:.2f}m",
                                feature_ref={"kind": "segment", "id": feature_id},
                                location={"lon": end_point[0], "lat": end_point[1]},
                            )
                        )
        
        return errors, warnings

    def _get_centroid(self, geometry: Dict[str, Any]) -> Dict[str, float]:
        """Get centroid of geometry for error location."""
        coords = geometry.get("coordinates", [])
        if not coords:
            return {"lon": 0.0, "lat": 0.0}
        
        # Simple centroid: middle coordinate
        mid_idx = len(coords) // 2
        mid_coord = coords[mid_idx]
        return {"lon": mid_coord[0], "lat": mid_coord[1]}
