"""Rule-engine and crop-catalogue tests."""

from __future__ import annotations

from app.clients.nasa_power import parse_nasa_payload
from app.domain.crops import CROP_CATALOG, resolve_crop, resolve_crops, validate_catalog
from app.domain.scoring import evaluate_candidates, evaluate_crop
from app.schemas import AnalyzeRequest, FieldProfile
from app.services.agronomy import build_environment
from tests.helpers import climatology_payload, daily_payload, request_payload


def _environment():
    return build_environment(
        parse_nasa_payload(climatology_payload()),
        parse_nasa_payload(daily_payload()),
        FieldProfile(soil_texture="clay_loam", soil_ph=7.4, organic_matter_pct=1.8),
        recent_days=30,
    )[0]


def _request(**preference_overrides) -> AnalyzeRequest:
    payload = request_payload()
    payload["preferences"].update(preference_overrides)
    return AnalyzeRequest.model_validate(payload)


def test_crop_catalogue_is_consistent_and_resolves_aliases():
    assert validate_catalog() == []
    assert resolve_crop("buğday").key == "wheat"
    assert resolve_crop("Kışlık Buğday").key == "wheat"
    assert resolve_crop("sugar beet").key == "sugar_beet"
    assert resolve_crop("şeker pancarı").key == "sugar_beet"
    assert resolve_crop("unknown crop") is None
    found, unknown = resolve_crops(["wheat", "nohut", "nope"])
    assert {crop.key for crop in found} == {"wheat", "chickpea"}
    assert unknown == ["nope"]


def test_wheat_outranks_maize_in_ankara():
    environment = _environment()
    evaluations, warnings = evaluate_candidates(_request(), environment)
    by_key = {evaluation.crop.key: evaluation for evaluation in evaluations}
    assert by_key["wheat"].rule_score > by_key["maize"].rule_score
    assert by_key["wheat"].rule_score >= 80
    assert by_key["maize"].rule_score < 80
    assert by_key["wheat"].components["water"] > by_key["maize"].components["water"]
    assert evaluations[0].crop.key == "wheat"
    assert isinstance(warnings, list)


def test_irrigation_improves_water_balance():
    environment = _environment()
    rainfed_request = _request()
    rainfed_request.resources.irrigation = "rainfed"
    rainfed = evaluate_crop(CROP_CATALOG["wheat"], rainfed_request, environment)
    irrigated_request = _request()
    irrigated_request.resources.irrigation = "full"
    irrigated_request.resources.water_availability = "high"
    irrigated = evaluate_crop(CROP_CATALOG["wheat"], irrigated_request, environment)

    assert rainfed.components["water"] is not None
    assert irrigated.components["water"] is not None
    assert irrigated.components["water"] > rainfed.components["water"]
    assert irrigated.rule_score > rainfed.rule_score


def test_excluded_crop_is_removed_with_warning():
    environment = _environment()
    evaluations, warnings = evaluate_candidates(_request(excluded_crops=["wheat"]), environment)
    assert all(evaluation.crop.key != "wheat" for evaluation in evaluations)
    assert any("excluded" in warning.lower() for warning in warnings)


def test_interest_boost_is_applied_and_bounded():
    environment = _environment()
    baseline, _ = evaluate_candidates(_request(crops_of_interest=[]), environment)
    interested, _ = evaluate_candidates(_request(crops_of_interest=["wheat"]), environment)
    baseline_wheat = next(item for item in baseline if item.crop.key == "wheat")
    interested_wheat = next(item for item in interested if item.crop.key == "wheat")
    assert interested_wheat.rule_score == min(100.0, round(baseline_wheat.rule_score + 4.0, 1))


def test_planting_month_changes_calendar_component():
    environment = _environment()
    on_time = evaluate_crop(CROP_CATALOG["wheat"], _request(planting_month=10), environment)
    late = evaluate_crop(CROP_CATALOG["wheat"], _request(planting_month=6), environment)
    assert on_time.components["calendar"] == 100
    assert late.components["calendar"] == 25
    assert late.rule_score < on_time.rule_score


def test_bad_ph_reduces_score():
    environment = _environment()
    good = evaluate_crop(CROP_CATALOG["wheat"], _request(), environment)
    bad_request = _request()
    bad_request.field.soil_ph = 4.2
    bad = evaluate_crop(CROP_CATALOG["wheat"], bad_request, environment)
    assert bad.components["ph"] == 0
    assert bad.rule_score < good.rule_score


def test_texture_mismatch_reduces_score():
    environment = _environment()
    good = evaluate_crop(CROP_CATALOG["wheat"], _request(), environment)
    sandy_request = _request()
    sandy_request.field.soil_texture = "sand"
    sandy = evaluate_crop(CROP_CATALOG["wheat"], sandy_request, environment)
    assert sandy.components["texture"] < good.components["texture"]


def test_max_growing_days_filters_candidates():
    environment = _environment()
    evaluations, warnings = evaluate_candidates(_request(max_growing_days=110), environment)
    assert evaluations
    assert all(evaluation.crop.growing_days <= 110 for evaluation in evaluations)
    assert any("season" in warning.lower() for warning in warnings)


def test_data_completeness_affects_confidence():
    environment = _environment()
    full = evaluate_crop(CROP_CATALOG["wheat"], _request(), environment)
    partial_request = _request()
    partial_request.field.soil_ph = None
    partial_request.field.organic_matter_pct = None
    partial_request.field.soil_texture = "unknown"
    partial_request.field.salinity_ds_m = None
    partial = evaluate_crop(CROP_CATALOG["wheat"], partial_request, environment)
    assert full.data_completeness > partial.data_completeness
    assert partial.confidence in {"low", "medium"}
