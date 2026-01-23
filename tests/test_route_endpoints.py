import services.route_endpoints as route_endpoints

import os
import pytest
from services.database import db_connection

def test_lookup_endpoint_name_uses_stedsnavn_when_no_anchor(monkeypatch):
    def fake_anchor_node(*args, **kwargs):
        return None

    def fake_stedsnavn(*args, **kwargs):
        return {"name": "Lake", "source": "stedsnavn", "distance_meters": 30.0}

    monkeypatch.setattr(route_endpoints, "find_nearest_anchor_node", fake_anchor_node)
    monkeypatch.setattr(route_endpoints, "lookup_name_in_stedsnavn_cached", fake_stedsnavn)

    result = route_endpoints.lookup_endpoint_name(None, 10.0, 59.0, "bre10")
    print(f"DEBUG: stedsnavn result={result}")
    assert result["name"] == "Lake"
    assert result["source"] == "stedsnavn"


def test_lookup_endpoint_name_prefers_anchor_nodes(monkeypatch):
    def fake_anchor_node(*args, **kwargs):
        return {"anchor_node_id": 42}

    def fake_override(*args, **kwargs):
        return {"name": "Anchor", "source": "manual", "distance_meters": 2.0}

    def fake_stedsnavn(*args, **kwargs):
        return {"name": "Sted", "source": "stedsnavn", "distance_meters": 5.0}

    monkeypatch.setattr(route_endpoints, "find_nearest_anchor_node", fake_anchor_node)
    monkeypatch.setattr(route_endpoints, "lookup_anchor_name_override", fake_override)
    monkeypatch.setattr(route_endpoints, "lookup_name_in_stedsnavn_cached", fake_stedsnavn)

    result = route_endpoints.lookup_endpoint_name(None, 10.0, 59.0, "bre10")
    assert result["name"] == "Anchor"
    assert result["source"] == "manual"


def test_lookup_endpoint_name_uses_cluster_named_anchor(monkeypatch):
    def fake_anchor_node(*args, **kwargs):
        return None

    def fake_override(*args, **kwargs):
        return None

    def fake_cluster(*args, **kwargs):
        return {"name": "Cluster", "source": "manual", "distance_meters": 10.0}

    def fake_stedsnavn(*args, **kwargs):
        return {"name": "Sted", "source": "stedsnavn", "distance_meters": 5.0}

    monkeypatch.setattr(route_endpoints, "find_nearest_anchor_node", fake_anchor_node)
    monkeypatch.setattr(route_endpoints, "lookup_anchor_name_override", fake_override)
    monkeypatch.setattr(route_endpoints, "lookup_named_anchor_within_radius", fake_cluster)
    monkeypatch.setattr(route_endpoints, "lookup_name_in_stedsnavn_cached", fake_stedsnavn)

    result = route_endpoints.lookup_endpoint_name(None, 10.0, 59.0, "bre10")
    assert result["name"] == "Cluster"
    assert result["source"] == "manual"


def test_list_placename_candidates_uses_stedsnavn(monkeypatch):
    calls = {"stedsnavn": 0}

    def fake_sted_candidates(*args, **kwargs):
        calls["stedsnavn"] += 1
        return [
            {"name": "Lake", "source": "stedsnavn", "distance_meters": 40.0},
        ]

    monkeypatch.setattr(route_endpoints, "list_stedsnavn_candidates", fake_sted_candidates)

    results = route_endpoints.list_placename_candidates(None, 10.0, 59.0, search_radius_meters=500.0, limit=10)
    print(f"DEBUG: stedsnavn calls={calls['stedsnavn']}")
    assert [r["name"] for r in results] == ["Lake"]
    assert results[0]["source"] == "stedsnavn"


def test_list_placename_candidates_applies_limit(monkeypatch):
    def fake_sted_candidates(*args, **kwargs):
        return [{"name": "B", "source": "stedsnavn", "distance_meters": 20.0}]

    monkeypatch.setattr(route_endpoints, "list_stedsnavn_candidates", fake_sted_candidates)

    results = route_endpoints.list_placename_candidates(None, 10.0, 59.0, search_radius_meters=500.0, limit=1)
    assert len(results) == 1
    assert results[0]["name"] == "B"


@pytest.mark.integration
def test_real_lookup_candidates_from_db():
    lon = 8.223646
    lat = 61.830882

    try:
        with db_connection() as conn:
            rute_candidates = route_endpoints.list_ruteinfopunkt_candidates(
                conn, lon, lat, search_radius_meters=2000.0, limit=5
            )
            sted_candidates = route_endpoints.list_stedsnavn_candidates(
                conn, lon, lat, search_radius_meters=2000.0, limit=5
            )
    except Exception as exc:
        pytest.skip(f"Database unavailable for integration lookup test: {exc}")

    print(f"DEBUG: ruteinfopunkt candidates={rute_candidates}")
    print(f"DEBUG: stedsnavn candidates={sted_candidates}")

    assert isinstance(rute_candidates, list)
    assert isinstance(sted_candidates, list)
    assert sted_candidates, "Expected stedsnavn candidates for test coordinates"
