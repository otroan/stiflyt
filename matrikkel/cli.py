#!/usr/bin/env python3
"""Production CLI tool for looking up matrikkelenhet and owner information.

This CLI tool provides a command-line interface to the Matrikkel API,
allowing users to query matrikkelenheter and retrieve owner information.
"""

import argparse
import sys
import json
import csv
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from matrikkel.matrikkel_client import (
    MatrikkelClient,
    MatrikkelConfig,
    MatrikkelIdent,
    OwnerInfo
)
from services.matrikkel_owner_service import (
    parse_matrikkelenhet_string,
    get_matrikkel_config
)


def serialize_zeep_object(obj: Any, max_depth: int = 3, current_depth: int = 0) -> Any:
    """Recursively serialize a zeep object to show all its data.

    Args:
        obj: The object to serialize
        max_depth: Maximum recursion depth
        current_depth: Current recursion depth

    Returns:
        Serialized representation (dict, list, or primitive)
    """
    if current_depth >= max_depth:
        return str(obj)

    if obj is None:
        return None

    # Handle primitives
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # Handle lists and tuples
    if isinstance(obj, (list, tuple)):
        return [serialize_zeep_object(item, max_depth, current_depth + 1) for item in obj]

    # Handle zeep objects and other complex objects
    if hasattr(obj, '__dict__') or hasattr(obj, '__class__'):
        result = {}

        # Try to get all attributes
        for attr in dir(obj):
            if attr.startswith('_'):
                continue

            try:
                value = getattr(obj, attr)
                if callable(value):
                    continue

                # Recursively serialize
                result[attr] = serialize_zeep_object(value, max_depth, current_depth + 1)
            except Exception:
                # Skip attributes that can't be accessed
                continue

        # Also try to access as dict if it's a zeep object
        try:
            if hasattr(obj, '__dict__'):
                for key, value in obj.__dict__.items():
                    if not key.startswith('_'):
                        result[key] = serialize_zeep_object(value, max_depth, current_depth + 1)
        except Exception:
            pass

        return result

    # Fallback to string representation
    return str(obj)


def extract_matrikkelenhet_data(matrikkelenhet_obj: Any) -> Dict[str, Any]:
    """Extract all available data from a Matrikkelenhet object.

    Args:
        matrikkelenhet_obj: The Matrikkelenhet object from the API

    Returns:
        Dictionary with all available fields from the object
    """
    data = {}

    if not matrikkelenhet_obj:
        return data

    # Common attributes to check
    attributes_to_check = [
        'id', 'kommune', 'gardsnummer', 'bruksnummer', 'festenummer', 'seksjonsnummer',
        'bruksnavn', 'matrikkelnummertekst', 'arealmerknadtekst', 'lagretberegnetareal',
        'geometri', 'koordinater', 'eierforhold', 'status', 'oppdatert', 'opprettet'
    ]

    # Try to extract all attributes
    for attr in dir(matrikkelenhet_obj):
        if attr.startswith('_'):
            continue

        try:
            value = getattr(matrikkelenhet_obj, attr)
            if not callable(value):
                # Try to serialize the value
                if hasattr(value, '__dict__'):
                    # Complex object - try to convert to dict
                    try:
                        value = {k: v for k, v in value.__dict__.items() if not k.startswith('_')}
                    except:
                        value = str(value)
                elif isinstance(value, (list, tuple)):
                    # List - try to serialize items
                    try:
                        value = [str(item) for item in value]
                    except:
                        value = str(value)

                data[attr] = value
        except Exception:
            # Skip attributes that can't be accessed
            continue

    return data


def format_matrikkelenhet_string(ident: MatrikkelIdent) -> str:
    """Format MatrikkelIdent as a string.

    Args:
        ident: MatrikkelIdent object

    Returns:
        Formatted string like "1234-56/78" or "1234-56/78/90"
    """
    parts = [f"{ident.kommune}-{ident.gardsnummer}/{ident.bruksnummer}"]
    if ident.festenummer:
        parts.append(str(ident.festenummer))
    if ident.seksjonsnummer:
        parts.append(str(ident.seksjonsnummer))
    return "/".join(parts) if len(parts) > 1 else parts[0]


