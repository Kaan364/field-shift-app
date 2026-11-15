"""End-to-end tests for the one-request farmer plan (`/api/v1/farm-plan`)."""

from __future__ import annotations

import pytest

from tests.helpers import FakeNASA

PLAN = {
    "location": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
    "area_hectares": 12.5,
    "soil_texture": "clay_loam",
    "soil_ph": 7.4,
    "organic_matter_pct": 1.8,
    "irrigation": "limited",
    "water_availability": "medium",
    "goal": "max_profit",
    "planting_month": 10,
    "free_text": "Toprağım yoruldu, suyum az.",
    "rotation_years": 3,
    "top_n": 3,
    "language": "tr",
}


def test_farm_plan_is_complete(client):
    response = client.post("/api/v1/farm-plan", json=PLAN)
    assert response.status_code == 200, response.text
    data = response.json()

    for key in (
        "plan_id",
        "generated_at",
        "language",
        "location",
        "environment",
        "recommendations",
        "advice",
        "rotation",
        "soil_health",
        "water",
        "climate",
        "summary",
        "warnings",
        "data_sources",
        "ai",
        "disclaimer",
    ):
        assert key in data, key

    assert data["plan_id"]
    assert data["location"]["region_name"] == "Ankara"
    assert data["language"] == "tr"
    assert data["summary"]
    assert data["disclaimer"]
    assert "decision support" in data["disclaimer"].lower()
    assert data["data_sources"]
    assert data["ai"]["used"] is True


def test_farm_plan_recommendations_are_ranked_and_explained(client):
    data = client.post("/api/v1/farm-plan", json=PLAN).json()
    recs = data["recommendations"]

    assert 1 <= len(recs) <= 3
    scores = [rec["scores"]["final_score"] for rec in recs]
    assert scores == sorted(scores, reverse=True)
    assert [rec["rank"] for rec in recs] == list(range(1, len(recs) + 1))
    for rec in recs:
        assert rec["rationale"]
        assert rec["actions"]
        assert rec["risks"]
        assert rec["planting_window"]


def test_farm_plan_climate_section_has_trends(client):
    climate = client.post("/api/v1/farm-plan", json=PLAN).json()["climate"]

    assert climate["available"] is True
    assert climate["start_year"] <= climate["end_year"]
    assert climate["available_years"] >= 20
    assert climate["risk_level"] in {"low", "medium", "high", "unknown"}
    assert climate["risk_label"]
    assert climate["messages"]
    keys = {trend["key"] for trend in climate["trends"]}
    assert {"temperature", "precipitation"} <= keys
    for trend in climate["trends"]:
        assert trend["direction"] in {"up", "down", "stable"}
        assert trend["message"]
        assert trend["unit"]


def test_farm_plan_degrades_gracefully_without_annual_data(settings):
    from fastapi.testclient import TestClient

    from app.ai.heuristic import HeuristicProvider
    from app.main import create_app

    nasa = FakeNASA(annual={})
    app = create_app(settings, nasa_client=nasa, ai_provider=HeuristicProvider())
    with TestClient(app) as client:
        response = client.post("/api/v1/farm-plan", json=PLAN)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["rotation"]["years"]
    assert data["soil_health"]["score"] is not None
    assert data["water"]["deficit_mm"] >= 0
    assert any("trend" in warning.lower() for warning in data["warnings"])


@pytest.mark.parametrize(
    "override",
    [
        {"area_hectares": 0},
        {"area_hectares": 2_000_000},
        {"rotation_years": 5},
        {"rotation_years": 1},
        {"soil_ph": 2},
        {"top_n": 0},
    ],
)
def test_farm_plan_validation(client, override):
    payload = dict(PLAN)
    payload.update(override)
    response = client.post("/api/v1/farm-plan", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("irrigation", ["rainfed", "limited", "full"])
def test_farm_plan_works_for_every_irrigation_choice(client, irrigation):
    payload = dict(PLAN)
    payload["irrigation"] = irrigation
    payload["water_availability"] = {"rainfed": "low", "limited": "medium", "full": "high"}[irrigation]
    response = client.post("/api/v1/farm-plan", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["water"]["summary"]


def test_farm_plan_without_optional_soil_data(client):
    payload = dict(PLAN)
    for key in ("soil_texture", "soil_ph", "organic_matter_pct"):
        payload.pop(key, None)
    response = client.post("/api/v1/farm-plan", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["soil_health"]["data_gaps"]


def test_farm_plan_nasa_failure_is_a_clean_502(settings):
    from fastapi.testclient import TestClient

    from app.ai.heuristic import HeuristicProvider
    from app.main import create_app

    app = create_app(
        settings,
        nasa_client=FakeNASA(error="NASA down"),
        ai_provider=HeuristicProvider(),
    )
    with TestClient(app) as client:
        response = client.post("/api/v1/farm-plan", json=PLAN)

    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "nasa_power_unavailable"
    assert body["request_id"]
