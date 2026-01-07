"""Find available route numbers for a given prefix."""
import re
from typing import Dict, Set, List, Tuple, Optional
from services.database import db_connection, get_route_schema, quote_identifier
from psycopg.rows import dict_row


def parse_rutenummer(rutenummer: str) -> Optional[Tuple[str, int, Optional[str]]]:
    """
    Parse rutenummer into prefix, number, and optional letter.

    Format: 3-letter prefix + number + optional letter (e.g., "bre26a")

    Args:
        rutenummer: Route number string (e.g., "bre26", "bre26a")

    Returns:
        Tuple of (prefix, number, letter) or None if invalid format
    """
    # Pattern: 3 lowercase letters + digits + optional lowercase letter
    pattern = r'^([a-z]{3})(\d+)([a-z]?)$'
    match = re.match(pattern, rutenummer.lower())

    if not match:
        return None

    prefix = match.group(1)
    number = int(match.group(2))
    letter = match.group(3) if match.group(3) else None

    return (prefix, number, letter)


def get_existing_rutenummer(prefix: str) -> List[str]:
    """
    Get all existing rutenummer with the given prefix from database.

    Args:
        prefix: 3-letter prefix (e.g., "bre")

    Returns:
        List of rutenummer strings
    """
    with db_connection() as conn:
        route_schema = get_route_schema(conn)
        schema_quoted = quote_identifier(route_schema)

        query = f"""
            SELECT DISTINCT rutenummer
            FROM {schema_quoted}.fotruteinfo
            WHERE LOWER(rutenummer) LIKE LOWER(%s)
            ORDER BY rutenummer
        """

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (f"{prefix}%",))
            rows = cur.fetchall()
            return [row["rutenummer"] for row in rows]


def analyze_available_numbers(prefix: str) -> Dict:
    """
    Analyze available route numbers for a given prefix.

    Note: Ignores optional letters (e.g., "bre10v" is treated as "bre10")
    since letters have different meanings (vinterrute, alternative veier, etc.)

    Args:
        prefix: 3-letter prefix (e.g., "bre")

    Returns:
        Dictionary with:
        - existing: sorted list of existing numbers
        - gaps: list of missing numbers in sequence
        - next_available: next available number
        - suggestions: list of suggested available numbers (gaps first)
    """
    # Get all existing rutenummer
    existing_rutenummer = get_existing_rutenummer(prefix)

    # Parse and organize by number (ignore letters)
    existing_numbers: Set[int] = set()
    max_number = 0

    for rutenummer in existing_rutenummer:
        parsed = parse_rutenummer(rutenummer)
        if not parsed:
            continue

        parsed_prefix, number, letter = parsed

        # Only process if prefix matches
        if parsed_prefix != prefix.lower():
            continue

        # Add number to set (ignore letter)
        existing_numbers.add(number)
        max_number = max(max_number, number)

    # Find gaps in sequence
    gaps = []
    if existing_numbers:
        min_number = min(existing_numbers)
        for num in range(min_number, max_number + 1):
            if num not in existing_numbers:
                gaps.append(num)
    else:
        # No existing numbers, suggest starting from 1
        gaps = []

    # Find next available number
    next_available = None
    if gaps:
        next_available = min(gaps)
    elif existing_numbers:
        # Check if max_number + 1 is available
        if max_number + 1 not in existing_numbers:
            next_available = max_number + 1
    else:
        # No existing numbers
        next_available = 1

    # Generate suggestions (only numbers, no letters)
    suggestions = []

    # Add gaps (up to 10)
    for gap in sorted(gaps)[:10]:
        suggestions.append(f"{prefix}{gap}")

    # If we have less than 10 suggestions and next_available is beyond max, add it
    if len(suggestions) < 10 and next_available and next_available > max_number:
        if next_available not in [int(s[len(prefix):]) for s in suggestions]:
            suggestions.append(f"{prefix}{next_available}")

    return {
        "prefix": prefix,
        "existing": sorted(existing_numbers),
        "gaps": sorted(gaps),
        "next_available": next_available,
        "suggestions": suggestions[:10]  # Limit to 10 suggestions
    }


def format_available_numbers(result: Dict) -> str:
    """
    Format available numbers analysis as human-readable text.

    Args:
        result: Result dictionary from analyze_available_numbers

    Returns:
        Formatted string
    """
    lines = []
    lines.append(f"Analyse av ledige løpenummer for prefiks: {result['prefix']}")
    lines.append("=" * 70)
    lines.append("")

    # Existing numbers summary
    existing = result['existing']
    if existing:
        lines.append(f"Eksisterende løpenummer: {len(existing)}")
        # Show range
        min_num = min(existing)
        max_num = max(existing)
        lines.append(f"  Range: {min_num} - {max_num}")
        lines.append("")
    else:
        lines.append("Ingen eksisterende løpenummer funnet.")
        lines.append("")

    # Gaps
    gaps = result['gaps']
    if gaps:
        lines.append(f"Hull i sekvensen ({len(gaps)}):")
        # Show gaps in groups if many
        if len(gaps) <= 20:
            lines.append(f"  {', '.join(map(str, gaps))}")
        else:
            # Show first 10 and last 10
            lines.append(f"  {', '.join(map(str, gaps[:10]))} ... {', '.join(map(str, gaps[-10:]))}")
            lines.append(f"  (Totalt {len(gaps)} hull)")
        lines.append("")
    else:
        lines.append("Ingen hull i sekvensen.")
        lines.append("")

    # Next available
    next_available = result['next_available']
    if next_available:
        lines.append(f"Neste ledige løpenummer (uten bokstav): {result['prefix']}{next_available}")
        lines.append("")

    # Suggestions
    suggestions = result['suggestions']
    if suggestions:
        lines.append("Foreslåtte ledige rutenummer:")
        for i, suggestion in enumerate(suggestions, 1):
            lines.append(f"  {i}. {suggestion}")
        lines.append("")

    return "\n".join(lines)

