"""Output formatters for CLI."""
import json
import csv
import yaml
from typing import List, Dict, Any, Optional, Tuple
from io import StringIO


def format_json(data: Dict[str, Any]) -> str:
    """
    Format data as pretty-printed JSON.

    Args:
        data: Dictionary to format

    Returns:
        JSON string
    """
    return json.dumps(data, indent=2, ensure_ascii=False)


def format_table(segments: List[Dict[str, Any]], show_geometry: bool = False) -> str:
    """
    Format segments as a human-readable table.

    Args:
        segments: List of segment dictionaries with routes as list
        show_geometry: Whether to include geometry info in table

    Returns:
        Formatted table string
    """
    if not segments:
        return "No segments found."

    lines = []

    # Calculate column widths - need to handle routes as list
    def get_routes_str(routes_list):
        """Format routes list as comma-separated string of rutenummer."""
        if not routes_list:
            return ""
        route_strs = [r.get("rutenummer", "") if isinstance(r, dict) else str(r) for r in routes_list]
        return ", ".join(route_strs)

    def get_rutenavn_str(routes_list):
        """Get rutenavn values from routes, excluding 'Ukjent'."""
        if not routes_list:
            return ""
        navn_list = []
        for r in routes_list:
            if isinstance(r, dict):
                rutenavn = r.get("rutenavn", "")
                # Only include if not "Ukjent" and not empty
                if rutenavn and rutenavn != "Ukjent":
                    navn_list.append(rutenavn)
        return ", ".join(navn_list) if navn_list else ""

    def get_vedlikeholdsansvarlig_str(routes_list):
        """Get unique vedlikeholdsansvarlig values from routes."""
        if not routes_list:
            return ""
        orgs = set()
        for r in routes_list:
            if isinstance(r, dict):
                org = r.get("vedlikeholdsansvarlig")
                if org:
                    orgs.add(org)
        return ", ".join(sorted(orgs)) if orgs else "N/A"

    col_widths = {
        "objid": max(len("objid"), max(len(str(s.get("objid", ""))) for s in segments)),
        "rutenummer": max(len("rutenummer"), max(len(get_routes_str(s.get("routes", []))) for s in segments)),
        "rutenavn": max(len("rutenavn"), max(len(get_rutenavn_str(s.get("routes", []))) for s in segments)),
        "vedlikeholdsansvarlig": max(len("vedlikeholdsansvarlig"), max(len(get_vedlikeholdsansvarlig_str(s.get("routes", []))) for s in segments)),
        "length_meters": max(len("length (m)"), max(len(f"{s.get('length_meters', 0):.1f}") if s.get('length_meters') else len("N/A") for s in segments)),
    }

    # Ensure minimum widths
    for key in col_widths:
        col_widths[key] = max(col_widths[key], 8)

    # Build header
    header = (
        f"{'objid':<{col_widths['objid']}} | "
        f"{'rutenummer':<{col_widths['rutenummer']}} | "
        f"{'rutenavn':<{col_widths['rutenavn']}} | "
        f"{'vedlikeholdsansvarlig':<{col_widths['vedlikeholdsansvarlig']}} | "
        f"{'length (m)':>{col_widths['length_meters']}}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    # Build rows
    for segment in segments:
        objid = str(segment.get("objid", ""))
        routes = segment.get("routes", [])
        rutenummer_str = get_routes_str(routes)
        rutenavn_str = get_rutenavn_str(routes)
        vedlikeholdsansvarlig_str = get_vedlikeholdsansvarlig_str(routes)
        length_meters = segment.get("length_meters")
        length_str = f"{length_meters:.1f}" if length_meters is not None else "N/A"

        row = (
            f"{objid:<{col_widths['objid']}} | "
            f"{rutenummer_str:<{col_widths['rutenummer']}} | "
            f"{rutenavn_str:<{col_widths['rutenavn']}} | "
            f"{vedlikeholdsansvarlig_str:<{col_widths['vedlikeholdsansvarlig']}} | "
            f"{length_str:>{col_widths['length_meters']}}"
        )
        lines.append(row)

    return "\n".join(lines)


def format_csv(segments: List[Dict[str, Any]], include_geometry: bool = False) -> str:
    """
    Format segments as CSV.

    Creates one row per segment with routes as comma-separated lists.

    Args:
        segments: List of segment dictionaries with routes as list
        include_geometry: Whether to include geometry column

    Returns:
        CSV string
    """
    if not segments:
        return ""

    output = StringIO()
    fieldnames = ["objid", "rutenummer", "rutenavn", "vedlikeholdsansvarlig", "length_meters"]
    if include_geometry:
        fieldnames.append("geometry")

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()

    for segment in segments:
        routes = segment.get("routes", [])
        rutenummer_list = [r.get("rutenummer", "") if isinstance(r, dict) else str(r) for r in routes]
        rutenavn_list = [r.get("rutenavn", "") if isinstance(r, dict) else "" for r in routes]
        vedlikeholdsansvarlig_list = [r.get("vedlikeholdsansvarlig", "") if isinstance(r, dict) else "" for r in routes]

        # Get unique organizations
        orgs = set(org for org in vedlikeholdsansvarlig_list if org)

        row = {
            "objid": segment.get("objid"),
            "rutenummer": ", ".join(rutenummer_list),
            "rutenavn": ", ".join(rutenavn_list),
            "vedlikeholdsansvarlig": ", ".join(sorted(orgs)) if orgs else "",
            "length_meters": segment.get("length_meters", ""),
        }
        if include_geometry and segment.get("geometry"):
            row["geometry"] = json.dumps(segment.get("geometry"))
        writer.writerow(row)

    return output.getvalue()


def format_text_summary(response: Dict[str, Any]) -> str:
    """
    Format a summary of the query results.

    Args:
        response: API response dictionary

    Returns:
        Summary string
    """
    total = response.get("total", 0)
    limit = response.get("limit", 0)
    offset = response.get("offset", 0)
    segments = response.get("segments", [])

    lines = []
    lines.append(f"Found {total} segment(s)")
    if total > len(segments):
        lines.append(f"Showing {len(segments)} segment(s) (offset: {offset}, limit: {limit})")
    lines.append("")

    return "\n".join(lines)


def format_complete_route_table(route: Dict[str, Any]) -> str:
    """
    Format a complete route as a human-readable table.

    Args:
        route: Complete route dictionary

    Returns:
        Formatted table string
    """
    lines = []

    # Header section
    lines.append("=" * 60)
    lines.append("COMPLETE ROUTE")
    lines.append("=" * 60)
    lines.append("")

    # Basic information
    rutenummer = route.get("rutenummer", "N/A")
    rutenavn = route.get("rutenavn") or "N/A"
    vedlikeholdsansvarlig = route.get("vedlikeholdsansvarlig") or "N/A"
    total_length_km = route.get("total_length_km", 0.0)
    total_length_meters = route.get("total_length_meters", 0.0)
    is_connected = route.get("is_connected", False)
    segment_count = route.get("segment_count", 0)
    component_count = route.get("component_count", 1)

    lines.append(f"Rutenummer:        {rutenummer}")
    lines.append(f"Rutenavn:         {rutenavn}")
    lines.append(f"Vedlikeholdsansvarlig: {vedlikeholdsansvarlig}")
    lines.append(f"Total lengde:      {total_length_km:.2f} km ({total_length_meters:.1f} m)")
    lines.append(f"Segmenter:         {segment_count}")
    lines.append(f"Komponenter:       {component_count}")
    lines.append(f"Koblet:            {'Ja' if is_connected else 'Nei'}")
    lines.append("")

    # Endpoint names - always show this section
    from_name = route.get("from_name")
    to_name = route.get("to_name")

    lines.append("-" * 60)
    lines.append("ENDPUNKTER")
    lines.append("-" * 60)
    if from_name:
        name = from_name.get("name", "N/A")
        source = from_name.get("source", "unknown")
        distance = from_name.get("distance_meters")
        distance_str = f"{distance:.1f} m" if distance is not None else "N/A"
        tilrettelegging = from_name.get("tilrettelegging")
        if tilrettelegging:
            lines.append(f"Fra:  {name} ({source}, {distance_str}, tilrettelegging: {tilrettelegging})")
        else:
            lines.append(f"Fra:  {name} ({source}, {distance_str})")
    else:
        lines.append("Fra:  Ikke funnet")

    if to_name:
        name = to_name.get("name", "N/A")
        source = to_name.get("source", "unknown")
        distance = to_name.get("distance_meters")
        distance_str = f"{distance:.1f} m" if distance is not None else "N/A"
        tilrettelegging = to_name.get("tilrettelegging")
        if tilrettelegging:
            lines.append(f"Til:  {name} ({source}, {distance_str}, tilrettelegging: {tilrettelegging})")
        else:
            lines.append(f"Til:  {name} ({source}, {distance_str})")
    else:
        lines.append("Til:  Ikke funnet")
    lines.append("")

    # Components (if multiple)
    components = route.get("components")
    if components and len(components) > 1:
        lines.append("-" * 60)
        lines.append("KOMPONENTER")
        lines.append("-" * 60)
        for comp in components:
            index = comp.get("index", 0)
            segment_count_comp = comp.get("segment_count", 0)
            length_km = comp.get("length_meters", 0.0) / 1000.0
            is_main = comp.get("is_main", False)
            main_str = " (Hovedrute)" if is_main else ""
            lines.append(f"  Komponent {index}: {segment_count_comp} segmenter, {length_km:.2f} km{main_str}")
        lines.append("")

    # Segments (if included)
    segments = route.get("segments")
    if segments:
        lines.append("-" * 60)
        lines.append("SEGMENTER")
        lines.append("-" * 60)
        for seg in segments:
            objid = seg.get("objid", "N/A")
            length_m = seg.get("length_meters")
            length_str = f"{length_m:.1f} m" if length_m is not None else "N/A"
            routes = seg.get("routes", [])
            rutenummer_str = ", ".join([r.get("rutenummer", "") for r in routes if isinstance(r, dict)])
            lines.append(f"  objid {objid}: {length_str} ({rutenummer_str})")
        lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)


