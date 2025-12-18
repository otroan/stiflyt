"""Service for fetching owner information from Matrikkel API."""
import os
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
from dotenv import load_dotenv
from matrikkel.matrikkel_client import MatrikkelClient, MatrikkelConfig, MatrikkelIdent, OwnerInfo

# Load environment variables from .env file (if present)
# This ensures .env is loaded even if database.py hasn't been imported yet
load_dotenv()


def get_matrikkel_config() -> Optional[MatrikkelConfig]:
    """
    Get Matrikkel API configuration from environment variables.

    Returns:
        MatrikkelConfig if credentials are available, None otherwise
    """
    username = os.getenv('MATRIKKEL_USERNAME')
    password = os.getenv('MATRIKKEL_PASSWORD')

    if not username or not password:
        return None

    # Build config, using dataclass defaults if env vars are not set
    config_kwargs = {
        'username': username,
        'password': password,
    }

    # Only override base_url if explicitly set in environment
    base_url = os.getenv('MATRIKKEL_BASE_URL')
    if base_url:
        config_kwargs['base_url'] = base_url

    # Only override klient_identifikasjon if explicitly set in environment
    klient_identifikasjon = os.getenv('MATRIKKEL_KLIENT_IDENTIFIKASJON')
    if klient_identifikasjon:
        config_kwargs['klient_identifikasjon'] = klient_identifikasjon

    return MatrikkelConfig(**config_kwargs)


def parse_matrikkelenhet_string(matrikkel_str: str) -> Optional[MatrikkelIdent]:
    """
    Parse a formatted matrikkelenhet string into components.

    Formats supported:
    - "1234-56/78" -> kommune=1234, gardsnummer=56, bruksnummer=78
    - "1234-56/78/90" -> kommune=1234, gardsnummer=56, bruksnummer=78, festenummer=90
    - "1234-Umatrikulert" -> returns None (cannot be queried)

    Args:
        matrikkel_str: Formatted matrikkelenhet string

    Returns:
        MatrikkelIdent object or None if parsing fails or is umatrikulert
    """
    if not matrikkel_str or 'Umatrikulert' in matrikkel_str:
        return None

    try:
        # Split on '-' to separate kommune from rest
        parts = matrikkel_str.split('-', 1)
        if len(parts) != 2:
            return None

        kommune = int(parts[0])
        rest = parts[1]

        # Split on '/' to get gardsnummer, bruksnummer, festenummer
        numbers = rest.split('/')
        if len(numbers) < 2:
            return None

        gardsnummer = int(numbers[0])
        bruksnummer = int(numbers[1])
        festenummer = int(numbers[2]) if len(numbers) > 2 and numbers[2] else None

        return MatrikkelIdent(
            kommune=kommune,
            gardsnummer=gardsnummer,
            bruksnummer=bruksnummer,
            festenummer=festenummer
        )
    except (ValueError, IndexError):
        return None


def format_owner_info(owners: List[OwnerInfo]) -> str:
    """
    Format owner information as a string for Excel display.

    Args:
        owners: List of OwnerInfo objects

    Returns:
        Formatted string with owner names and addresses
    """
    if not owners:
        return ""

    owner_strings = []
    for owner in owners:
        parts = []
        if owner.navn:
            parts.append(owner.navn)
        if owner.adresse:
            parts.append(owner.adresse)
        if parts:
            owner_strings.append(", ".join(parts))

    return "; ".join(owner_strings) if owner_strings else ""


