"""
Metadata validators for route validation.
"""

from collections import defaultdict
from typing import Dict, List, Any
from .base import BaseValidator, ValidationResult, ValidationIssue, Severity
from ..database import ROUTE_SCHEMA, quote_identifier, validate_schema_name
from psycopg.rows import dict_row


def _resolve_segment_objids_to_uuids(
    conn,
    schema_quoted: str,
    segment_objids: List[str],
) -> Dict[str, str]:
    """
    Resolve segment objids to UUIDs (lokalid or object_uuid/uuid/global_id) from fotrute.
    Returns mapping objid_str -> uuid_str. Missing or unresolvable objids are omitted.
    """
    if not segment_objids:
        return {}
    try:
        objids_int = []
        for s in segment_objids:
            try:
                objids_int.append(int(s))
            except (ValueError, TypeError):
                pass
        if not objids_int:
            return {}
    except Exception:
        return {}

    uuid_col = None
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'fotrute'
                  AND column_name IN ('object_uuid', 'uuid', 'global_id', 'lokalid')
                ORDER BY CASE column_name
                    WHEN 'object_uuid' THEN 1 WHEN 'uuid' THEN 2
                    WHEN 'global_id' THEN 3 WHEN 'lokalid' THEN 4
                    ELSE 5 END
                LIMIT 1
                """,
                (ROUTE_SCHEMA,),
            )
            row = cur.fetchone()
            uuid_col = row.get('column_name') if row else None
    except Exception:
        return {}

    if not uuid_col:
        return {}

    col_quoted = quote_identifier(uuid_col)
    objid_to_uuid = {}
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT objid, {schema_quoted}.fotrute.{col_quoted}::text as uuid_val
                FROM {schema_quoted}.fotrute
                WHERE objid = ANY(%s)
                """,
                (objids_int,),
            )
            for r in cur.fetchall():
                u = r.get('uuid_val')
                if u:
                    objid_to_uuid[str(r['objid'])] = u
    except Exception:
        pass
    return objid_to_uuid


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
            _objids = [oid for segs in rutenavn_by_segment.values() for oid in segs]
            _objid_to_uuid = _resolve_segment_objids_to_uuids(conn, schema_quoted, _objids)
            _uuids = [_objid_to_uuid[oid] for oid in _objids if oid in _objid_to_uuid]
            _value_by_segment_uuid = {
                val: [_objid_to_uuid[oid] for oid in segs if oid in _objid_to_uuid]
                for val, segs in rutenavn_by_segment.items()
            }
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_RUTENAVN',
                message=f'Route has segments with different rutenavn values: {sorted(rutenavn_values)} (Expected: all segments should have the same rutenavn)',
                severity=Severity.WARNING,
                affected_segments=_uuids,
                metadata={
                    'values': sorted(rutenavn_values),
                    'value_by_segment': rutenavn_by_segment,
                    'value_by_segment_uuid': _value_by_segment_uuid,
                }
            ))

        # Warn if any rutenavn is "Ukjent" (check all rows, not just first per segment)
        ukjent_segments = set()
        for segment_objid, fotruteinfo_rows in segments_dict.items():
            for row in fotruteinfo_rows:
                rutenavn = row.get('rutenavn')
                if rutenavn and str(rutenavn).strip().lower() == "ukjent":
                    ukjent_segments.add(str(segment_objid))
                    break

        if ukjent_segments:
            _objids = sorted(ukjent_segments)
            _objid_to_uuid = _resolve_segment_objids_to_uuids(conn, schema_quoted, _objids)
            _uuids = [_objid_to_uuid[oid] for oid in _objids if oid in _objid_to_uuid]
            result.add_issue(ValidationIssue(
                type='RUTENAVN_UKJENT',
                message='Route has segments with rutenavn "Ukjent". All routes should have a name.',
                severity=Severity.WARNING,
                affected_segments=_uuids if _uuids else _objids,
                metadata={'value': 'Ukjent', 'segment_objids': _objids}
            ))

        # Check vedlikeholdsansvarlig consistency
        vedlikeholdsansvarlig_values = set(all_vedlikeholdsansvarlig)
        if len(vedlikeholdsansvarlig_values) > 1:
            _objids = [oid for segs in vedlikeholdsansvarlig_by_segment.values() for oid in segs]
            _objid_to_uuid = _resolve_segment_objids_to_uuids(conn, schema_quoted, _objids)
            _uuids = [_objid_to_uuid[oid] for oid in _objids if oid in _objid_to_uuid]
            _value_by_segment_uuid = {
                val: [_objid_to_uuid[oid] for oid in segs if oid in _objid_to_uuid]
                for val, segs in vedlikeholdsansvarlig_by_segment.items()
            }
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_VEDLIKEHOLDSANSVARLIG',
                message=f'Route has segments with different vedlikeholdsansvarlig values: {sorted(vedlikeholdsansvarlig_values)} (Note: Different organizations may be responsible for different segments - this may be expected)',
                severity=Severity.WARNING,
                affected_segments=_uuids,
                metadata={
                    'values': sorted(vedlikeholdsansvarlig_values),
                    'value_by_segment': vedlikeholdsansvarlig_by_segment,
                    'value_by_segment_uuid': _value_by_segment_uuid,
                }
            ))

        # Check rutetype consistency
        rutetype_values = set(all_rutetype)
        if len(rutetype_values) > 1:
            _objids = [oid for segs in rutetype_by_segment.values() for oid in segs]
            _objid_to_uuid = _resolve_segment_objids_to_uuids(conn, schema_quoted, _objids)
            _uuids = [_objid_to_uuid[oid] for oid in _objids if oid in _objid_to_uuid]
            _value_by_segment_uuid = {
                val: [_objid_to_uuid[oid] for oid in segs if oid in _objid_to_uuid]
                for val, segs in rutetype_by_segment.items()
            }
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_RUTETYPE',
                message=f'Route has segments with different rutetype values: {sorted(rutetype_values)} (Expected: all segments should have the same rutetype)',
                severity=Severity.WARNING,
                affected_segments=_uuids,
                metadata={
                    'values': sorted(rutetype_values),
                    'value_by_segment': rutetype_by_segment,
                    'value_by_segment_uuid': _value_by_segment_uuid,
                }
            ))

        # Check gradering consistency
        gradering_values = set(all_gradering)
        if len(gradering_values) > 1:
            _objids = [oid for segs in gradering_by_segment.values() for oid in segs]
            _objid_to_uuid = _resolve_segment_objids_to_uuids(conn, schema_quoted, _objids)
            _uuids = [_objid_to_uuid[oid] for oid in _objids if oid in _objid_to_uuid]
            _value_by_segment_uuid = {
                val: [_objid_to_uuid[oid] for oid in segs if oid in _objid_to_uuid]
                for val, segs in gradering_by_segment.items()
            }
            result.add_issue(ValidationIssue(
                type='INCONSISTENT_GRADERING',
                message=f'Route has segments with different gradering values: {sorted(gradering_values)} (Expected: all segments should have the same gradering)',
                severity=Severity.WARNING,
                affected_segments=_uuids,
                metadata={
                    'values': sorted(gradering_values),
                    'value_by_segment': gradering_by_segment,
                    'value_by_segment_uuid': _value_by_segment_uuid,
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


class DuplicateRutenummerInSegmentValidator(BaseValidator):
    """Validates for duplicate rutenummer entries within a segment."""

    def get_name(self) -> str:
        return "duplicate_rutenummer_in_segment"

    def get_category(self) -> str:
        return "metadata"

    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """Validate for duplicate rutenummer within a segment."""
        rutenummer = route_data.get('rutenummer')
        segments_dict = route_data.get('segments_dict', {})

        result = ValidationResult(rutenummer)

        for segment_objid, fotruteinfo_rows in segments_dict.items():
            if len(fotruteinfo_rows) <= 1:
                continue

            rutenummer_counts = {}
            rutenummer_rows = {}
            for row in fotruteinfo_rows:
                val = row.get('rutenummer')
                if not val:
                    continue
                rutenummer_counts[val] = rutenummer_counts.get(val, 0) + 1
                if val not in rutenummer_rows:
                    rutenummer_rows[val] = []
                rutenummer_rows[val].append(row.get('fotruteinfo_objid'))

            for val, count in rutenummer_counts.items():
                if count > 1:
                    result.add_issue(ValidationIssue(
                        type='DUPLICATE_RUTENUMMER_IN_SEGMENT',
                        message=f'Segment {segment_objid} has duplicate rutenummer "{val}" ({count} times) in its fotruteinfo rows',
                        severity=Severity.ERROR,
                        affected_segments=[str(segment_objid)],
                        metadata={
                            'rutenummer': val,
                            'count': count,
                            'fotruteinfo_objids': rutenummer_rows.get(val, []),
                        }
                    ))

        return result


class RouteNameSuggestionValidator(BaseValidator):
    """Suggests rutenavn based on route endpoints when missing or 'Ukjent'."""

    def get_name(self) -> str:
        return "route_name_suggestion"

    def get_category(self) -> str:
        return "metadata"

    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        """Suggest rutenavn using anchor endpoint names."""
        rutenummer = route_data.get('rutenummer')
        segments_dict = route_data.get('segments_dict', {})

        result = ValidationResult(rutenummer)

        # Check if any segment has missing or "Ukjent" rutenavn
        needs_suggestion = False
        for _, fotruteinfo_rows in segments_dict.items():
            for row in fotruteinfo_rows:
                rutenavn = row.get('rutenavn')
                if not rutenavn or str(rutenavn).strip().lower() == "ukjent":
                    needs_suggestion = True
                    break
            if needs_suggestion:
                break

        if not needs_suggestion:
            return result

        # Load route geometry for endpoint name lookup
        from .base import Severity
        from ..database import ROUTE_SCHEMA, quote_identifier, validate_schema_name
        from ..route_endpoints import get_route_endpoint_names
        import json

        if not validate_schema_name(ROUTE_SCHEMA):
            return result

        schema_quoted = quote_identifier(ROUTE_SCHEMA)
        geometry = None
        query = f"""
            SELECT lwr.route_geometries->>%s as route_geometry_json
            FROM {schema_quoted}.links_with_routes lwr
            WHERE %s = ANY(lwr.rutenummer_list)
              AND lwr.route_geometries->>%s IS NOT NULL
            LIMIT 1
        """
        with conn.cursor() as cur:
            cur.execute(query, (rutenummer, rutenummer, rutenummer))
            row = cur.fetchone()
            if row and row[0]:
                try:
                    geometry = json.loads(row[0])
                except (json.JSONDecodeError, TypeError, ValueError):
                    geometry = None

        if not geometry:
            return result

        start_name = None
        end_name = None

        if geometry:
            endpoint_names = get_route_endpoint_names(conn, geometry, rutenummer) or {}
            start_point = endpoint_names.get('start_point') or {}
            end_point = endpoint_names.get('end_point') or {}
            start_name = start_point.get('name')
            end_name = end_point.get('name')

        if not start_name and not end_name:
            try:
                from psycopg.rows import dict_row

                # Check if navn column exists in anchor_nodes
                has_navn_column = False
                try:
                    with conn.cursor() as check_cur:
                        check_cur.execute("""
                            SELECT EXISTS (
                                SELECT 1
                                FROM information_schema.columns
                                WHERE table_schema = %s
                                  AND table_name = 'anchor_nodes'
                                  AND column_name = 'navn'
                            )
                        """, (ROUTE_SCHEMA,))
                        has_navn_column = check_cur.fetchone()[0]
                except Exception:
                    # If check fails, assume column doesn't exist
                    has_navn_column = False

                # Build SELECT clause conditionally
                navn_select = "an_a.navn as from_name, an_b.navn as to_name" if has_navn_column else "NULL as from_name, NULL as to_name"

                endpoint_query = f"""
                    WITH route_links_expanded AS (
                        SELECT
                            UNNEST(lwr.rutenummer_list) as rutenummer,
                            lwr.link_id,
                            lwr.a_node,
                            lwr.b_node
                        FROM {schema_quoted}.links_with_routes lwr
                        WHERE %s = ANY(lwr.rutenummer_list)
                    ),
                    first_last_links AS (
                        SELECT
                            rutenummer,
                            (SELECT a_node FROM route_links_expanded rle2
                             WHERE rle2.rutenummer = rle.rutenummer
                             ORDER BY link_id ASC LIMIT 1) as first_a_node,
                            (SELECT b_node FROM route_links_expanded rle2
                             WHERE rle2.rutenummer = rle.rutenummer
                             ORDER BY link_id DESC LIMIT 1) as last_b_node
                        FROM route_links_expanded rle
                        GROUP BY rutenummer
                    )
                    SELECT
                        fll.rutenummer,
                        {navn_select}
                    FROM first_last_links fll
                    LEFT JOIN {schema_quoted}.anchor_nodes an_a ON an_a.node_id = fll.first_a_node
                    LEFT JOIN {schema_quoted}.anchor_nodes an_b ON an_b.node_id = fll.last_b_node
                    LIMIT 1
                """
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(endpoint_query, (rutenummer,))
                    endpoint_row = cur.fetchone()
                    if endpoint_row:
                        start_name = endpoint_row.get('from_name')
                        end_name = endpoint_row.get('to_name')
            except Exception:
                # If endpoint lookup fails, skip suggestion
                return result

        if not start_name and not end_name:
            return result

        if start_name and end_name:
            suggested = f"{start_name} - {end_name}"
        else:
            suggested = start_name or end_name

        result.add_issue(ValidationIssue(
            type='RUTENAVN_SUGGESTION',
            message='Suggested rutenavn based on anchor endpoints.',
            severity=Severity.INFO,
            metadata={
                'suggested_rutenavn': suggested,
                'from_name': start_name,
                'to_name': end_name,
            }
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
