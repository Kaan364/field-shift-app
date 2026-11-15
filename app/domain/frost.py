"""Frost, heat and drought risk for a field and a crop.

The calculation is intentionally simple and explainable. NASA POWER monthly
climatology gives a normal minimum and maximum temperature for each month; the
module turns those into a rough probability of frost or heat stress, then
adjusts the result with the crop's own tolerance values.

The output is an early-warning indicator, not a forecast. The UI says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.crops import CropProfile, MONTH_NAMES_EN, resolve_crop
from app.schemas import EnvironmentSnapshot, Irrigation

MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

RISK_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "unknown": "Unknown",
}


@dataclass
class FrostInfo:
    risk_level: str
    risk_label: str
    probability_pct: float
    first_frost_month: str | None
    last_frost_month: str | None
    frost_free_window: str
    frost_free_days: int
    min_temp_c: float | None
    frost_months: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


@dataclass
class HeatInfo:
    risk_level: str
    risk_label: str
    probability_pct: float
    max_temp_c: float | None
    heat_months: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


@dataclass
class DroughtInfo:
    risk_level: str
    risk_label: str
    deficit_mm: float
    annual_rain_mm: float | None
    dry_months: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


@dataclass
class MonthRisk:
    month: str
    frost_probability_pct: float
    heat_probability_pct: float
    risk_level: str


@dataclass
class RiskSection:
    overall_level: str
    overall_label: str
    crop_key: str | None
    crop_name: str | None
    summary: str
    frost: FrostInfo
    heat: HeatInfo
    drought: DroughtInfo
    months: list[MonthRisk] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _frost_probability(min_temp_c: float | None) -> float:
    """Rough chance (0-100) that a month brings a damaging frost."""

    if min_temp_c is None:
        return 0.0
    if min_temp_c <= -5:
        return 95.0
    if min_temp_c <= -2:
        return 88.0
    if min_temp_c <= 0:
        return 72.0
    if min_temp_c <= 2:
        return 45.0
    if min_temp_c <= 4:
        return 18.0
    return 3.0


def _heat_probability(max_temp_c: float | None) -> float:
    """Rough chance (0-100) that a month brings heat stress."""

    if max_temp_c is None:
        return 0.0
    if max_temp_c >= 38:
        return 90.0
    if max_temp_c >= 35:
        return 68.0
    if max_temp_c >= 32:
        return 42.0
    if max_temp_c >= 28:
        return 16.0
    return 3.0


def _level(value: float, *, medium: float = 35.0, high: float = 60.0) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def _month_index(name: str) -> int | None:
    text = (name or "").strip()[:3].title()
    for index, month in enumerate(MONTH_NAMES_EN, start=1):
        if month[:3] == text:
            return index
    return None


def _crop_window(crop: CropProfile) -> set[int]:
    """Months in which the crop is normally in the field."""

    months = set(crop.planting_months)
    if not months:
        return set(range(1, 13))
    start = min(months)
    days = max(60, crop.growing_days)
    covered: set[int] = set()
    remaining = days
    month = start
    while remaining > 0:
        covered.add(month)
        remaining -= MONTH_DAYS[month - 1]
        month = month % 12 + 1
    return covered


def _longest_frost_free_window(probabilities: dict[int, float]) -> tuple[set[int], int]:
    """Longest run of months whose frost chance is below 35%."""

    best: set[int] = set()
    best_days = 0
    for start in range(1, 13):
        run: set[int] = set()
        days = 0
        month = start
        while month not in run and probabilities.get(month, 0.0) < 35.0:
            run.add(month)
            days += MONTH_DAYS[month - 1]
            month = month % 12 + 1
        if days > best_days:
            best, best_days = run, days
    return best, best_days


def _window_label(months: set[int]) -> str:
    if not months:
        return "No reliably frost-free month"
    ordered = sorted(months)
    if len(ordered) == 12:
        return "All year"
    return f"{MONTH_NAMES_EN[ordered[0] - 1]} to {MONTH_NAMES_EN[ordered[-1] - 1]}"


def assess_risk(
    environment: EnvironmentSnapshot,
    *,
    crop: CropProfile | None = None,
    water_deficit_mm: float = 0.0,
    irrigation: Irrigation = Irrigation.RAINFED,
) -> RiskSection:
    monthly = environment.monthly
    frost_probs: dict[int, float] = {}
    heat_probs: dict[int, float] = {}
    month_rows: list[MonthRisk] = []
    frost_months: list[str] = []
    heat_months: list[str] = []
    dry_months: list[str] = []
    min_values: list[float] = []
    max_values: list[float] = []

    for item in monthly:
        index = _month_index(item.month)
        if index is None:
            continue
        frost = _frost_probability(item.min_temp_c)
        heat = _heat_probability(item.max_temp_c)
        frost_probs[index] = frost
        heat_probs[index] = heat
        if item.min_temp_c is not None:
            min_values.append(item.min_temp_c)
        if item.max_temp_c is not None:
            max_values.append(item.max_temp_c)
        if frost >= 35:
            frost_months.append(item.month)
        if heat >= 35:
            heat_months.append(item.month)
        if item.precip_month_mm is not None and item.evapotranspiration_mm_per_day is not None:
            et0_month = item.evapotranspiration_mm_per_day * 30.0
            if item.precip_month_mm < et0_month * 0.45:
                dry_months.append(item.month)
        month_rows.append(
            MonthRisk(
                month=item.month,
                frost_probability_pct=round(frost, 1),
                heat_probability_pct=round(heat, 1),
                risk_level=_level(max(frost, heat), medium=35, high=60),
            )
        )

    frost_free, frost_free_days = _longest_frost_free_window(frost_probs)
    # Frost months in calendar order; first = spring? Use the coldest months to
    # name the last frost of spring and the first frost of autumn.
    ordered_frost = sorted(frost_probs)
    last_spring = None
    first_autumn = None
    for index in range(1, 13):
        if frost_probs.get(index, 0) >= 35:
            if index <= 6:
                last_spring = index
            elif first_autumn is None:
                first_autumn = index
    first_frost = MONTH_NAMES_EN[first_autumn - 1] if first_autumn else None
    last_frost = MONTH_NAMES_EN[last_spring - 1] if last_spring else None

    window = _crop_window(crop) if crop else set(range(1, 13))
    window_frost = [frost_probs.get(month, 0.0) for month in window]
    peak_frost = max(window_frost) if window_frost else 0.0
    frost_sensitivity = 1.0 - (crop.frost_tolerance if crop else 0.5)
    frost_risk_value = peak_frost * (0.35 + 0.65 * frost_sensitivity)

    window_heat = [heat_probs.get(month, 0.0) for month in window]
    peak_heat = max(window_heat) if window_heat else 0.0
    heat_sensitivity = 1.0 - (crop.heat_tolerance if crop else 0.5)
    heat_risk_value = peak_heat * (0.35 + 0.65 * heat_sensitivity)

    if water_deficit_mm >= 150:
        drought_value = 85.0
    elif water_deficit_mm >= 80:
        drought_value = 62.0
    elif water_deficit_mm >= 30:
        drought_value = 38.0
    else:
        drought_value = 12.0
    if irrigation == Irrigation.FULL:
        drought_value *= 0.55
    elif irrigation == Irrigation.LIMITED:
        drought_value *= 0.8
    else:
        drought_value = min(100.0, drought_value * 1.1)

    frost_level = _level(frost_risk_value)
    heat_level = _level(heat_risk_value)
    drought_level = _level(drought_value)

    overall_value = max(frost_risk_value, heat_risk_value, drought_value)
    overall_level = _level(overall_value, medium=30, high=55)

    crop_name = crop.name if crop else None
    frost = FrostInfo(
        risk_level=frost_level,
        risk_label=RISK_LABELS[frost_level],
        probability_pct=round(frost_risk_value, 1),
        first_frost_month=first_frost,
        last_frost_month=last_frost,
        frost_free_window=_window_label(frost_free),
        frost_free_days=frost_free_days,
        min_temp_c=None if not min_values else round(min(min_values), 1),
        frost_months=frost_months,
        notes=[
            "Frost risk is estimated from 25-year monthly minimum temperatures, not from a weather forecast.",
            "Valleys and low fields can be several degrees colder than the regional average.",
        ],
        tips=[
            "Keep the planting date inside the frost-free window.",
            "Watch the 5-day forecast before sowing or spraying.",
            "Have a cover, smoke or sprinkler plan ready for a late frost night.",
        ]
        if frost_level != "low"
        else ["The normal frost risk is low, but a late cold night is still possible."],
    )

    heat = HeatInfo(
        risk_level=heat_level,
        risk_label=RISK_LABELS[heat_level],
        probability_pct=round(heat_risk_value, 1),
        max_temp_c=None if not max_values else round(max(max_values), 1),
        heat_months=heat_months,
        notes=[
            "Heat stress is estimated from normal monthly maximum temperatures.",
            "Heat during flowering can reduce grain, fruit or seed set even when water is enough.",
        ],
        tips=[
            "Irrigate early in the morning or in the evening during hot spells.",
            "Use mulch or residue cover to keep the soil cooler.",
            "Choose a variety whose flowering avoids the hottest weeks.",
        ]
        if heat_level != "low"
        else ["Normal heat stress is low for this crop in this climate."],
    )

    drought = DroughtInfo(
        risk_level=drought_level,
        risk_label=RISK_LABELS[drought_level],
        deficit_mm=round(max(0.0, water_deficit_mm), 1),
        annual_rain_mm=environment.climate.annual_precip_mm,
        dry_months=dry_months,
        notes=[
            "The drought signal compares the crop's seasonal water need with rainfall and the irrigation you reported.",
            "A dry month can still be saved by irrigation, mulching and early sowing.",
        ],
        tips=[
            "Plan the irrigation budget before the season starts.",
            "Harvest rainwater where you can and keep residue on the soil.",
            "Avoid high-water crops on the driest part of the farm.",
        ]
        if drought_level != "low"
        else ["Water balance looks comfortable at the reported irrigation level."],
    )

    actions: list[str] = []
    if frost_level == "high":
        actions.append("Do not sow a frost-sensitive crop before the last frost month.")
    elif frost_level == "medium":
        actions.append("Keep a few days of flexibility around the sowing date because of frost.")
    if heat_level == "high":
        actions.append("Shift sowing so flowering does not fall in the hottest month.")
    if drought_level == "high":
        actions.append("Secure water or choose a drought-tolerant crop before planting.")
    if not actions:
        actions.append("Risk levels look manageable. Keep the weekly field check and the 5-day forecast.")
    actions.append("Record the actual frost, heat and rainfall dates each season to improve next year's plan.")

    pieces: list[str] = []
    if crop_name:
        pieces.append(f"For {crop_name}:")
    pieces.append(f"frost {frost.risk_label.lower()}, heat {heat.risk_label.lower()}, drought {drought.risk_label.lower()}.")
    if last_frost and first_frost:
        pieces.append(f"Normal last spring frost: {last_frost}. First autumn frost: {first_frost}.")
    if frost_free_days:
        pieces.append(f"Longest frost-free run: about {frost_free_days} days ({frost.frost_free_window}).")
    summary = " ".join(pieces)

    return RiskSection(
        overall_level=overall_level,
        overall_label=RISK_LABELS[overall_level],
        crop_key=crop.key if crop else None,
        crop_name=crop_name,
        summary=summary,
        frost=frost,
        heat=heat,
        drought=drought,
        months=month_rows,
        actions=actions,
        notes=[
            "This is a climate-normal risk indicator, not a weather forecast.",
            "Use the local extension service and the 5-day forecast before a critical operation.",
        ],
    )


def risk_for_crop_key(
    environment: EnvironmentSnapshot,
    crop_key: str,
    *,
    water_deficit_mm: float = 0.0,
    irrigation: Irrigation = Irrigation.RAINFED,
) -> RiskSection:
    crop = resolve_crop(crop_key)
    return assess_risk(
        environment,
        crop=crop,
        water_deficit_mm=water_deficit_mm,
        irrigation=irrigation,
    )
