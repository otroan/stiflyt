"""
Metadata validators for route validation.
"""

from collections import defaultdict
from typing import Dict, List, Any
from .base import BaseValidator, ValidationResult, ValidationIssue, Severity
from ..database import ROUTE_SCHEMA, quote_identifier, validate_schema_name


class MetadataConsistencyValidator(BaseValidator):
    """Validates metadata consistency across route segments."""
    
    def get_name(self) -> str:
        return "metadata_consistency"
    
    def get_category(self) -> str:
        return "metadata"
    
    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """Validate metadata consistency across segments."""
        rutenummer = route_data.get('rutenummer')
        segments_dict = route_data.get('segments_dict', {})
        
        result = ValidationResult(rutenummer)
        
        if not segments_dict:
            return result
        
        schema_quoted = quote_identifier(ROUTE_SCHEMA)
        
        # Collect all values across all segments
        all_rutenummer = []
        all_rutenavn = []
        all_vedlikeholdsansvarlig = []
        all_rutetype = []
        all_gradering = []
        
        # Track which segments have which values
        rutenavn_by_segment = {}
        vedlikeholdsansvarlig_by_segment = {}
        rutetype_by_segment = {}
        gradering_by_segment = {}
        
        for segment_objid, fotruteinfo_rows in segments_dict.items():
            segment_rutenavn = [r.get('rutenavn') for r in fotruteinfo_rows if r.get('rutenavn')]
            segment_vedlikeholdsansvarlig = [r.get('vedlikeholdsansvarlig') for r in fotruteinfo_rows if r.get('vedlikeholdsansvarlig')]
            segment_rutetype = [r.get('rutetype') for r in fotruteinfo_rows if r.get('rutetype')]
            segment_gradering = [r.get('gradering') for r in fotruteinfo_rows if r.get('gradering')]
            
            # Track which segments have which values
            if segment_rutenavn:
                val = segment_rutenavn[0]
                if val not in rutenavn_by_segment:
                    rutenavn_by_segment[val] = []
                rutenavn_by_segment[val].append(str(segment_objid))
            
            if segment_vedlikeholdsansvarlig:
                val = segment_vedlikeholdsansvarlig[0]
                if val not in vedlikeholdsansvarlig_by_segment:
                    vedlikeholdsansvarlig_by_segment[val] = []
                vedlikeholdsansvarlig_by_segment[val].append(str(segment_objid))
            
            if segment_rutetype:
                val = segment_rutetype[0]
                if val not in rutetype_by_segment:
                    rutetype_by_segment[val] = []
                rutetype_by_segment[val].append(str(segment_objid))
            
            if segment_gradering:
                val = segment_gradering[0]
                if val not in gradering_by_segment:
                    gradering_by_segment[val] = []
                gradering_by_segment[val].append(str(segment_objid))
            
            # Collect values
            for row in fotruteinfo_rows:
                if row.get('rutenummer'):
                    all_rutenummer.append(row['rutenummer'])
                if row.get('rutenavn'):
                    all_rutenavn.append(row.get('rutenavn'))
                if row.get('vedlikeholdsansvarlig'):
                    all_vedlikeholdsansvarlig.append(row.get('vedlikeholdsansvarlig'))
                if row.get('rutetype'):
                    all_rutetype.append(row.get('rutetype'))
                if row.get('gradering'):
                    all_gradering.append(row.get('gradering'))
        
        # Check rutenummer consistency
        rutenummer_values = set(all_rutenummer)
        if len(rutenummer_values) > 1:
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_RUTENUMMER',
                message=f'Route has segments with different rutenummer values: {sorted(rutenummer_values)}',
                severity=Severity.ERROR,
                metadata={'values': sorted(rutenummer_values)}
            ))
        
        # Check rutenavn consistency
        rutenavn_values = set(all_rutenavn)
        if len(rutenavn_values) > 1:
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_RUTENAVN',
                message=f'Route has segments with different rutenavn values: {sorted(rutenavn_values)} (Expected: all segments should have the same rutenavn)',
                severity=Severity.WARNING,
                metadata={
                    'values': sorted(rutenavn_values),
                    'value_by_segment': rutenavn_by_segment
                }
            ))
        
        # Check vedlikeholdsansvarlig consistency
        vedlikeholdsansvarlig_values = set(all_vedlikeholdsansvarlig)
        if len(vedlikeholdsansvarlig_values) > 1:
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_VEDLIKEHOLDSANSVARLIG',
                message=f'Route has segments with different vedlikeholdsansvarlig values: {sorted(vedlikeholdsansvarlig_values)} (Note: Different organizations may be responsible for different segments - this may be expected)',
                severity=Severity.WARNING,
                metadata={
                    'values': sorted(vedlikeholdsansvarlig_values),
                    'value_by_segment': vedlikeholdsansvarlig_by_segment
                }
            ))
        
        # Check rutetype consistency
        rutetype_values = set(all_rutetype)
        if len(rutetype_values) > 1:
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_RUTETYPE',
                message=f'Route has segments with different rutetype values: {sorted(rutetype_values)} (Expected: all segments should have the same rutetype)',
                severity=Severity.WARNING,
                metadata={
                    'values': sorted(rutetype_values),
                    'value_by_segment': rutetype_by_segment
                }
            ))
        
        # Check gradering consistency
        gradering_values = set(all_gradering)
        if len(gradering_values) > 1:
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_GRADERING',
                message=f'Route has segments with different gradering values: {sorted(gradering_values)} (Expected: all segments should have the same gradering)',
                severity=Severity.WARNING,
                metadata={
                    'values': sorted(gradering_values),
                    'value_by_segment': gradering_by_segment
                }
            ))
        
        return result