def format_complete_route_csv(route: Dict[str, Any]) -> str:
    """
    Format a complete route as CSV.

    Args:
        route: Complete route dictionary

    Returns:
        CSV string
    """
    output = StringIO()
    fieldnames = [
        "rutenummer", "rutenavn", "vedlikeholdsansvarlig",
        "total_length_km", "total_length_meters",
        "segment_count", "component_count", "is_connected",
        "from_name", "from_source", "from_distance_meters", "from_tilrettelegging",
        "to_name", "to_source", "to_distance_meters", "to_tilrettelegging"
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()

    from_name = route.get("from_name")
    to_name = route.get("to_name")

    row = {
        "rutenummer": route.get("rutenummer"),
        "rutenavn": route.get("rutenavn"),
        "vedlikeholdsansvarlig": route.get("vedlikeholdsansvarlig"),
        "total_length_km": route.get("total_length_km"),
        "total_length_meters": route.get("total_length_meters"),
        "segment_count": route.get("segment_count"),
        "component_count": route.get("component_count"),
        "is_connected": route.get("is_connected"),
        "from_name": from_name.get("name") if from_name else None,
        "from_source": from_name.get("source") if from_name else None,
        "from_distance_meters": from_name.get("distance_meters") if from_name else None,
        "from_tilrettelegging": from_name.get("tilrettelegging") if from_name else None,
        "to_name": to_name.get("name") if to_name else None,
        "to_source": to_name.get("source") if to_name else None,
        "to_distance_meters": to_name.get("distance_meters") if to_name else None,
        "to_tilrettelegging": to_name.get("tilrettelegging") if to_name else None,
    }
    writer.writerow(row)

    return output.getvalue()


def format_routes_table(routes: List[Dict[str, Any]], show_geometry: bool = False) -> str:
    """
    Format routes as a human-readable table.

    Args:
        routes: List of route dictionaries
        show_geometry: Whether to include geometry info in table

    Returns:
        Formatted table string
    """
    if not routes:
        return "No routes found."

    lines = []

    # Calculate column widths
    col_widths = {
        "rutenummer": max(len("rutenummer"), max(len(str(r.get("rutenummer", ""))) for r in routes)),
        "rutenavn": max(len("rutenavn"), max(len(str(r.get("rutenavn", "") or "")) for r in routes)),
        "from_name": max(len("from"), max(len(str(r.get("from_name", "") or "")) for r in routes)),
        "to_name": max(len("to"), max(len(str(r.get("to_name", "") or "")) for r in routes)),
        "vedlikeholdsansvarlig": max(len("vedlikeholdsansvarlig"), max(len(str(r.get("vedlikeholdsansvarlig", "") or "")) for r in routes)),
        "rutetype": max(len("rutetype"), max(len(str(r.get("rutetype", "") or "")) for r in routes)),
        "total_length_m": max(len("length (m)"), max(len(f"{r.get('total_length_m', 0):.1f}") if r.get('total_length_m') else len("N/A") for r in routes)),
        "segment_count": max(len("segments"), max(len(str(r.get("segment_count", 0))) for r in routes)),
    }

    # Ensure minimum widths
    for key in col_widths:
        col_widths[key] = max(col_widths[key], 8)

    # Build header
    header = (
        f"{'rutenummer':<{col_widths['rutenummer']}} | "
        f"{'rutenavn':<{col_widths['rutenavn']}} | "
        f"{'from':<{col_widths['from_name']}} | "
        f"{'to':<{col_widths['to_name']}} | "
        f"{'vedlikeholdsansvarlig':<{col_widths['vedlikeholdsansvarlig']}} | "
        f"{'rutetype':<{col_widths['rutetype']}} | "
        f"{'length (m)':>{col_widths['total_length_m']}} | "
        f"{'segments':>{col_widths['segment_count']}}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    # Build rows
    for route in routes:
        rutenummer = str(route.get("rutenummer", ""))
        rutenavn = str(route.get("rutenavn") or "")
        from_name = str(route.get("from_name") or "")
        to_name = str(route.get("to_name") or "")
        vedlikeholdsansvarlig = str(route.get("vedlikeholdsansvarlig") or "")
        rutetype = str(route.get("rutetype") or "")
        total_length_m = route.get("total_length_m")
        length_str = f"{total_length_m:.1f}" if total_length_m is not None else "N/A"
        segment_count = route.get("segment_count", 0)

        row = (
            f"{rutenummer:<{col_widths['rutenummer']}} | "
            f"{rutenavn:<{col_widths['rutenavn']}} | "
            f"{from_name:<{col_widths['from_name']}} | "
            f"{to_name:<{col_widths['to_name']}} | "
            f"{vedlikeholdsansvarlig:<{col_widths['vedlikeholdsansvarlig']}} | "
            f"{rutetype:<{col_widths['rutetype']}} | "
            f"{length_str:>{col_widths['total_length_m']}} | "
            f"{segment_count:>{col_widths['segment_count']}}"
        )
        lines.append(row)

    return "\n".join(lines)


def format_routes_csv(routes: List[Dict[str, Any]], include_geometry: bool = False) -> str:
    """
    Format routes as CSV.

    Args:
        routes: List of route dictionaries
        include_geometry: Whether to include geometry column

    Returns:
        CSV string
    """
    if not routes:
        return ""

    output = StringIO()
    fieldnames = ["rutenummer", "rutenavn", "from_name", "to_name", "vedlikeholdsansvarlig", "rutetype", "total_length_m", "segment_count"]
    if include_geometry:
        fieldnames.append("route_geometry")

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()

    for route in routes:
        row = {k: route.get(k) for k in fieldnames}
        if include_geometry and "route_geometry" in row and row["route_geometry"]:
            row["route_geometry"] = json.dumps(row["route_geometry"])
        writer.writerow(row)

    return output.getvalue()


def format_routes_summary(response: Dict[str, Any]) -> str:
    """
    Format summary information for routes response.

    Args:
        response: Response dictionary with routes, total, limit, offset

    Returns:
        Summary string
    """
    total = response.get("total", 0)
    limit = response.get("limit", 0)
    offset = response.get("offset", 0)
    routes = response.get("routes", [])
    count = len(routes)

    lines = []
    lines.append(f"Found {total} route(s) total")
    lines.append(f"Showing {count} route(s) (offset: {offset}, limit: {limit})")
    if count < total:
        lines.append(f"Use --offset and --limit for pagination")
    lines.append("")

    return "\n".join(lines)


def format_route_registry_yaml(routes_by_number: Dict[int, Dict[str, Any]], as_list: bool = False) -> str:
    """
    Format routes as YAML according to the route registry schema.

    Groups routes by number and handles variants (v for winter, a-z for alternatives).

    Args:
        routes_by_number: Dictionary mapping route number to route data.
                         Each route data dict should have:
                         - rutenummer: full rutenummer (e.g., "bre10", "bre10v")
                         - rutenavn: route name
                         - vedlikeholdsansvarlig: authority
                         - from_name: optional endpoint name dict
                         - to_name: optional endpoint name dict
                         - status: optional status (defaults to "active")
                         - authority: optional authority (defaults based on vedlikeholdsansvarlig)
        as_list: If True, output as YAML list. If False, output single entry (for one route number).

    Returns:
        YAML string formatted according to route.schema.json
    """
    from cli.find_available_numbers import parse_rutenummer

    # Convert to list of registry entries
    registry_entries = []

    for number, routes in sorted(routes_by_number.items()):
        # Find main route (no letter) or use first route as main
        main_route = None
        variants = {}

        for rutenummer, route_data in routes.items():
            parsed = parse_rutenummer(rutenummer)
            if not parsed:
                continue

            prefix, route_num, letter = parsed

            if letter is None:
                # This is the main route
                main_route = route_data
                main_route['rutenummer'] = rutenummer
            else:
                # This is a variant
                variants[letter] = route_data
                variants[letter]['rutenummer'] = rutenummer

        # If no main route found, use first route
        if main_route is None and routes:
            first_rutenummer = next(iter(routes.keys()))
            main_route = routes[first_rutenummer]
            main_route['rutenummer'] = first_rutenummer

        if main_route is None:
            continue

        # Build registry entry
        entry = {
            'number': number,
            'status': main_route.get('status', 'active'),
            'authority': main_route.get('authority', _map_authority(main_route.get('vedlikeholdsansvarlig'))),
        }

        # Add title if available
        rutenavn = main_route.get('rutenavn')
        if rutenavn and rutenavn != 'Ukjent':
            entry['title'] = rutenavn

        # Add endpoints if available
        from_name = main_route.get('from_name')
        to_name = main_route.get('to_name')
        if from_name or to_name:
            entry['endpoints'] = {}
            if from_name and from_name.get('name'):
                entry['endpoints']['a'] = from_name['name']
            if to_name and to_name.get('name'):
                entry['endpoints']['b'] = to_name['name']

        # Add variants if any
        if variants:
            entry['variants'] = {}
            for letter, variant_data in sorted(variants.items()):
                variant_entry = {
                    'status': variant_data.get('status', 'active'),
                }

                # Add variant-specific title if different from main
                variant_rutenavn = variant_data.get('rutenavn')
                if variant_rutenavn and variant_rutenavn != rutenavn and variant_rutenavn != 'Ukjent':
                    variant_entry['title'] = variant_rutenavn

                entry['variants'][letter] = variant_entry

        registry_entries.append(entry)

    # Format as YAML - output as list if as_list=True, otherwise single entry
    if as_list:
        return yaml.dump(registry_entries, allow_unicode=True, sort_keys=False, default_flow_style=False)
    else:
        # Single entry (for one route number)
        if len(registry_entries) == 1:
            return yaml.dump(registry_entries[0], allow_unicode=True, sort_keys=False, default_flow_style=False)
        else:
            # Multiple entries - output as list
            return yaml.dump(registry_entries, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _map_authority(vedlikeholdsansvarlig: Optional[str]) -> str:
    """
    Map vedlikeholdsansvarlig to authority enum value.

    Args:
        vedlikeholdsansvarlig: Organization name

    Returns:
        Authority enum value: "dnt", "turrutebasen", "legacy", or "import"
    """
    if not vedlikeholdsansvarlig:
        return "legacy"

    vedlikeholdsansvarlig_lower = vedlikeholdsansvarlig.lower()

    if 'dnt' in vedlikeholdsansvarlig_lower:
        return "dnt"
    elif 'turrutebasen' in vedlikeholdsansvarlig_lower:
        return "turrutebasen"
    else:
        return "legacy"


def build_changeset_report(validation_report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a changeset-style report from a validation report.

    The report suggests normalized values for inconsistent metadata fields,
    prioritizing non-"Ukjent" values.
    """
    rutenummer = validation_report.get("rutenummer")
    warnings = validation_report.get("warnings", [])
    segment_metadata = validation_report.get("segment_metadata", [])

    segment_length = {}
    segment_rows = {}
    segment_lokalid = {}
    for seg in segment_metadata:
        segment_objid = str(seg.get("segment_objid"))
        segment_length[segment_objid] = seg.get("length_meters") or 0.0
        segment_rows[segment_objid] = seg.get("fotruteinfo_rows", [])
        segment_lokalid[segment_objid] = seg.get("segment_lokalid")

    warning_type_to_field = {
        "INCONSISTENT_RUTENAVN": "rutenavn",
        "INCONSISTENT_VEDLIKEHOLDSANSVARLIG": "vedlikeholdsansvarlig",
        "INCONSISTENT_RUTETYPE": "rutetype",
        "INCONSISTENT_GRADERING": "gradering",
    }

    report_fields = []
    duplicate_rutenummer_fixes = []
    rutenavn_suggestions = []
    rutenavn_ukjent = []

    errors = validation_report.get("errors", [])
    warnings = validation_report.get("warnings", [])
    info_issues = validation_report.get("geometry_info", [])

    summary = validation_report.get("summary", {}) or {}
    rutenavn_values = summary.get("rutenavn_values") or []
    rutenavn_all_ukjent = (
        len(rutenavn_values) == 1 and str(rutenavn_values[0]).strip().lower() == "ukjent"
    )

    for warning in warnings:
        if warning.get("type") != "RUTENAVN_UKJENT":
            continue
        if not rutenavn_all_ukjent:
            continue
        affected_segments = warning.get("affected_segments") or []
        affected_lokalid = []
        for segment_objid in affected_segments:
            segment_objid_str = str(segment_objid)
            segment_id = segment_lokalid.get(segment_objid_str)
            if segment_id:
                affected_lokalid.append(segment_id)
            else:
                affected_lokalid.append(segment_objid_str)
        rutenavn_ukjent.append({
            "affected_segments": affected_lokalid,
        })
    for info in info_issues:
        if info.get("type") != "RUTENAVN_SUGGESTION":
            continue
        metadata = info.get("metadata", {}) or {}
        rutenavn_suggestions.append({
            "suggested_rutenavn": metadata.get("suggested_rutenavn"),
            "from_name": metadata.get("from_name"),
            "to_name": metadata.get("to_name"),
        })

    for err in errors:
        if err.get("type") != "DUPLICATE_RUTENUMMER_IN_SEGMENT":
            continue

        metadata = err.get("metadata", {}) or {}
        dup_rutenummer = metadata.get("rutenummer")
        affected_segments = err.get("affected_segments") or []

        for segment_objid in affected_segments:
            segment_objid_str = str(segment_objid)
            rows = segment_rows.get(segment_objid_str, [])
            if not rows or not dup_rutenummer:
                continue

            before_list = []
            after_list = []
            seen = set()
            removed_indices = []

            for idx, row in enumerate(rows):
                row_rutenummer = row.get("rutenummer")
                row_rutenavn = row.get("rutenavn")
                before_list.append({
                    "index": idx,
                    "rutenummer": row_rutenummer,
                    "rutenavn": row_rutenavn,
                })

                if row_rutenummer == dup_rutenummer:
                    if row_rutenummer in seen:
                        removed_indices.append(idx)
                        continue
                    seen.add(row_rutenummer)

                after_list.append({
                    "index": idx,
                    "rutenummer": row_rutenummer,
                    "rutenavn": row_rutenavn,
                })

            if removed_indices:
                duplicate_rutenummer_fixes.append({
                    "segment_lokalid": segment_lokalid.get(segment_objid_str),
                    "rutenummer": dup_rutenummer,
                    "removed_indices": removed_indices,
                    "before": before_list,
                    "after": after_list,
                })

    for warning in warnings:
        warning_type = warning.get("type")
        if warning_type not in warning_type_to_field:
            continue

        field = warning_type_to_field[warning_type]
        metadata = warning.get("metadata", {}) or {}
        values = metadata.get("values") or []
        value_by_segment = metadata.get("value_by_segment") or {}

        # Normalize segment IDs to strings
        normalized_value_by_segment = {}
        for val, segment_ids in value_by_segment.items():
            normalized_value_by_segment[val] = [str(sid) for sid in segment_ids]

        # Fallback: build value->segments map from segment metadata
        if not normalized_value_by_segment:
            fallback_map = {}
            for segment_objid, rows in segment_rows.items():
                for row in rows:
                    row_val = row.get(field)
                    if not row_val:
                        continue
                    if row_val not in fallback_map:
                        fallback_map[row_val] = []
                    if segment_objid not in fallback_map[row_val]:
                        fallback_map[row_val].append(segment_objid)
            normalized_value_by_segment = fallback_map

        # Build candidate list
        candidates = []
        for val in values or normalized_value_by_segment.keys():
            segment_ids = normalized_value_by_segment.get(val, [])
            count = len(segment_ids)
            length_sum = sum(segment_length.get(sid, 0.0) for sid in segment_ids)
            is_ukjent = str(val).strip().lower() == "ukjent"
            score = -1.0 if is_ukjent else (length_sum + (count * 0.001))
            candidates.append({
                "value": val,
                "segment_count": count,
                "length_meters": float(length_sum),
                "score": score,
            })

        if not candidates:
            continue

        # Sort candidates: highest score first, "Ukjent" always last
        candidates.sort(key=lambda c: (c["score"], c["segment_count"]), reverse=True)

        selected = candidates[0]
        selected_value = selected["value"]

        # Determine if confirmation is needed (close scores)
        needs_confirmation = False
        if len(candidates) > 1:
            first = candidates[0]["score"]
            second = candidates[1]["score"]
            if first <= 0:
                needs_confirmation = True
            else:
                # Within 10% is considered ambiguous
                needs_confirmation = (second / first) >= 0.9

        # Build update suggestions
        updates = []
        route_rutenummer = validation_report.get("rutenummer")
        for segment_objid, rows in segment_rows.items():
            before_list = []
            after_list = []
            changed = False
            for idx, row in enumerate(rows):
                row_rutenummer = row.get("rutenummer")
                row_value = row.get(field)
                before_list.append({
                    "index": idx,
                    "rutenummer": row_rutenummer,
                    field: row_value,
                })
                updated_value = row_value
                if row_rutenummer == route_rutenummer:
                    updated_value = selected_value
                if updated_value != row_value:
                    changed = True
                after_list.append({
                    "index": idx,
                    "rutenummer": row_rutenummer,
                    field: updated_value,
                })

            if changed:
                updates.append({
                    "segment_lokalid": segment_lokalid.get(segment_objid),
                    "before": before_list,
                    "after": after_list,
                })

        report_fields.append({
            "field": field,
            "selected_value": selected_value,
            "candidates": candidates,
            "updates": updates,
            "needs_confirmation": needs_confirmation,
            "warning_type": warning_type,
        })

    return {
        "rutenummer": rutenummer,
        "rutenavn_suggestions": rutenavn_suggestions,
        "rutenavn_ukjent": rutenavn_ukjent,
        "duplicate_rutenummer_fixes": duplicate_rutenummer_fixes,
        "fields": report_fields,
    }


def format_changeset_report(report: Dict[str, Any]) -> str:
    """Format changeset report as a human-readable text block."""
    rutenummer = report.get("rutenummer", "N/A")
    fields = report.get("fields", [])
    rutenavn_suggestions = report.get("rutenavn_suggestions", [])
    rutenavn_ukjent = report.get("rutenavn_ukjent", [])
    duplicate_fixes = report.get("duplicate_rutenummer_fixes", [])

    lines = []
    lines.append("=" * 80)
    lines.append(f"CHANGESET REPORT: {rutenummer}")
    lines.append("=" * 80)
    if rutenavn_suggestions:
        lines.append("RUTENAVN SUGGESTIONS:")
        lines.append("-" * 80)
        for suggestion in rutenavn_suggestions:
            suggested = suggestion.get("suggested_rutenavn")
            from_name = suggestion.get("from_name")
            to_name = suggestion.get("to_name")
            lines.append(f"Suggested: {suggested}")
            if from_name or to_name:
                lines.append(f"  from: {from_name or '(unknown)'}")
                lines.append(f"  to:   {to_name or '(unknown)'}")
        lines.append("")
    if rutenavn_ukjent:
        lines.append("RUTENAVN UKJENT:")
        lines.append("-" * 80)
        for entry in rutenavn_ukjent:
            segments = entry.get("affected_segments", [])
            lines.append(f"Affected segments: {segments}")
        lines.append("")
    if duplicate_fixes:
        lines.append("DUPLICATE RUTENUMMER FIXES:")
        lines.append("-" * 80)
        for fix in duplicate_fixes:
            segment_ref = fix.get("segment_lokalid") or "(missing lokalid)"
            dup_rutenummer = fix.get("rutenummer")
            removed_indices = fix.get("removed_indices", [])
            before_list = fix.get("before", [])
            after_list = fix.get("after", [])
            before_str = ", ".join(
                f"{item.get('index')}:{item.get('rutenummer')}={item.get('rutenavn')}" for item in before_list
            )
            after_str = ", ".join(
                f"{item.get('index')}:{item.get('rutenummer')}={item.get('rutenavn')}" for item in after_list
            )
            removed_str = ", ".join(str(idx) for idx in removed_indices)
            lines.append(f"Segment {segment_ref}: remove duplicate rutenummer \"{dup_rutenummer}\" at indices [{removed_str}]")
            lines.append(f"  before: [{before_str}]")
            lines.append(f"  after:  [{after_str}]")
        lines.append("")
    if not fields:
        lines.append("No changeset suggestions (no inconsistent metadata warnings).")
        lines.append("")
        return "\n".join(lines)

    for field_report in fields:
        field = field_report.get("field")
        selected_value = field_report.get("selected_value")
        candidates = field_report.get("candidates", [])
        updates = field_report.get("updates", [])
        needs_confirmation = field_report.get("needs_confirmation", False)
        warning_type = field_report.get("warning_type", "")

        lines.append(f"Field: {field} ({warning_type})")
        lines.append(f"Selected value: {selected_value}")
        lines.append(f"Needs confirmation: {'YES' if needs_confirmation else 'NO'}")
        lines.append("Candidates:")
        for cand in candidates:
            lines.append(
                f"  - {cand['value']} (segments: {cand['segment_count']}, length_m: {cand['length_meters']:.1f}, score: {cand['score']:.3f})"
            )
        lines.append("Suggested updates:")
        if updates:
            for upd in updates:
                segment_ref = upd.get("segment_lokalid") or "(missing lokalid)"
                before_list = upd.get("before", [])
                after_list = upd.get("after", [])
                before_str = ", ".join(
                    f"{item.get('index')}:{item.get('rutenummer')}={item.get(field)}" for item in before_list
                )
                after_str = ", ".join(
                    f"{item.get('index')}:{item.get('rutenummer')}={item.get(field)}" for item in after_list
                )
                lines.append(
                    f"  - segment {segment_ref}: [{before_str}] -> [{after_str}]"
                )
        else:
            lines.append("  (no updates)")
        lines.append("")

    return "\n".join(lines)

