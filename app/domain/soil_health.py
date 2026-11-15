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
    SoilTexture.UNKNOWN: "Bilmiyorum",
    SoilTexture.SAND: "Kum",
    SoilTexture.LOAMY_SAND: "Tınlı kum",
    SoilTexture.SANDY_LOAM: "Kumlu tın",
    SoilTexture.LOAM: "Tın (ideal)",
    SoilTexture.SILT_LOAM: "Siltli tın",
    SoilTexture.SILT: "Silt",
    SoilTexture.CLAY_LOAM: "Killi tın",
    SoilTexture.SANDY_CLAY_LOAM: "Kumlu killi tın",
    SoilTexture.CLAY: "Kil (ağır)",
}

DRAINAGE_LABELS = {Drainage.POOR: "Zayıf", Drainage.MEDIUM: "Orta", Drainage.GOOD: "İyi"}

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
        return "bilinmiyor"
    if score >= 80:
        return "iyi"
    if score >= 55:
        return "orta"
    return "zayıf"


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
        return "bilinmiyor"
    if score >= 80:
        return "iyi"
    if score >= 65:
        return "orta-iyi"
    if score >= 50:
        return "orta"
    if score >= 35:
        return "zayıf"
    return "çok zayıf"


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
            "organic_matter": "Toprak analizi yaptırıp organik madde oranını öğren.",
            "ph": "Toprak analizindeki pH değerini öğren.",
            "texture": "Toprağı eline al: dağılıyorsa kumlu, yapışıyorsa killi, ufalanıyorsa tınlıdır.",
            "salinity": "Toprak analizinde tuzluluk (EC) değerini iste.",
            "slope": "Tarlanın eğimini gözle tahmin et veya ölç.",
        }.get(key, "Bu bilgi henüz yok.")
    if score >= 80:
        return {
            "organic_matter": "Organik madde iyi. Anızı yakmadan toprağa karıştırmaya devam et.",
            "ph": "pH uygun. Kireç veya asit düzenleyiciye gerek yok.",
            "texture": "Toprak bünyesi uygun. Sıkışmayı önlemek için ağır makineleri ıslak toprağa sokma.",
            "salinity": "Tuzluluk düşük. Aşırı gübreden kaçınmaya devam et.",
            "drainage": "Drenaj iyi. Su birikintisi oluşmuyorsa böyle devam et.",
            "moisture": "Toprak nemi uygun aralıkta.",
            "soil_temp": "Toprak sıcaklığı ekim için uygun.",
            "slope": "Eğim düşük; erozyon riski sınırlı.",
            "rotation": "Ekim nöbeti çeşitliliği iyi.",
        }.get(key, "Durum iyi.")
    if key == "organic_matter":
        return "Her yıl 2-3 ton/da yanmış hayvan gübresi veya yeşil gübre ekle. Anızı yakma."
    if key == "ph":
        if field.soil_ph is not None and field.soil_ph < 6.0:
            return "Toprak asitli. Kireç miktarını toprak analizine göre uzmanla belirle."
        return "Toprak alkali. Jips/kükürt ve organik madde için uzmana danış; sulama suyunu kontrol et."
    if key == "texture":
        return "Organik madde ve malçla bünyeyi iyileştir; ıslak toprakta sürüm yapma."
    if key == "salinity":
        return "Drenajı iyileştir, aşırı gübreden kaçın, tuzlu suyla sulama yapma."
    if key == "drainage":
        return "Drenaj kanalı aç; ağır toprakta su birikmesini önle."
    if key == "moisture":
        return "Anız/malç ile toprak nemini koru; damla sulama ve malçlama kullan."
    if key == "soil_temp":
        return "Toprak sıcaklığı sınırda; ekimi toprak ısınınca yap."
    if key == "slope":
        return "Eğime dik ekim, şerit ekim ve anız bırakma ile erozyonu azalt."
    if key == "rotation":
        return "Ekim nöbetine baklagil veya yem bitkisi ekle."
    return "Bu değeri iyileştirmek için yerel tarım uzmanına danış."


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
        "Organik madde (humus)",
        field.organic_matter_pct,
        "%",
        band_score(field.organic_matter_pct, (3.0, 6.0), (0.0, 10.0)),
    )
    add("ph", "Toprak pH'ı", field.soil_ph, "pH", band_score(field.soil_ph, (6.2, 7.5), (4.0, 9.5)))
    add(
        "texture",
        "Toprak bünyesi",
        None,
        "",
        _texture_score(field.soil_texture),
    )
    add("salinity", "Tuzluluk (EC)", field.salinity_ds_m, "dS/m", _salinity_score(field.salinity_ds_m))
    add(
        "drainage",
        "Drenaj",
        None,
        "",
        {Drainage.GOOD: 100.0, Drainage.MEDIUM: 70.0, Drainage.POOR: 35.0}.get(field.drainage),
    )
    add(
        "moisture",
        "Toprak nemi (NASA)",
        soil.root_zone_moisture_mean,
        "0-1",
        band_score(soil.root_zone_moisture_mean, (0.40, 0.70), (0.0, 1.0)),
    )
    add(
        "soil_temp",
        "Toprak sıcaklığı (NASA)",
        soil.mean_soil_temp_c,
        "°C",
        band_score(soil.mean_soil_temp_c, (15.0, 25.0), (0.0, 40.0)),
    )
    add("slope", "Tarla eğimi", field.slope_pct, "%", _slope_score(field.slope_pct))

    best_rotation = rotation.best if rotation is not None and rotation.applicable else None
    add(
        "rotation",
        "Ekim nöbeti çeşitliliği",
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
            "Toprak sağlığın iyi görünüyor. Her yıl toprak analizi yaptır ve anızı yakma.",
            "Ekim nöbetine bir baklagil ekleyerek azot ihtiyacını azalt.",
            "Yağış ve toprak nemini kaydet; sulamayı ihtiyaca göre yap.",
        ]
    actions.append("Toprak analizini 2-3 yılda bir tekrarla; analiz olmadan gübre dozu verme.")

    gaps: list[str] = []
    if field.soil_ph is None:
        gaps.append("pH girilmedi; toprak analizi gerekir.")
    if field.organic_matter_pct is None:
        gaps.append("Organik madde girilmedi; toprak analizi gerekir.")
    if field.soil_texture == SoilTexture.UNKNOWN:
        gaps.append("Toprak bünyesi girilmedi.")
    if field.salinity_ds_m is None:
        gaps.append("Tuzluluk (EC) girilmedi.")
    gaps.append("NASA POWER N-P-K, pH veya organik madde sağlamaz; bu değerler çiftçi/laboratuvar verisidir.")

    outlook = None
    if score is not None:
        legume = bool(best_rotation and any(year.traits.nitrogen_fixing for year in best_rotation.years))
        if score < 55:
            outlook = "Toprak zayıf. Bu planla 2-3 yılda organik madde ve yapı iyileşebilir; ilk yıl sabırlı ol."
        elif legume:
            outlook = "Bu ekim nöbeti toprağa azot ve organik madde kazandırır; 2-3 yılda iyileşme beklenir."
        else:
            outlook = "Toprağı korumak için anız bırakma, az sürüm ve baklagil eklemeyi sürdür."

    if score is None:
        summary = "Toprak karnesi henüz oluşmadı. En az pH ve organik madde bilgisi gir."
    elif ranked:
        summary = (
            f"Toprak sağlığı {score:.0f}/100 ({_label(score)}). "
            f"En zayıf konu: {ranked[0].label}."
        )
    else:
        summary = f"Toprak sağlığı {score:.0f}/100 ({_label(score)})."

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
            "Toprak karnesi; pH, organik madde ve tuzluluk gibi çiftçi/laboratuvar verileri ile NASA toprak nemi/sıcaklığı proxy'lerini birleştirir.",
            "Puanlar yaklaşık ve açıklanabilir bir modeldir; resmî toprak verimliliği sınıflandırması değildir.",
        ],
    )
