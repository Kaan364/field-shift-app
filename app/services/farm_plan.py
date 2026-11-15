"""Complete farm plan orchestration.

This service combines the existing recommendation pipeline with the new
rotation, soil-health, water and climate-outlook modules. The farmer UI makes
one request and receives one coherent story instead of stitching together four
independent API calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.clients.nasa_power import NASAPowerClient
from app.config import Settings
from app.domain.crops import CROP_CATALOG, resolve_crop
from app.domain.economics import build_economics
from app.domain.frost import assess_risk
from app.domain.rotation import RotationOption, RotationResult, build_rotation, score_label
from app.domain.scoring import evaluate_candidates
from app.domain.soil_health import SoilHealthReport, assess_soil_health
from app.domain.water import WaterPlan, build_water_plan
from app.schemas import (
    ClimateSection,
    ClimateTrendInfo,
    DataSource,
    EconomicsResponse,
    EnvironmentSnapshot,
    FarmPlanRequest,
    FarmPlanResponse,
    FrostRiskResponse,
    MonthlyWaterInfo,
    RotationAlternative,
    RotationPlan,
    RotationResponse,
    RotationScores,
    RotationYearInfo,
    SoilHealthResponse,
    SoilHealthSection,
    SoilIndicatorInfo,
    WaterPlanResponse,
    WaterSection,
)
from app.services.advice import AdviceService
from app.services.agronomy import irrigation_supply_mm, season_metrics
from app.services.climate import ClimateOutlook, build_climate_outlook
from app.services.recommendation import RecommendationService
from app.services.sections import economics_payload, risk_payload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------
def _rotation_scores(option: RotationOption) -> RotationScores:
    return RotationScores(
        overall=option.overall,
        soil_health=option.soil,
        water=option.water,
        resilience=option.resilience,
        profit=option.profit,
        risk=option.risk,
        label=score_label(option.overall),
    )


def _rotation_plan(result: RotationResult) -> RotationPlan:
    if not result.applicable or result.best is None:
        return RotationPlan(
            applicable=False,
            years_requested=result.years_requested,
            headline=result.headline,
            summary=result.summary,
            notes=result.notes,
        )

    best = result.best
    years: list[RotationYearInfo] = []
    for item in best.years:
        crop = item.crop
        years.append(
            RotationYearInfo(
                year=item.year,
                crop_key=crop.key,
                crop_name=crop.name,
                crop_name_local=crop.local_name,
                category=crop.category,
                icon=item.traits.icon,
                family=item.traits.family,
                family_label=item.traits.family_label,
                rule_score=item.rule_score,
                planting_window=item.planting_window,
                growing_days=crop.growing_days,
                water_need_mm=item.water_need_mm,
                season_rain_mm=item.season_rain_mm,
                role=item.role,
                benefit=item.benefit,
                actions=item.actions,
                cover_crop=item.cover_crop,
                note=item.note,
            )
        )

    alternatives: list[RotationAlternative] = []
    for option in result.options[1:3]:
        alternatives.append(
            RotationAlternative(
                crops=[year.crop.key for year in option.years],
                crop_names=[year.crop.name for year in option.years],
                scores=_rotation_scores(option),
                total_water_mm=option.total_water_mm,
                irrigation_need_mm=option.irrigation_need_mm,
            )
        )

    return RotationPlan(
        applicable=True,
        years_requested=result.years_requested,
        headline=result.headline,
        summary=result.summary,
        scores=_rotation_scores(best),
        years=years,
        total_water_mm=best.total_water_mm,
        season_rain_mm=best.season_rain_mm,
        irrigation_need_mm=best.irrigation_need_mm,
        benefits=best.benefits,
        cautions=best.cautions,
        alternatives=alternatives,
        notes=result.notes,
    )


def _soil_section(report: SoilHealthReport) -> SoilHealthSection:
    return SoilHealthSection(
        score=report.score,
        label=report.label,
        grade=report.grade,
        summary=report.summary,
        indicators=[
            SoilIndicatorInfo(
                key=item.key,
                label=item.label,
                value=item.value,
                unit=item.unit,
                score=item.score,
                status=item.status,
                advice=item.advice,
            )
            for item in report.indicators
        ],
        actions=report.actions,
        data_gaps=report.data_gaps,
        outlook=report.outlook,
        notes=report.notes,
    )


def _water_section(plan: WaterPlan) -> WaterSection:
    return WaterSection(
        summary=plan.summary,
        label=plan.label,
        annual_rain_mm=plan.annual_rain_mm,
        annual_et0_mm=plan.annual_et0_mm,
        crop_need_mm=plan.crop_need_mm,
        season_rain_mm=plan.season_rain_mm,
        irrigation_supply_mm=plan.irrigation_supply_mm,
        deficit_mm=plan.deficit_mm,
        deficit_m3=plan.deficit_m3,
        deficit_ton_per_decare=plan.deficit_ton_per_decare,
        area_decare=plan.area_decare,
        months=[
            MonthlyWaterInfo(
                month=item.month,
                rain_mm=item.rain_mm,
                et0_mm=item.et0_mm,
                balance_mm=item.balance_mm,
                status=item.status,
            )
            for item in plan.months
        ],
        drought_months=plan.drought_months,
        tips=plan.tips,
        notes=plan.notes,
    )


def _climate_section(outlook: ClimateOutlook) -> ClimateSection:
    return ClimateSection(
        available=outlook.available,
        start_year=outlook.start_year,
        end_year=outlook.end_year,
        available_years=outlook.available_years,
        baseline_temp_c=outlook.baseline_temp_c,
        recent_temp_c=outlook.recent_temp_c,
        baseline_precip_mm=outlook.baseline_precip_mm,
        recent_precip_mm=outlook.recent_precip_mm,
        risk_level=outlook.risk_level,
        risk_label=outlook.risk_label,
        trends=[
            ClimateTrendInfo(
                key=item.key,
                label=item.label,
                direction=item.direction,  # type: ignore[arg-type]
                change=item.change,
                per_decade=item.per_decade,
                unit=item.unit,
                message=item.message,
            )
            for item in outlook.trends
        ],
        messages=outlook.messages,
        dry_months=outlook.dry_months,
        warmest_year=outlook.warmest_year,
        driest_year=outlook.driest_year,
        notes=outlook.notes,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class FarmPlanService:
    def __init__(
        self,
        recommender: RecommendationService,
        advice_service: AdviceService,
        nasa_client: NASAPowerClient,
        settings: Settings,
    ) -> None:
        self.recommender = recommender
        self.advice = advice_service
        self.nasa = nasa_client
        self.settings = settings

    async def _prepare(self, payload: FarmPlanRequest):
        analyze_request = self.advice._to_analyze_request(payload)
        environment, evaluations, warnings, _has_daily = await self.recommender.prepare(analyze_request)
        return analyze_request, environment, evaluations, warnings

    @staticmethod
    def _start_key(payload: FarmPlanRequest) -> str | None:
        if not payload.start_crop:
            return None
        crop = resolve_crop(payload.start_crop)
        return None if crop is None else crop.key

    def _rotation(
        self,
        payload: FarmPlanRequest,
        analyze_request,
        environment: EnvironmentSnapshot,
        evaluations,
    ) -> RotationResult:
        return build_rotation(
            analyze_request,
            environment,
            evaluations,
            years=payload.rotation_years,
            start_crop_key=self._start_key(payload),
        )

    def _water_crops(self, rotation: RotationResult, recommendations) -> list:
        if rotation.applicable and rotation.best is not None:
            return [year.crop for year in rotation.best.years]
        if not recommendations:
            return []
        top = recommendations[0]
        crop_key = getattr(top, "crop_key", None) or getattr(getattr(top, "crop", None), "key", None)
        crop = CROP_CATALOG.get(crop_key or "")
        return [crop] if crop is not None else []

    def _water(
        self,
        payload: FarmPlanRequest,
        analyze_request,
        environment: EnvironmentSnapshot,
        rotation: RotationResult,
        recommendations,
    ) -> WaterPlan:
        crops = self._water_crops(rotation, recommendations)
        best = rotation.best if rotation.applicable else None
        return build_water_plan(
            environment,
            analyze_request.field,
            analyze_request.resources,
            crops=crops,
            season_rain_mm=best.season_rain_mm if best is not None else None,
            planting_month=payload.planting_month,
        )

    async def _climate(
        self, payload: FarmPlanRequest, environment: EnvironmentSnapshot
    ) -> ClimateOutlook:
        return await build_climate_outlook(
            self.nasa, payload.location.latitude, payload.location.longitude, environment
        )

    def _extra_sources(self) -> list[DataSource]:
        return [
            DataSource(
                name="Rotation engine",
                url=None,
                description=(
                    "Explainable rotation model scoring legume share, family diversity, residue "
                    "cover, rooting depth, water balance and climate resilience."
                ),
            ),
            DataSource(
                name="Soil health report card",
                url=None,
                description=(
                    "Approximate soil-health score built from farmer/lab soil values plus "
                    "NASA POWER soil moisture and temperature."
                ),
            ),
            DataSource(
                name="NASA POWER - Annual",
                url=(
                    f"{self.settings.nasa_power_base_url}/annual/point"
                    "?parameters=T2M,T2M_MIN,T2M_MAX,PRECTOTCORR,GWETROOT&community=AG&format=JSON"
                ),
                description="Long-term temperature/rainfall direction (historical data, not a forecast).",
            ),
            DataSource(
                name="Farm budget model",
                url=None,
                description=(
                    "Transparent per-hectare yield, price and cost assumptions in USD; "
                    "planning figures, not market quotes."
                ),
            ),
            DataSource(
                name="Climate risk model",
                url=None,
                description=(
                    "Frost, heat and drought indicators derived from 25-year monthly normals "
                    "and crop tolerance values."
                ),
            ),
        ]

    # ------------------------------------------------------------------
    # Individual sections
    # ------------------------------------------------------------------
    async def rotation(self, payload: FarmPlanRequest) -> RotationResponse:
        analyze_request, environment, evaluations, warnings = await self._prepare(payload)
        rotation = self._rotation(payload, analyze_request, environment, evaluations)
        return RotationResponse(
            generated_at=datetime.now(timezone.utc),
            location=payload.location,
            environment=environment,
            rotation=_rotation_plan(rotation),
            warnings=warnings,
        )

    async def soil_health(self, payload: FarmPlanRequest) -> SoilHealthResponse:
        analyze_request, environment, evaluations, warnings = await self._prepare(payload)
        rotation = self._rotation(payload, analyze_request, environment, evaluations)
        report = assess_soil_health(analyze_request.field, environment, rotation)
        return SoilHealthResponse(
            generated_at=datetime.now(timezone.utc),
            location=payload.location,
            environment=environment,
            soil_health=_soil_section(report),
            rotation=_rotation_plan(rotation),
            warnings=warnings,
        )

    async def water_plan(self, payload: FarmPlanRequest) -> WaterPlanResponse:
        analyze_request, environment, evaluations, warnings = await self._prepare(payload)
        rotation = self._rotation(payload, analyze_request, environment, evaluations)
        recommendations = evaluations[: payload.top_n]
        water = self._water(payload, analyze_request, environment, rotation, recommendations)
        return WaterPlanResponse(
            generated_at=datetime.now(timezone.utc),
            location=payload.location,
            environment=environment,
            water=_water_section(water),
            rotation=_rotation_plan(rotation),
            warnings=warnings,
        )

    async def economics(self, payload: FarmPlanRequest) -> EconomicsResponse:
        analyze_request, environment, evaluations, warnings = await self._prepare(payload)
        rotation = self._rotation(payload, analyze_request, environment, evaluations)
        crops = self._water_crops(rotation, evaluations[: payload.top_n])
        water = self._water(payload, analyze_request, environment, rotation, evaluations[: payload.top_n])
        per_crop_deficit = water.deficit_mm / max(1, len(crops))
        economics = build_economics(
            environment,
            analyze_request.field,
            analyze_request.resources,
            crops,
            area_hectares=analyze_request.field.area_hectares,
            water_deficit_mm=per_crop_deficit,
        )
        risk = assess_risk(
            environment,
            crop=crops[0] if crops else None,
            water_deficit_mm=per_crop_deficit,
            irrigation=analyze_request.resources.irrigation,
        )
        return EconomicsResponse(
            generated_at=datetime.now(timezone.utc),
            location=payload.location,
            environment=environment,
            economics=economics_payload(economics),
            risk=risk_payload(risk),
            warnings=warnings,
        )

    async def frost_risk(self, payload: FarmPlanRequest) -> FrostRiskResponse:
        analyze_request, environment, evaluations, warnings = await self._prepare(payload)
        crop = resolve_crop(payload.start_crop) if payload.start_crop else None
        if crop is None and evaluations:
            crop = evaluations[0].crop
        deficit = 0.0
        if crop is not None:
            season = season_metrics(environment, crop, payload.planting_month)
            deficit = max(
                0.0,
                float(crop.water_need_mm)
                - ((season.total_precip_mm or 0.0) + irrigation_supply_mm(analyze_request.resources)),
            )
        risk = assess_risk(
            environment,
            crop=crop,
            water_deficit_mm=deficit,
            irrigation=analyze_request.resources.irrigation,
        )
        return FrostRiskResponse(
            generated_at=datetime.now(timezone.utc),
            location=payload.location,
            environment=environment,
            risk=risk_payload(risk),
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Complete plan
    # ------------------------------------------------------------------
    async def plan(self, payload: FarmPlanRequest) -> FarmPlanResponse:
        advice = await self.advice.advise(payload)
        analyze_request = self.advice._to_analyze_request(payload)
        evaluations, scoring_warnings = evaluate_candidates(analyze_request, advice.environment)
        rotation = self._rotation(payload, analyze_request, advice.environment, evaluations)
        soil_report = assess_soil_health(analyze_request.field, advice.environment, rotation)
        water = self._water(payload, analyze_request, advice.environment, rotation, advice.recommendations)
        climate = await self._climate(payload, advice.environment)

        plan_crops = self._water_crops(rotation, advice.recommendations)
        per_crop_deficit = water.deficit_mm / max(1, len(plan_crops))
        economics = build_economics(
            advice.environment,
            analyze_request.field,
            analyze_request.resources,
            plan_crops,
            area_hectares=analyze_request.field.area_hectares,
            water_deficit_mm=per_crop_deficit,
        )
        risk_crop = plan_crops[0] if plan_crops else None
        risk = assess_risk(
            advice.environment,
            crop=risk_crop,
            water_deficit_mm=per_crop_deficit,
            irrigation=analyze_request.resources.irrigation,
        )

        warnings = list(advice.warnings) + scoring_warnings

        if not rotation.applicable:
            warnings.append(rotation.summary)
        if soil_report.score is not None and soil_report.score < 45:
            warnings.append(
                "Soil health scored low. Plan a soil test and an organic-matter strategy before planting."
            )
        if water.deficit_mm > 100 and payload.irrigation == "rainfed":
            warnings.append(
                "There is no irrigation and the water deficit is high. Choose a drought-tolerant crop before planting."
            )
        if not climate.available:
            warnings.append(
                "The long-term climate trend could not be loaded; the climate card shows only the current regional average."
            )
        if economics.total_gross_margin_usd < 0:
            warnings.append(
                "The estimated budget is negative at these assumptions. Check costs and the sale price before planting."
            )
        if risk.overall_level == "high":
            warnings.append(
                "Weather risk is high for the leading crop. Read the frost, heat and drought actions before sowing."
            )

        sources = list(advice.data_sources) + self._extra_sources()

        return FarmPlanResponse(
            plan_id=uuid4().hex,
            generated_at=datetime.now(timezone.utc),
            language=payload.language,
            location=payload.location,
            environment=advice.environment,
            recommendations=advice.recommendations,
            advice=advice.advice,
            rotation=_rotation_plan(rotation),
            soil_health=_soil_section(soil_report),
            water=_water_section(water),
            climate=_climate_section(climate),
            economics=economics_payload(economics),
            risk=risk_payload(risk),
            summary=advice.summary,
            warnings=_dedupe(warnings),
            data_sources=sources,
            ai=advice.ai,
            disclaimer=advice.disclaimer,
        )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = (item or "").strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output
