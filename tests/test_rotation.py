"""Crop-rotation planner tests.

These cover the two things that matter for a farmer-facing rotation: the
agronomic invariants (no repeated crop, no same-family neighbour) and the
promise that year 1 agrees with the single-season recommendation.
"""

from __future__ import annotations

import pytest

from app.domain.rotation import GOAL_WEIGHTS, score_label
from app.schemas import Goal

BASE_PLAN = {
    "location": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
    "area_hectares": 12.5,
    "soil_texture": "clay_loam",
    "soil_ph": 7.4,
    "organic_matter_pct": 1.8,
    "salinity_ds_m": 1.2,
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


def test_goal_weights_sum_to_one():
    for goal, weights in GOAL_WEIGHTS.items():
        assert set(weights) == {"soil", "water", "resilience", "profit", "risk"}, goal
        assert sum(weights.values()) == pytest.approx(1.0), goal


def test_default_rotation_has_three_distinct_years(client):
    rotation = _plan(client)["rotation"]

    assert rotation["applicable"] is True
    assert rotation["years_requested"] == 3
    assert len(rotation["years"]) == 3

    crops = [year["crop_key"] for year in rotation["years"]]
    assert len(crops) == len(set(crops)), crops
    assert all(year["year"] == index for index, year in enumerate(rotation["years"], start=1))

    families = [year["family"] for year in rotation["years"]]
    for previous, current in zip(families, families[1:]):
        assert previous != current, families


def test_rotation_year_one_matches_best_single_crop(client):
    plan = _plan(client)
    top = plan["recommendations"][0]
    first = plan["rotation"]["years"][0]

    assert first["crop_key"] == top["crop_key"]
    assert first["crop_name_local"] == top["crop_name_local"]


@pytest.mark.parametrize("years", [2, 3, 4])
def test_requested_rotation_length_is_respected(client, years):
    rotation = _plan(client, rotation_years=years)["rotation"]
    assert len(rotation["years"]) == years
    assert rotation["summary"]
    assert rotation["benefits"]


def test_rotation_explains_itself(client):
    rotation = _plan(client)["rotation"]

    assert rotation["headline"]
    assert rotation["summary"]
    assert 0 <= rotation["scores"]["overall"] <= 100
    for key in ("soil_health", "water", "resilience", "profit", "risk"):
        assert 0 <= rotation["scores"][key] <= 100, key
    assert rotation["cautions"]
    assert rotation["alternatives"]
    for alternative in rotation["alternatives"]:
        assert len(alternative["crop_names"]) == len(rotation["years"])
        assert alternative["total_water_mm"] > 0

    for year in rotation["years"]:
        assert year["icon"]
        assert year["family_label"]
        assert year["planting_window"]
        assert year["water_need_mm"] > 0
        assert year["benefit"]
        assert year["actions"]


def test_previous_crop_does_not_repeat_in_year_one(client):
    rotation = _plan(client, previous_crop="wheat")["rotation"]
    assert rotation["years"][0]["crop_key"] != "wheat"


def test_low_water_goal_prefers_thriftier_rotation(client):
    profit = _plan(client, goal="max_profit")["rotation"]
    thrifty = _plan(client, goal="low_water")["rotation"]

    profit_water = sum(year["water_need_mm"] for year in profit["years"])
    thrifty_water = sum(year["water_need_mm"] for year in thrifty["years"])

    assert thrifty["scores"]["water"] >= profit["scores"]["water"]
    assert thrifty_water <= profit_water * 1.15


def test_score_labels_are_plain_turkish():
    assert score_label(None) == "bilinmiyor"
    assert score_label(95) == "çok iyi"
    assert score_label(72) == "iyi"
    assert score_label(60) == "orta"
    assert score_label(45) == "zayıf"
    assert score_label(10) == "çok zayıf"


def test_rotation_endpoint_returns_a_rotation_without_advice(client):
    response = client.post("/api/v1/rotation", json=BASE_PLAN)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["rotation"]["applicable"] is True
    assert len(data["rotation"]["years"]) == 3
    assert data["environment"]["climate"]["annual_precip_mm"] > 0
    assert isinstance(data["warnings"], list)


def test_all_goals_produce_a_valid_rotation(client):
    for goal in Goal:
        rotation = _plan(client, goal=goal.value)["rotation"]
        assert rotation["applicable"] is True, goal
        assert len(rotation["years"]) >= 2, goal
