"""Climate trend outlook built from NASA POWER annual data.

The challenge is not only "what is the climate now?" but "how is it shifting?".
This module turns 20+ years of annual NASA POWER values into a *descriptive*
trend (warming, rainfall direction, frost signal) and a plain-language risk
level.

It is explicitly **not** a forecast. A linear trend over a short period can be
misleading, and the API response repeats that caveat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from app.clients.nasa_power import NASAAPIError, NASAResult
from app.schemas import EnvironmentSnapshot

logger = logging.getLogger(__name__)

MIN_YEARS = 6


@dataclass
class ClimateTrend:
    key: str
    label: str
    direction: str  # up | down | stable
    change: float
    per_decade: float
    unit: str
    message: str


@dataclass
class ClimateOutlook:
    available: bool
    start_year: int | None = None
    end_year: int | None = None
    available_years: int = 0
    baseline_temp_c: float | None = None
    recent_temp_c: float | None = None
    baseline_precip_mm: float | None = None
    recent_precip_mm: float | None = None
    risk_level: str = "unknown"
    risk_label: str = "Unknown"
    trends: list[ClimateTrend] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    dry_months: list[str] = field(default_factory=list)
    warmest_year: int | None = None
    driest_year: int | None = None
    notes: list[str] = field(default_factory=list)


def _year_series(result: NASAResult, parameter: str) -> list[tuple[int, float]]:
    series = result.parameters.get(parameter, {})
    points: list[tuple[int, float]] = []
    for key, value in series.items():
        if value is None:
            continue
        text = str(key).strip()
        if not text.isdigit():
            continue
        year = int(text)
        if 1981 <= year <= 2100:
            points.append((year, float(value)))
    points.sort()
    return points


def _mean(values: Iterable[float]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _slope(points: list[tuple[int, float]]) -> float:
    """Least-squares slope per year."""

    if len(points) < 2:
        return 0.0
    n = len(points)
    mean_x = sum(year for year, _ in points) / n
    mean_y = sum(value for _, value in points) / n
    numerator = sum((year - mean_x) * (value - mean_y) for year, value in points)
    denominator = sum((year - mean_x) ** 2 for year, _ in points)
    return numerator / denominator if denominator else 0.0


def _direction(change: float, threshold: float) -> str:
    if change > threshold:
        return "up"
    if change < -threshold:
        return "down"
    return "stable"


def _head_tail_mean(points: list[tuple[int, float]], head: int = 5) -> tuple[float | None, float | None]:
    if len(points) < 2:
        return None, None
    head_mean = _mean([value for _, value in points[:head]])
    tail_mean = _mean([value for _, value in points[-head:]])
    return head_mean, tail_mean


def _dry_months(environment: EnvironmentSnapshot) -> list[str]:
    months = [
        item.month
        for item in environment.monthly
        if item.precip_month_mm is not None and item.precip_month_mm < 25.0
    ]
    return months


def _empty_outlook(environment: EnvironmentSnapshot, reason: str) -> ClimateOutlook:
    return ClimateOutlook(
        available=False,
        risk_level="unknown",
        risk_label="No data",
        dry_months=_dry_months(environment),
        messages=[
            "The long-term temperature/rainfall trend could not be loaded; the plan uses the climate average.",
            "This is not a forecast. Follow local meteorological and extension-service warnings.",
        ],
        notes=[reason],
    )


def build_outlook_from_annual(
    annual: NASAResult,
    environment: EnvironmentSnapshot,
) -> ClimateOutlook:
    temps = _year_series(annual, "T2M")
    precip = _year_series(annual, "PRECTOTCORR")
    tmin = _year_series(annual, "T2M_MIN")

    if len(temps) < MIN_YEARS or len(precip) < MIN_YEARS:
        return _empty_outlook(
            environment,
            f"Not enough annual data (temperature {len(temps)}, rainfall {len(precip)} years).",
        )

    years = [year for year, _ in temps]
    start_year, end_year = years[0], years[-1]
    temp_slope = _slope(temps)
    precip_slope = _slope(precip)
    temp_change = temp_slope * (end_year - start_year)
    precip_change = precip_slope * (end_year - start_year)
    baseline_temp, recent_temp = _head_tail_mean(temps)
    baseline_precip, recent_precip = _head_tail_mean(precip)
    precip_percent = (
        (precip_change / baseline_precip * 100.0)
        if baseline_precip and baseline_precip > 0
        else 0.0
    )

    trends: list[ClimateTrend] = []
    messages: list[str] = []

    temp_direction = _direction(temp_change, 0.15)
    trends.append(
        ClimateTrend(
            key="temperature",
            label="Mean temperature",
            direction=temp_direction,
            change=round(temp_change, 2),
            per_decade=round(temp_slope * 10.0, 2),
            unit="°C",
            message=(
                f"In the last {end_year - start_year + 1} years mean temperature changed by "
                f"{temp_change:+.1f}°C ({temp_slope * 10.0:+.1f}°C per decade)."
            ),
        )
    )
    if temp_direction == "up":
        messages.append(
            f"The climate is warming: mean temperature rose {temp_change:+.1f}°C in the last "
            f"{end_year - start_year + 1} years. Heat-tolerant varieties and earlier sowing matter."
        )
    elif temp_direction == "down":
        messages.append(
            f"Mean temperature fell {temp_change:+.1f}°C. Account for frost risk in the sowing calendar."
        )
    else:
        messages.append("There is no clear trend in mean temperature.")

    precip_direction = _direction(precip_change, max(10.0, (baseline_precip or 0) * 0.03))
    trends.append(
        ClimateTrend(
            key="precipitation",
            label="Annual rainfall",
            direction=precip_direction,
            change=round(precip_change, 1),
            per_decade=round(precip_slope * 10.0, 1),
            unit="mm",
            message=(
                f"Annual rainfall changed by {precip_change:+.0f} mm ({precip_percent:+.0f}%); "
                f"about {precip_slope * 10.0:+.0f} mm per decade."
            ),
        )
    )
    if precip_direction == "down":
        messages.append(
            f"Rainfall is falling ({precip_percent:+.0f}%). Water harvesting, mulch and "
            "drought-tolerant crops become more important."
        )
    elif precip_direction == "up":
        messages.append(
            f"Rainfall is rising ({precip_percent:+.0f}%). The timing can still change; "
            "drainage and disease monitoring matter."
        )
    else:
        messages.append("There is no clear annual rainfall trend; the within-year distribution can change.")

    if len(tmin) >= MIN_YEARS:
        tmin_slope = _slope(tmin)
        tmin_change = tmin_slope * (tmin[-1][0] - tmin[0][0])
        trends.append(
            ClimateTrend(
                key="cold",
                label="Cold-season minimum temperature",
                direction=_direction(tmin_change, 0.2),
                change=round(tmin_change, 2),
                per_decade=round(tmin_slope * 10.0, 2),
                unit="°C",
                message=(
                    f"Mean annual minimum temperature changed by {tmin_change:+.1f}°C. "
                    "Frost dates can shift; keep the local frost calendar up to date."
                ),
            )
        )

    risk_score = 0
    if temp_change > 0.8:
        risk_score += 2
    elif temp_change > 0.3:
        risk_score += 1
    if precip_percent < -10:
        risk_score += 2
    elif precip_percent < -4:
        risk_score += 1
    aridity = environment.climate.aridity_index
    climate_class = environment.climate.climate_class
    if climate_class in {"hyper_arid", "arid"}:
        risk_score += 2
    elif climate_class == "semi_arid":
        risk_score += 1
    if aridity is not None and aridity < 0.2:
        risk_score += 1

    if risk_score >= 3:
        risk_level, risk_label = "high", "High"
    elif risk_score >= 1:
        risk_level, risk_label = "medium", "Medium"
    else:
        risk_level, risk_label = "low", "Low"

    warmest_year = max(temps, key=lambda item: item[1])[0]
    driest_year = min(precip, key=lambda item: item[1])[0]

    return ClimateOutlook(
        available=True,
        start_year=start_year,
        end_year=end_year,
        available_years=len(temps),
        baseline_temp_c=None if baseline_temp is None else round(baseline_temp, 2),
        recent_temp_c=None if recent_temp is None else round(recent_temp, 2),
        baseline_precip_mm=None if baseline_precip is None else round(baseline_precip, 1),
        recent_precip_mm=None if recent_precip is None else round(recent_precip, 1),
        risk_level=risk_level,
        risk_label=risk_label,
        trends=trends,
        messages=messages,
        dry_months=_dry_months(environment),
        warmest_year=warmest_year,
        driest_year=driest_year,
        notes=[
            f"NASA POWER monthly data was aggregated to years ({start_year}-{end_year}, {len(temps)} years).",
            "The trend is the linear direction of past data; it is not a forecast or an official climate projection.",
            "A single year can move against the trend. Use local observation when deciding.",
        ],
    )


async def build_climate_outlook(
    nasa_client,
    latitude: float,
    longitude: float,
    environment: EnvironmentSnapshot,
) -> ClimateOutlook:
    get_annual = getattr(nasa_client, "get_annual", None)
    if get_annual is None:
        return _empty_outlook(environment, "The NASA client does not support annual data.")
    try:
        annual = await get_annual(latitude, longitude)
    except NASAAPIError as exc:
        logger.info("Annual NASA data could not be loaded: %s", exc)
        return _empty_outlook(environment, f"Annual NASA data could not be loaded: {exc}")
    except Exception as exc:  # noqa: BLE001 - outlook must never break the plan
        logger.warning("Climate trend could not be calculated: %s", exc, exc_info=True)
        return _empty_outlook(environment, "Unexpected error while calculating the climate trend.")
    return build_outlook_from_annual(annual, environment)
