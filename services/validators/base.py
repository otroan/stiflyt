"""
Base classes for route validators.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from enum import Enum


class Severity(Enum):
    """Validation issue severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue:
    """Represents a single validation issue."""
    
    def __init__(
        self,
        type: str,
        message: str,
        severity: Severity,
        affected_segments: Optional[List[str]] = None,
        affected_links: Optional[List[int]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.type = type
        self.message = message
        self.severity = severity
        self.affected_segments = affected_segments or []
        self.affected_links = affected_links or []
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'type': self.type,
            'message': self.message,
            'severity': self.severity.value,
        }
        if self.affected_segments:
            result['affected_segments'] = self.affected_segments
        if self.affected_links:
            result['affected_links'] = self.affected_links
        if self.metadata:
            result.update(self.metadata)
        return result


class ValidationResult:
    """Result of running validators on a route."""
    
    def __init__(self, rutenummer: str):
        self.rutenummer = rutenummer
        self.errors: List[ValidationIssue] = []
        self.warnings: List[ValidationIssue] = []
        self.info: List[ValidationIssue] = []
        self.metadata: Dict[str, Any] = {}
    
    def add_issue(self, issue: ValidationIssue):
        """Add a validation issue to the appropriate list."""
        if issue.severity == Severity.ERROR:
            self.errors.append(issue)
        elif issue.severity == Severity.WARNING:
            self.warnings.append(issue)
        else:
            self.info.append(issue)
    
    def get_status(self) -> str:
        """Get overall validation status."""
        if self.errors:
            return 'ERROR'
        elif self.warnings:
            return 'WARNING'
        else:
            return 'OK'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'rutenummer': self.rutenummer,
            'status': self.get_status(),
            'errors': [issue.to_dict() for issue in self.errors],
            'warnings': [issue.to_dict() for issue in self.warnings],
            'info': [issue.to_dict() for issue in self.info],
            'metadata': self.metadata,
        }


class BaseValidator(ABC):
    """Base class for all route validators."""
    
    @abstractmethod
    def get_name(self) -> str:
        """Return the name of this validator."""
        pass
    
    @abstractmethod
    def get_category(self) -> str:
        """Return the category of this validator (metadata/geometry/topology)."""
        pass
    
    @abstractmethod
    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """
        Validate route data.
        
        Args:
            route_data: Dictionary containing route data (segments, links, etc.)
            conn: Database connection
            
        Returns:
            ValidationResult with any issues found
        """
        pass
    
    def get_dependencies(self) -> List[str]:
        """
        Return list of validator names this validator depends on.
        
        Override if this validator depends on results from other validators.
        """
        return []
