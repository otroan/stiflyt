#!/usr/bin/env python3
"""
Validerer alle rutene i databasen og genererer en feilrapport.

Eksempel:
    python scripts/validate_routes.py
    python scripts/validate_routes.py --route bre5
    python scripts/validate_routes.py --output report.json
"""
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.database import get_db_connection, ROUTE_SCHEMA
from services.route_service import get_route_segments, combine_route_geometry
import psycopg2
from psycopg2.extras import RealDictCursor


def validate_route_length(conn, route_geom):
    """Validerer at lengde kan beregnes korrekt."""
    errors = []
    warnings = []

    try:
        # Sjekk geometritype
        check_type_query = "SELECT ST_GeometryType(%s::geometry) as geom_type;"
        with conn.cursor() as cur:
            cur.execute(check_type_query, (route_geom,))
            geom_type = cur.fetchone()[0]

        if geom_type == 'ST_MultiLineString':
            # Prøv feilende metode først (for å fange feilen)
            try:
                length_query = """
                    SELECT SUM(ST_Length(ST_Transform(ST_GeometryN(%s::geometry, generate_series(1, ST_NumGeometries(%s::geometry))), 4326)::geography)) as length_meters;
                """
                with conn.cursor() as cur:
                    cur.execute(length_query, (route_geom, route_geom))
                    length = cur.fetchone()[0]
            except Exception as e:
                # Fanger alle typer feil, inkludert SyntaxError og InternalError
                error_type = type(e).__name__
                error_msg = str(e)
                # Sjekk om det er generate_series-feilen
                if 'generate_series' in error_msg or 'set-returning function' in error_msg:
                    errors.append({
                        'category': 'SQL_SYNTAX_ERROR',
                        'message': error_msg.split('\n')[0],  # Første linje av feilen
                        'error_type': error_type,
                        'operation': 'get_route_length_multilinestring',
                        'suggestion': 'Bruk LATERAL JOIN eller loop i stedet for generate_series i SUM. Se validate_routes.py for eksempel.'
                    })
                else:
                    errors.append({
                        'category': 'LENGTH_CALCULATION_ERROR',
                        'message': error_msg.split('\n')[0],
                        'error_type': error_type,
                        'operation': 'get_route_length_multilinestring'
                    })

                # Prøv alternativ metode med ny transaksjon
                try:
                    # Rollback først hvis transaksjon er avbrutt
                    conn.rollback()

                    with conn.cursor() as cur:
                        cur.execute('SELECT ST_NumGeometries(%s::geometry) as num', (route_geom,))
                        num = cur.fetchone()[0]

                        total = 0
                        for i in range(1, num + 1):
                            cur.execute('SELECT ST_Length(ST_Transform(ST_GeometryN(%s::geometry, %s), 4326)::geography) as length',
                                      (route_geom, i))
                            length = cur.fetchone()[0]
                            total += length

                        warnings.append({
                            'category': 'WORKAROUND_APPLIED',
                            'message': f'Brukte loop-metode i stedet for generate_series. Lengde: {total:.2f} m ({total/1000:.2f} km)',
                            'length_meters': total,
                            'length_km': total / 1000.0
                        })
                except Exception as e2:
                    errors.append({
                        'category': 'LENGTH_CALCULATION_FAILED',
                        'message': f'Både generate_series og loop-metode feilet: {str(e2)}',
                        'operation': 'get_route_length_multilinestring'
                    })
        else:
            # LineString - skal fungere
            try:
                length_query = "SELECT ST_Length(ST_Transform(%s::geometry, 4326)::geography) as length_meters;"
                with conn.cursor() as cur:
                    cur.execute(length_query, (route_geom,))
                    length = cur.fetchone()[0]
            except Exception as e:
                errors.append({
                    'category': 'LENGTH_CALCULATION_ERROR',
                    'message': str(e),
                    'operation': 'get_route_length_linestring'
                })
    except Exception as e:
        errors.append({
            'category': 'GEOMETRY_TYPE_CHECK_FAILED',
            'message': str(e),
            'operation': 'check_geometry_type'
        })

    return errors, warnings


