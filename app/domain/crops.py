"""Crop knowledge base.

This is a deliberately transparent, agronomy-inspired catalogue. Each crop
stores the environmental envelope used by the rule engine. Values are
approximate and must be calibrated with local extension services and variety
trials before being used for real farm decisions.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

MONTH_NAMES_TR = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)

# Texture families used for a coarse compatibility score.
TEXTURE_GROUP = {
    "sand": "light",
    "loamy_sand": "light",
    "sandy_loam": "light_medium",
    "silt": "medium",
    "loam": "medium",
    "silt_loam": "medium",
    "clay_loam": "medium_heavy",
    "sandy_clay_loam": "medium_heavy",
    "clay": "heavy",
}


@dataclass(frozen=True)
class CropProfile:
    key: str
    name: str
    local_name: str
    category: str

    # Growing-season mean temperature envelope (°C)
    temp_opt: tuple[float, float]
    temp_abs: tuple[float, float]

    # Seasonal water requirement (mm) and tolerances (0..1)
    water_need_mm: int
    drought_tolerance: float
    frost_tolerance: float
    heat_tolerance: float
    salinity_tolerance: float

    # Soil chemistry / texture envelope
    ph_opt: tuple[float, float]
    ph_abs: tuple[float, float]
    textures: tuple[str, ...]

    growing_days: int
    planting_months: tuple[int, ...]
    nitrogen_need: str  # low | medium | high

    # Qualitative business attributes (0..1)
    organic_suitability: float
    market_demand: float
    gross_margin: float
    yield_potential: float

    notes: str

    @property
    def is_legume(self) -> bool:
        return self.category == "legume"

    def planting_window(self, language: str = "tr") -> str:
        if language == "en":
            names = (
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
            )
        else:
            names = MONTH_NAMES_TR
        months = sorted(self.planting_months)
        if len(months) == 1:
            return names[months[0] - 1]
        return f"{names[months[0] - 1]}–{names[months[-1] - 1]}"


CROPS: tuple[CropProfile, ...] = (
    CropProfile(
        key="wheat",
        name="Winter wheat",
        local_name="Kışlık Buğday",
        category="cereal",
        temp_opt=(8, 18),
        temp_abs=(-12, 34),
        water_need_mm=450,
        drought_tolerance=0.55,
        frost_tolerance=0.85,
        heat_tolerance=0.45,
        salinity_tolerance=0.55,
        ph_opt=(6.3, 7.6),
        ph_abs=(5.2, 8.6),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=240,
        planting_months=(10, 11),
        nitrogen_need="medium",
        organic_suitability=0.75,
        market_demand=0.92,
        gross_margin=0.55,
        yield_potential=0.65,
        notes="Kışlık tahıl; kök çürüklüğü ve septoria takibi önemlidir.",
    ),
    CropProfile(
        key="barley",
        name="Barley",
        local_name="Arpa",
        category="cereal",
        temp_opt=(7, 18),
        temp_abs=(-12, 35),
        water_need_mm=380,
        drought_tolerance=0.72,
        frost_tolerance=0.9,
        heat_tolerance=0.5,
        salinity_tolerance=0.7,
        ph_opt=(6.4, 8.0),
        ph_abs=(5.5, 9.0),
        textures=("loam", "silt_loam", "clay_loam", "sandy_loam"),
        growing_days=210,
        planting_months=(10, 11),
        nitrogen_need="medium",
        organic_suitability=0.72,
        market_demand=0.78,
        gross_margin=0.5,
        yield_potential=0.6,
        notes="Kurağa ve tuzluluğa buğdaydan daha dayanıklıdır.",
    ),
    CropProfile(
        key="maize",
        name="Maize (corn)",
        local_name="Mısır",
        category="cereal",
        temp_opt=(18, 27),
        temp_abs=(8, 38),
        water_need_mm=600,
        drought_tolerance=0.35,
        frost_tolerance=0.1,
        heat_tolerance=0.6,
        salinity_tolerance=0.35,
        ph_opt=(6.0, 7.2),
        ph_abs=(5.0, 8.3),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=130,
        planting_months=(4, 5),
        nitrogen_need="high",
        organic_suitability=0.55,
        market_demand=0.92,
        gross_margin=0.68,
        yield_potential=0.85,
        notes="Yüksek verim potansiyeli; sulama ve azot olmadan riskli.",
    ),
    CropProfile(
        key="sunflower",
        name="Sunflower",
        local_name="Ayçiçeği",
        category="oilseed",
        temp_opt=(17, 27),
        temp_abs=(5, 40),
        water_need_mm=500,
        drought_tolerance=0.55,
        frost_tolerance=0.2,
        heat_tolerance=0.65,
        salinity_tolerance=0.55,
        ph_opt=(6.0, 7.8),
        ph_abs=(5.0, 8.8),
        textures=("loam", "silt_loam", "clay_loam", "sandy_loam"),
        growing_days=130,
        planting_months=(4, 5),
        nitrogen_need="medium",
        organic_suitability=0.65,
        market_demand=0.85,
        gross_margin=0.62,
        yield_potential=0.7,
        notes="Çiçeklenme döneminde sulama verimi belirgin artırır.",
    ),
    CropProfile(
        key="chickpea",
        name="Chickpea",
        local_name="Nohut",
        category="legume",
        temp_opt=(15, 26),
        temp_abs=(2, 36),
        water_need_mm=350,
        drought_tolerance=0.82,
        frost_tolerance=0.35,
        heat_tolerance=0.55,
        salinity_tolerance=0.45,
        ph_opt=(6.5, 8.2),
        ph_abs=(5.5, 9.0),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=115,
        planting_months=(3, 4),
        nitrogen_need="low",
        organic_suitability=0.88,
        market_demand=0.8,
        gross_margin=0.62,
        yield_potential=0.55,
        notes="Baklagil; azot bağlar, ekim nöbetinde toprak sağlığına katkı sağlar.",
    ),
    CropProfile(
        key="lentil",
        name="Lentil",
        local_name="Mercimek",
        category="legume",
        temp_opt=(12, 23),
        temp_abs=(0, 34),
        water_need_mm=300,
        drought_tolerance=0.86,
        frost_tolerance=0.5,
        heat_tolerance=0.45,
        salinity_tolerance=0.4,
        ph_opt=(6.3, 8.0),
        ph_abs=(5.3, 8.8),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=105,
        planting_months=(10, 11),
        nitrogen_need="low",
        organic_suitability=0.9,
        market_demand=0.75,
        gross_margin=0.58,
        yield_potential=0.5,
        notes="Kurak koşullara uygun, düşük girdili baklagil.",
    ),
    CropProfile(
        key="potato",
        name="Potato",
        local_name="Patates",
        category="root",
        temp_opt=(13, 22),
        temp_abs=(2, 32),
        water_need_mm=550,
        drought_tolerance=0.3,
        frost_tolerance=0.3,
        heat_tolerance=0.3,
        salinity_tolerance=0.25,
        ph_opt=(5.5, 6.8),
        ph_abs=(4.5, 8.0),
        textures=("sandy_loam", "loam", "silt_loam"),
        growing_days=115,
        planting_months=(3, 4),
        nitrogen_need="high",
        organic_suitability=0.7,
        market_demand=0.88,
        gross_margin=0.66,
        yield_potential=0.8,
        notes="Yumru kalitesi için düzenli sulama ve iyi drenaj gerekir.",
    ),
    CropProfile(
        key="tomato",
        name="Tomato (field)",
        local_name="Domates (tarla)",
        category="vegetable",
        temp_opt=(18, 29),
        temp_abs=(8, 38),
        water_need_mm=620,
        drought_tolerance=0.3,
        frost_tolerance=0.05,
        heat_tolerance=0.5,
        salinity_tolerance=0.45,
        ph_opt=(6.0, 7.0),
        ph_abs=(5.0, 8.2),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=125,
        planting_months=(4, 5),
        nitrogen_need="high",
        organic_suitability=0.7,
        market_demand=0.9,
        gross_margin=0.8,
        yield_potential=0.8,
        notes="Yüksek gelir ama yüksek su, gübre ve işçilik ihtiyacı.",
    ),
    CropProfile(
        key="cotton",
        name="Cotton",
        local_name="Pamuk",
        category="fiber",
        temp_opt=(22, 32),
        temp_abs=(12, 42),
        water_need_mm=700,
        drought_tolerance=0.5,
        frost_tolerance=0.05,
        heat_tolerance=0.8,
        salinity_tolerance=0.72,
        ph_opt=(6.0, 8.0),
        ph_abs=(5.2, 8.8),
        textures=("loam", "clay_loam", "silt_loam"),
        growing_days=170,
        planting_months=(4, 5),
        nitrogen_need="high",
        organic_suitability=0.55,
        market_demand=0.85,
        gross_margin=0.72,
        yield_potential=0.78,
        notes="Sıcak ve uzun sezon ister; sulama olmadan ekonomik değildir.",
    ),
    CropProfile(
        key="soybean",
        name="Soybean",
        local_name="Soya",
        category="legume",
        temp_opt=(18, 28),
        temp_abs=(8, 38),
        water_need_mm=550,
        drought_tolerance=0.4,
        frost_tolerance=0.1,
        heat_tolerance=0.5,
        salinity_tolerance=0.45,
        ph_opt=(6.0, 7.0),
        ph_abs=(5.2, 8.2),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=130,
        planting_months=(5, 6),
        nitrogen_need="low",
        organic_suitability=0.86,
        market_demand=0.82,
        gross_margin=0.62,
        yield_potential=0.7,
        notes="Baklagil; rhizobium aşılaması ve düzenli nem ister.",
    ),
    CropProfile(
        key="canola",
        name="Canola",
        local_name="Kanola",
        category="oilseed",
        temp_opt=(10, 21),
        temp_abs=(-6, 33),
        water_need_mm=450,
        drought_tolerance=0.45,
        frost_tolerance=0.72,
        heat_tolerance=0.35,
        salinity_tolerance=0.5,
        ph_opt=(6.0, 7.5),
        ph_abs=(5.0, 8.3),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=190,
        planting_months=(9, 10),
        nitrogen_need="high",
        organic_suitability=0.6,
        market_demand=0.76,
        gross_margin=0.6,
        yield_potential=0.64,
        notes="Kışlık yağlık; ekim nöbetinde hastalık kırıcı rol oynar.",
    ),
    CropProfile(
        key="sugar_beet",
        name="Sugar beet",
        local_name="Şeker Pancarı",
        category="root",
        temp_opt=(13, 23),
        temp_abs=(2, 33),
        water_need_mm=620,
        drought_tolerance=0.35,
        frost_tolerance=0.5,
        heat_tolerance=0.4,
        salinity_tolerance=0.45,
        ph_opt=(6.2, 7.8),
        ph_abs=(5.3, 8.5),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=190,
        planting_months=(3, 4),
        nitrogen_need="high",
        organic_suitability=0.6,
        market_demand=0.7,
        gross_margin=0.56,
        yield_potential=0.78,
        notes="Kontratlı üretim ve şeker fabrikası lojistiği gerekir.",
    ),
    CropProfile(
        key="alfalfa",
        name="Alfalfa",
        local_name="Yonca",
        category="forage",
        temp_opt=(15, 28),
        temp_abs=(-8, 40),
        water_need_mm=750,
        drought_tolerance=0.55,
        frost_tolerance=0.65,
        heat_tolerance=0.65,
        salinity_tolerance=0.62,
        ph_opt=(6.5, 8.0),
        ph_abs=(5.8, 8.8),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=250,
        planting_months=(3, 4),
        nitrogen_need="low",
        organic_suitability=0.95,
        market_demand=0.68,
        gross_margin=0.52,
        yield_potential=0.75,
        notes="Çok yıllık yem bitkisi; toprak yapısını iyileştirir.",
    ),
    CropProfile(
        key="olive",
        name="Olive",
        local_name="Zeytin",
        category="perennial",
        temp_opt=(15, 27),
        temp_abs=(-8, 40),
        water_need_mm=450,
        drought_tolerance=0.9,
        frost_tolerance=0.3,
        heat_tolerance=0.82,
        salinity_tolerance=0.72,
        ph_opt=(6.0, 8.2),
        ph_abs=(5.2, 8.8),
        textures=("loam", "clay_loam", "sandy_loam"),
        growing_days=240,
        planting_months=(2, 3),
        nitrogen_need="low",
        organic_suitability=0.85,
        market_demand=0.88,
        gross_margin=0.68,
        yield_potential=0.62,
        notes="Çok yıllık; yatırım geri dönüşü uzun, don riskine hassas.",
    ),
    CropProfile(
        key="grape",
        name="Grape (vineyard)",
        local_name="Üzüm (Bağ)",
        category="perennial",
        temp_opt=(16, 29),
        temp_abs=(-10, 42),
        water_need_mm=420,
        drought_tolerance=0.86,
        frost_tolerance=0.38,
        heat_tolerance=0.78,
        salinity_tolerance=0.55,
        ph_opt=(6.0, 8.0),
        ph_abs=(5.0, 8.8),
        textures=("loam", "clay_loam", "sandy_loam"),
        growing_days=220,
        planting_months=(2, 3),
        nitrogen_need="low",
        organic_suitability=0.82,
        market_demand=0.86,
        gross_margin=0.7,
        yield_potential=0.65,
        notes="Çok yıllık; çeşit seçimi ve budama takvimi kritik.",
    ),
    CropProfile(
        key="apple",
        name="Apple",
        local_name="Elma",
        category="perennial",
        temp_opt=(11, 23),
        temp_abs=(-12, 36),
        water_need_mm=520,
        drought_tolerance=0.5,
        frost_tolerance=0.72,
        heat_tolerance=0.42,
        salinity_tolerance=0.3,
        ph_opt=(6.0, 7.2),
        ph_abs=(5.0, 8.2),
        textures=("loam", "silt_loam", "clay_loam"),
        growing_days=240,
        planting_months=(2, 3),
        nitrogen_need="medium",
        organic_suitability=0.78,
        market_demand=0.84,
        gross_margin=0.68,
        yield_potential=0.7,
        notes="Çok yıllık; soğuklama ihtiyacı ve don riski çeşide göre değişir.",
    ),
    CropProfile(
        key="triticale",
        name="Triticale",
        local_name="Tritikale",
        category="cereal",
        temp_opt=(7, 18),
        temp_abs=(-14, 34),
        water_need_mm=420,
        drought_tolerance=0.7,
        frost_tolerance=0.9,
        heat_tolerance=0.45,
        salinity_tolerance=0.65,
        ph_opt=(6.2, 7.8),
        ph_abs=(5.0, 8.8),
        textures=("loam", "silt_loam", "clay_loam", "sandy_loam"),
        growing_days=220,
        planting_months=(10, 11),
        nitrogen_need="medium",
        organic_suitability=0.72,
        market_demand=0.6,
        gross_margin=0.48,
        yield_potential=0.68,
        notes="Buğday ve çavdar melezi; kışa ve kurağa dayanıklı, hayvan yemi olarak da kullanılır.",
    ),
    CropProfile(
        key="oats",
        name="Oats",
        local_name="Yulaf",
        category="cereal",
        temp_opt=(7, 17),
        temp_abs=(-12, 32),
        water_need_mm=400,
        drought_tolerance=0.62,
        frost_tolerance=0.82,
        heat_tolerance=0.35,
        salinity_tolerance=0.5,
        ph_opt=(5.8, 7.5),
        ph_abs=(4.8, 8.5),
        textures=("loam", "silt_loam", "clay_loam", "sandy_loam"),
        growing_days=180,
        planting_months=(3, 4),
        nitrogen_need="medium",
        organic_suitability=0.74,
        market_demand=0.58,
        gross_margin=0.45,
        yield_potential=0.6,
        notes="Serin ve nemli koşulları sever; yeşil gübre ve yem karışımlarında da kullanılır.",
    ),
    CropProfile(
        key="safflower",
        name="Safflower",
        local_name="Aspir",
        category="oilseed",
        temp_opt=(12, 26),
        temp_abs=(2, 38),
        water_need_mm=350,
        drought_tolerance=0.85,
        frost_tolerance=0.45,
        heat_tolerance=0.7,
        salinity_tolerance=0.7,
        ph_opt=(6.0, 8.2),
        ph_abs=(5.0, 9.0),
        textures=("loam", "clay_loam", "sandy_loam"),
        growing_days=140,
        planting_months=(3, 4),
        nitrogen_need="low",
        organic_suitability=0.72,
        market_demand=0.55,
        gross_margin=0.5,
        yield_potential=0.5,
        notes="Kurağa çok dayanıklı yağ bitkisi; suyu az olan tarlalarda alternatif olabilir.",
    ),
    CropProfile(
        key="sainfoin",
        name="Sainfoin",
        local_name="Korunga",
        category="forage",
        temp_opt=(10, 24),
        temp_abs=(-8, 36),
        water_need_mm=350,
        drought_tolerance=0.8,
        frost_tolerance=0.72,
        heat_tolerance=0.5,
        salinity_tolerance=0.55,
        ph_opt=(6.8, 8.2),
        ph_abs=(6.0, 9.0),
        textures=("loam", "clay_loam", "silt_loam"),
        growing_days=240,
        planting_months=(3, 4),
        nitrogen_need="low",
        organic_suitability=0.94,
        market_demand=0.5,
        gross_margin=0.42,
        yield_potential=0.6,
        notes="Çok yıllık baklagil yem bitkisi; kurağa dayanıklı, toprağı azotla zenginleştirir.",
    ),
    CropProfile(
        key="vetch",
        name="Vetch",
        local_name="Fiğ",
        category="forage",
        temp_opt=(10, 22),
        temp_abs=(-6, 32),
        water_need_mm=320,
        drought_tolerance=0.72,
        frost_tolerance=0.6,
        heat_tolerance=0.4,
        salinity_tolerance=0.4,
        ph_opt=(6.2, 8.0),
        ph_abs=(5.2, 8.8),
        textures=("loam", "clay_loam", "silt_loam", "sandy_loam"),
        growing_days=200,
        planting_months=(10, 11),
        nitrogen_need="low",
        organic_suitability=0.92,
        market_demand=0.35,
        gross_margin=0.35,
        yield_potential=0.45,
        notes="Yeşil gübre ve yem için baklagil; toprağa azot bağlar, anızı yakmadan toprağa karıştırılır.",
    ),
)

CROP_CATALOG: dict[str, CropProfile] = {crop.key: crop for crop in CROPS}

_EXTRA_ALIASES = {
    "buğday": "wheat",
    "bugday": "wheat",
    "wheat": "wheat",
    "arpa": "barley",
    "barley": "barley",
    "mısır": "maize",
    "misir": "maize",
    "corn": "maize",
    "maize": "maize",
    "ayçiçeği": "sunflower",
    "aycicegi": "sunflower",
    "sunflower": "sunflower",
    "nohut": "chickpea",
    "chickpea": "chickpea",
    "mercimek": "lentil",
    "lentil": "lentil",
    "patates": "potato",
    "potato": "potato",
    "domates": "tomato",
    "tomato": "tomato",
    "pamuk": "cotton",
    "cotton": "cotton",
    "soya": "soybean",
    "soybean": "soybean",
    "kanola": "canola",
    "kolza": "canola",
    "canola": "canola",
    "şeker pancarı": "sugar_beet",
    "seker pancari": "sugar_beet",
    "sugar beet": "sugar_beet",
    "sugar_beet": "sugar_beet",
    "yonca": "alfalfa",
    "alfalfa": "alfalfa",
    "zeytin": "olive",
    "olive": "olive",
    "üzüm": "grape",
    "uzum": "grape",
    "bağ": "grape",
    "bag": "grape",
    "grape": "grape",
    "elma": "apple",
    "apple": "apple",
    "tritikale": "triticale",
    "triticale": "triticale",
    "yulaf": "oats",
    "oats": "oats",
    "aspir": "safflower",
    "safflower": "safflower",
    "korunga": "sainfoin",
    "sainfoin": "sainfoin",
    "fiğ": "vetch",
    "fig": "vetch",
    "vetch": "vetch",
}


def _normalize(text: str) -> str:
    lowered = text.strip().casefold().replace("ı", "i")
    decomposed = unicodedata.normalize("NFKD", lowered)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = ascii_text.replace("ş", "s").replace("ğ", "g").replace("ç", "c").replace("ö", "o").replace("ü", "u")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


_ALIAS_MAP: dict[str, str] = {}
for _key, _crop in CROP_CATALOG.items():
    _ALIAS_MAP[_normalize(_key)] = _key
    _ALIAS_MAP[_normalize(_crop.name)] = _key
    _ALIAS_MAP[_normalize(_crop.local_name)] = _key
for _alias, _key in _EXTRA_ALIASES.items():
    _ALIAS_MAP[_normalize(_alias)] = _key


def resolve_crop(text: str) -> CropProfile | None:
    """Resolve a free-text crop name (Turkish or English) to a crop profile."""

    if not text:
        return None
    normalized = _normalize(text)
    key = _ALIAS_MAP.get(normalized)
    if key:
        return CROP_CATALOG[key]
    # allow "kışlık buğday" / "winter wheat" style suffixes
    for alias, candidate in sorted(_ALIAS_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if normalized.startswith(alias + " ") or normalized.endswith(" " + alias):
            return CROP_CATALOG[candidate]
    return None


def resolve_crops(values: Iterable[str]) -> tuple[list[CropProfile], list[str]]:
    """Resolve a list of names; return (found, unknown)."""

    found: list[CropProfile] = []
    unknown: list[str] = []
    for value in values:
        crop = resolve_crop(value)
        if crop is None:
            unknown.append(value)
        elif crop not in found:
            found.append(crop)
    return found, unknown


def validate_catalog() -> list[str]:
    """Return a list of catalogue consistency problems (empty == valid)."""

    problems: list[str] = []
    keys: set[str] = set()
    for crop in CROPS:
        if crop.key in keys:
            problems.append(f"duplicate crop key: {crop.key}")
        keys.add(crop.key)
        if crop.temp_opt[0] >= crop.temp_opt[1]:
            problems.append(f"{crop.key}: temp_opt is invalid")
        if crop.temp_abs[0] > crop.temp_opt[0] or crop.temp_abs[1] < crop.temp_opt[1]:
            problems.append(f"{crop.key}: temp_abs does not contain temp_opt")
        if crop.ph_opt[0] >= crop.ph_opt[1]:
            problems.append(f"{crop.key}: ph_opt is invalid")
        if not crop.planting_months or any(m < 1 or m > 12 for m in crop.planting_months):
            problems.append(f"{crop.key}: invalid planting months")
        for field in (
            "drought_tolerance",
            "frost_tolerance",
            "heat_tolerance",
            "salinity_tolerance",
            "organic_suitability",
            "market_demand",
            "gross_margin",
            "yield_potential",
        ):
            value = getattr(crop, field)
            if not 0 <= value <= 1:
                problems.append(f"{crop.key}: {field} out of range")
        if crop.growing_days <= 0 or crop.water_need_mm <= 0:
            problems.append(f"{crop.key}: non-positive growing days / water need")
    return problems
