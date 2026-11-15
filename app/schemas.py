"""Pydantic request/response models (the public API contract)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class SoilTexture(str, Enum):
    UNKNOWN = "unknown"
    SAND = "sand"
    LOAMY_SAND = "loamy_sand"
    SANDY_LOAM = "sandy_loam"
    LOAM = "loam"
    SILT_LOAM = "silt_loam"
    SILT = "silt"
    CLAY_LOAM = "clay_loam"
    SANDY_CLAY_LOAM = "sandy_clay_loam"
    CLAY = "clay"


class Drainage(str, Enum):
    POOR = "poor"
    MEDIUM = "medium"
    GOOD = "good"


class Irrigation(str, Enum):
    RAINFED = "rainfed"
    LIMITED = "limited"
    FULL = "full"


class WaterAvailability(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LaborAvailability(str, Enum):
    FAMILY = "family"
    HIRED = "hired"
    MIXED = "mixed"
    SCARCE = "scarce"


class Mechanization(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MarketAccess(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Goal(str, Enum):
    MAX_YIELD = "max_yield"
    MAX_PROFIT = "max_profit"
    LOW_WATER = "low_water"
    LOW_INPUT = "low_input"
    ORGANIC = "organic"
    SOIL_HEALTH = "soil_health"
    RISK_AVERSE = "risk_averse"


class Language(str, Enum):
    TR = "tr"
    EN = "en"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class Location(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="WGS84 latitude")
    longitude: float = Field(..., ge=-180, le=180, description="WGS84 longitude")
    region_name: str | None = Field(None, max_length=120)
    elevation_m: float | None = Field(None, ge=-500, le=9000)

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={"example": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"}},
    )


class FieldProfile(BaseModel):
    area_hectares: float = Field(1.0, gt=0, le=1_000_000)
    soil_texture: SoilTexture = SoilTexture.UNKNOWN
    soil_ph: float | None = Field(None, ge=3.5, le=10.0)
    organic_matter_pct: float | None = Field(None, ge=0, le=30)
    salinity_ds_m: float | None = Field(None, ge=0, le=40)
    soil_depth_cm: float | None = Field(None, ge=10, le=300)
    drainage: Drainage = Drainage.MEDIUM
    slope_pct: float | None = Field(None, ge=0, le=80)
    previous_crop: str | None = Field(None, max_length=80)

    model_config = ConfigDict(validate_assignment=True)


class Resources(BaseModel):
    irrigation: Irrigation = Irrigation.RAINFED
    water_availability: WaterAvailability = WaterAvailability.MEDIUM
    budget_usd: float | None = Field(None, ge=0)
    labor: LaborAvailability = LaborAvailability.FAMILY
    mechanization: Mechanization = Mechanization.MEDIUM
    organic_certified: bool = False

    model_config = ConfigDict(validate_assignment=True)


class Preferences(BaseModel):
    goal: Goal = Goal.MAX_PROFIT
    crops_of_interest: list[str] = Field(default_factory=list, max_length=10)
    excluded_crops: list[str] = Field(default_factory=list, max_length=10)
    planting_month: int | None = Field(None, ge=1, le=12)
    market_access: MarketAccess = MarketAccess.MEDIUM
    max_growing_days: int | None = Field(None, ge=60, le=400)

    model_config = ConfigDict(validate_assignment=True)

    @field_validator("crops_of_interest", "excluded_crops")
    @classmethod
    def _clean_crop_names(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned


class AnalyzeRequest(BaseModel):
    location: Location
    field: FieldProfile = Field(default_factory=FieldProfile)
    resources: Resources = Field(default_factory=Resources)
    preferences: Preferences = Field(default_factory=Preferences)
    top_n: int = Field(3, ge=1, le=8)
    language: Language = Language.TR

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "location": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
                "field": {
                    "area_hectares": 12.5,
                    "soil_texture": "clay_loam",
                    "soil_ph": 7.4,
                    "organic_matter_pct": 1.8,
                    "drainage": "medium",
                },
                "resources": {
                    "irrigation": "limited",
                    "water_availability": "medium",
                    "budget_usd": 6000,
                    "labor": "family",
                    "mechanization": "medium",
                },
                "preferences": {
                    "goal": "max_profit",
                    "crops_of_interest": ["wheat", "chickpea"],
                    "excluded_crops": [],
                    "planting_month": 10,
                    "market_access": "medium",
                },
                "top_n": 3,
                "language": "tr",
            }
        }
    )


# ---------------------------------------------------------------------------
# Environment / NASA data models
# ---------------------------------------------------------------------------
class MonthlyClimate(BaseModel):
    month: str
    mean_temp_c: float | None = None
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    precip_mm_per_day: float | None = None
    precip_month_mm: float | None = None
    relative_humidity_pct: float | None = None
    solar_kwh_m2_day: float | None = None
    wind_speed_m_s: float | None = None
    evapotranspiration_mm_per_day: float | None = None
    root_zone_moisture: float | None = None
    topsoil_moisture: float | None = None
    soil_temp_c: float | None = None
    frost_risk: bool = False
    heat_stress: bool = False


class ClimateSummary(BaseModel):
    annual_mean_temp_c: float | None = None
    growing_season_mean_temp_c: float | None = None
    annual_precip_mm: float | None = None
    annual_evapotranspiration_mm: float | None = None
    aridity_index: float | None = None
    climate_class: str | None = None
    growing_season_days: int | None = None
    frost_months: list[str] = Field(default_factory=list)
    heat_stress_months: list[str] = Field(default_factory=list)
    annual_solar_kwh_m2_day: float | None = None


class SoilSummary(BaseModel):
    root_zone_moisture_mean: float | None = None
    topsoil_moisture_mean: float | None = None
    mean_soil_temp_c: float | None = None
    soil_condition_score: float | None = Field(None, ge=0, le=100)
    soil_condition_label: str | None = None

    # Farmer-reported values (NASA POWER does not provide nutrients/pH)
    soil_texture: SoilTexture = SoilTexture.UNKNOWN
    soil_ph: float | None = None
    organic_matter_pct: float | None = None
    salinity_ds_m: float | None = None
    drainage: Drainage = Drainage.MEDIUM

    data_gaps: list[str] = Field(default_factory=list)


class RecentWeather(BaseModel):
    window_days: int
    available_days: int
    mean_temp_c: float | None = None
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    total_precip_mm: float | None = None
    rainy_days: int | None = None
    longest_dry_spell_days: int | None = None
    mean_root_zone_moisture: float | None = None


class EnvironmentSnapshot(BaseModel):
    nasa_elevation_m: float | None = None
    climate: ClimateSummary
    soil: SoilSummary
    recent_weather: RecentWeather | None = None
    monthly: list[MonthlyClimate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Recommendation response models
# ---------------------------------------------------------------------------
class ScoreBreakdown(BaseModel):
    rule_score: float = Field(..., ge=0, le=100)
    ai_score: float | None = Field(None, ge=0, le=100)
    final_score: float = Field(..., ge=0, le=100)
    components: dict[str, float | None] = Field(default_factory=dict)


class CropRecommendation(BaseModel):
    rank: int
    crop_key: str
    crop_name: str
    crop_name_local: str
    category: str
    scores: ScoreBreakdown
    rationale: str
    risks: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    planting_window: str
    growing_days: int
    water_need_mm: int
    confidence: Literal["low", "medium", "high"] = "medium"


class AIMetadata(BaseModel):
    provider: str
    model: str | None = None
    kind: Literal["llm", "deterministic"] = "deterministic"
    used: bool = False
    fallback_used: bool = False
    latency_ms: int | None = None
    error: str | None = None
    notes: str | None = None


class DataSource(BaseModel):
    name: str
    url: str | None = None
    description: str


class AnalyzeResponse(BaseModel):
    analysis_id: str
    generated_at: datetime
    language: Language
    location: Location
    environment: EnvironmentSnapshot
    recommendations: list[CropRecommendation]
    summary: str
    general_risks: list[str] = Field(default_factory=list)
    general_actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    ai: AIMetadata
    disclaimer: str


class EnvironmentResponse(BaseModel):
    generated_at: datetime
    location: Location
    environment: EnvironmentSnapshot
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Free-text advice ("ne ekeyim?" akışı)
# ---------------------------------------------------------------------------
class AdviceRequest(BaseModel):
    """Çiftçinin kendi cümleleriyle soru sorduğu basit akış.

    Tüm alanlar isteğe bağlıdır (konum hariç); çiftçi bilmediği alanı boş bırakır.
    """

    location: Location
    area_hectares: float | None = Field(None, gt=0, le=1_000_000, description="Dönüm değil, hektar")
    soil_texture: SoilTexture = SoilTexture.UNKNOWN
    soil_ph: float | None = Field(None, ge=3.5, le=10.0)
    organic_matter_pct: float | None = Field(None, ge=0, le=30)
    salinity_ds_m: float | None = Field(None, ge=0, le=40)
    drainage: Drainage = Drainage.MEDIUM
    slope_pct: float | None = Field(None, ge=0, le=80)
    previous_crop: str | None = Field(None, max_length=80, description="Geçen sezon ekilen ürün (TR/EN adı)")
    irrigation: Irrigation = Irrigation.RAINFED
    water_availability: WaterAvailability = WaterAvailability.MEDIUM
    market_access: MarketAccess = MarketAccess.MEDIUM
    goal: Goal = Goal.MAX_PROFIT
    planting_month: int | None = Field(None, ge=1, le=12)
    free_text: str = Field("", max_length=2000, description="Çiftçinin kendi cümleleriyle anlattıkları")
    top_n: int = Field(3, ge=1, le=5)
    language: Language = Language.TR

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "location": {"latitude": 41.6771, "longitude": 26.5557, "region_name": "Edirne"},
                "area_hectares": 2.0,
                "soil_texture": "clay_loam",
                "irrigation": "limited",
                "goal": "max_profit",
                "free_text": (
                    "Edirne'de 20 dönüm tarlam var. Ne ekeceğimi bilmiyorum. "
                    "Bitkiyi nasıl büyüteceğimi, nasıl besleyeceğimi ve nasıl bakacağımı da bilmiyorum."
                ),
                "top_n": 3,
                "language": "tr",
            }
        },
    )


class AdvicePlan(BaseModel):
    """Sadeleştirilmiş, düşük okuryazarlık için kısa cümleli öneri planı."""

    headline: str = ""
    why: str = ""
    steps: list[str] = Field(default_factory=list)
    grow: list[str] = Field(default_factory=list)
    feed: list[str] = Field(default_factory=list)
    care: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    ask_farmer: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator("headline", "why", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        """Bazı modeller tek cümlelik alanı liste olarak döndürüyor; birleştir."""

        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return " ".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    @field_validator("steps", "grow", "feed", "care", "risks", "ask_farmer", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> str:
        text = str(value or "medium").strip().lower()
        return text if text in {"low", "medium", "high"} else "medium"


class AdviceResponse(BaseModel):
    advice_id: str
    generated_at: datetime
    language: Language
    location: Location
    environment: EnvironmentSnapshot
    recommendations: list[CropRecommendation]
    advice: AdvicePlan
    summary: str
    warnings: list[str] = Field(default_factory=list)
    ai: AIMetadata
    data_sources: list[DataSource] = Field(default_factory=list)
    disclaimer: str


class GeocodeResponse(BaseModel):
    found: bool = False
    latitude: float | None = None
    longitude: float | None = None
    display_name: str | None = None
    city: str | None = None
    district: str | None = None
    region: str | None = None
    country: str | None = None
    source: str = "nominatim"
    error: str | None = None


# ---------------------------------------------------------------------------
# Metadata endpoints
# ---------------------------------------------------------------------------
class CropInfo(BaseModel):
    key: str
    name: str
    local_name: str
    category: str
    growing_days: int
    water_need_mm: int
    planting_months: list[int]
    planting_window: str
    nitrogen_need: str
    notes: str
    icon: str = "🌱"
    family: str = ""
    family_label: str = ""
    rotation_role: str = ""
    rotation_benefit: str = ""


class AIProviderInfo(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    key: str
    label: str
    kind: Literal["llm", "deterministic", "aggregator"]
    model_examples: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    best_for: str
    cost_tier: str
    latency: str
    privacy: str
    json_reliability: str
    recommended: bool = False


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    ai_provider: str
    ai_configured: bool
    geocoding_enabled: bool = False
    nasa_power_base_url: str
    cache_entries: int | None = None
    timestamp: datetime


class ApiInfo(BaseModel):
    name: str
    version: str
    description: str
    docs_url: str
    openapi_url: str
    endpoints: dict[str, str]
    example_request: dict[str, Any]


# ---------------------------------------------------------------------------
# Multi-year rotation, soil health, water and climate outlook
# ---------------------------------------------------------------------------
class FarmPlanRequest(AdviceRequest):
    """Farmer request for the complete plan (advice + rotation + soil + water)."""

    rotation_years: int = Field(3, ge=2, le=4, description="2, 3 veya 4 yıllık ekim nöbeti")
    start_crop: str | None = Field(
        None,
        max_length=80,
        description="Rotasyonun ilk yılı için isteğe bağlı ürün anahtarı/adı",
    )

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "location": {"latitude": 41.6771, "longitude": 26.5557, "region_name": "Edirne"},
                "area_hectares": 2.0,
                "soil_texture": "clay_loam",
                "soil_ph": 7.0,
                "organic_matter_pct": 2.2,
                "previous_crop": "wheat",
                "irrigation": "limited",
                "water_availability": "medium",
                "goal": "soil_health",
                "planting_month": 10,
                "free_text": "Toprağım yoruldu, bu yıl ne eksem iyi olur?",
                "rotation_years": 3,
                "top_n": 3,
                "language": "tr",
            }
        },
    )


class RotationYearInfo(BaseModel):
    year: int
    crop_key: str
    crop_name: str
    crop_name_local: str
    category: str
    icon: str
    family: str
    family_label: str
    rule_score: float
    planting_window: str
    growing_days: int
    water_need_mm: int
    season_rain_mm: float | None = None
    role: str
    benefit: str
    actions: list[str] = Field(default_factory=list)
    cover_crop: str | None = None
    note: str | None = None


class RotationScores(BaseModel):
    overall: float = Field(..., ge=0, le=100)
    soil_health: float = Field(..., ge=0, le=100)
    water: float = Field(..., ge=0, le=100)
    resilience: float = Field(..., ge=0, le=100)
    profit: float = Field(..., ge=0, le=100)
    risk: float = Field(..., ge=0, le=100)
    label: str = ""


class RotationAlternative(BaseModel):
    crops: list[str]
    crop_names: list[str]
    scores: RotationScores
    total_water_mm: float
    irrigation_need_mm: float


class RotationPlan(BaseModel):
    applicable: bool
    years_requested: int
    headline: str
    summary: str
    scores: RotationScores | None = None
    years: list[RotationYearInfo] = Field(default_factory=list)
    total_water_mm: float = 0
    season_rain_mm: float = 0
    irrigation_need_mm: float = 0
    benefits: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    alternatives: list[RotationAlternative] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SoilIndicatorInfo(BaseModel):
    key: str
    label: str
    value: float | None = None
    unit: str = ""
    score: float | None = Field(None, ge=0, le=100)
    status: str
    advice: str


class SoilHealthSection(BaseModel):
    score: float | None = Field(None, ge=0, le=100)
    label: str
    grade: str
    summary: str
    indicators: list[SoilIndicatorInfo] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    outlook: str | None = None
    notes: list[str] = Field(default_factory=list)


class MonthlyWaterInfo(BaseModel):
    month: str
    rain_mm: float | None = None
    et0_mm: float | None = None
    balance_mm: float | None = None
    status: str


class WaterSection(BaseModel):
    summary: str
    label: str
    annual_rain_mm: float | None = None
    annual_et0_mm: float | None = None
    crop_need_mm: float
    season_rain_mm: float | None = None
    irrigation_supply_mm: float
    deficit_mm: float
    deficit_m3: float
    deficit_ton_per_decare: float
    area_decare: float
    months: list[MonthlyWaterInfo] = Field(default_factory=list)
    drought_months: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ClimateTrendInfo(BaseModel):
    key: str
    label: str
    direction: Literal["up", "down", "stable"]
    change: float
    per_decade: float
    unit: str
    message: str


class ClimateSection(BaseModel):
    available: bool
    start_year: int | None = None
    end_year: int | None = None
    available_years: int = 0
    baseline_temp_c: float | None = None
    recent_temp_c: float | None = None
    baseline_precip_mm: float | None = None
    recent_precip_mm: float | None = None
    risk_level: str = "unknown"
    risk_label: str = "Bilinmiyor"
    trends: list[ClimateTrendInfo] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    dry_months: list[str] = Field(default_factory=list)
    warmest_year: int | None = None
    driest_year: int | None = None
    notes: list[str] = Field(default_factory=list)


class FarmPlanResponse(BaseModel):
    plan_id: str
    generated_at: datetime
    language: Language
    location: Location
    environment: EnvironmentSnapshot
    recommendations: list[CropRecommendation]
    advice: AdvicePlan
    rotation: RotationPlan
    soil_health: SoilHealthSection
    water: WaterSection
    climate: ClimateSection
    summary: str
    warnings: list[str] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    ai: AIMetadata
    disclaimer: str


class RotationResponse(BaseModel):
    generated_at: datetime
    location: Location
    environment: EnvironmentSnapshot
    rotation: RotationPlan
    warnings: list[str] = Field(default_factory=list)


class SoilHealthResponse(BaseModel):
    generated_at: datetime
    location: Location
    environment: EnvironmentSnapshot
    soil_health: SoilHealthSection
    rotation: RotationPlan | None = None
    warnings: list[str] = Field(default_factory=list)


class WaterPlanResponse(BaseModel):
    generated_at: datetime
    location: Location
    environment: EnvironmentSnapshot
    water: WaterSection
    rotation: RotationPlan | None = None
    warnings: list[str] = Field(default_factory=list)
