"""Agronomy interpretation tests (pure functions, no network)."""

from __future__ import annotations

from app.clients.nasa_power import parse_nasa_payload
from app.domain.crops import CROP_CATALOG
from app.schemas import FieldProfile
from app.services.agronomy import build_environment, season_metrics
from tests.helpers import climatology_payload, daily_payload


def _environment():
    climatology = parse_nasa_payload(climatology_payload())
    daily = parse_nasa_payload(daily_payload())
    return build_environment(
        climatology,
        daily,
        FieldProfile(
            soil_texture="clay_loam",
            soil_ph=7.4,
            organic_matter_pct=1.8,
            salinity_ds_m=1.2,
        ),
        recent_days=30,
    )


def test_climate_summary_matches_known_values():
    environment, notes = _environment()
    climate = environment.climate

    assert climate.annual_precip_mm == 418.2
    assert climate.annual_mean_temp_c == 10.31
    assert climate.annual_evapotranspiration_mm > 1000
    assert climate.aridity_index is not None
    assert 0 < climate.aridity_index < 1
    assert climate.climate_class == "semi_arid"
    assert climate.growing_season_days == 244
    assert "January" in climate.frost_months
    assert "July" in climate.heat_stress_months
    assert environment.nasa_elevation_m == 1128.1
    assert len(environment.monthly) == 12
    assert notes


def test_soil_summary_is_bounded_and_flags_gaps():
    environment, _ = _environment()
    soil = environment.soil
    assert soil.soil_condition_score is not None
    assert 0 <= soil.soil_condition_score <= 100
    assert soil.soil_condition_label in {"good", "fair", "poor", "very poor"}
    assert soil.soil_ph == 7.4
    assert soil.root_zone_moisture_mean == 0.551
    assert any("N-P-K" in gap for gap in soil.data_gaps)


def test_recent_weather_ignores_fill_values_and_computes_dry_spell():
    environment, _ = _environment()
    recent = environment.recent_weather
    assert recent is not None
    assert recent.available_days == 27
    assert recent.total_precip_mm == 20.0
    assert recent.rainy_days == 4
    assert recent.longest_dry_spell_days == 11
    assert recent.min_temp_c == 2.0
    assert recent.max_temp_c == 23.2


def test_season_metrics_use_crop_calendar():
    environment, _ = _environment()
    wheat = CROP_CATALOG["wheat"]
    season = season_metrics(environment, wheat, preferred_month=10)
    assert season.start_month == 10
    assert season.months == (10, 11, 12, 1, 2, 3, 4, 5)
    assert season.window_label == "October–May"
    assert season.mean_temp_c is not None and season.mean_temp_c < 8
    assert season.total_precip_mm is not None and 320 < season.total_precip_mm < 340
    assert len(season.frost_months) == 8


def test_monthly_values_are_complete():
    environment, _ = _environment()
    january = environment.monthly[0]
    assert january.month == "January"
    assert january.mean_temp_c == -2.08
    assert january.frost_risk is True
    assert january.precip_month_mm == 49.6
    assert january.root_zone_moisture == 0.61
    july = environment.monthly[6]
    assert july.heat_stress is True
    assert july.soil_temp_c == 24.41