def analyze_owner_fetch_errors(owner_results: List[Tuple[Dict, Optional[str], Optional[Exception]]]) -> Dict[str, Any]:
    """
    Analyze errors from fetch_owners_for_matrikkelenheter results.

    Args:
        owner_results: List of tuples from fetch_owners_for_matrikkelenheter

    Returns:
        dict with:
            - has_errors: bool - True if any errors found
            - error_count: int - Number of items with errors
            - total_count: int - Total number of items
            - error_summary: str - Human-readable error summary
            - error_details: List[str] - List of error messages (first 10)
    """
    total_count = len(owner_results)
    errors = []
    error_items = []

    for item, owner_info, error in owner_results:
        if error is not None:
            matrikkel_str = item.get('matrikkelenhet', 'Ukjent matrikkelenhet')
            error_msg = str(error)
            errors.append(f"{matrikkel_str}: {error_msg}")
            error_items.append({
                'matrikkelenhet': matrikkel_str,
                'error': error_msg
            })

    error_count = len(errors)
    has_errors = error_count > 0

    # Create summary message
    if has_errors:
        if error_count == total_count:
            error_summary = f"Kunne ikke hente eierinformasjon for noen av {total_count} eiendommer."
        else:
            error_summary = f"Kunne ikke hente eierinformasjon for {error_count} av {total_count} eiendommer."

        # Add details (limit to first 10 to avoid overwhelming the user)
        if error_count <= 10:
            error_summary += f" Detaljer: {'; '.join(errors)}"
        else:
            error_summary += f" Første 10 feil: {'; '.join(errors[:10])} (og {error_count - 10} flere)"
    else:
        error_summary = None

    return {
        'has_errors': has_errors,
        'error_count': error_count,
        'total_count': total_count,
        'error_summary': error_summary,
        'error_details': errors[:10]  # Limit to first 10 for display
    }


