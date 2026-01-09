"""
Validator registry for managing and running validators.
"""

from typing import Dict, List, Optional, Callable, Any
from .base import BaseValidator, ValidationResult


class ValidatorRegistry:
    """Registry for managing route validators."""
    
    def __init__(self):
        self._validators: Dict[str, BaseValidator] = {}
        self._enabled: Dict[str, bool] = {}
    
    def register(self, validator: BaseValidator, enabled: bool = True):
        """
        Register a validator.
        
        Args:
            validator: Validator instance to register
            enabled: Whether this validator is enabled by default
        """
        name = validator.get_name()
        self._validators[name] = validator
        self._enabled[name] = enabled
    
    def unregister(self, name: str):
        """Unregister a validator by name."""
        if name in self._validators:
            del self._validators[name]
            del self._enabled[name]
    
    def get_validator(self, name: str) -> Optional[BaseValidator]:
        """Get a validator by name."""
        return self._validators.get(name)
    
    def list_validators(self, category: Optional[str] = None) -> List[str]:
        """
        List all registered validator names.
        
        Args:
            category: If provided, filter by category
            
        Returns:
            List of validator names
        """
        if category:
            return [
                name for name, validator in self._validators.items()
                if validator.get_category() == category
            ]
        return list(self._validators.keys())
    
    def enable(self, name: str):
        """Enable a validator."""
        if name in self._validators:
            self._enabled[name] = True
    
    def disable(self, name: str):
        """Disable a validator."""
        if name in self._validators:
            self._enabled[name] = False
    
    def is_enabled(self, name: str) -> bool:
        """Check if a validator is enabled."""
        return self._enabled.get(name, False)
    
    def run_validators(
        self,
        route_data: Dict[str, Any],
        conn,
        validator_names: Optional[List[str]] = None,
        categories: Optional[List[str]] = None
    ) -> ValidationResult:
        """
        Run validators on route data.
        
        Args:
            route_data: Dictionary containing route data
            conn: Database connection
            validator_names: If provided, only run these validators
            categories: If provided, only run validators in these categories
            
        Returns:
            Combined ValidationResult from all validators
        """
        rutenummer = route_data.get('rutenummer', 'unknown')
        result = ValidationResult(rutenummer)
        
        # Determine which validators to run
        validators_to_run = []
        if validator_names:
            # Run specific validators
            for name in validator_names:
                if name in self._validators and self._enabled.get(name, True):
                    validators_to_run.append(self._validators[name])
        elif categories:
            # Run validators in specific categories
            for name, validator in self._validators.items():
                if validator.get_category() in categories and self._enabled.get(name, True):
                    validators_to_run.append(validator)
        else:
            # Run all enabled validators
            for name, validator in self._validators.items():
                if self._enabled.get(name, True):
                    validators_to_run.append(validator)
        
        # Resolve dependencies
        validators_to_run = self._resolve_dependencies(validators_to_run)
        
        # Run validators
        for validator in validators_to_run:
            try:
                validator_result = validator.validate(route_data, conn)
                # Merge results
                for issue in validator_result.errors:
                    result.add_issue(issue)
                for issue in validator_result.warnings:
                    result.add_issue(issue)
                for issue in validator_result.info:
                    result.add_issue(issue)
                # Merge metadata
                result.metadata.update(validator_result.metadata)
            except Exception as e:
                # If a validator fails, add it as an error
                from .base import ValidationIssue, Severity
                result.add_issue(ValidationIssue(
                    type='VALIDATOR_ERROR',
                    message=f'Validator {validator.get_name()} failed: {str(e)}',
                    severity=Severity.ERROR,
                    metadata={'validator': validator.get_name()}
                ))
        
        return result
    
    def _resolve_dependencies(self, validators: List[BaseValidator]) -> List[BaseValidator]:
        """
        Resolve validator dependencies and return validators in correct order.
        
        Args:
            validators: List of validators to run
            
        Returns:
            List of validators in dependency order
        """
        # Simple topological sort
        validator_map = {v.get_name(): v for v in validators}
        result = []
        added = set()
        
        def add_with_deps(validator: BaseValidator):
            if validator.get_name() in added:
                return
            for dep_name in validator.get_dependencies():
                if dep_name in validator_map:
                    add_with_deps(validator_map[dep_name])
            result.append(validator)
            added.add(validator.get_name())
        
        for validator in validators:
            add_with_deps(validator)
        
        return result


# Global registry instance
_global_registry: Optional[ValidatorRegistry] = None


def get_validator_registry() -> ValidatorRegistry:
    """Get the global validator registry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ValidatorRegistry()
    return _global_registry


def register_validator(validator: BaseValidator, enabled: bool = True):
    """
    Register a validator in the global registry.
    
    Can be used as a decorator:
    
    @register_validator
    class MyValidator(BaseValidator):
        ...
    """
    registry = get_validator_registry()
    registry.register(validator, enabled=enabled)
    return validator