class DuplicateMetadataValidator(BaseValidator):
    """Validates for duplicate metadata values within segments."""
    
    def get_name(self) -> str:
        return "duplicate_metadata"
    
    def get_category(self) -> str:
        return "metadata"
    
    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """Validate for duplicate metadata within segments."""
        rutenummer = route_data.get('rutenummer')
        segments_dict = route_data.get('segments_dict', {})
        
        result = ValidationResult(rutenummer)
        
        for segment_objid, fotruteinfo_rows in segments_dict.items():
            if len(fotruteinfo_rows) <= 1:
                continue  # No duplicates possible with single row
            
            segment_rutenavn = [r.get('rutenavn') for r in fotruteinfo_rows if r.get('rutenavn')]
            segment_vedlikeholdsansvarlig = [r.get('vedlikeholdsansvarlig') for r in fotruteinfo_rows if r.get('vedlikeholdsansvarlig')]
            segment_rutetype = [r.get('rutetype') for r in fotruteinfo_rows if r.get('rutetype')]
            segment_gradering = [r.get('gradering') for r in fotruteinfo_rows if r.get('gradering')]
            
            # Check duplicates in rutenavn
            rutenavn_counts = {}
            for val in segment_rutenavn:
                rutenavn_counts[val] = rutenavn_counts.get(val, 0) + 1
            for val, count in rutenavn_counts.items():
                if count > 1:
                    result.add_issue(ValidationIssue(
                        type='DUPLICATE_RUTENAVN_IN_SEGMENT',
                        message=f'Segment {segment_objid} has duplicate rutenavn "{val}" ({count} times) in its fotruteinfo rows',
                        severity=Severity.ERROR,
                        affected_segments=[str(segment_objid)],
                        metadata={'value': val, 'count': count}
                    ))
            
            # Check duplicates in vedlikeholdsansvarlig
            vedlikeholdsansvarlig_counts = {}
            for val in segment_vedlikeholdsansvarlig:
                vedlikeholdsansvarlig_counts[val] = vedlikeholdsansvarlig_counts.get(val, 0) + 1
            for val, count in vedlikeholdsansvarlig_counts.items():
                if count > 1:
                    result.add_issue(ValidationIssue(
                        type='DUPLICATE_VEDLIKEHOLDSANSVARLIG_IN_SEGMENT',
                        message=f'Segment {segment_objid} has duplicate vedlikeholdsansvarlig "{val}" ({count} times) in its fotruteinfo rows',
                        severity=Severity.ERROR,
                        affected_segments=[str(segment_objid)],
                        metadata={'value': val, 'count': count}
                    ))
            
            # Check duplicates in rutetype
            rutetype_counts = {}
            for val in segment_rutetype:
                rutetype_counts[val] = rutetype_counts.get(val, 0) + 1
            for val, count in rutetype_counts.items():
                if count > 1:
                    result.add_issue(ValidationIssue(
                        type='DUPLICATE_RUTETYPE_IN_SEGMENT',
                        message=f'Segment {segment_objid} has duplicate rutetype "{val}" ({count} times) in its fotruteinfo rows',
                        severity=Severity.WARNING,
                        affected_segments=[str(segment_objid)],
                        metadata={'value': val, 'count': count}
                    ))
            
            # Check duplicates in gradering
            gradering_counts = {}
            for val in segment_gradering:
                gradering_counts[val] = gradering_counts.get(val, 0) + 1
            for val, count in gradering_counts.items():
                if count > 1:
                    result.add_issue(ValidationIssue(
                        type='DUPLICATE_GRADERING_IN_SEGMENT',
                        message=f'Segment {segment_objid} has duplicate gradering "{val}" ({count} times) in its fotruteinfo rows',
                        severity=Severity.WARNING,
                        affected_segments=[str(segment_objid)],
                        metadata={'value': val, 'count': count}
                    ))
        
        return result


