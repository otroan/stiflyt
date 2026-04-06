#!/usr/bin/env python3
"""
Investigate route 20160407 endpoint detection bug.

The route should go from Sunndalssetra to a junction, but the tool thinks
it goes from Slæom to Sunndalssetra. The link from Slæom to that junction
does NOT have rutenummer 20160407.
"""

import sys
from services.database import get_db_connection, ROUTE_SCHEMA
from psycopg.rows import dict_row


def check_has_navn_column(conn):
    """Check if anchor_nodes has navn column."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'anchor_nodes'
                  AND column_name = 'navn'
            )
        """, (ROUTE_SCHEMA,))
        return cur.fetchone()[0]


def get_node_names(conn, node_ids):
    """Get node names from ops.endpoint_names if available."""
    names = {}
    try:
        from services.operational_database import op_db_connection
        from services.operational_store import get_endpoint_names_for_anchors
        with op_db_connection() as op_conn:
            name_dict = get_endpoint_names_for_anchors(op_conn, node_ids, rutenummer=None)
            for node_id, info in name_dict.items():
                if info and info.get("name"):
                    names[node_id] = info.get("name")
    except Exception:
        pass  # Operational DB might not be available
    return names


def investigate_route(rutenummer: str):
    """Investigate a specific route's endpoint detection."""

    with get_db_connection() as conn:
        has_navn = check_has_navn_column(conn)
        navn_select = "an_a.navn as a_node_name, an_b.navn as b_node_name" if has_navn else "NULL as a_node_name, NULL as b_node_name"

        # 1. Get all links for this route
        print(f"\n=== Links with route {rutenummer} ===")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                SELECT
                    lwr.link_id,
                    lwr.a_node,
                    lwr.b_node,
                    lwr.rutenummer_list,
                    lwr.segment_objids,
                    {navn_select}
                FROM {ROUTE_SCHEMA}.links_with_routes lwr
                LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_a ON an_a.node_id = lwr.a_node
                LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_b ON an_b.node_id = lwr.b_node
                WHERE %s = ANY(lwr.rutenummer_list)
                ORDER BY lwr.link_id
            """, (rutenummer,))

            links = cur.fetchall()
            print(f"Found {len(links)} links with route {rutenummer}")

            # Get node names from ops.endpoint_names
            all_node_ids = []
            for link in links:
                if link['a_node']:
                    all_node_ids.append(int(link['a_node']))
                if link['b_node']:
                    all_node_ids.append(int(link['b_node']))
            node_names = get_node_names(conn, list(set(all_node_ids)))

            for link in links:
                a_name = node_names.get(link['a_node']) if link['a_node'] else None
                b_name = node_names.get(link['b_node']) if link['b_node'] else None
                a_display = a_name or link.get('a_node_name') or f"node_{link['a_node']}"
                b_display = b_name or link.get('b_node_name') or f"node_{link['b_node']}"

                print(f"\n  Link {link['link_id']}:")
                print(f"    Nodes: {link['a_node']} ({a_display}) -> {link['b_node']} ({b_display})")
                print(f"    Routes: {link['rutenummer_list']}")
                if link['segment_objids']:
                    print(f"    Segments: {link['segment_objids'][:5]}..." if len(link['segment_objids']) > 5 else f"    Segments: {link['segment_objids']}")

        # 2. Replicate the endpoint detection logic
        print(f"\n=== Endpoint Detection Logic (as in route_service.py) ===")
        navn_select_endpoints = "an_a.navn as first_node_name, an_b.navn as last_node_name" if has_navn else "NULL as first_node_name, NULL as last_node_name"
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                WITH route_links_expanded AS (
                    SELECT
                        UNNEST(lwr.rutenummer_list) as rutenummer,
                        lwr.link_id,
                        lwr.a_node,
                        lwr.b_node
                    FROM {ROUTE_SCHEMA}.links_with_routes lwr
                    WHERE lwr.rutenummer_list && ARRAY[%s]
                ),
                route_nodes AS (
                    SELECT
                        rutenummer,
                        node_id,
                        COUNT(*) as occurrence_count,
                        array_agg(DISTINCT link_id ORDER BY link_id) as link_ids
                    FROM (
                        SELECT rutenummer, a_node as node_id, link_id FROM route_links_expanded
                        UNION ALL
                        SELECT rutenummer, b_node as node_id, link_id FROM route_links_expanded
                    ) all_nodes
                    WHERE rutenummer = %s
                    GROUP BY rutenummer, node_id
                ),
                route_endpoints AS (
                    SELECT
                        rutenummer,
                        MIN(node_id) FILTER (WHERE occurrence_count = 1) as first_node,
                        MAX(node_id) FILTER (WHERE occurrence_count = 1) as last_node
                    FROM route_nodes
                    GROUP BY rutenummer
                )
                SELECT
                    re.rutenummer,
                    re.first_node,
                    re.last_node,
                    {navn_select_endpoints}
                FROM route_endpoints re
                LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_a ON an_a.node_id = re.first_node
                LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_b ON an_b.node_id = re.last_node
            """, (rutenummer, rutenummer))

            endpoint = cur.fetchone()
            if endpoint:
                first_name = node_names.get(endpoint['first_node']) if endpoint['first_node'] else None
                last_name = node_names.get(endpoint['last_node']) if endpoint['last_node'] else None
                first_display = first_name or endpoint.get('first_node_name') or f"node_{endpoint['first_node']}"
                last_display = last_name or endpoint.get('last_node_name') or f"node_{endpoint['last_node']}"

                print(f"\n  Detected endpoints:")
                print(f"    First node: {endpoint['first_node']} ({first_display})")
                print(f"    Last node: {endpoint['last_node']} ({last_display})")
            else:
                print("  No endpoints detected!")

        # 3. Show node occurrence counts
        print(f"\n=== Node Occurrence Counts ===")
        navn_select_nodes = "an.navn as node_name" if has_navn else "NULL as node_name"
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                WITH route_links_expanded AS (
                    SELECT
                        UNNEST(lwr.rutenummer_list) as rutenummer,
                        lwr.link_id,
                        lwr.a_node,
                        lwr.b_node
                    FROM {ROUTE_SCHEMA}.links_with_routes lwr
                    WHERE lwr.rutenummer_list && ARRAY[%s]
                ),
                route_nodes AS (
                    SELECT
                        node_id,
                        COUNT(*) as occurrence_count,
                        array_agg(DISTINCT link_id ORDER BY link_id) as link_ids
                    FROM (
                        SELECT rutenummer, a_node as node_id, link_id FROM route_links_expanded WHERE rutenummer = %s
                        UNION ALL
                        SELECT rutenummer, b_node as node_id, link_id FROM route_links_expanded WHERE rutenummer = %s
                    ) all_nodes
                    GROUP BY node_id
                )
                SELECT
                    rn.node_id,
                    rn.occurrence_count,
                    rn.link_ids,
                    {navn_select_nodes}
                FROM route_nodes rn
                LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an ON an.node_id = rn.node_id
                ORDER BY rn.occurrence_count, rn.node_id
            """, (rutenummer, rutenummer, rutenummer))

            nodes = cur.fetchall()
            print(f"\n  Node occurrence counts:")
            for node in nodes:
                node_name = node_names.get(node['node_id']) if node['node_id'] else None
                node_display = node_name or node.get('node_name') or f"node_{node['node_id']}"
                endpoint_marker = " [ENDPOINT]" if node['occurrence_count'] == 1 else ""
                print(f"    Node {node['node_id']} ({node_display}): appears {node['occurrence_count']} time(s){endpoint_marker}")
                if node['occurrence_count'] == 1:
                    print(f"      Links: {node['link_ids']}")

        # 4. Compare with bre26 (should be duplicate)
        print(f"\n=== Comparison with bre26 ===")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                SELECT
                    lwr.link_id,
                    lwr.a_node,
                    lwr.b_node,
                    lwr.rutenummer_list,
                    {navn_select},
                    CASE
                        WHEN '20160407' = ANY(lwr.rutenummer_list) AND 'bre26' = ANY(lwr.rutenummer_list) THEN 'SHARED'
                        WHEN '20160407' = ANY(lwr.rutenummer_list) THEN 'ONLY_20160407'
                        WHEN 'bre26' = ANY(lwr.rutenummer_list) THEN 'ONLY_bre26'
                    END as route_marker
                FROM {ROUTE_SCHEMA}.links_with_routes lwr
                LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_a ON an_a.node_id = lwr.a_node
                LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_b ON an_b.node_id = lwr.b_node
                WHERE '20160407' = ANY(lwr.rutenummer_list) OR 'bre26' = ANY(lwr.rutenummer_list)
                ORDER BY lwr.link_id
            """)

            comparison_links = cur.fetchall()
            print(f"\n  Links comparison:")
            shared_count = sum(1 for l in comparison_links if l['route_marker'] == 'SHARED')
            only_20160407 = sum(1 for l in comparison_links if l['route_marker'] == 'ONLY_20160407')
            only_bre26 = sum(1 for l in comparison_links if l['route_marker'] == 'ONLY_bre26')

            print(f"    Shared links: {shared_count}")
            print(f"    Only 20160407: {only_20160407}")
            print(f"    Only bre26: {only_bre26}")

            if only_20160407 > 0:
                print(f"\n  ⚠️  Found {only_20160407} links that have 20160407 but NOT bre26:")
                for link in comparison_links:
                    if link['route_marker'] == 'ONLY_20160407':
                        a_name = node_names.get(link['a_node']) if link['a_node'] else None
                        b_name = node_names.get(link['b_node']) if link['b_node'] else None
                        a_display = a_name or link.get('a_node_name') or f"node_{link['a_node']}"
                        b_display = b_name or link.get('b_node_name') or f"node_{link['b_node']}"
                        print(f"    Link {link['link_id']}: {link['a_node']} ({a_display}) -> {link['b_node']} ({b_display})")
                        print(f"      Routes: {link['rutenummer_list']}")

            if only_bre26 > 0:
                print(f"\n  ⚠️  Found {only_bre26} links that have bre26 but NOT 20160407:")
                for link in comparison_links:
                    if link['route_marker'] == 'ONLY_bre26':
                        a_name = node_names.get(link['a_node']) if link['a_node'] else None
                        b_name = node_names.get(link['b_node']) if link['b_node'] else None
                        a_display = a_name or link.get('a_node_name') or f"node_{link['a_node']}"
                        b_display = b_name or link.get('b_node_name') or f"node_{link['b_node']}"
                        print(f"    Link {link['link_id']}: {link['a_node']} ({a_display}) -> {link['b_node']} ({b_display})")
                        print(f"      Routes: {link['rutenummer_list']}")

        # 5. Check segments to see which links should actually have this route
        print(f"\n=== Segment-based validation ===")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                SELECT DISTINCT
                    rs.segment_objid,
                    rs.rutenummer
                FROM {ROUTE_SCHEMA}.route_segments rs
                WHERE rs.rutenummer = %s
            """, (rutenummer,))

            segments = cur.fetchall()
            segment_objids = [s['segment_objid'] for s in segments]
            print(f"  Found {len(segments)} segments with route {rutenummer}")

            # Check which links contain these segments
            if segment_objids:
                cur.execute(f"""
                    SELECT DISTINCT
                        lwr.link_id,
                        lwr.a_node,
                        lwr.b_node,
                        lwr.rutenummer_list,
                        lwr.segment_objids,
                        {navn_select},
                        CASE
                            WHEN lwr.segment_objids && %s::bigint[] THEN 'HAS_SEGMENTS'
                            ELSE 'NO_SEGMENTS'
                        END as validation
                    FROM {ROUTE_SCHEMA}.links_with_routes lwr
                    LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_a ON an_a.node_id = lwr.a_node
                    LEFT JOIN {ROUTE_SCHEMA}.anchor_nodes an_b ON an_b.node_id = lwr.b_node
                    WHERE %s = ANY(lwr.rutenummer_list)
                """, (segment_objids, rutenummer))

                validated_links = cur.fetchall()
                invalid_links = [l for l in validated_links if l['validation'] == 'NO_SEGMENTS']

                if invalid_links:
                    print(f"\n  ⚠️  BUG FOUND: {len(invalid_links)} links have route {rutenummer} but don't contain any segments with that route:")
                    for link in invalid_links:
                        a_name = node_names.get(link['a_node']) if link['a_node'] else None
                        b_name = node_names.get(link['b_node']) if link['b_node'] else None
                        a_display = a_name or link.get('a_node_name') or f"node_{link['a_node']}"
                        b_display = b_name or link.get('b_node_name') or f"node_{link['b_node']}"
                        print(f"    Link {link['link_id']}: {link['a_node']} ({a_display}) -> {link['b_node']} ({b_display})")
                        print(f"      Routes: {link['rutenummer_list']}")
                        print(f"      Segments: {link['segment_objids']}")
                else:
                    print(f"  ✓ All links with route {rutenummer} contain matching segments")


if __name__ == "__main__":
    rutenummer = sys.argv[1] if len(sys.argv) > 1 else "20160407"
    investigate_route(rutenummer)
