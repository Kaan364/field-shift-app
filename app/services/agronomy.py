"""Agronomic interpretation of NASA POWER data.

NASA POWER supplies gridded climate and soil-moisture/temperature proxies. It
does **not** supply soil nutrients (N-P-K), pH or organic matter. Those must
come from the farmer or a laboratory analysis. This module keeps that
distinction explicit in the response (``data_gaps`` and ``notes``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from app.clients.nasa_power import NASAResult
from app.domain.crops import MONTH_NAMES_TR, CropProfile
from app.schemas import (
    ClimateSummary,
    EnvironmentSnapshot,
    FieldProfile,
    Irrigation,
    MonthlyClimate,
    RecentWeather,
    Resources,
    SoilSummary,
    SoilTexture,
    WaterAvailability,
)

MONTH_KEYS: tuple[str, ...] = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)
MONTH_DAYS: tuple[int, ...] = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

CLIMATE_CLASS_LABELS_TR = {
    "hyper_arid": "hiper-kurak",
    "arid": "kurak",
    "semi_arid": "yarı kurak",
    "dry_sub_humid": "kuru-yarı nemli",
    "humid": "nemli",
    "per_humid": "çok nemli",
    "unknown": "bilinmiyor",
}

IRRIGATION_SUPPLY_MM: dict[tuple[Irrigation, WaterAvailability], float] = {
    (Irrigation.RAINFED, WaterAvailability.LOW): 0.0,
    (Irrigation.RAINFED, WaterAvailability.MEDIUM): 0.0,
    (Irrigation.RAINFED, WaterAvailability.HIGH): 0.0,
    (Irrigation.LIMITED, WaterAvailability.LOW): 50.0,
    (Irrigation.LIMITED, WaterAvailability.MEDIUM): 120.0,
    (Irrigation.LIMITED, WaterAvailability.HIGH): 180.0,
    (Irrigation.FULL, WaterAvailability.LOW): 180.0,
    (Irrigation.FULL, WaterAvailability.MEDIUM): 350.0,
    (Irrigation.FULL, WaterAvailability.HIGH): 500.0,
}


def _mean(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _sum(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _parameter_by_month(result: NASAResult, parameter: str) -> dict[int, float | None]:
    series = result.parameters.get(parameter, {})
    return {index + 1: series.get(key) for index, key in enumerate(MONTH_KEYS)}


def band_score(
    value: float | None,
    optimal: tuple[float, float],
    hard: tuple[float, float],
) -> float | None:
    """Linear 0-100 score that is 100 inside ``optimal`` and 0 outside ``hard``."""

    if value is None:
        return None
    low, high = optimal
    hard_low, hard_high = hard
    if low <= value <= high:
        return 100.0
    if value < low:
        if value <= hard_low:
            return 0.0
        return 100.0 * (value - hard_low) / (low - hard_low)
    if value >= hard_high:
        return 0.0
    return 100.0 * (hard_high - value) / (hard_high - high)


def irrigation_supply_mm(resources: Resources) -> float:
    """Effective seasonal irrigation supply used in the water balance."""

    return IRRIGATION_SUPPLY_MM.get((resources.irrigation, resources.water_availability), 0.0)


def _extraterrestrial_radiation_mm_day(latitude: float, month: int) -> float:
    """FAO-56 extraterrestrial radiation (Ra) expressed in mm/day."""

    day_of_year = sum(MONTH_DAYS[: month - 1]) + 15
    phi = math.radians(max(-66.0, min(66.0, latitude)))
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
    delta = 0.409 * math.sin(2.0 * math.pi * day_of_year / 365.0 - 1.39)
    x = -math.tan(phi) * math.tan(delta)
    omega = math.acos(max(-1.0, min(1.0, x)))
    ra_mj = (
        (24.0 * 60.0 / math.pi)
        * 0.0820
        * dr
        * (
            omega * math.sin(phi) * math.sin(delta)
            + math.cos(phi) * math.cos(delta) * math.sin(omega)
        )
    )
    return ra_mj * 0.408


def monthly_reference_et0(climatology: NASAResult) -> dict[int, float | None]:
    """Hargreaves-Samani reference evapotranspiration (mm/day) per month.

    NASA POWER exposes actual evaporation/evapotranspiration, which is not a
    valid denominator for an aridity index. Hargreaves is a transparent,
    temperature-based reference ET that can be computed from the climatology.
    """

    t2m = _parameter_by_month(climatology, "T2M")
    tmax = _parameter_by_month(climatology, "T2M_MAX")
    tmin = _parameter_by_month(climatology, "T2M_MIN")
    result: dict[int, float | None] = {}
    for month in range(1, 13):
        mean = t2m[month]
        high = tmax[month]
        low = tmin[month]
        if mean is None or high is None or low is None:
            result[month] = None
            continue
        ra = _extraterrestrial_radiation_mm_day(climatology.latitude, month)
        et0 = 0.0023 * (mean + 17.8) * math.sqrt(max(0.1, high - low)) * ra
        result[month] = max(0.0, et0)
    return result


def summarize_climate(climatology: NASAResult) -> ClimateSummary:
    t2m = _parameter_by_month(climatology, "T2M")
    tmax = _parameter_by_month(climatology, "T2M_MAX")
    tmin = _parameter_by_month(climatology, "T2M_MIN")
    precip_day = _parameter_by_month(climatology, "PRECTOTCORR")
    solar = _parameter_by_month(climatology, "ALLSKY_SFC_SW_DWN")
    et0_daily = monthly_reference_et0(climatology)

    monthly_precip = {
        month: (None if precip_day[month] is None else precip_day[month] * MONTH_DAYS[month - 1])
        for month in range(1, 13)
    }
    annual_precip = _sum(monthly_precip.values())

    monthly_evap = {
        month: (None if et0_daily[month] is None else et0_daily[month] * MONTH_DAYS[month - 1])
        for month in range(1, 13)
    }
    annual_evap = _sum(monthly_evap.values())

    aridity_index = None
    if annual_precip is not None and annual_evap and annual_evap > 0:
        aridity_index = annual_precip / annual_evap

    if aridity_index is None:
        climate_class = "unknown"
    elif aridity_index < 0.05:
        climate_class = "hyper_arid"
    elif aridity_index < 0.20:
        climate_class = "arid"
    elif aridity_index < 0.50:
        climate_class = "semi_arid"
    elif aridity_index < 0.65:
        climate_class = "dry_sub_humid"
    elif aridity_index < 1.0:
        climate_class = "humid"
    else:
        climate_class = "per_humid"

    growing_months = [month for month in range(1, 13) if (t2m[month] or -99) >= 5.0]
    growing_days = sum(MONTH_DAYS[month - 1] for month in growing_months)
    growing_temps = [t2m[month] for month in growing_months if t2m[month] is not None]

    frost_months = [
        MONTH_NAMES_TR[month - 1]
        for month in range(1, 13)
        if tmin[month] is not None and tmin[month] < 0
    ]
    heat_months = [
        MONTH_NAMES_TR[month - 1]
        for month in range(1, 13)
        if tmax[month] is not None and tmax[month] >= 32
    ]

    return ClimateSummary(
        annual_mean_temp_c=_round(_mean(t2m.values())),
        growing_season_mean_temp_c=_round(_mean(growing_temps)),
        annual_precip_mm=_round(annual_precip, 1),
        annual_evapotranspiration_mm=_round(annual_evap, 1),
        aridity_index=_round(aridity_index, 3),
        climate_class=climate_class,
        growing_season_days=growing_days or None,
        frost_months=frost_months,
        heat_stress_months=heat_months,
        annual_solar_kwh_m2_day=_round(_mean(solar.values())),
    )


def summarize_soil(climatology: NASAResult, field: FieldProfile) -> SoilSummary:
    gwetroot = _parameter_by_month(climatology, "GWETROOT")
    gwettop = _parameter_by_month(climatology, "GWETTOP")
    soil_temp = _parameter_by_month(climatology, "TS")

    root_mean = _mean(gwetroot.values())
    top_mean = _mean(gwettop.values())
    soil_temp_mean = _mean(soil_temp.values())

    scores: list[tuple[float, float]] = []
    moisture_score = band_score(root_mean, (0.40, 0.70), (0.0, 1.0))
    if moisture_score is not None:
        scores.append((moisture_score, 0.40))
    temp_score = band_score(soil_temp_mean, (15.0, 25.0), (0.0, 40.0))
    if temp_score is not None:
        scores.append((temp_score, 0.25))
    ph_score = band_score(field.soil_ph, (6.2, 7.5), (4.0, 9.5))
    if ph_score is not None:
        scores.append((ph_score, 0.20))
    organic_score = band_score(field.organic_matter_pct, (2.5, 8.0), (0.0, 12.0))
    if organic_score is not None:
        scores.append((organic_score, 0.15))

    condition_score = None
    if scores:
        total_weight = sum(weight for _, weight in scores)
        condition_score = sum(score * weight for score, weight in scores) / total_weight

    gaps: list[str] = []
    if field.soil_ph is None:
        gaps.append("Toprak pH'ı girilmedi; pH puanı NASA verisinden tahmin edilemez.")
    if field.organic_matter_pct is None:
        gaps.append("Organik madde oranı girilmedi; toprak analizi önerilir.")
    if field.soil_texture == SoilTexture.UNKNOWN:
        gaps.append("Toprak dokusu girilmedi; bünye uyumu varsayılan puanla değerlendirildi.")
    if field.salinity_ds_m is None:
        gaps.append("Toprak tuzluluğu (EC) girilmedi; tuzluluk riski sınırlı doğrulukla değerlendirildi.")
    gaps.append(
        "NASA POWER besin elementleri (N-P-K) ve organik madde sağlamaz; "
        "bu değerler çiftçi beyanı veya laboratuvar analizi ile doğrulanmalıdır."
    )

    return SoilSummary(
        root_zone_moisture_mean=_round(root_mean, 3),
        topsoil_moisture_mean=_round(top_mean, 3),
        mean_soil_temp_c=_round(soil_temp_mean),
        soil_condition_score=_round(condition_score, 1),
        soil_condition_label=soil_condition_label(condition_score),
        soil_texture=field.soil_texture,
        soil_ph=field.soil_ph,
        organic_matter_pct=field.organic_matter_pct,
        salinity_ds_m=field.salinity_ds_m,
        drainage=field.drainage,
        data_gaps=gaps,
    )


def soil_condition_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 80:
        return "iyi"
    if score >= 60:
        return "orta"
    if score >= 40:
        return "zayıf"
    return "çok zayıf"


def summarize_recent_weather(daily: NASAResult, window_days: int) -> RecentWeather | None:
    temps = daily.parameters.get("T2M", {})
    tmax = daily.parameters.get("T2M_MAX", {})
    tmin = daily.parameters.get("T2M_MIN", {})
    precip = daily.parameters.get("PRECTOTCORR", {})
    moisture = daily.parameters.get("GWETROOT", {})

    dates = sorted(temps.keys())
    available_temps = [temps[d] for d in dates if temps[d] is not None]
    if not available_temps:
        return None

    precip_values = [precip.get(d) for d in dates]
    valid_precip = [value for value in precip_values if value is not None]

    rainy_days = None
    longest_dry = None
    if valid_precip:
        rainy_days = sum(1 for value in valid_precip if value >= 1.0)
        longest = current = 0
        for value in precip_values:
            if value is None:
                current = 0
            elif value < 1.0:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        longest_dry = longest

    tmax_values = [tmax[d] for d in dates if tmax.get(d) is not None]
    tmin_values = [tmin[d] for d in dates if tmin.get(d) is not None]
    moisture_values = [moisture[d] for d in dates if moisture.get(d) is not None]

    return RecentWeather(
        window_days=window_days,
        available_days=len(available_temps),
        mean_temp_c=_round(_mean(available_temps)),
        min_temp_c=_round(min(tmin_values) if tmin_values else min(available_temps)),
        max_temp_c=_round(max(tmax_values) if tmax_values else max(available_temps)),
        total_precip_mm=_round(sum(valid_precip), 1) if valid_precip else None,
        rainy_days=rainy_days,
        longest_dry_spell_days=longest_dry,
        mean_root_zone_moisture=_round(_mean(moisture_values), 3),
    )


def build_environment(
    climatology: NASAResult,
    daily: NASAResult | None,
    field: FieldProfile,
    *,
    recent_days: int = 30,
) -> tuple[EnvironmentSnapshot, list[str]]:
    climate = summarize_climate(climatology)
    soil = summarize_soil(climatology, field)

    monthly: list[MonthlyClimate] = []
    t2m = _parameter_by_month(climatology, "T2M")
    tmax = _parameter_by_month(climatology, "T2M_MAX")
    tmin = _parameter_by_month(climatology, "T2M_MIN")
    precip = _parameter_by_month(climatology, "PRECTOTCORR")
    humidity = _parameter_by_month(climatology, "RH2M")
    solar = _parameter_by_month(climatology, "ALLSKY_SFC_SW_DWN")
    wind = _parameter_by_month(climatology, "WS2M")
    et0 = monthly_reference_et0(climatology)
    root_moisture = _parameter_by_month(climatology, "GWETROOT")
    top_moisture = _parameter_by_month(climatology, "GWETTOP")
    soil_temp = _parameter_by_month(climatology, "TS")

    for month in range(1, 13):
        monthly.append(
            MonthlyClimate(
                month=MONTH_NAMES_TR[month - 1],
                mean_temp_c=_round(t2m[month]),
                min_temp_c=_round(tmin[month]),
                max_temp_c=_round(tmax[month]),
                precip_mm_per_day=_round(precip[month]),
                precip_month_mm=_round(
                    None if precip[month] is None else precip[month] * MONTH_DAYS[month - 1], 1
                ),
                relative_humidity_pct=_round(humidity[month]),
                solar_kwh_m2_day=_round(solar[month]),
                wind_speed_m_s=_round(wind[month]),
                evapotranspiration_mm_per_day=_round(et0[month]),
                root_zone_moisture=_round(root_moisture[month], 3),
                topsoil_moisture=_round(top_moisture[month], 3),
                soil_temp_c=_round(soil_temp[month]),
                frost_risk=bool(tmin[month] is not None and tmin[month] < 0),
                heat_stress=bool(tmax[month] is not None and tmax[month] >= 32),
            )
        )

    recent = summarize_recent_weather(daily, recent_days) if daily is not None else None

    notes = list(soil.data_gaps)
    notes.append(
        "NASA POWER iklim verisi 25 yıllık (2001-2025) grid tabanlı bir ortalamadır; "
        "tarla ölçeğinde ve bu yılın gerçek hasat verisi değildir."
    )
    notes.append(
        "Kuraklık sınıfı, sıcaklık ve yağıştan hesaplanan Hargreaves referans evapotranspirasyonuna "
        "(ET0) göre tahmin edilir; resmî bir kuraklık endeksi değildir."
    )
    notes.append(
        "NASA POWER çözünürlüğü yaklaşık 0.5° × 0.625°'dir (ekvatora yakın ~50-70 km). "
        "Aynı grid hücresindeki iki tarla farklı toprak koşullarına sahip olabilir."
    )
    if daily is not None and recent is not None and recent.available_days < recent_days:
        notes.append(
            f"Son {recent_days} günün yalnızca {recent.available_days} günü için geçerli veri bulundu; "
            "NASA POWER'da son günler gecikmeli olabilir."
        )
    if recent is None:
        notes.append("Son günlük hava verisi alınamadı; analiz iklim ortalamalarına dayanıyor.")

    env = EnvironmentSnapshot(
        nasa_elevation_m=_round(climatology.elevation_m, 1),
        climate=climate,
        soil=soil,
        recent_weather=recent,
        monthly=monthly,
        notes=notes,
    )
    return env, notes


# ---------------------------------------------------------------------------
# Crop-calendar helpers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SeasonMetrics:
    start_month: int
    months: tuple[int, ...]
    window_label: str
    mean_temp_c: float | None
    total_precip_mm: float | None
    frost_months: list[str]
    heat_months: list[str]

    @property
    def days(self) -> int:
        return sum(MONTH_DAYS[month - 1] for month in self.months)


def month_span_label(months: tuple[int, ...]) -> str:
    if not months:
        return ""
    if len(months) == 1:
        return MONTH_NAMES_TR[months[0] - 1]
    return f"{MONTH_NAMES_TR[months[0] - 1]}–{MONTH_NAMES_TR[months[-1] - 1]}"


def choose_start_month(crop: CropProfile, preferred_month: int | None) -> int:
    months = crop.planting_months
    if not months:
        return 1
    if preferred_month is None:
        return months[0]
    if preferred_month in months:
        return preferred_month

    def circular_distance(month: int, target: int) -> int:
        raw = abs(month - target)
        return min(raw, 12 - raw)

    return min(months, key=lambda month: circular_distance(month, preferred_month))


def season_metrics(
    environment: EnvironmentSnapshot,
    crop: CropProfile,
    preferred_month: int | None = None,
) -> SeasonMetrics:
    start = choose_start_month(crop, preferred_month)
    length = max(1, min(12, math.ceil(crop.growing_days / 30)))
    months = tuple(((start - 1 + offset) % 12) + 1 for offset in range(length))

    monthly_by_number = {index + 1: item for index, item in enumerate(environment.monthly)}
    temps = [monthly_by_number[m].mean_temp_c for m in months]
    precip = [monthly_by_number[m].precip_month_mm for m in months]
    frost = [
        monthly_by_number[m].month
        for m in months
        if monthly_by_number[m].frost_risk
    ]
    heat = [
        monthly_by_number[m].month
        for m in months
        if monthly_by_number[m].heat_stress
    ]

    return SeasonMetrics(
        start_month=start,
        months=months,
        window_label=month_span_label(months),
        mean_temp_c=_round(_mean(temps)),
        total_precip_mm=_round(_sum(precip), 1),
        frost_months=frost,
        heat_months=heat,
    )
