"""Proof of concept: Extract route bre10 and find matrikkelenhet per km."""
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database connection parameters
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/matrikkel")
USE_UNIX_SOCKET = os.getenv("USE_UNIX_SOCKET", "true").lower() == "true"
SOCKET_DIR = os.getenv("DB_SOCKET_DIR", "/var/run/postgresql")
DB_NAME = os.getenv("DB_NAME", "matrikkel")
DB_USER = os.getenv("DB_USER", "stiflyt_reader")

# Fixed schema name - ALWAYS use 'stiflyt' schema
ROUTE_SCHEMA = os.getenv("ROUTE_SCHEMA", "stiflyt")
TEIG_SCHEMA = os.getenv("TEIG_SCHEMA", "stiflyt")


def get_db_connection():
    """Get database connection."""
    if USE_UNIX_SOCKET:
        conn_params = {
            'host': SOCKET_DIR,
            'database': DB_NAME,
            'user': DB_USER,
        }
    else:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        conn_params = {
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'database': parsed.path.lstrip('/'),
            'user': parsed.username,
            'password': parsed.password
        }

    # Remove None values
    conn_params = {k: v for k, v in conn_params.items() if v is not None}
    return psycopg2.connect(**conn_params)


def get_route_segments(conn, rutenummer):
    """Get all segments for a route."""
    query = f"""
        SELECT
            f.objid,
            f.senterlinje,
            fi.rutenummer,
            fi.rutenavn,
            fi.vedlikeholdsansvarlig
        FROM {ROUTE_SCHEMA}.fotrute f
        JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE fi.rutenummer = %s
        ORDER BY f.objid;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (rutenummer,))
        return cur.fetchall()


def combine_route_geometry(conn, segments):
    """Combine route segments into a single linestring."""
    if not segments:
        return None

    # Collect all geometries
    query = f"""
        SELECT ST_LineMerge(ST_Collect(senterlinje::geometry))::geometry as combined_geom
        FROM {ROUTE_SCHEMA}.fotrute
        WHERE objid = ANY(%s);
    """

    segment_ids = [seg['objid'] for seg in segments]

    with conn.cursor() as cur:
        cur.execute(query, (segment_ids,))
        result = cur.fetchone()
        return result[0] if result else None


def get_route_length(conn, route_geom):
    """Get route length in meters."""
    query = """
        SELECT ST_Length(ST_Transform(%s::geometry, 3857)) as length_meters;
    """

    with conn.cursor() as cur:
        cur.execute(query, (route_geom,))
        result = cur.fetchone()
        return result[0] if result else 0.0


def find_matrikkelenhet_intersections(conn, route_geom):
    """Find all intersections between route and teig polygons."""
    query = f"""
        SELECT
            t.matrikkelnummertekst,
            t.kommunenummer,
            t.kommunenavn,
            t.arealmerknadtekst,
            t.lagretberegnetareal,
            t.teigid,
            m.bruksnavn,
            m.gardsnummer,
            m.bruksnummer,
            m.festenummer,
            ST_Intersection(t.omrade::geometry, %s::geometry) as intersection_geom,
            ST_Length(ST_Transform(ST_Intersection(t.omrade::geometry, %s::geometry), 3857)) as length_meters
        FROM {TEIG_SCHEMA}.teig t
        LEFT JOIN {TEIG_SCHEMA}.matrikkelenhet m ON m.teig_fk = t.teigid
        WHERE ST_Intersects(t.omrade::geometry, %s::geometry)
        AND ST_GeometryType(ST_Intersection(t.omrade::geometry, %s::geometry)) IN ('ST_LineString', 'ST_MultiLineString');
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (route_geom, route_geom, route_geom, route_geom))
        return cur.fetchall()