def validate_route_geometry(conn, segments):
    """Validerer at geometri kan kombineres."""
    errors = []
    warnings = []

    try:
        route_geom = combine_route_geometry(conn, segments)
        if not route_geom:
            errors.append({
                'category': 'GEOMETRY_COMBINE_FAILED',
                'message': 'Kunne ikke kombinere segmenter til en geometri',
                'operation': 'combine_route_geometry'
            })
            return None, errors, warnings

        # Sjekk om geometri er gyldig
        with conn.cursor() as cur:
            cur.execute('SELECT ST_IsValid(%s::geometry) as is_valid', (route_geom,))
            is_valid = cur.fetchone()[0]

            if not is_valid:
                errors.append({
                    'category': 'INVALID_GEOMETRY',
                    'message': 'Kombinert geometri er ikke gyldig',
                    'operation': 'ST_IsValid'
                })

            # Sjekk om geometri er enkel (ingen self-intersections)
            cur.execute('SELECT ST_IsSimple(%s::geometry) as is_simple', (route_geom,))
            is_simple = cur.fetchone()[0]

            if not is_simple:
                warnings.append({
                    'category': 'NON_SIMPLE_GEOMETRY',
                    'message': 'Geometri har self-intersections eller er ikke enkel',
                    'operation': 'ST_IsSimple'
                })

        return route_geom, errors, warnings
    except Exception as e:
        errors.append({
            'category': 'GEOMETRY_VALIDATION_ERROR',
            'message': str(e),
            'operation': 'validate_route_geometry'
        })
        return None, errors, warnings


def validate_segments(conn, rutenummer):
    """Validerer segmenter for en rute."""
    errors = []
    warnings = []

    try:
        segments = get_route_segments(conn, rutenummer)
        if not segments:
            errors.append({
                'category': 'NO_SEGMENTS',
                'message': 'Ingen segmenter funnet for rute',
                'operation': 'get_route_segments'
            })
            return segments, errors, warnings

        # Sjekk segmentlengder
        segment_lengths = []
        for seg in segments:
            try:
                with conn.cursor() as cur:
                    cur.execute('SELECT ST_Length(ST_Transform(%s::geometry, 4326)::geography) as length',
                              (seg['senterlinje'],))
                    length = cur.fetchone()[0]
                    segment_lengths.append(length)

                    if length == 0:
                        warnings.append({
                            'category': 'ZERO_LENGTH_SEGMENT',
                            'message': f'Segment {seg["objid"]} har lengde 0',
                            'segment_objid': seg['objid']
                        })
            except Exception as e:
                warnings.append({
                    'category': 'SEGMENT_LENGTH_ERROR',
                    'message': f'Kunne ikke beregne lengde for segment {seg["objid"]}: {str(e)}',
                    'segment_objid': seg['objid']
                })

        return segments, errors, warnings
    except Exception as e:
        errors.append({
            'category': 'SEGMENT_VALIDATION_ERROR',
            'message': str(e),
            'operation': 'validate_segments'
        })
        return [], errors, warnings


def validate_route(rutenummer):
    """Validerer en enkelt rute."""
    conn = get_db_connection()

    all_errors = []
    all_warnings = []
    validation_info = {
        'rutenummer': rutenummer,
        'segment_count': 0,
        'geometry_type': None,
        'can_process': True
    }

    try:
        # Valider segmenter
        segments, seg_errors, seg_warnings = validate_segments(conn, rutenummer)
        all_errors.extend(seg_errors)
        all_warnings.extend(seg_warnings)
        validation_info['segment_count'] = len(segments)

        if seg_errors:
            validation_info['can_process'] = False
            return {
                **validation_info,
                'status': 'ERROR',
                'errors': all_errors,
                'warnings': all_warnings
            }

        # Valider geometri
        route_geom, geom_errors, geom_warnings = validate_route_geometry(conn, segments)
        all_errors.extend(geom_errors)
        all_warnings.extend(geom_warnings)

        if geom_errors:
            validation_info['can_process'] = False
            return {
                **validation_info,
                'status': 'ERROR',
                'errors': all_errors,
                'warnings': all_warnings
            }

        if route_geom:
            # Sjekk geometritype
            with conn.cursor() as cur:
                cur.execute('SELECT ST_GeometryType(%s::geometry) as geom_type', (route_geom,))
                validation_info['geometry_type'] = cur.fetchone()[0]

            # Valider lengdeberegning
            length_errors, length_warnings = validate_route_length(conn, route_geom)
            all_errors.extend(length_errors)
            all_warnings.extend(length_warnings)

            if length_errors:
                validation_info['can_process'] = False

        # Bestem status
        if all_errors:
            status = 'ERROR'
        elif all_warnings:
            status = 'WARNING'
        else:
            status = 'OK'

        return {
            **validation_info,
            'status': status,
            'errors': all_errors,
            'warnings': all_warnings
        }
    finally:
        conn.close()


