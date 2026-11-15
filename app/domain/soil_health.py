"""Farmer-friendly soil-health report.

Combines farmer-reported soil information (texture, pH, organic matter,
salinity, drainage, slope) with NASA POWER soil-moisture/temperature proxies
and, when available, the diversity of the proposed rotation.

NASA POWER does **not** provide N-P-K, pH or organic matter. Those values are
farmer/laboratory inputs, and the report says so explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.crops import TEXTURE_GROUP
from app.domain.rotation import RotationResult
from app.schemas import Drainage, EnvironmentSnapshot, FieldProfile, SoilTexture
from app.services.agronomy import band_score

INDICATOR_WEIGHTS = {
    "organic_matter": 0.22,
    "ph": 0.14,
    "texture": 0.14,
    "salinity": 0.09,
    "drainage": 0.08,
    "moisture": 0.12,
    "soil_temp": 0.06,
    "slope": 0.05,
    "rotation": 0.10,
}

TEXTURE_LABELS = {
    SoilTexture.UNKNOWN: "I don't know",
    SoilTexture.SAND: "Sand",
    SoilTexture.LOAMY_SAND: "Loamy sand",
    SoilTexture.SANDY_LOAM: "Sandy loam",
    SoilTexture.LOAM: "Loam (ideal)",
    SoilTexture.SILT_LOAM: "Silt loam",
    SoilTexture.SILT: "Silt",
    SoilTexture.CLAY_LOAM: "Clay loam",
    SoilTexture.SANDY_CLAY_LOAM: "Sandy clay loam",
    SoilTexture.CLAY: "Clay (heavy)",
}

DRAINAGE_LABELS = {Drainage.POOR: "Poor", Drainage.MEDIUM: "Medium", Drainage.GOOD: "Good"}

TEXTURE_SCORES = {
    "medium": 100.0,
    "medium_heavy": 82.0,
    "light_medium": 74.0,
    "heavy": 58.0,
    "light": 52.0,
}


@dataclass
class SoilIndicator:
    key: str
    label: str
    value: float | None
    unit: str
    score: float | None
    status: str
    advice: str


@dataclass
class SoilHealthReport:
    score: float | None
    label: str
    grade: str
    summary: str
    indicators: list[SoilIndicator] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    outlook: str | None = None
    notes: list[str] = field(default_factory=list)


def _status(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "good"
    if score >= 55:
        return "fair"
    return "poor"


def _grade(score: float | None) -> str:
    if score is None:
        return "-"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "good"
    if score >= 65:
        return "fair to good"
    if score >= 50:
        return "fair"
    if score >= 35:
        return "poor"
    return "very poor"


def _texture_score(texture: SoilTexture) -> float | None:
    if texture == SoilTexture.UNKNOWN:
        return None
    group = TEXTURE_GROUP.get(texture.value)
    return None if group is None else TEXTURE_SCORES.get(group)


def _salinity_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 1.5:
        return 100.0
    if value <= 4.0:
        return 100.0 - (value - 1.5) * 18.0
    return max(0.0, 55.0 - (value - 4.0) * 12.0)


def _slope_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 2:
        return 100.0
    if value <= 6:
        return 82.0
    if value <= 12:
        return 55.0
    return 25.0


def _indicator_advice(key: str, score: float | None, field: FieldProfile) -> str:
    if score is None:
        return {
            "organic_matter": "Get a soil test and ask for the organic-matter percentage.",
            "ph": "Get the pH value from a soil test.",
            "texture": "Rub soil in your hand: crumbly is loam, gritty is sand, sticky is clay.",
            "salinity": "Ask for the salinity (EC) value in the soil test.",
            "slope": "Estimate or measure the slope of the field.",
        }.get(key, "This information is not available yet.")
    if score >= 80:
        return {
            "organic_matter": "Organic matter is good. Keep returning residue to the soil and never burn it.",
            "ph": "pH is suitable. No lime or acidifier is needed now.",
            "texture": "Soil texture is suitable. Keep heavy machines off wet soil to avoid compaction.",
            "salinity": "Salinity is low. Keep avoiding too much fertiliser.",
            "drainage": "Drainage is good. Keep it that way if water does not pool.",
            "moisture": "Soil moisture is in a good range.",
            "soil_temp": "Soil temperature is suitable for sowing.",
            "slope": "Slope is low; erosion risk is limited.",
            "rotation": "Rotation diversity is good.",
        }.get(key, "The condition is good.")
    if key == "organic_matter":
        return "Add 2-3 tonnes of mature manure or a green manure every year. Do not burn residue."
    if key == "ph":
        if field.soil_ph is not None and field.soil_ph < 6.0:
            return "The soil is acidic. Ask an expert how much lime to apply after a soil test."
        return "The soil is alkaline. Ask an expert about gypsum/sulphur and organic matter; check irrigation water."
    if key == "texture":
        return "Improve structure with organic matter and mulch; do not plough wet soil."
    if key == "salinity":
        return "Improve drainage, avoid excess fertiliser and do not irrigate with salty water."
    if key == "drainage":
        return "Open a drainage channel; stop water pooling on heavy soil."
    if key == "moisture":
        return "Keep soil moisture with residue/mulch; use drip irrigation and mulching."
    if key == "soil_temp":
        return "Soil temperature is borderline; sow after the soil warms up."
    if key == "slope":
        return "Reduce erosion with contour sowing, strip cropping and leaving residue."
    if key == "rotation":
        return "Add a legume or a forage crop to the rotation."
    return "Ask your local extension service how to improve this value."


def assess_soil_health(
    field: FieldProfile,
    environment: EnvironmentSnapshot,
    rotation: RotationResult | None = None,
) -> SoilHealthReport:
    soil = environment.soil
    indicators: list[SoilIndicator] = []

    def add(key: str, label: str, value: float | None, unit: str, score: float | None) -> None:
        indicators.append(
            SoilIndicator(
                key=key,
                label=label,
                value=None if value is None else round(value, 2),
                unit=unit,
                score=None if score is None else round(score, 1),
                status=_status(score),
                advice=_indicator_advice(key, score, field),
            )
        )

    add(
        "organic_matter",
        "Organic matter (humus)",
        field.organic_matter_pct,
        "%",
        band_score(field.organic_matter_pct, (3.0, 6.0), (0.0, 10.0)),
    )
    add("ph", "Soil pH", field.soil_ph, "pH", band_score(field.soil_ph, (6.2, 7.5), (4.0, 9.5)))
    add(
        "texture",
        "Soil texture",
        None,
        "",
        _texture_score(field.soil_texture),
    )
    add("salinity", "Salinity (EC)", field.salinity_ds_m, "dS/m", _salinity_score(field.salinity_ds_m))
    add(
        "drainage",
        "Drainage",
        None,
        "",
        {Drainage.GOOD: 100.0, Drainage.MEDIUM: 70.0, Drainage.POOR: 35.0}.get(field.drainage),
    )
    add(
        "moisture",
        "Soil moisture (NASA)",
        soil.root_zone_moisture_mean,
        "0-1",
        band_score(soil.root_zone_moisture_mean, (0.40, 0.70), (0.0, 1.0)),
    )
    add(
        "soil_temp",
        "Soil temperature (NASA)",
        soil.mean_soil_temp_c,
        "°C",
        band_score(soil.mean_soil_temp_c, (15.0, 25.0), (0.0, 40.0)),
    )
    add("slope", "Field slope", field.slope_pct, "%", _slope_score(field.slope_pct))

    best_rotation = rotation.best if rotation is not None and rotation.applicable else None
    add(
        "rotation",
        "Rotation diversity",
        None,
        "",
        None if best_rotation is None else best_rotation.soil,
    )

    present = [(item.score, INDICATOR_WEIGHTS[item.key]) for item in indicators if item.score is not None]
    if present:
        total_weight = sum(weight for _, weight in present)
        score = sum(value * weight for value, weight in present) / total_weight
    else:
        score = None
    score = None if score is None else round(score, 1)

    ranked = sorted(
        [item for item in indicators if item.score is not None and item.score < 65],
        key=lambda item: (item.score or 0),
    )
    actions = [item.advice for item in ranked[:3]]
    if not actions:
        actions = [
            "Your soil looks good. Test it every year and never burn residue.",
            "Add a legume to the rotation to reduce nitrogen fertiliser.",
            "Record rainfall and soil moisture; irrigate only when the crop needs it.",
        ]
    actions.append("Repeat the soil test every 2-3 years; never apply fertiliser without a test.")

    gaps: list[str] = []
    if field.soil_ph is None:
        gaps.append("pH was not entered; a soil test is needed.")
    if field.organic_matter_pct is None:
        gaps.append("Organic matter was not entered; a soil test is needed.")
    if field.soil_texture == SoilTexture.UNKNOWN:
        gaps.append("Soil texture was not entered.")
    if field.salinity_ds_m is None:
        gaps.append("Salinity (EC) was not entered.")
    gaps.append("NASA POWER does not provide N-P-K, pH or organic matter; these are farmer/lab values.")

    outlook = None
    if score is not None:
        legume = bool(best_rotation and any(year.traits.nitrogen_fixing for year in best_rotation.years))
        if score < 55:
            outlook = "Soil is weak. This plan can improve organic matter and structure in 2-3 years; be patient in year one."
        elif legume:
            outlook = "This rotation adds nitrogen and organic matter; expect improvement in 2-3 years."
        else:
            outlook = "Keep protecting the soil with residue cover, reduced tillage and a legume in the rotation."

    if score is None:
        summary = "The soil report card is not ready. Enter at least pH and organic matter."
    elif ranked:
        summary = (
            f"Soil health is {score:.0f}/100 ({_label(score)}). "
            f"Weakest topic: {ranked[0].label}."
        )
    else:
        summary = f"Soil health is {score:.0f}/100 ({_label(score)})."

    return SoilHealthReport(
        score=score,
        label=_label(score),
        grade=_grade(score),
        summary=summary,
        indicators=indicators,
        actions=actions[:4],
        data_gaps=gaps,
        outlook=outlook,
        notes=[
            "Soil report card: combines farmer/lab values such as pH, organic matter and salinity with NASA soil-moisture and temperature proxies.",
            "The scores are an approximate, explainable model; they are not an official soil-fertility classification.",
        ],
    )
