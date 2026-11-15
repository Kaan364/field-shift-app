"""Multi-year crop-rotation planner.

The single-season recommendation answers "what should I plant this year?".
This module answers the harder question the NASA Space Apps brief asks:
*which sequence of crops protects the soil, conserves water and keeps the farm
resilient over several seasons?*

Design principles
-----------------
* **Transparent.** Every score is a weighted sum of named, inspectable parts.
* **Anchored.** Year 1 is the crop the farmer would plant now, so the rotation
  never contradicts the single-season advice.
* **Conservative.** A rotation is only suggested when agronomic constraints are
  respected (no same family back-to-back, no repeated crop, no perennials in an
  annual sequence). It is decision support, not a promise of yield.

The model is intentionally simple and approximate. It rewards legume/forage
slots, residue cover, family diversity and rooting depth, and penalises water
demand in dry climates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

from app.domain.crop_meta import RotationTraits, traits_for
from app.domain.crops import CropProfile, resolve_crop
from app.domain.scoring import CropEvaluation
from app.schemas import AnalyzeRequest, EnvironmentSnapshot, Goal, Irrigation
from app.services.agronomy import irrigation_supply_mm, season_metrics

# Goal-dependent weights. They always sum to 1.0.
GOAL_WEIGHTS: dict[Goal, dict[str, float]] = {
    Goal.MAX_PROFIT: {"soil": 0.20, "water": 0.15, "resilience": 0.10, "profit": 0.40, "risk": 0.15},
    Goal.MAX_YIELD: {"soil": 0.20, "water": 0.20, "resilience": 0.15, "profit": 0.30, "risk": 0.15},
    Goal.LOW_WATER: {"soil": 0.20, "water": 0.45, "resilience": 0.15, "profit": 0.10, "risk": 0.10},
    Goal.LOW_INPUT: {"soil": 0.30, "water": 0.20, "resilience": 0.15, "profit": 0.15, "risk": 0.20},
    Goal.ORGANIC: {"soil": 0.40, "water": 0.15, "resilience": 0.20, "profit": 0.10, "risk": 0.15},
    Goal.SOIL_HEALTH: {"soil": 0.45, "water": 0.15, "resilience": 0.20, "profit": 0.05, "risk": 0.15},
    Goal.RISK_AVERSE: {"soil": 0.20, "water": 0.20, "resilience": 0.30, "profit": 0.10, "risk": 0.20},
}

_SCORE_LABELS = (
    (85.0, "very good"),
    (70.0, "good"),
    (55.0, "fair"),
    (40.0, "weak"),
)


def score_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    for threshold, label in _SCORE_LABELS:
        if score >= threshold:
            return label
    return "very weak"


@dataclass
class RotationYear:
    year: int
    crop: CropProfile
    traits: RotationTraits
    rule_score: float
    planting_window: str
    water_need_mm: int
    season_rain_mm: float | None
    role: str
    benefit: str
    actions: list[str] = field(default_factory=list)
    cover_crop: str | None = None
    note: str | None = None


@dataclass
class RotationOption:
    crops: tuple[str, ...]
    years: list[RotationYear]
    overall: float
    soil: float
    water: float
    resilience: float
    profit: float
    risk: float
    total_water_mm: float
    season_rain_mm: float
    irrigation_need_mm: float
    benefits: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)


@dataclass
class RotationResult:
    applicable: bool
    years_requested: int
    headline: str
    summary: str
    options: list[RotationOption] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def best(self) -> RotationOption | None:
        return self.options[0] if self.options else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _family_diversity(crops: list[CropProfile]) -> int:
    return len({traits_for(crop.key).family for crop in crops})


def _soil_score(
    crops: list[CropProfile],
    previous_crop: CropProfile | None,
    organic_matter_pct: float | None,
) -> float:
    traits = [traits_for(crop.key) for crop in crops]
    count = len(crops) or 1
    families = len({t.family for t in traits})
    family_points = min(1.0, max(0, families - 1) / 2.0) * 25.0
    legume_points = (sum(1 for t in traits if t.nitrogen_fixing) / count) * 30.0
    residue_points = _mean([t.residue_cover for t in traits]) * 20.0
    rooting_points = min(1.0, len({t.rooting for t in traits}) / 3.0) * 10.0
    improver_points = min(1.0, sum(1 for t in traits if t.soil_improver) / 2.0) * 15.0
    score = family_points + legume_points + residue_points + rooting_points + improver_points

    if organic_matter_pct is not None and organic_matter_pct < 2.0:
        # Low organic matter makes legume/forage slots even more valuable.
        score += 5.0
    if previous_crop is not None:
        previous_traits = traits_for(previous_crop.key)
        if previous_traits.family == traits[0].family:
            score -= 8.0
        elif previous_traits.soil_improver:
            score += 4.0
    return _clamp(score)


def _resilience_score(crops: list[CropProfile]) -> float:
    traits = [traits_for(crop.key) for crop in crops]
    count = len(crops) or 1
    families = len({t.family for t in traits})
    family_points = min(1.0, max(0, families - 1) / 2.0) * 30.0
    windows = {min(crop.planting_months) for crop in crops if crop.planting_months}
    window_points = min(1.0, len(windows) / 3.0) * 15.0
    drought_points = _mean([crop.drought_tolerance for crop in crops]) * 20.0
    frost_points = _mean([crop.frost_tolerance for crop in crops]) * 15.0
    heat_points = _mean([crop.heat_tolerance for crop in crops]) * 15.0
    break_points = _mean([t.break_crop for t in traits]) * 5.0
    if count == len({crop.category for crop in crops}):
        family_points = min(30.0, family_points + 3.0)
    return _clamp(family_points + window_points + drought_points + frost_points + heat_points + break_points)


def _profit_score(crops: list[CropProfile]) -> float:
    margin = _mean([crop.gross_margin for crop in crops])
    market = _mean([crop.market_demand for crop in crops])
    yield_potential = _mean([crop.yield_potential for crop in crops])
    return _clamp(100.0 * (0.45 * margin + 0.35 * market + 0.20 * yield_potential))


def _risk_score(
    crops: list[CropProfile],
    evaluations: list[CropEvaluation],
    request: AnalyzeRequest,
    climate_class: str | None,
    previous_crop: CropProfile | None,
) -> float:
    score = 100.0
    traits = [traits_for(crop.key) for crop in crops]
    dry_climate = climate_class in {"hyper_arid", "arid", "semi_arid"}
    high_water = sum(1 for crop in crops if crop.water_need_mm >= 550)
    if dry_climate:
        score -= high_water * 8.0
    high_nitrogen = sum(1 for crop in crops if crop.nitrogen_need == "high")
    score -= high_nitrogen * 4.0
    if not any(t.nitrogen_fixing for t in traits):
        score -= 8.0
    for evaluation in evaluations:
        if evaluation.rule_score < 60:
            score -= (60.0 - evaluation.rule_score) * 0.4
    if previous_crop is not None and traits_for(previous_crop.key).family == traits[0].family:
        score -= 6.0
    if request.resources.irrigation == Irrigation.RAINFED and dry_climate:
        score -= high_water * 5.0
    # Even a well-diversified rotation keeps weather, pest and price risk.
    return _clamp(score, high=96.0)


def _water_score(
    crops: list[CropProfile],
    request: AnalyzeRequest,
    environment: EnvironmentSnapshot,
    total_rain: float,
    total_need: float,
) -> float:
    supply = total_rain + irrigation_supply_mm(request.resources) * len(crops)
    ratio = supply / total_need if total_need > 0 else 1.0
    if ratio >= 1.0:
        balance_points = 100.0
    else:
        balance_points = max(0.0, 100.0 - (1.0 - ratio) * 130.0)
    drought_points = _mean([crop.drought_tolerance for crop in crops]) * 100.0
    score = 0.68 * balance_points + 0.32 * drought_points
    climate_class = environment.climate.climate_class or "unknown"
    if climate_class in {"hyper_arid", "arid"}:
        score -= 4.0
    elif climate_class == "semi_arid":
        score -= 2.0
    return _clamp(score)


def _year_actions(
    year: int,
    crop: CropProfile,
    traits: RotationTraits,
    previous: CropProfile | None,
    deficit_mm: float | None,
    planting_month: int | None,
) -> list[str]:
    actions: list[str] = []
    window = crop.planting_window("en")
    actions.append(f"Sowing window: {window}. Check that the soil has enough moisture.")
    if year == 1 and planting_month is not None:
        actions.append("Get a soil test before sowing; set fertiliser rates from the test.")
    if previous is not None:
        if traits_for(previous.key).nitrogen_fixing:
            actions.append(
                "The previous crop was a legume; discuss reducing nitrogen fertiliser with a soil test."
            )
        else:
            actions.append("Do not burn the previous residue; incorporate it or leave it as mulch.")
    if deficit_mm is not None and deficit_mm > 30:
        actions.append(
            f"About {int(deficit_mm)} mm of extra water may be needed this season; plan irrigation now."
        )
    if traits.nitrogen_fixing:
        actions.append("If you incorporate this legume after harvest, the soil gains more nitrogen.")
    if traits.family == "cereal":
        actions.append("Leave the residue after harvest; it keeps the soil cool and reduces erosion.")
    actions.append("Walk the field once a week; catch pests and disease early.")
    return actions[:5]


def _cover_crop(crop: CropProfile) -> str | None:
    traits = traits_for(crop.key)
    if traits.family == "cereal":
        return "After harvest you can sow a vetch + barley mix as a green manure."
    if traits.family in {"oilseed", "root"}:
        return "Before winter, a vetch or oats mix can cover the soil."
    return None


def _build_year(
    year: int,
    crop: CropProfile,
    evaluation: CropEvaluation,
    request: AnalyzeRequest,
    environment: EnvironmentSnapshot,
    previous: CropProfile | None,
) -> RotationYear:
    planting_month = request.preferences.planting_month if year == 1 else None
    season = season_metrics(environment, crop, planting_month)
    rain = season.total_precip_mm
    need = float(crop.water_need_mm)
    deficit = None
    if rain is not None:
        supply = rain + irrigation_supply_mm(request.resources)
        deficit = max(0.0, need - supply)

    traits = traits_for(crop.key)
    return RotationYear(
        year=year,
        crop=crop,
        traits=traits,
        rule_score=round(evaluation.rule_score, 1),
        planting_window=crop.planting_window("en"),
        water_need_mm=crop.water_need_mm,
        season_rain_mm=None if rain is None else round(rain, 1),
        role=traits.role or crop.category,
        benefit=traits.benefit,
        actions=_year_actions(year, crop, traits, previous, deficit, planting_month),
        cover_crop=_cover_crop(crop),
    )


def _summarize(
    crops: list[CropProfile],
    request: AnalyzeRequest,
    total_rain: float,
    total_need: float,
) -> tuple[list[str], list[str]]:
    traits = [traits_for(crop.key) for crop in crops]
    benefits: list[str] = []
    cautions: list[str] = []

    if any(t.nitrogen_fixing for t in traits):
        benefits.append("A legume/forage crop fixes nitrogen from the air and can cut nitrogen fertiliser cost.")
    if len({t.family for t in traits}) >= 2:
        benefits.append("Different crop families do not follow each other, so disease and pest pressure fall.")
    if _mean([t.residue_cover for t in traits]) >= 0.5:
        benefits.append("Residue and roots cover the soil; water loss and erosion are reduced.")
    if len({t.rooting for t in traits}) >= 2:
        benefits.append("Different rooting depths use water and nutrients from different soil layers.")
    if total_need > 0 and total_rain + irrigation_supply_mm(request.resources) * len(crops) >= total_need:
        benefits.append("The total water need looks coverable by local rainfall and the reported irrigation.")

    cautions.append("Yield may not rise in year one; soil health improves over 2-3 years.")
    if _mean([crop.water_need_mm for crop in crops]) >= 550:
        cautions.append("These crops need a lot of water; settle the irrigation supply before the season.")
    if request.resources.irrigation == Irrigation.RAINFED:
        cautions.append("Without irrigation, yield can fall in a dry year; choose a drought-tolerant variety.")
    cautions.append("Prices and markets change every year; look for a buyer or cooperative before sowing.")
    cautions.append("NASA data is a regional average; observe and test your own soil separately.")
    return benefits, cautions


def _score_option(
    crops: list[CropProfile],
    years: list[RotationYear],
    request: AnalyzeRequest,
    environment: EnvironmentSnapshot,
    evaluations: list[CropEvaluation],
    previous_crop: CropProfile | None,
) -> RotationOption:
    total_need = sum(float(crop.water_need_mm) for crop in crops)
    total_rain = sum(y.season_rain_mm or 0.0 for y in years)
    soil = _soil_score(crops, previous_crop, request.field.organic_matter_pct)
    water = _water_score(crops, request, environment, total_rain, total_need)
    resilience = _resilience_score(crops)
    profit = _profit_score(crops)
    risk = _risk_score(crops, evaluations, request, environment.climate.climate_class, previous_crop)

    weights = GOAL_WEIGHTS.get(request.preferences.goal, GOAL_WEIGHTS[Goal.MAX_PROFIT])
    overall = (
        soil * weights["soil"]
        + water * weights["water"]
        + resilience * weights["resilience"]
        + profit * weights["profit"]
        + risk * weights["risk"]
    )
    supply = total_rain + irrigation_supply_mm(request.resources) * len(crops)
    benefits, cautions = _summarize(crops, request, total_rain, total_need)
    return RotationOption(
        crops=tuple(crop.key for crop in crops),
        years=years,
        overall=round(_clamp(overall), 1),
        soil=round(soil, 1),
        water=round(water, 1),
        resilience=round(resilience, 1),
        profit=round(profit, 1),
        risk=round(risk, 1),
        total_water_mm=round(total_need, 1),
        season_rain_mm=round(total_rain, 1),
        irrigation_need_mm=round(max(0.0, total_need - supply), 1),
        benefits=benefits,
        cautions=cautions,
    )


# ---------------------------------------------------------------------------
# Candidate pool
# ---------------------------------------------------------------------------
def _candidate_pool(
    evaluations: list[CropEvaluation],
    *,
    exclude: str | None,
    limit: int = 8,
) -> list[CropEvaluation]:
    annual = [
        evaluation
        for evaluation in evaluations
        if not traits_for(evaluation.crop.key).multi_year
        and traits_for(evaluation.crop.key).family != "perennial"
    ]
    if exclude:
        annual = [evaluation for evaluation in annual if evaluation.crop.key != exclude]
    if not annual:
        return []

    selected: list[CropEvaluation] = []
    seen: set[str] = set()

    def add(evaluation: CropEvaluation) -> None:
        if evaluation.crop.key not in seen and len(selected) < limit:
            seen.add(evaluation.crop.key)
            selected.append(evaluation)

    for evaluation in annual[: max(4, limit - 2)]:
        add(evaluation)

    # Guarantee soil-building options are on the table.
    for evaluation in annual:
        if traits_for(evaluation.crop.key).nitrogen_fixing:
            add(evaluation)
        if sum(1 for item in selected if traits_for(item.crop.key).nitrogen_fixing) >= 2:
            break
    for evaluation in annual:
        if traits_for(evaluation.crop.key).break_crop >= 0.6:
            add(evaluation)

    return selected


def _generate_sequences(
    pool: list[CropEvaluation],
    start: CropEvaluation,
    years: int,
) -> list[list[CropEvaluation]]:
    rest = [evaluation for evaluation in pool if evaluation.crop.key != start.crop.key]
    if years <= 1 or not rest:
        return [[start]]
    sequences: list[list[CropEvaluation]] = []
    for tail in permutations(rest, years - 1):
        sequence = [start, *tail]
        families = [traits_for(item.crop.key).family for item in sequence]
        if any(families[index] == families[index + 1] for index in range(len(families) - 1)):
            # Same family back-to-back is a disease/nutrient trap.
            continue
        if years >= 4 and len(set(families)) < 3:
            continue
        sequences.append(sequence)
    return sequences


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_rotation(
    request: AnalyzeRequest,
    environment: EnvironmentSnapshot,
    evaluations: list[CropEvaluation],
    *,
    years: int = 3,
    start_crop_key: str | None = None,
    max_sequences: int = 400,
) -> RotationResult:
    """Build a multi-year rotation anchored on the current-year best crop."""

    years = max(2, min(4, years))
    notes: list[str] = []
    by_key = {evaluation.crop.key: evaluation for evaluation in evaluations}
    previous_crop = resolve_crop(request.field.previous_crop or "")

    annual = [
        evaluation
        for evaluation in evaluations
        if not traits_for(evaluation.crop.key).multi_year
        and traits_for(evaluation.crop.key).family != "perennial"
    ]
    if not annual:
        return RotationResult(
            applicable=False,
            years_requested=years,
            headline="A yearly rotation could not be built for this field.",
            summary=(
                "The candidate crops are perennial (orchard/vineyard), so an annual rotation does not apply. "
                "Use the single-crop recommendation instead."
            ),
            notes=["Perennial crops need an orchard care plan rather than a yearly rotation."],
        )

    top_overall = evaluations[0].crop if evaluations else None
    if start_crop_key and start_crop_key in by_key:
        start = by_key[start_crop_key]
    else:
        start = annual[0]

    if traits_for(start.crop.key).multi_year or traits_for(start.crop.key).family == "perennial":
        start = annual[0]

    if top_overall is not None and top_overall.key != start.crop.key:
        notes.append(
            f"The strongest single crop this year is {top_overall.name}. "
            f"Because it is perennial, the yearly rotation starts with {start.crop.name}."
        )

    pool = _candidate_pool(evaluations, exclude=start.crop.key)
    if not pool:
        return RotationResult(
            applicable=False,
            years_requested=years,
            headline=f"No suitable rotation partner was found for {start.crop.name}.",
            summary="There are too few candidate crops. Try another goal or change the excluded list.",
            notes=notes,
        )

    sequences = _generate_sequences(pool, start, years)
    if not sequences:
        years = 2
        sequences = _generate_sequences(pool, start, 2)
        notes.append("No suitable 3-year sequence was found; a 2-year plan is shown.")

    scored: list[RotationOption] = []
    for sequence in sequences[:max_sequences]:
        crops = [item.crop for item in sequence]
        year_plans: list[RotationYear] = []
        previous: CropProfile | None = None
        for index, evaluation in enumerate(sequence, start=1):
            year_plans.append(
                _build_year(index, evaluation.crop, evaluation, request, environment, previous)
            )
            previous = evaluation.crop
        scored.append(
            _score_option(crops, year_plans, request, environment, sequence, previous_crop)
        )

    if not scored:
        return RotationResult(
            applicable=False,
            years_requested=years,
            headline="The rotation plan could not be built.",
            summary="Not enough suitable crops were found. Relax the filters and try again.",
            notes=notes,
        )

    scored.sort(key=lambda option: (option.overall, option.soil, option.resilience), reverse=True)
    best = scored[0]

    names = [year.crop.name for year in best.years]
    headline = f"{len(best.years)}-year plan: " + " → ".join(names)
    summary_parts = [f"Plant {names[0]} this year."]
    for offset, name in enumerate(names[1:], start=1):
        if offset == 1:
            summary_parts.append(f"Next year: {name}.")
        elif offset == 2:
            summary_parts.append(f"The year after: {name}.")
        else:
            summary_parts.append(f"Year {offset + 1}: {name}.")
    summary_parts.append(
        f"This sequence scores {best.soil:.0f} for soil health, {best.water:.0f} for water balance "
        f"and {best.resilience:.0f} for climate resilience."
    )
    if best.irrigation_need_mm > 0:
        summary_parts.append(
            f"About {best.irrigation_need_mm:.0f} mm of extra irrigation may be needed in total."
        )
    summary = " ".join(summary_parts)

    if not any(traits_for(crop.key).nitrogen_fixing for crop in [y.crop for y in best.years]):
        notes.append(
            "This plan has no legume. Add one year of chickpea, lentil or vetch to put nitrogen back in the soil."
        )
    notes.append(
        "Rotation scores are an approximate model; they are not a yield or profit guarantee. "
        "Confirm local varieties, markets and irrigation with an expert."
    )
    return RotationResult(
        applicable=True,
        years_requested=len(best.years),
        headline=headline,
        summary=summary,
        options=scored[:3],
        notes=notes,
    )
