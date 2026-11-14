"""Deterministic crop suitability scoring.

The score is intentionally explainable: every crop gets a 0-100 score plus a
component breakdown. The rule engine is the "anchor" of the product; the LLM
can re-rank and explain, but it cannot silently replace the agronomic maths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.domain.crops import CROPS, CropProfile, TEXTURE_GROUP, resolve_crops
from app.schemas import (
    AnalyzeRequest,
    EnvironmentSnapshot,
    Goal,
    Irrigation,
    SoilTexture,
)
from app.services.agronomy import (
    SeasonMetrics,
    band_score,
    irrigation_supply_mm,
    season_metrics,
)

COMPONENT_WEIGHTS: dict[str, float] = {
    "temperature": 0.20,
    "water": 0.24,
    "ph": 0.10,
    "texture": 0.10,
    "salinity": 0.04,
    "climate_risk": 0.10,
    "goal_fit": 0.14,
    "market": 0.05,
    "calendar": 0.03,
}

COMPONENT_LABELS_TR = {
    "temperature": "Sıcaklık",
    "water": "Su dengesi",
    "ph": "Toprak pH'ı",
    "texture": "Toprak dokusu",
    "salinity": "Tuzluluk",
    "climate_risk": "İklim riski",
    "goal_fit": "Hedefe uygunluk",
    "market": "Pazar",
    "calendar": "Ekim takvimi",
}

TEXTURE_ORDER = ["light", "light_medium", "medium", "medium_heavy", "heavy"]

NITROGEN_FACTOR = {"low": 1.0, "medium": 0.6, "high": 0.25}


@dataclass
class CropEvaluation:
    crop: CropProfile
    rule_score: float
    components: dict[str, float | None]
    strengths: list[str] = field(default_factory=list)
    limiting_factors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    season: SeasonMetrics | None = None
    water_ratio: float | None = None
    irrigation_supply_mm: float = 0.0
    confidence: str = "medium"
    interest_boost: float = 0.0

    @property
    def data_completeness(self) -> float:
        present = sum(1 for value in self.components.values() if value is not None)
        return present / len(COMPONENT_WEIGHTS)


def _circular_distance(month: int, target: int) -> int:
    raw = abs(month - target)
    return min(raw, 12 - raw)


def _texture_score(field_texture: SoilTexture, crop: CropProfile) -> float | None:
    if field_texture == SoilTexture.UNKNOWN:
        return None
    actual_group = TEXTURE_GROUP.get(field_texture.value)
    if actual_group is None:
        return None
    preferred_groups = {
        TEXTURE_GROUP[texture]
        for texture in crop.textures
        if texture in TEXTURE_GROUP
    }
    if not preferred_groups:
        return None
    if actual_group in preferred_groups:
        return 100.0
    distance = min(abs(TEXTURE_ORDER.index(actual_group) - TEXTURE_ORDER.index(group)) for group in preferred_groups)
    return max(0.0, 100.0 - 22.0 * distance)


def _salinity_score(field_salinity: float | None, crop: CropProfile) -> float | None:
    if field_salinity is None:
        return None
    threshold = 1.2 + 5.5 * crop.salinity_tolerance
    if field_salinity <= threshold:
        return 100.0
    return max(0.0, 100.0 - (field_salinity - threshold) * 20.0)


def _goal_fit_score(crop: CropProfile, goal: Goal) -> float:
    low_nitrogen = NITROGEN_FACTOR.get(crop.nitrogen_need, 0.5)
    if goal == Goal.MAX_YIELD:
        value = crop.yield_potential
    elif goal == Goal.MAX_PROFIT:
        value = 0.55 * crop.gross_margin + 0.45 * crop.market_demand
    elif goal == Goal.LOW_WATER:
        value = 0.6 * crop.drought_tolerance + 0.4 * (1 - min(crop.water_need_mm, 900) / 900)
    elif goal == Goal.LOW_INPUT:
        value = 0.5 * low_nitrogen + 0.3 * crop.organic_suitability + 0.2 * crop.drought_tolerance
    elif goal == Goal.ORGANIC:
        value = crop.organic_suitability
    elif goal == Goal.SOIL_HEALTH:
        value = 0.55 * crop.organic_suitability + 0.45 * (1.0 if crop.is_legume else 0.4)
    elif goal == Goal.RISK_AVERSE:
        value = (
            0.4 * crop.frost_tolerance
            + 0.3 * crop.drought_tolerance
            + 0.3 * crop.market_demand
        )
    else:  # pragma: no cover - enum is exhaustive
        value = 0.5
    return round(100.0 * value, 1)


def _market_score(crop: CropProfile, market_access: str) -> float:
    value = 100.0 * crop.market_demand
    if market_access == "low":
        value = min(value, 70.0)
    elif market_access == "high":
        value = min(100.0, value + 5.0)
    return round(value, 1)


def _calendar_score(crop: CropProfile, preferred_month: int | None) -> float:
    if preferred_month is None:
        return 100.0
    distance = min(_circular_distance(preferred_month, month) for month in crop.planting_months)
    if distance == 0:
        return 100.0
    if distance == 1:
        return 85.0
    if distance == 2:
        return 50.0
    return 25.0


def _climate_risk_score(
    crop: CropProfile,
    season: SeasonMetrics,
    environment: EnvironmentSnapshot,
    irrigation: Irrigation,
) -> float:
    frost_penalty = len(season.frost_months) * (1.0 - crop.frost_tolerance) * 14.0
    heat_penalty = len(season.heat_months) * (1.0 - crop.heat_tolerance) * 12.0
    score = 100.0 - frost_penalty - heat_penalty

    climate_class = environment.climate.climate_class or "unknown"
    aridity_penalty = {
        "hyper_arid": 22.0,
        "arid": 18.0,
        "semi_arid": 10.0,
        "dry_sub_humid": 4.0,
    }.get(climate_class, 0.0)
    if irrigation == Irrigation.LIMITED:
        aridity_penalty *= 0.5
    elif irrigation == Irrigation.FULL:
        aridity_penalty = 0.0
    return max(0.0, min(100.0, score - aridity_penalty))


def _water_score(
    crop: CropProfile,
    season: SeasonMetrics,
    irrigation_supply: float,
    irrigation: Irrigation,
) -> tuple[float | None, float | None]:
    if season.total_precip_mm is None:
        return None, None
    supply = season.total_precip_mm + irrigation_supply
    ratio = supply / crop.water_need_mm
    if ratio < 0.95:
        deficit = 1.0 - ratio
        score = 100.0 - deficit * 140.0 * (1.0 - 0.6 * crop.drought_tolerance)
    elif ratio > 1.7:
        score = max(50.0, 100.0 - (ratio - 1.7) * 30.0)
    else:
        score = 100.0
    return round(max(0.0, min(100.0, score)), 1), round(ratio, 3)


def _build_messages(
    crop: CropProfile,
    components: dict[str, float | None],
    season: SeasonMetrics,
    water_ratio: float | None,
) -> tuple[list[str], list[str]]:
    strengths: list[str] = []
    limits: list[str] = []

    for key, score in components.items():
        if score is None:
            continue
        label = COMPONENT_LABELS_TR[key]
        if key == "temperature" and score >= 80:
            strengths.append(f"Sıcaklık uygun ({season.mean_temp_c}°C)")
        elif key == "water" and score >= 80:
            strengths.append(
                f"Su dengesi uygun (sezon yağışı {season.total_precip_mm} mm, oran {water_ratio})"
            )
        elif key == "ph" and score >= 80:
            strengths.append("Toprak pH'ı uygun")
        elif key == "texture" and score >= 80:
            strengths.append("Toprak dokusu uygun")
        elif key == "salinity" and score >= 80:
            strengths.append("Tuzluluk riski düşük")
        elif key == "market" and score >= 80:
            strengths.append("Pazar talebi güçlü")
        elif key == "goal_fit" and score >= 80:
            strengths.append("Çiftçinin hedefiyle güçlü uyum")
        elif score <= 50 and key == "temperature":
            limits.append(
                f"Sıcaklık sınırda (sezon ort. {season.mean_temp_c}°C; optimum "
                f"{crop.temp_opt[0]}-{crop.temp_opt[1]}°C)"
            )
        elif score <= 50 and key == "water":
            limits.append(
                f"Su açığı var (sezon yağışı {season.total_precip_mm} mm, "
                f"ihtiyaç {crop.water_need_mm} mm, oran {water_ratio})"
            )
        elif score <= 50 and key == "ph":
            limits.append(f"Toprak pH'ı sınırda (optimum {crop.ph_opt[0]}-{crop.ph_opt[1]})")
        elif score <= 50 and key == "texture":
            limits.append("Toprak dokusu bu ekin için ideal değil")
        elif score <= 50 and key == "salinity":
            limits.append("Tuzluluk bu ekin için risk oluşturabilir")
        elif score <= 50 and key == "climate_risk":
            limits.append(
                f"İklim riski yüksek (don ayları: {len(season.frost_months)}, "
                f"sıcak stresi ayları: {len(season.heat_months)})"
            )
        elif score <= 50 and key == "calendar":
            limits.append("Ekim takvimi çiftçinin planladığı aydan uzak")
        elif score <= 50 and key == "market":
            limits.append("Pazar erişimi bu ürün için sınırlı olabilir")
        elif score <= 50 and key == "goal_fit":
            limits.append(f"{label} seçilen hedefe göre düşük")

    return strengths, limits


def evaluate_crop(
    crop: CropProfile,
    request: AnalyzeRequest,
    environment: EnvironmentSnapshot,
) -> CropEvaluation:
    field = request.field
    resources = request.resources
    season = season_metrics(environment, crop, request.preferences.planting_month)
    irrigation_supply = irrigation_supply_mm(resources)

    components: dict[str, float | None] = {}
    components["temperature"] = (
        None
        if season.mean_temp_c is None
        else round(
            band_score(season.mean_temp_c, crop.temp_opt, crop.temp_abs) or 0.0,
            1,
        )
    )
    water_score, water_ratio = _water_score(crop, season, irrigation_supply, resources.irrigation)
    components["water"] = water_score
    components["ph"] = (
        None if field.soil_ph is None else band_score(field.soil_ph, crop.ph_opt, crop.ph_abs)
    )
    components["texture"] = _texture_score(field.soil_texture, crop)
    components["salinity"] = _salinity_score(field.salinity_ds_m, crop)
    components["climate_risk"] = _climate_risk_score(crop, season, environment, resources.irrigation)
    components["goal_fit"] = _goal_fit_score(crop, request.preferences.goal)
    components["market"] = _market_score(crop, request.preferences.market_access.value)
    components["calendar"] = _calendar_score(crop, request.preferences.planting_month)

    present = {key: value for key, value in components.items() if value is not None}
    total_weight = sum(COMPONENT_WEIGHTS[key] for key in present)
    score = (
        sum(value * COMPONENT_WEIGHTS[key] for key, value in present.items()) / total_weight
        if total_weight
        else 0.0
    )

    # Hard agronomic limits: an unsuitable crop must not look good because of
    # strong market or goal-fit components.
    if components["temperature"] == 0:
        score *= 0.35
    if components["water"] == 0 and resources.irrigation == Irrigation.RAINFED:
        score *= 0.5
    if components["ph"] == 0:
        score *= 0.65
    if len(season.frost_months) >= 3 and crop.frost_tolerance < 0.35:
        score *= 0.55
    if len(season.heat_months) >= 3 and crop.heat_tolerance < 0.35:
        score *= 0.75

    strengths, limits = _build_messages(crop, components, season, water_ratio)

    warnings: list[str] = []
    if water_ratio is not None and water_ratio < 0.7:
        warnings.append(
            f"{crop.local_name}: sezonluk su açığı ({(water_ratio * 100):.0f}% karşılama). "
            "Sulama imkânı yoksa verim düşer."
        )
    if season.frost_months and crop.frost_tolerance < 0.4:
        warnings.append(
            f"{crop.local_name}: sezon içinde don riski olan aylar var "
            f"({', '.join(season.frost_months)})."
        )
    if len(season.frost_months) >= 3 and crop.frost_tolerance < 0.35:
        warnings.append(
            f"{crop.local_name}: çok yıllık/don hassas bir ürün için 3+ donlu ay ciddi risk; "
            "yerel çeşit ve mikro-klima doğrulaması olmadan önerilmez."
        )

    completeness = len(present) / len(COMPONENT_WEIGHTS)
    confidence = "high" if completeness >= 0.85 else "medium" if completeness >= 0.6 else "low"

    return CropEvaluation(
        crop=crop,
        rule_score=round(max(0.0, min(100.0, score)), 1),
        components={key: (None if value is None else round(value, 1)) for key, value in components.items()},
        strengths=strengths,
        limiting_factors=limits,
        warnings=warnings,
        season=season,
        water_ratio=water_ratio,
        irrigation_supply_mm=irrigation_supply,
        confidence=confidence,
    )


def evaluate_candidates(
    request: AnalyzeRequest,
    environment: EnvironmentSnapshot,
) -> tuple[list[CropEvaluation], list[str]]:
    warnings: list[str] = []
    candidates: list[CropProfile] = list(CROPS)

    if request.preferences.max_growing_days is not None:
        filtered: list[CropProfile] = []
        for crop in candidates:
            if crop.growing_days <= request.preferences.max_growing_days:
                filtered.append(crop)
            else:
                warnings.append(
                    f"{crop.local_name}, {request.preferences.max_growing_days} günlük sezon sınırını "
                    f"aştığı için elendi ({crop.growing_days} gün)."
                )
        candidates = filtered

    excluded, unknown_excluded = resolve_crops(request.preferences.excluded_crops)
    excluded_keys = {crop.key for crop in excluded}
    if excluded_keys:
        before = len(candidates)
        candidates = [crop for crop in candidates if crop.key not in excluded_keys]
        if len(candidates) < before:
            warnings.append(
                "Çiftçinin hariç tuttuğu ekinler değerlendirmeden çıkarıldı: "
                + ", ".join(sorted(crop.local_name for crop in excluded))
            )
    for name in unknown_excluded:
        warnings.append(f"Hariç tutulan ekin adı tanınmadı: '{name}'.")

    interested, unknown_interested = resolve_crops(request.preferences.crops_of_interest)
    interest_keys = {crop.key for crop in interested}
    for name in unknown_interested:
        warnings.append(f"İlgi listesindeki ekin adı tanınmadı: '{name}'.")
    if interest_keys & excluded_keys:
        warnings.append("Aynı ekin hem ilgi listesinde hem hariç listesinde; hariç listesi önceliklidir.")

    evaluations = [evaluate_crop(crop, request, environment) for crop in candidates]

    for evaluation in evaluations:
        if evaluation.crop.key in interest_keys:
            evaluation.interest_boost = 4.0
            evaluation.rule_score = round(min(100.0, evaluation.rule_score + 4.0), 1)
            evaluation.strengths.append("Çiftçinin ilgi gösterdiği ürünlerden biri")

    evaluations.sort(key=lambda item: (item.rule_score, item.crop.market_demand), reverse=True)
    return evaluations, warnings


def component_summary(evaluations: Iterable[CropEvaluation]) -> dict[str, float]:
    """Average component values across evaluations (useful for diagnostics)."""

    totals: dict[str, list[float]] = {}
    for evaluation in evaluations:
        for key, value in evaluation.components.items():
            if value is not None:
                totals.setdefault(key, []).append(value)
    return {key: round(sum(values) / len(values), 2) for key, values in totals.items()}
