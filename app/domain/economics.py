"""Simple, transparent crop budget (profit and cost) engine.

The numbers here are deliberately explicit, round and easy to explain. They are
planning assumptions, **not** market quotes: a farmer or extension officer can
replace them with local values without touching the rest of the app.

Money is expressed in US dollars per hectare and per decare (1 ha = 10 decare).
Yields are tonnes per hectare and prices are US dollars per tonne. Keeping one
currency avoids inventing exchange rates; the UI shows a clear caveat.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.crops import CropProfile, resolve_crop
from app.schemas import EnvironmentSnapshot, FieldProfile, Irrigation, Resources

DECARE_PER_HECTARE = 10.0
# Approximate on-farm cost of lifting and applying one cubic metre of water.
WATER_COST_USD_PER_M3 = 0.02


@dataclass(frozen=True)
class EconomicAssumptions:
    yield_t_per_ha: float
    price_usd_per_t: float
    costs_usd_per_ha: dict[str, float]

    @property
    def total_cost_usd_per_ha(self) -> float:
        return sum(self.costs_usd_per_ha.values())


# Typical small/medium-farm budgets. Values are rounded planning figures.
CROP_ECONOMICS: dict[str, EconomicAssumptions] = {
    "wheat": EconomicAssumptions(4.0, 250, {"seed": 90, "fertilizer": 180, "crop_protection": 40, "fuel_machinery": 90, "irrigation": 20, "labor": 80, "other": 50}),
    "barley": EconomicAssumptions(4.5, 220, {"seed": 80, "fertilizer": 150, "crop_protection": 30, "fuel_machinery": 80, "irrigation": 15, "labor": 70, "other": 45}),
    "triticale": EconomicAssumptions(4.5, 210, {"seed": 85, "fertilizer": 150, "crop_protection": 30, "fuel_machinery": 85, "irrigation": 15, "labor": 70, "other": 45}),
    "oats": EconomicAssumptions(4.0, 200, {"seed": 80, "fertilizer": 130, "crop_protection": 25, "fuel_machinery": 75, "irrigation": 15, "labor": 65, "other": 40}),
    "maize": EconomicAssumptions(9.0, 230, {"seed": 150, "fertilizer": 320, "crop_protection": 90, "fuel_machinery": 170, "irrigation": 150, "labor": 140, "other": 80}),
    "sunflower": EconomicAssumptions(3.0, 500, {"seed": 90, "fertilizer": 170, "crop_protection": 60, "fuel_machinery": 110, "irrigation": 60, "labor": 80, "other": 50}),
    "canola": EconomicAssumptions(2.8, 520, {"seed": 70, "fertilizer": 190, "crop_protection": 70, "fuel_machinery": 110, "irrigation": 50, "labor": 80, "other": 50}),
    "safflower": EconomicAssumptions(2.0, 600, {"seed": 60, "fertilizer": 120, "crop_protection": 40, "fuel_machinery": 100, "irrigation": 40, "labor": 70, "other": 50}),
    "chickpea": EconomicAssumptions(2.2, 700, {"seed": 120, "fertilizer": 80, "crop_protection": 60, "fuel_machinery": 100, "irrigation": 30, "labor": 80, "other": 50}),
    "lentil": EconomicAssumptions(1.8, 650, {"seed": 100, "fertilizer": 70, "crop_protection": 50, "fuel_machinery": 90, "irrigation": 25, "labor": 75, "other": 40}),
    "soybean": EconomicAssumptions(3.0, 450, {"seed": 120, "fertilizer": 120, "crop_protection": 80, "fuel_machinery": 120, "irrigation": 90, "labor": 80, "other": 40}),
    "alfalfa": EconomicAssumptions(15.0, 200, {"seed": 120, "fertilizer": 160, "crop_protection": 50, "fuel_machinery": 200, "irrigation": 220, "labor": 200, "other": 100}),
    "sainfoin": EconomicAssumptions(10.0, 200, {"seed": 110, "fertilizer": 90, "crop_protection": 40, "fuel_machinery": 170, "irrigation": 100, "labor": 160, "other": 80}),
    "vetch": EconomicAssumptions(4.0, 150, {"seed": 90, "fertilizer": 60, "crop_protection": 30, "fuel_machinery": 80, "irrigation": 20, "labor": 50, "other": 30}),
    "potato": EconomicAssumptions(35.0, 250, {"seed": 900, "fertilizer": 900, "crop_protection": 400, "fuel_machinery": 700, "irrigation": 600, "labor": 900, "other": 500}),
    "sugar_beet": EconomicAssumptions(60.0, 55, {"seed": 260, "fertilizer": 500, "crop_protection": 220, "fuel_machinery": 450, "irrigation": 350, "labor": 400, "other": 200}),
    "tomato": EconomicAssumptions(60.0, 300, {"seed": 900, "fertilizer": 1800, "crop_protection": 1200, "fuel_machinery": 1500, "irrigation": 1200, "labor": 4500, "other": 900}),
    "cotton": EconomicAssumptions(3.5, 1500, {"seed": 180, "fertilizer": 450, "crop_protection": 350, "fuel_machinery": 500, "irrigation": 600, "labor": 550, "other": 250}),
    "olive": EconomicAssumptions(5.0, 900, {"seed": 0, "fertilizer": 350, "crop_protection": 250, "fuel_machinery": 350, "irrigation": 300, "labor": 450, "other": 200}),
    "grape": EconomicAssumptions(12.0, 500, {"seed": 0, "fertilizer": 400, "crop_protection": 500, "fuel_machinery": 450, "irrigation": 400, "labor": 900, "other": 350}),
    "apple": EconomicAssumptions(30.0, 450, {"seed": 0, "fertilizer": 700, "crop_protection": 900, "fuel_machinery": 700, "irrigation": 600, "labor": 2500, "other": 600}),
}

DEFAULT_ASSUMPTIONS = EconomicAssumptions(
    3.0,
    300,
    {"seed": 100, "fertilizer": 180, "crop_protection": 80, "fuel_machinery": 120, "irrigation": 100, "labor": 150, "other": 80},
)

COST_LABELS = {
    "seed": "Seed",
    "fertilizer": "Fertiliser",
    "crop_protection": "Crop protection",
    "fuel_machinery": "Fuel and machinery",
    "irrigation": "Irrigation water",
    "labor": "Labour",
    "other": "Other costs",
}


@dataclass
class CostLine:
    key: str
    label: str
    amount_usd: float


@dataclass
class CropEconomics:
    crop_key: str
    crop_name: str
    area_hectares: float
    yield_t_per_ha: float
    price_usd_per_t: float
    expected_yield_t: float
    revenue_usd: float
    total_cost_usd: float
    gross_margin_usd: float
    margin_per_ha_usd: float
    margin_per_decare_usd: float
    total_cost_per_ha_usd: float
    break_even_price_usd_per_t: float
    break_even_yield_t_per_ha: float
    roi_pct: float
    low_profit_usd: float
    high_profit_usd: float
    costs: list[CostLine] = field(default_factory=list)
    confidence: str = "medium"
    summary: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class EconomicsSection:
    available: bool
    headline: str
    summary: str
    currency: str
    area_hectares: float
    area_decare: float
    total_revenue_usd: float
    total_cost_usd: float
    total_gross_margin_usd: float
    margin_per_decare_usd: float
    break_even_price_usd_per_t: float
    roi_pct: float
    low_profit_usd: float
    high_profit_usd: float
    crops: list[CropEconomics] = field(default_factory=list)
    years: list[dict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _round(value: float, digits: int = 0) -> float:
    return round(value, digits)


def _money(value: float) -> str:
    if abs(value) >= 1_000:
        return f"${value:,.0f}"
    return f"${value:.0f}"


def assumptions_for(crop: CropProfile) -> EconomicAssumptions:
    return CROP_ECONOMICS.get(crop.key, DEFAULT_ASSUMPTIONS)


def crop_economics(
    crop: CropProfile,
    area_hectares: float,
    *,
    water_deficit_mm: float = 0.0,
    irrigation: Irrigation = Irrigation.RAINFED,
    price_factor: float = 1.0,
    yield_factor: float = 1.0,
) -> CropEconomics:
    """Build a simple budget for one crop and one season."""

    area = max(0.1, float(area_hectares))
    base = assumptions_for(crop)
    yield_t_per_ha = max(0.1, base.yield_t_per_ha * yield_factor)
    price = max(1.0, base.price_usd_per_t * price_factor)
    expected_yield = yield_t_per_ha * area
    revenue = expected_yield * price

    costs = dict(base.costs_usd_per_ha)
    if water_deficit_mm > 0 and irrigation != Irrigation.RAINFED:
        # 1 mm over 1 ha is 10 m3. Only the deficit above rainfall is pumped.
        extra_water = water_deficit_mm * area * 10.0 * WATER_COST_USD_PER_M3
        per_ha = extra_water / area
        costs["irrigation"] = costs.get("irrigation", 0.0) + per_ha
    cost_lines = [
        CostLine(key=key, label=COST_LABELS.get(key, key.title()), amount_usd=_round(value * area))
        for key, value in costs.items()
    ]
    total_cost = sum(line.amount_usd for line in cost_lines)
    gross_margin = revenue - total_cost

    break_even_price = total_cost / expected_yield if expected_yield > 0 else 0.0
    break_even_yield = total_cost / (price * area) if price > 0 else 0.0
    roi = (gross_margin / total_cost * 100.0) if total_cost > 0 else 0.0

    # Simple uncertainty band: +/-15% revenue and +/-10% cost.
    low_profit = revenue * 0.85 - total_cost * 1.10
    high_profit = revenue * 1.15 - total_cost * 0.90

    if gross_margin >= 1000:
        tone = "strong"
    elif gross_margin >= 300:
        tone = "positive"
    elif gross_margin >= 0:
        tone = "thin"
    else:
        tone = "negative"

    summary = (
        f"{crop.name}: about {gross_margin / area:,.0f} USD profit per hectare "
        f"({gross_margin / (area * DECARE_PER_HECTARE):,.0f} USD per decare) "
        f"from a gross income of {revenue / area:,.0f} USD per hectare. "
        f"This is a {tone} margin before tax, land rent and your own labour value."
    )

    notes = [
        "Planning figures, not a market quote. Check local prices before you sell or borrow.",
        "The profit band assumes +/-15% price/yield and +/-10% cost variation.",
        "Land rent, loan interest and family labour are not included.",
    ]
    if water_deficit_mm > 50 and irrigation == Irrigation.RAINFED:
        notes.append("No irrigation: the budget assumes the crop survives on rainfall alone.")
    if gross_margin < 0:
        notes.append("This crop loses money at these assumptions. Consider a lower-cost crop or a contract price.")

    return CropEconomics(
        crop_key=crop.key,
        crop_name=crop.name,
        area_hectares=_round(area, 2),
        yield_t_per_ha=_round(yield_t_per_ha, 2),
        price_usd_per_t=_round(price, 2),
        expected_yield_t=_round(expected_yield, 2),
        revenue_usd=_round(revenue),
        total_cost_usd=_round(total_cost),
        gross_margin_usd=_round(gross_margin),
        margin_per_ha_usd=_round(gross_margin / area),
        margin_per_decare_usd=_round(gross_margin / (area * DECARE_PER_HECTARE)),
        total_cost_per_ha_usd=_round(total_cost / area),
        break_even_price_usd_per_t=_round(break_even_price, 2),
        break_even_yield_t_per_ha=_round(break_even_yield, 2),
        roi_pct=_round(roi, 1),
        low_profit_usd=_round(low_profit),
        high_profit_usd=_round(high_profit),
        costs=cost_lines,
        confidence="medium",
        summary=summary,
        notes=notes,
    )


def build_economics(
    environment: EnvironmentSnapshot,
    field: FieldProfile,
    resources: Resources,
    crops: list[CropProfile],
    *,
    area_hectares: float | None = None,
    water_deficit_mm: float = 0.0,
) -> EconomicsSection:
    """Budget for one crop or a multi-year rotation."""

    area = max(0.1, float(area_hectares or field.area_hectares or 1.0))
    if not crops:
        return EconomicsSection(
            available=False,
            headline="No crop to cost yet.",
            summary="Choose a location and a crop first. The money card will then show income, cost and profit.",
            currency="USD",
            area_hectares=_round(area, 2),
            area_decare=_round(area * DECARE_PER_HECTARE, 1),
            total_revenue_usd=0,
            total_cost_usd=0,
            total_gross_margin_usd=0,
            margin_per_decare_usd=0,
            break_even_price_usd_per_t=0,
            roi_pct=0,
            low_profit_usd=0,
            high_profit_usd=0,
            notes=["No budget was calculated because no crop was selected."],
        )

    budgets = [
        crop_economics(
            crop,
            area,
            water_deficit_mm=water_deficit_mm,
            irrigation=resources.irrigation,
        )
        for crop in crops
    ]
    total_revenue = sum(item.revenue_usd for item in budgets)
    total_cost = sum(item.total_cost_usd for item in budgets)
    total_margin = sum(item.gross_margin_usd for item in budgets)
    total_low = sum(item.low_profit_usd for item in budgets)
    total_high = sum(item.high_profit_usd for item in budgets)
    total_area = area * len(budgets)
    total_yield = sum(item.expected_yield_t for item in budgets)

    first = budgets[0]
    if len(budgets) == 1:
        headline = f"{first.crop_name}: about {_money(first.gross_margin_usd)} profit"
        summary = first.summary
    else:
        headline = f"{len(budgets)}-year plan: about {_money(total_margin)} total profit"
        summary = (
            f"Over {len(budgets)} seasons the plan could earn about {_money(total_revenue)} "
            f"and cost about {_money(total_cost)}, leaving roughly {_money(total_margin)}. "
            "Each season is shown separately so one weak year does not hide the rest."
        )

    years = [
        {
            "year": index,
            "crop_key": item.crop_key,
            "crop_name": item.crop_name,
            "revenue_usd": item.revenue_usd,
            "total_cost_usd": item.total_cost_usd,
            "gross_margin_usd": item.gross_margin_usd,
            "margin_per_decare_usd": item.margin_per_decare_usd,
            "confidence": item.confidence,
        }
        for index, item in enumerate(budgets, start=1)
    ]

    assumptions = [
        "Currency: US dollars. No exchange rate is assumed.",
        f"Area: {area:g} hectare(s) = {area * DECARE_PER_HECTARE:g} decare per season.",
        f"Rainfall: {environment.climate.annual_precip_mm or 'unknown'} mm/year (NASA POWER 25-year average).",
        "Yields, prices and costs are editable planning assumptions, not guarantees.",
    ]

    return EconomicsSection(
        available=True,
        headline=headline,
        summary=summary,
        currency="USD",
        area_hectares=_round(area, 2),
        area_decare=_round(area * DECARE_PER_HECTARE, 1),
        total_revenue_usd=_round(total_revenue),
        total_cost_usd=_round(total_cost),
        total_gross_margin_usd=_round(total_margin),
        margin_per_decare_usd=_round(total_margin / (total_area * DECARE_PER_HECTARE)) if total_area else 0,
        break_even_price_usd_per_t=_round(total_cost / total_yield, 2) if total_yield else 0,
        roi_pct=_round((total_margin / total_cost * 100.0) if total_cost else 0.0, 1),
        low_profit_usd=_round(total_low),
        high_profit_usd=_round(total_high),
        crops=budgets,
        years=years,
        assumptions=assumptions,
        notes=[
            "Money is before tax, land rent, loan interest and the value of family labour.",
            "Prices change. Confirm the buyer's price before planting a large area.",
            "A negative or thin margin is a warning, not a prediction.",
        ],
    )


def economics_for_crop_key(
    crop_key: str,
    area_hectares: float,
    *,
    water_deficit_mm: float = 0.0,
    irrigation: Irrigation = Irrigation.RAINFED,
) -> CropEconomics | None:
    crop = resolve_crop(crop_key)
    if crop is None:
        return None
    return crop_economics(
        crop, area_hectares, water_deficit_mm=water_deficit_mm, irrigation=irrigation
    )