def lookup_matrikkelenhet(
    ident: MatrikkelIdent,
    config: MatrikkelConfig,
    verbose: bool = False,
    debug: bool = False,
    raw: bool = False,
    include_historical: bool = False
) -> Dict[str, Any]:
    """Look up a matrikkelenhet and get owner information.

    Args:
        ident: MatrikkelIdent object
        config: MatrikkelConfig with API credentials
        verbose: If True, include all available data from Matrikkelenhet object
        debug: If True, enable debug output
        raw: If True, include raw API objects (Matrikkelenhet, eierforhold, Person)

    Returns:
        Dictionary with lookup results
    """
    result = {
        'matrikkelenhet': format_matrikkelenhet_string(ident),
        'ident': {
            'kommune': ident.kommune,
            'gardsnummer': ident.gardsnummer,
            'bruksnummer': ident.bruksnummer,
            'festenummer': ident.festenummer,
            'seksjonsnummer': ident.seksjonsnummer
        },
        'matrikkelenhet_id': None,
        'owners': [],
        'error': None,
        'verbose_data': {} if verbose else None,
        'raw_data': {} if raw else None
    }

    try:
        with MatrikkelClient(config) as client:
            # Find matrikkelenhet ID
            matrikkelenhet_id, _ = client.find_matrikkelenhet_id(ident)
            matrikkel_id_value = client._extract_id_value(matrikkelenhet_id)
            result['matrikkelenhet_id'] = matrikkel_id_value

            store_client = client._get_store_client()
            matrikkelenhet_client = client._get_matrikkelenhet_client()

            MatrikkelenhetId = matrikkelenhet_client.get_type("ns1:MatrikkelenhetId")
            try:
                matrikkel_id_obj = MatrikkelenhetId(id=int(matrikkel_id_value), objectType='Matrikkelenhet')
            except (TypeError, AttributeError):
                try:
                    matrikkel_id_obj = MatrikkelenhetId(value=int(matrikkel_id_value))
                except (TypeError, AttributeError):
                    matrikkel_id_obj = MatrikkelenhetId(int(matrikkel_id_value))

            ctx = client._create_matrikkel_context(store_client)
            matrikkelenhet_obj = store_client.service.getObject(matrikkel_id_obj, ctx)

            # If raw mode, capture raw objects
            if raw:
                raw_data = {
                    'matrikkelenhet_raw': serialize_zeep_object(matrikkelenhet_obj, max_depth=5),
                    'eierforhold_raw': [],
                    'person_raw': []
                }

                # Extract eierforhold (owner relationships) - raw
                eierforhold_list = None
                if hasattr(matrikkelenhet_obj, 'eierforhold'):
                    eierforhold_list = matrikkelenhet_obj.eierforhold
                elif hasattr(matrikkelenhet_obj, 'getEierforhold'):
                    eierforhold_list = matrikkelenhet_obj.getEierforhold()

                if eierforhold_list:
                    items = client._extract_list_items(eierforhold_list)
                    for eierforhold in items:
                        # Serialize eierforhold
                        raw_data['eierforhold_raw'].append(serialize_zeep_object(eierforhold, max_depth=5))

                        # Get eierId and fetch Person object
                        eier_id = None
                        if hasattr(eierforhold, 'eierId'):
                            eier_id = eierforhold.eierId
                        elif hasattr(eierforhold, 'getEierId'):
                            eier_id = eierforhold.getEierId()

                        if eier_id:
                            try:
                                person = store_client.service.getObject(eier_id, ctx)
                                raw_data['person_raw'].append(serialize_zeep_object(person, max_depth=5))
                            except Exception as e:
                                raw_data['person_raw'].append({
                                    'error': str(e),
                                    'eierId': serialize_zeep_object(eier_id, max_depth=3)
                                })

                result['raw_data'] = raw_data

            # Get owner information (processed)
            owners = client.get_owner_information(matrikkelenhet_id, debug=debug, include_historical=include_historical)
            result['owners'] = [
                {
                    'navn': owner.navn,
                    'adresse': owner.adresse,
                    'eierId': owner.eierId,
                    'fraDato': owner.fraDato,
                    'tilDato': owner.tilDato,
                    'andel': owner.andel,
                    'eierforhold_type': owner.eierforhold_type,
                    'is_current': owner.tilDato is None  # Current owner if tilDato is None
                }
                for owner in owners
            ]

            # If verbose, get full Matrikkelenhet object
            if verbose:
                result['verbose_data'] = extract_matrikkelenhet_data(matrikkelenhet_obj)

    except Exception as e:
        result['error'] = str(e)
        if debug:
            import traceback
            traceback.print_exc()

    return result


