"""Seasonal and monthly water balance for a crop or a rotation.

NASA POWER climatology provides rainfall and the temperature inputs for a
Hargreaves reference evapotranspiration. The crop coefficient is deliberately
not modelled: the crop catalogue already stores a seasonal water requirement,
so the plan compares *that* requirement with rainfall and the farmer's stated
irrigation capacity.

1 mm of water over 1 decare (1,000 m²) is 1 m³ = 1 tonne. The farmer-facing
text uses tonnes per decare because that is what is sold and pumped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.crops import CropProfile
from app.schemas import (
    Drainage,
    EnvironmentSnapshot,
    FieldProfile,
    Irrigation,
    Resources,
)
from app.services.agronomy import irrigation_supply_mm, season_metrics

DECARE_PER_HECTARE = 10.0


@dataclass
class MonthlyWaterRow:
    month: str
    rain_mm: float | None
    et0_mm: float | None
    balance_mm: float | None
    status: str


@dataclass
class WaterPlan:
    summary: str
    label: str
    annual_rain_mm: float | None
    annual_et0_mm: float | None
    crop_need_mm: float
    season_rain_mm: float | None
    irrigation_supply_mm: float
    deficit_mm: float
    deficit_m3: float
    deficit_ton_per_decare: float
    area_decare: float
    months: list[MonthlyWaterRow] = field(default_factory=list)
    drought_months: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _status(rain: float | None, et0: float | None) -> str:
    if rain is None or et0 is None:
        return "unknown"
    if rain < et0 * 0.45:
        return "dry"
    if rain < et0 * 0.85:
        return "low"
    return "enough"


def _tips(
    resources: Resources,
    field: FieldProfile,
    deficit_mm: float,
    drought_months: list[str],
) -> list[str]:
    tips: list[str] = []
    if resources.irrigation == Irrigation.RAINFED:
        tips.append("No irrigation: choose a drought-tolerant variety and sow when the soil has enough moisture.")
        tips.append("Leave residue and use mulch; it keeps moisture in the soil.")
    elif resources.irrigation == Irrigation.LIMITED:
        tips.append("Save water for the critical stages: flowering and grain/fruit filling.")
        tips.append("Use drip or night irrigation to use water efficiently.")
        tips.append("Avoid deep tillage; it lets moisture escape.")
    else:
        tips.append("Measure soil moisture; over-irrigation causes root rot and salinity.")
        tips.append("Irrigate early in the morning or in the evening to cut evaporation.")
        tips.append("Delay irrigation after rain; count the rainfall you received.")
    if field.drainage == Drainage.POOR:
        tips.append("Improve drainage; waterlogged soil rots roots and builds up salt.")
    if field.organic_matter_pct is not None and field.organic_matter_pct < 2.0:
        tips.append("Organic matter is low; add manure/compost to raise the soil's water-holding capacity.")
    if deficit_mm > 50:
        tips.append("Consider a small pond or tank to harvest rainwater.")
    if drought_months:
        tips.append("Driest months: " + ", ".join(drought_months[:4]) + ". Plan irrigation around them.")
    tips.append("Check the salinity of your irrigation water; salty water damages the soil.")
    return tips[:6]


def build_water_plan(
    environment: EnvironmentSnapshot,
    field: FieldProfile,
    resources: Resources,
    *,
    crops: list[CropProfile],
    season_rain_mm: float | None = None,
    planting_month: int | None = None,
) -> WaterPlan:
    annual_rain = environment.climate.annual_precip_mm
    annual_et0 = environment.climate.annual_evapotranspiration_mm

    if season_rain_mm is None:
        rains = [
            season_metrics(environment, crop, planting_month if index == 0 else None).total_precip_mm
            for index, crop in enumerate(crops)
        ]
        present = [value for value in rains if value is not None]
        season_rain_mm = round(sum(present), 1) if present else None

    need = float(sum(crop.water_need_mm for crop in crops))
    supply = (season_rain_mm or 0.0) + irrigation_supply_mm(resources) * max(1, len(crops))
    deficit = max(0.0, need - supply)
    area_decare = max(0.1, field.area_hectares * DECARE_PER_HECTARE)

    months: list[MonthlyWaterRow] = []
    drought_months: list[str] = []
    for item in environment.monthly:
        rain = item.precip_month_mm
        et0 = None
        if item.evapotranspiration_mm_per_day is not None:
            # Month length is approximately encoded in the rainfall field; use 30 days.
            et0 = round(item.evapotranspiration_mm_per_day * 30.0, 1)
        status = _status(rain, et0)
        if status == "dry":
            drought_months.append(item.month)
        months.append(
            MonthlyWaterRow(
                month=item.month,
                rain_mm=rain,
                et0_mm=et0,
                balance_mm=None if rain is None or et0 is None else round(rain - et0, 1),
                status=status,
            )
        )

    if need <= 0:
        label = "not calculated"
        summary = "The water need could not be calculated."
    elif deficit <= 10:
        label = "water is enough"
        summary = (
            f"The plan needs about {need:.0f} mm of water in total. "
            f"Rainfall and the irrigation you reported appear to cover it."
        )
    elif deficit <= 60:
        label = "a little irrigation needed"
        summary = (
            f"Total need is about {need:.0f} mm; rainfall is {season_rain_mm or 0:.0f} mm. "
            f"You may need about {deficit:.0f} mm of extra irrigation."
        )
    else:
        label = "irrigation is essential"
        summary = (
            f"Total need is about {need:.0f} mm; rainfall is {season_rain_mm or 0:.0f} mm. "
            f"You need about {deficit:.0f} mm of extra irrigation."
        )

    deficit_m3 = deficit * area_decare  # mm × decare = m³
    tips = _tips(resources, field, deficit, drought_months)

    notes = [
        "1 mm of water over 1 decare is 1 tonne (1 m³) of water.",
        "Rainfall is the NASA POWER 25-year climate average; this year's rain can be different.",
        "The crop water need is an approximate seasonal catalogue value; variety and soil change it.",
        "Check irrigation-water quality and salinity separately.",
    ]

    return WaterPlan(
        summary=summary,
        label=label,
        annual_rain_mm=annual_rain,
        annual_et0_mm=annual_et0,
        crop_need_mm=round(need, 1),
        season_rain_mm=season_rain_mm,
        irrigation_supply_mm=round(irrigation_supply_mm(resources) * max(1, len(crops)), 1),
        deficit_mm=round(deficit, 1),
        deficit_m3=round(deficit_m3, 1),
        deficit_ton_per_decare=round(deficit, 1),
        area_decare=round(area_decare, 1),
        months=months,
        drought_months=drought_months,
        tips=tips,
        notes=notes,
    )
