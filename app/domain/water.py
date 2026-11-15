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
        return "bilinmiyor"
    if rain < et0 * 0.45:
        return "kurak"
    if rain < et0 * 0.85:
        return "kuru"
    return "yeterli"


def _tips(
    resources: Resources,
    field: FieldProfile,
    deficit_mm: float,
    drought_months: list[str],
) -> list[str]:
    tips: list[str] = []
    if resources.irrigation == Irrigation.RAINFED:
        tips.append("Sulama yok: kuraklığa dayanıklı çeşit seç ve ekimi toprak nemi yeterliyken yap.")
        tips.append("Anızı bırak ve malç kullan; toprak nemini korur.")
    elif resources.irrigation == Irrigation.LIMITED:
        tips.append("Suyu en kritik dönemlere ayır: çiçeklenme ve tane/dane dolumu.")
        tips.append("Damla sulama veya gece sulaması ile suyu verimli kullan.")
        tips.append("Toprağı çok sürmekten kaçın; nem buharlaşmasın.")
    else:
        tips.append("Toprak nemini ölç; ihtiyaçtan fazla sulama kök çürüklüğü ve tuzluluk yapar.")
        tips.append("Sulamayı sabah erken veya akşam yap; buharlaşma kaybını azalt.")
        tips.append("Yağmurdan sonra sulamayı geciktir; yağışı hesaba kat.")
    if field.drainage == Drainage.POOR:
        tips.append("Drenajı iyileştir; su biriken yerde kök çürür ve tuz birikir.")
    if field.organic_matter_pct is not None and field.organic_matter_pct < 2.0:
        tips.append("Organik madde az; gübre/kompost ile toprağın su tutma kapasitesini artır.")
    if deficit_mm > 50:
        tips.append("Yağmur suyunu hasat etmek için küçük bir gölet veya depo düşün.")
    if drought_months:
        tips.append("En kurak aylar: " + ", ".join(drought_months[:4]) + ". Sulama planını bu aylara göre yap.")
    tips.append("Sulama suyunun tuzluluğunu kontrol et; tuzlu su toprağı bozar.")
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
        if status == "kurak":
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
        label = "hesaplanamadı"
        summary = "Su ihtiyacı hesaplanamadı."
    elif deficit <= 10:
        label = "su yeterli"
        summary = (
            f"Bu planın toplam su ihtiyacı yaklaşık {need:.0f} mm. "
            f"Yağış ve sulama imkânı bunu karşılıyor görünüyor."
        )
    elif deficit <= 60:
        label = "az sulama gerek"
        summary = (
            f"Toplam ihtiyaç yaklaşık {need:.0f} mm; yağış {season_rain_mm or 0:.0f} mm. "
            f"Yaklaşık {deficit:.0f} mm ek sulama gerekebilir."
        )
    else:
        label = "sulama şart"
        summary = (
            f"Toplam ihtiyaç yaklaşık {need:.0f} mm; yağış {season_rain_mm or 0:.0f} mm. "
            f"Yaklaşık {deficit:.0f} mm ek sulama gerekir."
        )

    deficit_m3 = deficit * area_decare  # mm × dekar = m³
    tips = _tips(resources, field, deficit, drought_months)

    notes = [
        "1 mm su, 1 dönümde 1 ton (1 m³) su demektir.",
        "Yağış verisi NASA POWER 25 yıllık iklim ortalamasıdır; bu yılın gerçek yağışı farklı olabilir.",
        "Bitki su ihtiyacı katalogdaki yaklaşık sezonluk değerdir; çeşit ve toprağa göre değişir.",
        "Sulama suyu kalitesi ve tuzluluk ayrıca kontrol edilmelidir.",
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
