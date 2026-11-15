"""Soil-health and water-balance tests."""

from __future__ import annotations

import pytest

BASE_PLAN = {
    "location": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
    "area_hectares": 10.0,
    "soil_texture": "clay_loam",
    "soil_ph": 7.4,
    "organic_matter_pct": 1.8,
    "salinity_ds_m": 1.2,
    "drainage": "medium",
    "slope_pct": 3,
    "irrigation": "limited",
    "water_availability": "medium",
    "goal": "max_profit",
    "planting_month": 10,
    "rotation_years": 3,
    "top_n": 3,
    "language": "tr",
}


def _plan(client, **overrides):
    payload = dict(BASE_PLAN)
    payload.update(overrides)
    response = client.post("/api/v1/farm-plan", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_soil_report_has_all_indicators(client):
    soil = _plan(client)["soil_health"]

    assert soil["grade"] in {"A", "B", "C", "D"}
    assert 0 <= soil["score"] <= 100
    assert soil["label"]
    assert soil["summary"]
    assert soil["actions"]
    assert soil["outlook"]

    keys = [indicator["key"] for indicator in soil["indicators"]]
    assert keys == [
        "organic_matter",
        "ph",
        "texture",
        "salinity",
        "drainage",
        "moisture",
        "soil_temp",
        "slope",
        "rotation",
    ]
    for indicator in soil["indicators"]:
        assert indicator["label"]
        assert indicator["status"] in {"iyi", "orta", "zayıf", "bilinmiyor"}
        assert indicator["advice"]


def test_soil_report_is_honest_about_unknowns(client):
    soil = _plan(
        client,
        soil_texture="unknown",
        soil_ph=None,
        organic_matter_pct=None,
        salinity_ds_m=None,
        slope_pct=None,
    )["soil_health"]

    assert soil["score"] is not None
    assert soil["data_gaps"]
    missing = [item for item in soil["indicators"] if item["score"] is None]
    assert missing
    assert any("N-P-K" in gap or "analiz" in gap.lower() for gap in soil["data_gaps"])


def test_good_soil_scores_better_than_poor_soil(client):
    good = _plan(
        client,
        soil_texture="loam",
        soil_ph=6.8,
        organic_matter_pct=3.4,
        salinity_ds_m=0.4,
        drainage="good",
        slope_pct=1,
    )["soil_health"]
    poor = _plan(
        client,
        soil_texture="clay",
        soil_ph=9.0,
        organic_matter_pct=0.4,
        salinity_ds_m=8.0,
        drainage="poor",
        slope_pct=20,
    )["soil_health"]

    assert good["score"] > poor["score"]
    assert good["grade"] <= poor["grade"]


def test_water_numbers_are_consistent(client):
    water = _plan(client, area_hectares=10.0)["water"]

    assert water["crop_need_mm"] > 0
    assert water["season_rain_mm"] >= 0
    assert water["deficit_mm"] >= 0
    assert water["deficit_m3"] == pytest.approx(water["area_decare"] * water["deficit_mm"], rel=1e-3)
    # 1 mm over 1 decare is 1 tonne.
    assert water["deficit_ton_per_decare"] == pytest.approx(water["deficit_mm"], abs=0.5)
    assert water["summary"]
    assert water["tips"]
    assert len(water["months"]) == 12
    for month in water["months"]:
        assert month["status"] in {"kurak", "kuru", "yeterli", "bilinmiyor"}


def test_water_deficit_scales_with_field_size(client):
    small = _plan(client, area_hectares=2.0)["water"]
    large = _plan(client, area_hectares=20.0)["water"]

    assert small["deficit_mm"] == pytest.approx(large["deficit_mm"], abs=0.5)
    assert large["deficit_m3"] == pytest.approx(small["deficit_m3"] * 10, rel=0.05)


def test_rainfed_field_gets_water_saving_tips(client):
    rainfed = _plan(client, irrigation="rainfed", water_availability="low")["water"]

    assert rainfed["irrigation_supply_mm"] == 0
    assert rainfed["tips"]
    assert any(
        word in " ".join(rainfed["tips"]).lower()
        for word in ("yağmur", "sulama", "malç", "az su", "damla")
    )


def test_full_irrigation_reduces_reported_deficit(client):
    limited = _plan(client, irrigation="limited")["water"]
    full = _plan(client, irrigation="full", water_availability="high")["water"]

    assert full["irrigation_supply_mm"] > limited["irrigation_supply_mm"]
    assert full["deficit_mm"] <= limited["deficit_mm"]


def test_soil_and_water_endpoints_work_standalone(client):
    soil = client.post("/api/v1/soil-health", json=BASE_PLAN)
    assert soil.status_code == 200, soil.text
    assert soil.json()["soil_health"]["indicators"]

    water = client.post("/api/v1/water-plan", json=BASE_PLAN)
    assert water.status_code == 200, water.text
    assert water.json()["water"]["months"]