class MissingFieldsValidator(BaseValidator):
    """Validates for missing required fields in segments."""
    
    def get_name(self) -> str:
        return "missing_fields"
    
    def get_category(self) -> str:
        return "metadata"
    
    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """Validate for missing required fields."""
        rutenummer = route_data.get('rutenummer')
        segments_dict = route_data.get('segments_dict', {})
        
        result = ValidationResult(rutenummer)
        
        segments_missing_rutenavn = []
        segments_missing_vedlikeholdsansvarlig = []
        all_rutenavn = []
        all_vedlikeholdsansvarlig = []
        
        for segment_objid, fotruteinfo_rows in segments_dict.items():
            segment_rutenavn = [r.get('rutenavn') for r in fotruteinfo_rows if r.get('rutenavn')]
            segment_vedlikeholdsansvarlig = [r.get('vedlikeholdsansvarlig') for r in fotruteinfo_rows if r.get('vedlikeholdsansvarlig')]
            
            has_rutenavn = len(segment_rutenavn) > 0
            has_vedlikeholdsansvarlig = len(segment_vedlikeholdsansvarlig) > 0
            
            if not has_rutenavn:
                segments_missing_rutenavn.append(str(segment_objid))
            if not has_vedlikeholdsansvarlig:
                segments_missing_vedlikeholdsansvarlig.append(str(segment_objid))
            
            # Collect values
            for row in fotruteinfo_rows:
                if row.get('rutenavn'):
                    all_rutenavn.append(row.get('rutenavn'))
                if row.get('vedlikeholdsansvarlig'):
                    all_vedlikeholdsansvarlig.append(row.get('vedlikeholdsansvarlig'))
            
            # Check for missing rutenummer (always required)
            has_rutenummer = any(r.get('rutenummer') for r in fotruteinfo_rows)
            if not has_rutenummer:
                result.add_issue(ValidationIssue(
                    type='MISSING_REQUIRED_FIELDS',
                    message=f'Segment {segment_objid} is missing required field: rutenummer',
                    severity=Severity.ERROR,
                    affected_segments=[str(segment_objid)],
                    metadata={'missing_fields': ['rutenummer']}
                ))
        
        # Check for missing rutenavn
        rutenavn_values = set(all_rutenavn)
        if segments_missing_rutenavn:
            if len(rutenavn_values) == 0:
                result.add_issue(ValidationIssue(
                    type='MISSING_RUTENAVN',
                    message=f'No segments have rutenavn set. Affected segments: {sorted(segments_missing_rutenavn)}',
                    severity=Severity.WARNING,
                    affected_segments=sorted(segments_missing_rutenavn)
                ))
            else:
                result.add_issue(ValidationIssue(
                    type='MISSING_RUTENAVN_SOME_SEGMENTS',
                    message=f'Some segments are missing rutenavn. Affected segments: {sorted(segments_missing_rutenavn)}',
                    severity=Severity.WARNING,
                    affected_segments=sorted(segments_missing_rutenavn)
                ))
        
        # Check for missing vedlikeholdsansvarlig
        vedlikeholdsansvarlig_values = set(all_vedlikeholdsansvarlig)
        if segments_missing_vedlikeholdsansvarlig:
            if len(vedlikeholdsansvarlig_values) == 0:
                result.add_issue(ValidationIssue(
                    type='MISSING_VEDLIKEHOLDSANSVARLIG',
                    message=f'No segments have vedlikeholdsansvarlig set. Affected segments: {sorted(segments_missing_vedlikeholdsansvarlig)}',
                    severity=Severity.WARNING,
                    affected_segments=sorted(segments_missing_vedlikeholdsansvarlig)
                ))
            else:
                result.add_issue(ValidationIssue(
                    type='MISSING_VEDLIKEHOLDSANSVARLIG_SOME_SEGMENTS',
                    message=f'Some segments are missing vedlikeholdsansvarlig. Affected segments: {sorted(segments_missing_vedlikeholdsansvarlig)}',
                    severity=Severity.WARNING,
                    affected_segments=sorted(segments_missing_vedlikeholdsansvarlig)
                ))
        
        return result
