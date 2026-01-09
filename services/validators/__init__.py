"""
Validator plugin architecture for route validation.

Validators can be used both in CLI tools and API endpoints.
"""

from .base import BaseValidator, ValidationResult, ValidationIssue
from .registry import ValidatorRegistry, register_validator, get_validator_registry
from .metadata import (
    MetadataConsistencyValidator,
    DuplicateMetadataValidator,
    MissingFieldsValidator,
)
from .geometry import (
    RouteGeometryValidator,
    LinkConnectivityValidator,
    SegmentGapValidator,
)

# Auto-register validators
def _register_default_validators():
    """Register default validators in the global registry."""
    from .registry import get_validator_registry
    
    registry = get_validator_registry()
    
    # Register metadata validators
    registry.register(MetadataConsistencyValidator(), enabled=True)
    registry.register(DuplicateMetadataValidator(), enabled=True)
    registry.register(MissingFieldsValidator(), enabled=True)
    
    # Register geometry validators
    registry.register(RouteGeometryValidator(), enabled=True)
    registry.register(LinkConnectivityValidator(), enabled=True)
    registry.register(SegmentGapValidator(), enabled=True)

# Auto-register on import
_register_default_validators()

__all__ = [
    'BaseValidator',
    'ValidationResult',
    'ValidationIssue',
    'ValidatorRegistry',
    'register_validator',
    'get_validator_registry',
    'MetadataConsistencyValidator',
    'DuplicateMetadataValidator',
    'MissingFieldsValidator',
    'RouteGeometryValidator',
    'LinkConnectivityValidator',
    'SegmentGapValidator',
]
