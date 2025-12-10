#!/usr/bin/env python3
"""
Validate all routes in the database and generate an error report.

Example:
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
    """Validate that length can be calculated correctly."""
    errors = []
    warnings = []

    try:
        # Check geometry type
        check_type_query = "SELECT ST_GeometryType(%s::geometry) as geom_type;"
        with conn.cursor() as cur:
            cur.execute(check_type_query, (route_geom,))
            geom_type = cur.fetchone()[0]

        if geom_type == 'ST_MultiLineString':
            # Try failing method first (to catch the error)
            try:
                length_query = """
                    SELECT SUM(ST_Length(ST_Transform(ST_GeometryN(%s::geometry, generate_series(1, ST_NumGeometries(%s::geometry))), 4326)::geography)) as length_meters;
                """
                with conn.cursor() as cur:
                    cur.execute(length_query, (route_geom, route_geom))
                    length = cur.fetchone()[0]
            except Exception as e:
                # Catch all types of errors, including SyntaxError and InternalError
                error_type = type(e).__name__
                error_msg = str(e)
                # Check if it's the generate_series error
                if 'generate_series' in error_msg or 'set-returning function' in error_msg:
                    errors.append({
                        'category': 'SQL_SYNTAX_ERROR',
                        'message': error_msg.split('\n')[0],  # First line of the error
                        'error_type': error_type,
                        'operation': 'get_route_length_multilinestring',
                        'suggestion': 'Use LATERAL JOIN or loop instead of generate_series in SUM. See validate_routes.py for example.'
                    })
                else:
                    errors.append({
                        'category': 'LENGTH_CALCULATION_ERROR',
                        'message': error_msg.split('\n')[0],
                        'error_type': error_type,
                        'operation': 'get_route_length_multilinestring'
                    })

                # Try alternative method with new transaction
                try:
                    # Rollback first if transaction is aborted
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
                            'message': f'Used loop method instead of generate_series. Length: {total:.2f} m ({total/1000:.2f} km)',
                            'length_meters': total,
                            'length_km': total / 1000.0
                        })
                except Exception as e2:
                    errors.append({
                        'category': 'LENGTH_CALCULATION_FAILED',
                        'message': f'Both generate_series and loop method failed: {str(e2)}',
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
    """Validate that geometry can be combined."""
    errors = []
    warnings = []

    try:
        route_geom = combine_route_geometry(conn, segments)
        if not route_geom:
            errors.append({
                'category': 'GEOMETRY_COMBINE_FAILED',
                'message': 'Could not combine segments into a geometry',
                'operation': 'combine_route_geometry'
            })
            return None, errors, warnings

        # Check if geometry is valid
        with conn.cursor() as cur:
            cur.execute('SELECT ST_IsValid(%s::geometry) as is_valid', (route_geom,))
            is_valid = cur.fetchone()[0]

            if not is_valid:
                errors.append({
                    'category': 'INVALID_GEOMETRY',
                    'message': 'Combined geometry is not valid',
                    'operation': 'ST_IsValid'
                })

            # Check if geometry is simple (no self-intersections)
            cur.execute('SELECT ST_IsSimple(%s::geometry) as is_simple', (route_geom,))
            is_simple = cur.fetchone()[0]

            if not is_simple:
                warnings.append({
                    'category': 'NON_SIMPLE_GEOMETRY',
                    'message': 'Geometry has self-intersections or is not simple',
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
    """Validate segments for a route."""
    errors = []
    warnings = []

    try:
        segments = get_route_segments(conn, rutenummer)
        if not segments:
            errors.append({
                'category': 'NO_SEGMENTS',
                'message': 'No segments found for route',
                'operation': 'get_route_segments'
            })
            return segments, errors, warnings

        # Check segment lengths
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
                            'message': f'Segment {seg["objid"]} has length 0',
                            'segment_objid': seg['objid']
                        })
            except Exception as e:
                warnings.append({
                    'category': 'SEGMENT_LENGTH_ERROR',
                    'message': f'Could not calculate length for segment {seg["objid"]}: {str(e)}',
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
    """Validate a single route."""
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
        # Validate segments
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
            # Check geometry type
            with conn.cursor() as cur:
                cur.execute('SELECT ST_GeometryType(%s::geometry) as geom_type', (route_geom,))
                validation_info['geometry_type'] = cur.fetchone()[0]

            # Validate length calculation
            length_errors, length_warnings = validate_route_length(conn, route_geom)
            all_errors.extend(length_errors)
            all_warnings.extend(length_warnings)

            if length_errors:
                validation_info['can_process'] = False

        # Determine status
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
    """Get all routes from the database."""
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
        print(f"Report saved to {output_file}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    # Print summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)
    print(f"Total number of routes: {total}")
    print(f"  ✓ OK: {ok} ({ok/total*100:.1f}%)")
    print(f"  ⚠ WARNING: {warnings} ({warnings/total*100:.1f}%)")
    print(f"  ✗ ERROR: {errors} ({errors/total*100:.1f}%)")
    print("="*60)

    # List failing routes
    if errors > 0:
        print("\nRoutes with errors:")
        for r in results:
            if r['status'] == 'ERROR':
                print(f"  - {r['rutenummer']}: {len(r['errors'])} errors")
                for err in r['errors']:
                    print(f"    • {err['category']}: {err['message'][:80]}")

    return report


def main():
    parser = argparse.ArgumentParser(description='Validate routes in the database')
    parser.add_argument('--route', help='Validate only a specific route (e.g. bre5)')
    parser.add_argument('--output', help='Output fil for rapport (JSON)')
    parser.add_argument('--format', choices=['json', 'markdown'], default='json', help='Rapportformat')

    args = parser.parse_args()

    if args.route:
        # Validate only one route
        print(f"Validating route: {args.route}")
        result = validate_route(args.route)

        if args.output:
            # Save to file
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
            print(f"\nReport saved to {args.output}")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # Validate all routes
        print("Getting all routes...")
        routes = get_all_routes()
        print(f"Found {len(routes)} routes. Starting validation...\n")

        results = []
        for i, rutenummer in enumerate(routes, 1):
            print(f"[{i}/{len(routes)}] Validating {rutenummer}...", end=' ')
            result = validate_route(rutenummer)
            results.append(result)

            if result['status'] == 'ERROR':
                print(f"✗ ERROR ({len(result['errors'])} errors)")
            elif result['status'] == 'WARNING':
                print(f"⚠ WARNING ({len(result['warnings'])} warnings)")
            else:
                print("✓ OK")

        generate_report(results, args.output)


if __name__ == '__main__':
    main()