def calculate_offsets(conn, route_geom, intersections, total_length):
    """Calculate offset from start for each intersection."""
    results = []

    for intersection in intersections:
        # Handle both LineString and MultiLineString
        # For MultiLineString, get the start point of the first line
        query = """
            SELECT ST_LineLocatePoint(
                %s::geometry,
                ST_StartPoint(
                    CASE
                        WHEN ST_GeometryType(%s::geometry) = 'ST_MultiLineString'
                        THEN ST_GeometryN(%s::geometry, 1)
                        ELSE %s::geometry
                    END
                )
            ) as fraction;
        """

        with conn.cursor() as cur:
            cur.execute(query, (route_geom, intersection['intersection_geom'],
                              intersection['intersection_geom'], intersection['intersection_geom']))
            result = cur.fetchone()
            fraction = result[0] if result else 0.0

        offset_meters = fraction * total_length
        offset_km = offset_meters / 1000.0

        results.append({
            'matrikkelnummertekst': intersection['matrikkelnummertekst'],
            'kommunenummer': intersection['kommunenummer'],
            'kommunenavn': intersection['kommunenavn'],
            'bruksnavn': intersection.get('bruksnavn'),  # Property name
            'gardsnummer': intersection.get('gardsnummer'),
            'bruksnummer': intersection.get('bruksnummer'),
            'festenummer': intersection.get('festenummer'),
            'arealmerknadtekst': intersection.get('arealmerknadtekst'),  # Area remark
            'lagretberegnetareal': intersection.get('lagretberegnetareal'),  # Stored calculated area
            'offset_meters': offset_meters,
            'offset_km': offset_km,
            'length_meters': intersection['length_meters'],
            'length_km': intersection['length_meters'] / 1000.0
        })

    # Sort by offset
    results.sort(key=lambda x: x['offset_meters'])
    return results


def format_matrikkelenhet(kommunenummer, gardsnummer, bruksnummer, festenummer=None):
    """Format matrikkelenhet as kommunenummer-gardsnummer/bruksnummer/festenummer.

    Example: 3110-43/15/2 (with festenummer)
    Example: 3110-43/15 (without festenummer)
    For umatrikulerte teig (gardsnummer=0 or bruksnummer=0): show as "Umatrikulert"
    """
    if not kommunenummer:
        return None

    # Check if umatrikulert (gardsnummer=0 or bruksnummer=0)
    if gardsnummer == 0 or bruksnummer == 0:
        return f"{kommunenummer}-Umatrikulert"

    if gardsnummer is None or bruksnummer is None:
        return None

    # Format as kommunenummer-gardsnummer/bruksnummer/festenummer
    formatted = f"{kommunenummer}-{gardsnummer}/{bruksnummer}"
    if festenummer is not None and festenummer != 0:
        formatted += f"/{festenummer}"

    return formatted


def group_by_km(matrikkelenheter):
    """Group matrikkelenheter by kilometer."""
    km_groups = {}

    for mat in matrikkelenheter:
        km_start = int(mat['offset_km'])
        km_end = int((mat['offset_km'] + mat['length_km']))

        # Add to all km ranges it spans
        for km in range(km_start, km_end + 1):
            if km not in km_groups:
                km_groups[km] = []

            # Check if this matrikkelenhet is already in this km
            if not any(m['matrikkelnummertekst'] == mat['matrikkelnummertekst']
                      for m in km_groups[km]):
                km_groups[km].append(mat)

    return km_groups