def batch_lookup(
    idents: List[MatrikkelIdent],
    config: MatrikkelConfig,
    verbose: bool = False,
    debug: bool = False,
    continue_on_error: bool = True,
    raw: bool = False,
    include_historical: bool = False
) -> List[Dict[str, Any]]:
    """Look up multiple matrikkelenheter in batch.

    Args:
        idents: List of MatrikkelIdent objects
        config: MatrikkelConfig with API credentials
        verbose: If True, include all available data
        debug: If True, enable debug output
        continue_on_error: If True, continue processing on errors
        raw: If True, include raw API objects

    Returns:
        List of result dictionaries
    """
    results = []

    try:
        with MatrikkelClient(config) as client:
            # Find matrikkelenhet IDs in batch
            matrikkelenhet_id_results = client.find_matrikkelenhet_ids_batch(idents)

            # Map results to idents
            ident_to_matrikkelenhet_id = {}
            ident_to_error = {}

            for ident, matrikkelenhet_id, error in matrikkelenhet_id_results:
                if matrikkelenhet_id and error is None:
                    ident_to_matrikkelenhet_id[ident] = matrikkelenhet_id
                else:
                    ident_to_error[ident] = error

            # Get owners in batch
            unique_matrikkelenhet_ids = list(ident_to_matrikkelenhet_id.values())
            owner_results = client.get_owners_batch(unique_matrikkelenhet_ids, debug=debug, include_historical=include_historical)

            # Map owner results back to matrikkelenhet IDs
            matrikkelenhet_id_to_owners = {}
            matrikkelenhet_id_to_error = {}

            for matrikkelenhet_id, owners, error in owner_results:
                if owners is not None and error is None:
                    matrikkelenhet_id_to_owners[matrikkelenhet_id] = owners
                else:
                    matrikkelenhet_id_to_error[matrikkelenhet_id] = error

            # Build results for each ident
            for ident in idents:
                result = {
                    'matrikkelenhet': format_matrikkelenhet_string(ident),
                    'ident': {
                        'kommune': ident.kommune,
                        'gardsnummer': ident.gardsnummer,
                        'bruksnummer': ident.bruksnummer,
                        'festenummer': ident.festenummer,
                        'seksjonsnummer': ident.seksjonsnummer
                    },
                    'matrikkelenhet_id': None,
                    'owners': [],
                    'error': None,
                    'verbose_data': {} if verbose else None,
                    'raw_data': {} if raw else None
                }

                if ident in ident_to_error:
                    result['error'] = str(ident_to_error[ident])
                elif ident in ident_to_matrikkelenhet_id:
                    matrikkelenhet_id = ident_to_matrikkelenhet_id[ident]
                    matrikkel_id_value = client._extract_id_value(matrikkelenhet_id)
                    result['matrikkelenhet_id'] = matrikkel_id_value

                    if matrikkelenhet_id in matrikkelenhet_id_to_error:
                        result['error'] = str(matrikkelenhet_id_to_error[matrikkelenhet_id])
                    elif matrikkelenhet_id in matrikkelenhet_id_to_owners:
                        owners = matrikkelenhet_id_to_owners[matrikkelenhet_id]
                        result['owners'] = [
                            {
                                'navn': owner.navn,
                                'adresse': owner.adresse,
                                'eierId': owner.eierId,
                                'fraDato': owner.fraDato,
                                'tilDato': owner.tilDato,
                                'andel': owner.andel,
                                'eierforhold_type': owner.eierforhold_type,
                                'is_current': owner.tilDato is None  # Current owner if tilDato is None
                            }
                            for owner in owners
                        ]

                        # If verbose or raw, get full object (this requires individual calls)
                        if verbose or raw:
                            try:
                                store_client = client._get_store_client()
                                matrikkelenhet_client = client._get_matrikkelenhet_client()

                                MatrikkelenhetId = matrikkelenhet_client.get_type("ns1:MatrikkelenhetId")
                                try:
                                    matrikkel_id_obj = MatrikkelenhetId(id=int(matrikkel_id_value), objectType='Matrikkelenhet')
                                except (TypeError, AttributeError):
                                    try:
                                        matrikkel_id_obj = MatrikkelenhetId(value=int(matrikkel_id_value))
                                    except (TypeError, AttributeError):
                                        matrikkel_id_obj = MatrikkelenhetId(int(matrikkel_id_value))

                                ctx = client._create_matrikkel_context(store_client)
                                matrikkelenhet_obj = store_client.service.getObject(matrikkel_id_obj, ctx)

                                if verbose:
                                    result['verbose_data'] = extract_matrikkelenhet_data(matrikkelenhet_obj)

                                if raw:
                                    raw_data = {
                                        'matrikkelenhet_raw': serialize_zeep_object(matrikkelenhet_obj, max_depth=5),
                                        'eierforhold_raw': [],
                                        'person_raw': []
                                    }

                                    # Extract eierforhold (owner relationships) - raw
                                    eierforhold_list = None
                                    if hasattr(matrikkelenhet_obj, 'eierforhold'):
                                        eierforhold_list = matrikkelenhet_obj.eierforhold
                                    elif hasattr(matrikkelenhet_obj, 'getEierforhold'):
                                        eierforhold_list = matrikkelenhet_obj.getEierforhold()

                                    if eierforhold_list:
                                        items = client._extract_list_items(eierforhold_list)
                                        for eierforhold in items:
                                            # Serialize eierforhold
                                            raw_data['eierforhold_raw'].append(serialize_zeep_object(eierforhold, max_depth=5))

                                            # Get eierId and fetch Person object
                                            eier_id = None
                                            if hasattr(eierforhold, 'eierId'):
                                                eier_id = eierforhold.eierId
                                            elif hasattr(eierforhold, 'getEierId'):
                                                eier_id = eierforhold.getEierId()

                                            if eier_id:
                                                try:
                                                    person = store_client.service.getObject(eier_id, ctx)
                                                    raw_data['person_raw'].append(serialize_zeep_object(person, max_depth=5))
                                                except Exception as e:
                                                    raw_data['person_raw'].append({
                                                        'error': str(e),
                                                        'eierId': serialize_zeep_object(eier_id, max_depth=3)
                                                    })

                                    result['raw_data'] = raw_data
                            except Exception as e:
                                if debug:
                                    print(f"Warning: Could not get verbose/raw data for {result['matrikkelenhet']}: {e}")

                results.append(result)

    except Exception as e:
        # If there's a general error, create error results for all idents
        for ident in idents:
            results.append({
                'matrikkelenhet': format_matrikkelenhet_string(ident),
                'ident': {
                    'kommune': ident.kommune,
                    'gardsnummer': ident.gardsnummer,
                    'bruksnummer': ident.bruksnummer,
                    'festenummer': ident.festenummer,
                    'seksjonsnummer': ident.seksjonsnummer
                },
                'matrikkelenhet_id': None,
                'owners': [],
                'error': str(e),
                'verbose_data': {} if verbose else None,
                'raw_data': {} if raw else None
            })
        if debug:
            import traceback
            traceback.print_exc()

    return results


