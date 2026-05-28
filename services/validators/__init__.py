"""
Validator plugin architecture for route validation.

Validators can be used both in CLI tools and API endpoints.
"""

from .base import BaseValidator, ValidationResult, ValidationIssue
from .registry import ValidatorRegistry, register_validator, get_validator_registry
from .metadata import (
    MetadataConsistencyValidator,
    DuplicateMetadataValidator,
    DuplicateRutenummerInSegmentValidator,
    RouteNameSuggestionValidator,
    MissingFieldsValidator,
    PanelNameDriftValidator,
)
from .geometry import (
    RouteGeometryValidator,
    LinkConnectivityValidator,
    SegmentGapValidator,
)
from .topology import RouteLoopValidator, RouteDisconnectedValidator

# Auto-register validators
def _register_default_validators():
    """Register default validators in the global registry."""
    from .registry import get_validator_registry

    registry = get_validator_registry()

    # Register metadata validators
    registry.register(MetadataConsistencyValidator(), enabled=True)
    registry.register(DuplicateMetadataValidator(), enabled=True)
    registry.register(DuplicateRutenummerInSegmentValidator(), enabled=True)
    registry.register(RouteNameSuggestionValidator(), enabled=True)
    registry.register(MissingFieldsValidator(), enabled=True)
    registry.register(PanelNameDriftValidator(), enabled=True)

    # Register geometry validators
    registry.register(RouteGeometryValidator(), enabled=True)
    registry.register(LinkConnectivityValidator(), enabled=True)
    registry.register(SegmentGapValidator(), enabled=True)

    # Register topology validators
    registry.register(RouteLoopValidator(), enabled=True)
    registry.register(RouteDisconnectedValidator(), enabled=True)

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
    'DuplicateRutenummerInSegmentValidator',
    'RouteNameSuggestionValidator',
    'MissingFieldsValidator',
    'PanelNameDriftValidator',
    'RouteGeometryValidator',
    'LinkConnectivityValidator',
    'SegmentGapValidator',
    'RouteLoopValidator',
    'RouteDisconnectedValidator',
]