def get_all_routes():
    """Henter alle rutene fra databasen."""
    conn = get_db_connection()
    try:
        query = f"""
            SELECT DISTINCT fi.rutenummer
            FROM {ROUTE_SCHEMA}.fotruteinfo fi
            ORDER BY fi.rutenummer
        """
        with conn.cursor() as cur:
            cur.execute(query)
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def generate_report(results, output_file=None):
    """Genererer en valideringsrapport."""
    total = len(results)
    ok = sum(1 for r in results if r['status'] == 'OK')
    warnings = sum(1 for r in results if r['status'] == 'WARNING')
    errors = sum(1 for r in results if r['status'] == 'ERROR')

    report = {
        'validation_date': datetime.now().isoformat(),
        'summary': {
            'total_routes': total,
            'ok_routes': ok,
            'warning_routes': warnings,
            'error_routes': errors
        },
        'routes': results
    }

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Rapport lagret til {output_file}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    # Print summary
    print("\n" + "="*60)
    print("VALIDERINGS SAMMENDRAG")
    print("="*60)
    print(f"Totalt antall ruter: {total}")
    print(f"  ✓ OK: {ok} ({ok/total*100:.1f}%)")
    print(f"  ⚠ ADVARSEL: {warnings} ({warnings/total*100:.1f}%)")
    print(f"  ✗ FEIL: {errors} ({errors/total*100:.1f}%)")
    print("="*60)

    # List feilende ruter
    if errors > 0:
        print("\nRuter med feil:")
        for r in results:
            if r['status'] == 'ERROR':
                print(f"  - {r['rutenummer']}: {len(r['errors'])} feil")
                for err in r['errors']:
                    print(f"    • {err['category']}: {err['message'][:80]}")

    return report


def main():
    parser = argparse.ArgumentParser(description='Validerer rutene i databasen')
    parser.add_argument('--route', help='Valider kun en spesifikk rute (f.eks. bre5)')
    parser.add_argument('--output', help='Output fil for rapport (JSON)')
    parser.add_argument('--format', choices=['json', 'markdown'], default='json', help='Rapportformat')

    args = parser.parse_args()

    if args.route:
        # Valider kun en rute
        print(f"Validerer rute: {args.route}")
        result = validate_route(args.route)

        if args.output:
            # Lagre til fil
            report = {
                'validation_date': datetime.now().isoformat(),
                'summary': {
                    'total_routes': 1,
                    'ok_routes': 1 if result['status'] == 'OK' else 0,
                    'warning_routes': 1 if result['status'] == 'WARNING' else 0,
                    'error_routes': 1 if result['status'] == 'ERROR' else 0
                },
                'routes': [result]
            }
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nRapport lagret til {args.output}")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # Valider alle ruter
        print("Henter alle ruter...")
        routes = get_all_routes()
        print(f"Fant {len(routes)} ruter. Starter validering...\n")

        results = []
        for i, rutenummer in enumerate(routes, 1):
            print(f"[{i}/{len(routes)}] Validerer {rutenummer}...", end=' ')
            result = validate_route(rutenummer)
            results.append(result)

            if result['status'] == 'ERROR':
                print(f"✗ FEIL ({len(result['errors'])} feil)")
            elif result['status'] == 'WARNING':
                print(f"⚠ ADVARSEL ({len(result['warnings'])} advarsler)")
            else:
                print("✓ OK")

        generate_report(results, args.output)


if __name__ == '__main__':
    main()