def format_output_text(result: Dict[str, Any], verbose: bool = False, raw: bool = False) -> str:
    """Format result as human-readable text.

    Args:
        result: Result dictionary from lookup
        verbose: If True, include verbose data
        raw: If True, include raw API data

    Returns:
        Formatted text string
    """
    lines = []

    if result['error']:
        lines.append(f"Matrikkelenhet: {result['matrikkelenhet']}")
        lines.append(f"Error: {result['error']}")
        return "\n".join(lines)

    lines.append(f"Matrikkelenhet: {result['matrikkelenhet']}")

    if verbose and result['matrikkelenhet_id']:
        lines.append(f"Matrikkelenhet ID: {result['matrikkelenhet_id']}")
        lines.append(f"Kommune: {result['ident']['kommune']}")
        lines.append(f"Gårdsnummer: {result['ident']['gardsnummer']}")
        lines.append(f"Bruksnummer: {result['ident']['bruksnummer']}")
        if result['ident']['festenummer']:
            lines.append(f"Festenummer: {result['ident']['festenummer']}")
        if result['ident']['seksjonsnummer']:
            lines.append(f"Seksjonsnummer: {result['ident']['seksjonsnummer']}")

        if result.get('verbose_data'):
            lines.append("")
            lines.append("Additional Information:")
            for key, value in sorted(result['verbose_data'].items()):
                if key not in ['eierforhold']:  # Skip eierforhold, we show owners separately
                    lines.append(f"  {key}: {value}")

    lines.append("")
    if result['owners']:
        # Separate current and historical owners
        all_owners = result['owners']
        current_owners = [o for o in all_owners if o.get('is_current', True)]
        historical_owners = [o for o in all_owners if not o.get('is_current', True)]

        if current_owners:
            lines.append("Current Owners:")
            for i, owner in enumerate(current_owners, 1):
                owner_parts = []
                if owner.get('navn'):
                    owner_parts.append(owner['navn'])
                if owner.get('adresse'):
                    owner_parts.append(owner['adresse'])

                # Add ownership period and share
                period_parts = []
                if owner.get('fraDato'):
                    period_parts.append(f"fra {owner['fraDato']}")
                if owner.get('andel'):
                    # Format andel nicely (e.g., "1/2" instead of dict string)
                    andel_str = owner['andel']
                    if isinstance(andel_str, str) and '{' in andel_str:
                        # Try to parse dict-like string
                        try:
                            import ast
                            andel_dict = ast.literal_eval(andel_str.replace('\n', '').replace(' ', ''))
                            if isinstance(andel_dict, dict):
                                teller = andel_dict.get('teller', '')
                                nevner = andel_dict.get('nevner', '')
                                andel_str = f"{teller}/{nevner}" if teller and nevner else andel_str
                        except:
                            pass
                    period_parts.append(f"andel: {andel_str}")
                if owner.get('eierforhold_type'):
                    period_parts.append(f"type: {owner['eierforhold_type']}")

                if owner_parts:
                    owner_str = ', '.join(owner_parts)
                    if period_parts:
                        owner_str += f" ({', '.join(period_parts)})"
                    lines.append(f"  {i}. {owner_str}")
                elif owner.get('eierId'):
                    period_str = f" ({', '.join(period_parts)})" if period_parts else ""
                    lines.append(f"  {i}. (Owner ID: {owner['eierId']}{period_str})")

        if historical_owners:
            lines.append("")
            lines.append(f"Historical Owners ({len(historical_owners)}):")
            for i, owner in enumerate(historical_owners, 1):
                owner_parts = []
                if owner.get('navn'):
                    owner_parts.append(owner['navn'])
                if owner.get('adresse'):
                    owner_parts.append(owner['adresse'])

                # Add ownership period
                period_parts = []
                if owner.get('fraDato'):
                    period_parts.append(f"fra {owner['fraDato']}")
                if owner.get('tilDato'):
                    period_parts.append(f"til {owner['tilDato']}")
                if owner.get('andel'):
                    period_parts.append(f"andel: {owner['andel']}")

                if owner_parts:
                    owner_str = ', '.join(owner_parts)
                    if period_parts:
                        owner_str += f" ({', '.join(period_parts)})"
                    lines.append(f"  {i}. {owner_str} [HISTORICAL]")
                elif owner.get('eierId'):
                    period_str = f" ({', '.join(period_parts)})" if period_parts else ""
                    lines.append(f"  {i}. (Owner ID: {owner['eierId']}{period_str}) [HISTORICAL]")

        if not current_owners and not historical_owners:
            lines.append("Owners: (No owner information available)")
    else:
        lines.append("Owners: (No owner information available)")

    # Raw data section
    if raw and result.get('raw_data'):
        lines.append("")
        lines.append("=" * 80)
        lines.append("RAW API DATA")
        lines.append("=" * 80)
        lines.append("")

        # Matrikkelenhet raw
        if result['raw_data'].get('matrikkelenhet_raw'):
            lines.append("Raw Matrikkelenhet Object:")
            lines.append(json.dumps(result['raw_data']['matrikkelenhet_raw'], indent=2, ensure_ascii=False))
            lines.append("")

        # Eierforhold raw
        if result['raw_data'].get('eierforhold_raw'):
            lines.append(f"Raw Eierforhold Objects ({len(result['raw_data']['eierforhold_raw'])}):")
            for i, eierforhold in enumerate(result['raw_data']['eierforhold_raw'], 1):
                lines.append(f"  Eierforhold {i}:")
                lines.append(json.dumps(eierforhold, indent=4, ensure_ascii=False))
                lines.append("")

        # Person raw
        if result['raw_data'].get('person_raw'):
            lines.append(f"Raw Person Objects ({len(result['raw_data']['person_raw'])}):")
            for i, person in enumerate(result['raw_data']['person_raw'], 1):
                lines.append(f"  Person {i}:")
                lines.append(json.dumps(person, indent=4, ensure_ascii=False))
                lines.append("")

    return "\n".join(lines)