def fetch_owners_for_matrikkelenheter(
    matrikkelenhet_items: List[Dict],
    config: Optional[MatrikkelConfig] = None
) -> List[Tuple[Dict, Optional[str], Optional[Exception]]]:
    """
    Fetch owner information for a list of matrikkelenhet items.

    This function:
    1. Extracts matrikkelenhet identifiers from items (either from fields or parsed from string)
    2. Uses MatrikkelClient to find matrikkelenhet IDs
    3. Fetches owner information for each matrikkelenhet
    4. Returns formatted owner information

    Args:
        matrikkelenhet_items: List of dicts with matrikkelenhet data. Each dict should have:
            - Either: 'kommunenummer', 'gardsnummer', 'bruksnummer', 'festenummer' fields
            - Or: 'matrikkelenhet' field with formatted string
        config: Optional MatrikkelConfig. If None, will try to get from environment.

    Returns:
        List of tuples: (original_item, formatted_owner_info or None, Exception or None)
        Each tuple represents the result for one matrikkelenhet item.
        If successful, formatted_owner_info contains the owner information string.
        If failed, formatted_owner_info is None and Exception contains the error.
    """
    if not matrikkelenhet_items:
        return []

    # Get config
    if config is None:
        config = get_matrikkel_config()

    if config is None:
        # No credentials available - return empty owner info for all items
        return [(item, None, None) for item in matrikkelenhet_items]

    results = []

    try:
        with MatrikkelClient(config) as client:
            # Step 1: Convert items to MatrikkelIdent objects and deduplicate
            # Use a dict to track unique matrikkelenheter and all items that map to each
            unique_idents: Dict[tuple, MatrikkelIdent] = {}  # Key: (kommune, gnr, bnr, feste)
            ident_to_items: Dict[tuple, List[Dict]] = defaultdict(list)  # Map ident key to all items with that ident
            items_without_ident: List[Dict] = []  # Items that couldn't be parsed

            for item in matrikkelenhet_items:
                # Try to get from fields first (preferred - more reliable)
                if all(key in item for key in ['kommunenummer', 'gardsnummer', 'bruksnummer']):
                    ident = MatrikkelIdent(
                        kommune=item['kommunenummer'],
                        gardsnummer=item.get('gardsnummer', 0),
                        bruksnummer=item.get('bruksnummer', 0),
                        festenummer=item.get('festenummer')
                    )
                # Fallback: parse from formatted string
                elif 'matrikkelenhet' in item:
                    ident = parse_matrikkelenhet_string(item['matrikkelenhet'])
                else:
                    ident = None

                if ident:
                    # Create a unique key for this matrikkelenhet
                    ident_key = (
                        ident.kommune,
                        ident.gardsnummer,
                        ident.bruksnummer,
                        ident.festenummer if ident.festenummer is not None else 0
                    )
                    # Store unique ident (first occurrence)
                    if ident_key not in unique_idents:
                        unique_idents[ident_key] = ident
                    # Map this item to the ident key
                    ident_to_items[ident_key].append(item)
                else:
                    # Item couldn't be parsed - will get None result
                    items_without_ident.append(item)

            if not unique_idents:
                # No valid identifiers found
                return [(item, None, None) for item in matrikkelenhet_items]

            # Step 2: Find matrikkelenhet IDs in batch (only for unique idents)
            unique_ident_list = list(unique_idents.values())
            matrikkelenhet_id_results = client.find_matrikkelenhet_ids_batch(unique_ident_list)

            # Step 3: Map results back to ident keys and get owner information
            ident_key_to_matrikkelenhet_id: Dict[tuple, Any] = {}
            ident_key_to_error: Dict[tuple, Exception] = {}

            for ident, matrikkelenhet_id, error in matrikkelenhet_id_results:
                # Find which ident_key this ident corresponds to
                ident_key = (
                    ident.kommune,
                    ident.gardsnummer,
                    ident.bruksnummer,
                    ident.festenummer if ident.festenummer is not None else 0
                )
                if matrikkelenhet_id and error is None:
                    ident_key_to_matrikkelenhet_id[ident_key] = matrikkelenhet_id
                else:
                    ident_key_to_error[ident_key] = error

            # Step 4: Get owners in batch (only for unique matrikkelenhet IDs)
            unique_matrikkelenhet_ids = list(ident_key_to_matrikkelenhet_id.values())
            owner_results = client.get_owners_batch(unique_matrikkelenhet_ids)

            # Step 5: Map owner results back to ident keys
            matrikkelenhet_id_to_owners: Dict[Any, List[OwnerInfo]] = {}
            matrikkelenhet_id_to_error: Dict[Any, Exception] = {}

            for matrikkelenhet_id, owners, error in owner_results:
                if owners is not None and error is None:
                    matrikkelenhet_id_to_owners[matrikkelenhet_id] = owners
                else:
                    matrikkelenhet_id_to_error[matrikkelenhet_id] = error

            # Step 6: Map results back to all original items
            # For each unique ident_key, get the owner info and apply to all items with that key
            for ident_key, items in ident_to_items.items():
                if ident_key in ident_key_to_error:
                    # Error finding matrikkelenhet ID
                    error = ident_key_to_error[ident_key]
                    for item in items:
                        results.append((item, None, error))
                elif ident_key in ident_key_to_matrikkelenhet_id:
                    matrikkelenhet_id = ident_key_to_matrikkelenhet_id[ident_key]
                    if matrikkelenhet_id in matrikkelenhet_id_to_error:
                        # Error getting owners
                        error = matrikkelenhet_id_to_error[matrikkelenhet_id]
                        for item in items:
                            results.append((item, None, error))
                    elif matrikkelenhet_id in matrikkelenhet_id_to_owners:
                        # Success - format owners and apply to all items with this ident
                        owners = matrikkelenhet_id_to_owners[matrikkelenhet_id]
                        formatted_owners = format_owner_info(owners)
                        for item in items:
                            results.append((item, formatted_owners, None))
                    else:
                        # No owners found
                        for item in items:
                            results.append((item, None, None))
                else:
                    # Should not happen, but handle gracefully
                    for item in items:
                        results.append((item, None, None))

            # Handle items that couldn't be parsed
            for item in items_without_ident:
                results.append((item, None, None))

    except Exception as e:
        # If there's a general error (e.g., connection issue), return error for all items
        return [(item, None, e) for item in matrikkelenhet_items]

    return results
