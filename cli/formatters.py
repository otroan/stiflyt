"""Output formatters for CLI."""
import json
import csv
import yaml
from typing import List, Dict, Any, Optional
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