def format_output_json(result: Dict[str, Any]) -> str:
    """Format result as JSON.

    Args:
        result: Result dictionary from lookup

    Returns:
        JSON string
    """
    return json.dumps(result, indent=2, ensure_ascii=False)


def format_output_csv(results: List[Dict[str, Any]]) -> List[List[str]]:
    """Format results as CSV rows.

    Args:
        results: List of result dictionaries

    Returns:
        List of CSV rows (list of strings)
    """
    rows = []

    # Header
    rows.append([
        'Matrikkelenhet',
        'Kommune',
        'Gårdsnummer',
        'Bruksnummer',
        'Festenummer',
        'Seksjonsnummer',
        'Matrikkelenhet ID',
        'Owner Name',
        'Owner Address',
        'Owner ID',
        'Fra Dato',
        'Til Dato',
        'Andel',
        'Eierforhold Type',
        'Is Current',
        'Error'
    ])

    # Data rows - one row per owner
    for result in results:
        if result['owners']:
            for owner in result['owners']:
                rows.append([
                    result['matrikkelenhet'],
                    str(result['ident']['kommune']),
                    str(result['ident']['gardsnummer']),
                    str(result['ident']['bruksnummer']),
                    str(result['ident']['festenummer']) if result['ident']['festenummer'] else '',
                    str(result['ident']['seksjonsnummer']) if result['ident']['seksjonsnummer'] else '',
                    str(result['matrikkelenhet_id']) if result['matrikkelenhet_id'] else '',
                    owner.get('navn', ''),
                    owner.get('adresse', ''),
                    str(owner.get('eierId', '')) if owner.get('eierId') else '',
                    owner.get('fraDato', '') if owner.get('fraDato') else '',
                    owner.get('tilDato', '') if owner.get('tilDato') else '',
                    owner.get('andel', '') if owner.get('andel') else '',
                    owner.get('eierforhold_type', '') if owner.get('eierforhold_type') else '',
                    'Yes' if owner.get('is_current', True) else 'No',
                    result['error'] if result['error'] else ''
                ])
        else:
            # No owners - still add a row
            rows.append([
                result['matrikkelenhet'],
                str(result['ident']['kommune']),
                str(result['ident']['gardsnummer']),
                str(result['ident']['bruksnummer']),
                str(result['ident']['festenummer']) if result['ident']['festenummer'] else '',
                str(result['ident']['seksjonsnummer']) if result['ident']['seksjonsnummer'] else '',
                str(result['matrikkelenhet_id']) if result['matrikkelenhet_id'] else '',
                '', '', '', '', '', '', '', '',  # Empty owner fields
                result['error'] if result['error'] else ''
            ])

    return rows


