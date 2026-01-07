"""Output formatters for CLI."""
import json
import csv
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
        """Format routes list as comma-separated string."""
        if not routes_list:
            return ""
        route_strs = [r.get("rutenummer", "") if isinstance(r, dict) else str(r) for r in routes_list]
        return ", ".join(route_strs)

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
        vedlikeholdsansvarlig_str = get_vedlikeholdsansvarlig_str(routes)
        length_meters = segment.get("length_meters")
        length_str = f"{length_meters:.1f}" if length_meters is not None else "N/A"

        row = (
            f"{objid:<{col_widths['objid']}} | "
            f"{rutenummer_str:<{col_widths['rutenummer']}} | "
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

