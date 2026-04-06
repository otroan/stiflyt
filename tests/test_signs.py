from services.signs import compute_sign_report_from_links


def test_compute_sign_report_endpoints():
    links = [
        {"a_node": 1, "b_node": 2, "length_m": 100.0, "rutenummer_list": ["r1"]},
        {"a_node": 2, "b_node": 3, "length_m": 200.0, "rutenummer_list": ["r1"]},
    ]
    anchor_nodes = {
        1: {"lon": 10.0, "lat": 60.0, "name": "Start"},
        2: {"lon": 10.1, "lat": 60.1, "name": None},
        3: {"lon": 10.2, "lat": 60.2, "name": "End"},
    }
    anchor_names = {
        1: {"name": "Start"},
        3: {"name": "End"},
    }

    report = compute_sign_report_from_links(links, anchor_nodes, anchor_names, {})

    assert report["totals"]["endpoint_count"] == 2
    assert report["totals"]["junction_count"] == 0
    assert report["totals"]["sign_count"] == 2

    sign_by_id = {item["anchor_node_id"]: item for item in report["signs"]}
    assert 1 in sign_by_id and 3 in sign_by_id

    sign_1 = sign_by_id[1]
    destinations_1 = {d["anchor_node_id"]: d for d in sign_1["destinations"]}
    assert destinations_1[3]["name"] == "End"
    assert destinations_1[3]["distance_meters"] == 300.0

    sign_3 = sign_by_id[3]
    destinations_3 = {d["anchor_node_id"]: d for d in sign_3["destinations"]}
    assert destinations_3[1]["name"] == "Start"
    assert destinations_3[1]["distance_meters"] == 300.0


def test_compute_sign_report_junction_all_route_endpoints():
    """Y-shaped r1: junction has no endpoint as direct neighbor but must list all route endpoints."""
    links = [
        {"a_node": 1, "b_node": 2, "length_m": 100.0, "rutenummer_list": ["r1"]},
        {"a_node": 2, "b_node": 3, "length_m": 100.0, "rutenummer_list": ["r1"]},
        {"a_node": 3, "b_node": 4, "length_m": 100.0, "rutenummer_list": ["r1"]},
        {"a_node": 4, "b_node": 5, "length_m": 100.0, "rutenummer_list": ["r1"]},
        {"a_node": 3, "b_node": 6, "length_m": 100.0, "rutenummer_list": ["r1"]},
        {"a_node": 6, "b_node": 7, "length_m": 100.0, "rutenummer_list": ["r1"]},
    ]
    anchor_nodes = {
        1: {"lon": 10.0, "lat": 60.0, "name": "ArmA"},
        2: {"lon": 10.1, "lat": 60.1, "name": None},
        3: {"lon": 10.15, "lat": 60.15, "name": "Junction"},
        4: {"lon": 10.2, "lat": 60.2, "name": None},
        5: {"lon": 10.3, "lat": 60.3, "name": "ArmB"},
        6: {"lon": 10.16, "lat": 60.16, "name": None},
        7: {"lon": 10.17, "lat": 60.17, "name": "ArmC"},
    }
    anchor_names = {
        1: {"name": "ArmA"},
        3: {"name": "Junction"},
        5: {"name": "ArmB"},
        7: {"name": "ArmC"},
    }

    report = compute_sign_report_from_links(links, anchor_nodes, anchor_names, {})
    sign_by_id = {item["anchor_node_id"]: item for item in report["signs"]}
    assert 3 in sign_by_id
    assert sign_by_id[3]["is_junction"] is True
    dest = {d["anchor_node_id"]: d for d in sign_by_id[3]["destinations"]}
    assert set(dest) == {1, 5, 7}
    assert dest[1]["distance_meters"] == 200.0
    assert dest[5]["distance_meters"] == 200.0
    assert dest[7]["distance_meters"] == 200.0