def parse_input(input_str: str) -> Optional[MatrikkelIdent]:
    """Parse input string or return None if invalid.

    Args:
        input_str: Input string (matrikkelenhet format or components)

    Returns:
        MatrikkelIdent object or None
    """
    # Try parsing as formatted string first
    ident = parse_matrikkelenhet_string(input_str)
    if ident:
        return ident

    # If that fails, return None (caller should handle)
    return None


def read_input_file(file_path: Path) -> List[str]:
    """Read matrikkelenhet identifiers from a file.

    Args:
        file_path: Path to input file

    Returns:
        List of matrikkelenhet strings (one per line, whitespace stripped)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    return lines


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Look up matrikkelenhet and owner information from Matrikkel API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple lookup - owners only
  %(prog)s --matrikkel "1234-56/78"

  # Verbose lookup - all information
  %(prog)s --matrikkel "1234-56/78" --verbose

  # Raw API data - see all raw objects from API
  %(prog)s --matrikkel "1234-56/78" --raw

  # Verbose + Raw - all information plus raw API data
  %(prog)s --matrikkel "1234-56/78" --verbose --raw

  # JSON output
  %(prog)s --matrikkel "1234-56/78" --json

  # Batch mode from file
  %(prog)s --file matrikkelenheter.txt --csv --output results.csv

  # Debug mode
  %(prog)s --matrikkel "1234-56/78" --verbose --debug

  # Include historical owners (default: only current owners)
  %(prog)s --matrikkel "1234-56/78" --historical
        """
    )

    # Input methods (mutually exclusive group)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--matrikkel',
        type=str,
        help='Matrikkelenhet string (e.g., "1234-56/78" or "1234-56/78/90")'
    )
    input_group.add_argument(
        '--file',
        type=Path,
        help='Input file with one matrikkelenhet per line'
    )

    # Output options
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show all available information from Matrikkelenhet object'
    )
    parser.add_argument(
        '--raw',
        action='store_true',
        help='Show raw API data (Matrikkelenhet, eierforhold, and Person objects)'
    )
    parser.add_argument(
        '--historical',
        action='store_true',
        help='Include historical owners (default: show only current owners)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser.add_argument(
        '--csv',
        action='store_true',
        help='Output as CSV (useful for batch mode)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Write output to file instead of stdout'
    )

    # Configuration
    parser.add_argument(
        '--base-url',
        type=str,
        help='Override API base URL'
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help='Use test API endpoint'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug output'
    )

    # Behavior
    parser.add_argument(
        '--continue-on-error',
        action='store_true',
        default=True,
        help='Continue processing on errors in batch mode (default: True)'
    )

    args = parser.parse_args()

    # Get configuration
    config = get_matrikkel_config()
    if not config:
        print("Error: Matrikkel credentials not found.", file=sys.stderr)
        print("Set MATRIKKEL_USERNAME and MATRIKKEL_PASSWORD environment variables.", file=sys.stderr)
        sys.exit(1)

    # Override base URL if specified
    if args.base_url:
        config.base_url = args.base_url
    elif args.test_mode:
        config.base_url = "https://prodtest.matrikkel.no/matrikkelapi/wsapi/v1"

    # Parse input
    idents: List[MatrikkelIdent] = []

    if args.file:
        # Batch mode from file
        try:
            input_lines = read_input_file(args.file)
            for line in input_lines:
                ident = parse_input(line)
                if ident:
                    idents.append(ident)
                else:
                    print(f"Warning: Could not parse '{line}' from file, skipping", file=sys.stderr)
        except Exception as e:
            print(f"Error reading file {args.file}: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.matrikkel:
        # Single lookup from string
        ident = parse_input(args.matrikkel)
        if not ident:
            print(f"Error: Could not parse matrikkelenhet '{args.matrikkel}'", file=sys.stderr)
            sys.exit(1)
        idents.append(ident)

    if not idents:
        print("Error: No valid matrikkelenhet identifiers found", file=sys.stderr)
        sys.exit(1)

    # Perform lookup
    if len(idents) == 1:
        # Single lookup
        result = lookup_matrikkelenhet(idents[0], config, verbose=args.verbose, debug=args.debug, raw=args.raw, include_historical=args.historical)
        results = [result]
    else:
        # Batch lookup
        results = batch_lookup(
            idents,
            config,
            verbose=args.verbose,
            debug=args.debug,
            continue_on_error=args.continue_on_error,
            raw=args.raw,
            include_historical=args.historical
        )

    # Format output
    output_lines = []

    if args.csv:
        # CSV output
        csv_rows = format_output_csv(results)
        output_lines = [",".join(row) for row in csv_rows]
    elif args.json:
        # JSON output
        if len(results) == 1:
            output_lines = [format_output_json(results[0])]
        else:
            output_lines = [json.dumps(results, indent=2, ensure_ascii=False)]
    else:
        # Text output
        for result in results:
            output_lines.append(format_output_text(result, verbose=args.verbose, raw=args.raw))
            if len(results) > 1:
                output_lines.append("")  # Separator between results

    output_text = "\n".join(output_lines)

    # Write output
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output_text)
        except Exception as e:
            print(f"Error writing to file {args.output}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output_text)

    # Determine exit code
    errors = sum(1 for r in results if r.get('error'))
    if errors == len(results):
        sys.exit(1)  # All failed
    elif errors > 0:
        sys.exit(2)  # Partial success
    else:
        sys.exit(0)  # Success


if __name__ == '__main__':
    main()