def main():
    """Main function."""
    rutenummer = "bre10"

    print("=" * 80)
    print(f"Proof of Concept: Route {rutenummer} Matrikkelenhet Analysis")
    print("=" * 80)

    try:
        conn = get_db_connection()
        print(f"\nConnected to database: {DB_NAME}")

        # Step 1: Get route segments
        print(f"\nStep 1: Fetching segments for route '{rutenummer}'...")
        segments = get_route_segments(conn, rutenummer)

        if not segments:
            print(f"ERROR: No segments found for route '{rutenummer}'")
            conn.close()
            return

        print(f"Found {len(segments)} segments")
        if segments:
            print(f"Route name: {segments[0]['rutenavn']}")
            print(f"Organization: {segments[0]['vedlikeholdsansvarlig']}")

        # Step 2: Combine segments into single geometry
        print("\nStep 2: Combining segments into single route geometry...")
        route_geom = combine_route_geometry(conn, segments)

        if not route_geom:
            print("ERROR: Could not combine route geometry")
            conn.close()
            return

        # Step 3: Calculate total length
        print("\nStep 3: Calculating route length...")
        total_length = get_route_length(conn, route_geom)
        total_length_km = total_length / 1000.0
        print(f"Total route length: {total_length:.2f} meters ({total_length_km:.2f} km)")

        # Step 4: Find intersections with teig
        print("\nStep 4: Finding intersections with teig polygons...")
        intersections, total_count = find_matrikkelenhet_intersections(conn, route_geom)
        print(f"Found {len(intersections)} intersections (total: {total_count})")
        if total_count > 100:
            print(f"WARNING: Limit of 100 matrikkelenheter applied. {total_count - 100} additional intersections were not processed.")

        if not intersections:
            print("No intersections found with teig polygons")
            conn.close()
            return

        # Step 5: Calculate offsets
        print("\nStep 5: Calculating offsets from route start...")
        matrikkelenheter = calculate_offsets(conn, route_geom, intersections, total_length)

        # Step 6: Group matrikkelenheter by their route intervals
        print("\nStep 6: Grouping matrikkelenheter by route intervals...")

        # Group by matrikkelenhet and collect their intervals
        matrikkel_intervals = {}
        for mat in matrikkelenheter:
            mat_id = mat['matrikkelnummertekst']
            if mat_id not in matrikkel_intervals:
                matrikkel_intervals[mat_id] = {
                    'intervals': [],
                    'total_length': 0.0,
                    'kommunenummer': mat['kommunenummer'],
                    'kommunenavn': mat['kommunenavn'],
                    'gardsnummer': mat.get('gardsnummer'),
                    'bruksnummer': mat.get('bruksnummer'),
                    'festenummer': mat.get('festenummer'),
                    'bruksnavn': mat.get('bruksnavn'),
                    'arealmerknadtekst': mat.get('arealmerknadtekst'),
                    'lagretberegnetareal': mat.get('lagretberegnetareal'),
                }

            start_km = mat['offset_km']
            end_km = mat['offset_km'] + mat['length_km']
            matrikkel_intervals[mat_id]['intervals'].append((start_km, end_km))
            matrikkel_intervals[mat_id]['total_length'] += mat['length_meters']

        # Merge overlapping intervals for each matrikkelenhet
        for mat_id in matrikkel_intervals:
            intervals = sorted(matrikkel_intervals[mat_id]['intervals'])
            merged = []
            for start, end in intervals:
                if merged and merged[-1][1] >= start:
                    # Merge with previous interval
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            matrikkel_intervals[mat_id]['intervals'] = merged

        # Step 7: Display results
        print("\n" + "=" * 80)
        print("RESULTS: Matrikkelenhet per Route Interval")
        print("=" * 80)

        print(f"\nRoute: {rutenummer} - {segments[0]['rutenavn']}")
        print(f"Total length: {total_length_km:.2f} km")
        print(f"Total matrikkelenheter: {len(matrikkel_intervals)}")

        print("\nMatrikkelenheter by Route Interval:")
        print("-" * 80)

        # Create a flat list of (interval_start, mat_id, mat_info, interval) for sorting
        interval_list = []
        for mat_id, mat_info in matrikkel_intervals.items():
            # Format matrikkelenhet as kommunenummer-gardsnummer/bruksnummer
            kommunenummer = mat_info.get('kommunenummer')
            gardsnummer = mat_info.get('gardsnummer')
            bruksnummer = mat_info.get('bruksnummer')

            if gardsnummer == 0 or bruksnummer == 0:
                formatted_matrikkel = format_matrikkelenhet(kommunenummer, 0, 0)
            elif gardsnummer is not None and bruksnummer is not None:
                formatted_matrikkel = format_matrikkelenhet(
                    kommunenummer,
                    gardsnummer,
                    bruksnummer,
                    mat_info.get('festenummer')
                )
            else:
                formatted_matrikkel = f"{kommunenummer}-Ingen matrikkelenhet" if kommunenummer else mat_id

            for start_km, end_km in mat_info['intervals']:
                interval_list.append((start_km, mat_id, mat_info, formatted_matrikkel, (start_km, end_km)))

        # Sort by interval start position
        interval_list.sort(key=lambda x: x[0])

        for start_km, mat_id, mat_info, formatted_matrikkel, (interval_start, interval_end) in interval_list:
            # Display this interval
            interval_str = f"{interval_start:.1f}-{interval_end:.1f}km"
            info_parts = [interval_str, formatted_matrikkel or mat_id]

            # Add property name (bruksnavn) if available
            if mat_info.get('bruksnavn'):
                info_parts.append(f"'{mat_info['bruksnavn']}'")

            # Add total route length through this matrikkelenhet
            mat_length = mat_info.get('total_length', 0.0)
            if mat_length > 0:
                info_parts.append(f"({mat_length:.1f} m)")

            # Add area remark if available
            if mat_info.get('arealmerknadtekst'):
                info_parts.append(f"[{mat_info['arealmerknadtekst']}]")

            # Add area if available
            if mat_info.get('lagretberegnetareal'):
                area_ha = mat_info['lagretberegnetareal'] / 10000.0
                info_parts.append(f"({area_ha:.2f} ha)")

            info_parts.append(f"- {mat_info['kommunenavn'] or mat_info['kommunenummer']}")

            print(f"  - {' '.join(info_parts)}")

        # Summary statistics
        print("\n" + "=" * 80)
        print("Summary Statistics:")
        print("=" * 80)

        unique_mats = set(m['matrikkelnummertekst'] for m in matrikkelenheter)
        kommuner = set(m['kommunenavn'] or m['kommunenummer'] for m in matrikkelenheter)

        # Calculate total length per matrikkelenhet
        matrikkel_lengths = {}
        for mat in matrikkelenheter:
            mat_id = mat['matrikkelnummertekst']
            if mat_id not in matrikkel_lengths:
                matrikkel_lengths[mat_id] = 0.0
            matrikkel_lengths[mat_id] += mat['length_meters']

        print(f"Total unique matrikkelenheter: {len(unique_mats)}")
        print(f"Municipalities traversed: {len(kommuner)}")
        print(f"Municipalities: {', '.join(sorted(kommuner))}")

        # Validate total length
        total_matrikkel_length = sum(matrikkel_lengths.values())
        total_matrikkel_length_km = total_matrikkel_length / 1000.0
        length_diff = total_length - total_matrikkel_length
        length_diff_percent = (length_diff / total_length * 100) if total_length > 0 else 0

        print("\n" + "=" * 80)
        print("Length Validation:")
        print("=" * 80)
        print(f"Total route length:        {total_length:10.2f} m ({total_length_km:8.3f} km)")
        print(f"Sum of matrikkelenhet:     {total_matrikkel_length:10.2f} m ({total_matrikkel_length_km:8.3f} km)")
        print(f"Difference:                {length_diff:10.2f} m ({abs(length_diff_percent):6.2f}%)")

        coverage_percent = (total_matrikkel_length / total_length * 100) if total_length > 0 else 0

        print(f"Route coverage by teig:      {coverage_percent:6.2f}%")

        if abs(length_diff_percent) < 1.0:
            print("✓ Validation PASSED: Lengths match within 1%")
        elif coverage_percent > 80:
            print(f"✓ Validation PASSED: {coverage_percent:.1f}% of route is covered by teig polygons")
            if abs(length_diff_percent) > 1.0:
                print(f"  Note: {abs(length_diff_percent):.2f}% difference may be due to overlapping polygons")
        elif coverage_percent > 50:
            print(f"⚠ Validation INFO: {coverage_percent:.1f}% of route is covered by teig polygons")
            print(f"  Remaining {100-coverage_percent:.1f}% likely passes through:")
            print("  - Unregistered areas (fjell, vann, offentlig område)")
            print("  - Areas without teig polygons")
        else:
            print(f"ℹ Validation INFO: {coverage_percent:.1f}% of route is covered by teig polygons")
            print(f"  {100-coverage_percent:.1f}% of route passes through areas without teig coverage:")
            print("  - Unregistered areas (fjell, vann, offentlig område)")
            print("  - Areas without teig polygons")
            print("  - This is normal for mountain/fjell routes")

        print("\nRoute length per matrikkelenhet:")
        print("-" * 80)
        for mat_id in sorted(unique_mats):
            mat_details = next((m for m in matrikkelenheter if m['matrikkelnummertekst'] == mat_id), None)
            if mat_details:
                kommunenummer = mat_details.get('kommunenummer')
                gardsnummer = mat_details.get('gardsnummer')
                bruksnummer = mat_details.get('bruksnummer')
                festenummer = mat_details.get('festenummer')

                formatted = format_matrikkelenhet(kommunenummer, gardsnummer, bruksnummer, festenummer)
                length = matrikkel_lengths[mat_id]
                length_km = length / 1000.0

                name_part = ""
                if mat_details.get('bruksnavn'):
                    name_part = f" '{mat_details['bruksnavn']}'"

                print(f"  {formatted or mat_id:30} {name_part:30} {length:8.1f} m ({length_km:6.3f} km)")

        conn.close()
        print("\n" + "=" * 80)
        print("Proof of concept completed successfully!")
        print("=" * 80)

    except psycopg2.Error as e:
        print(f"\nDatabase error: {e}")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

