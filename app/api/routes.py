"""HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.ai.provider_info import AI_PROVIDER_INFO
from app.domain.crop_meta import traits_for
from app.domain.crops import CROP_CATALOG
from app.schemas import (
    AdviceRequest,
    AdviceResponse,
    AIProviderInfo,
    AnalyzeRequest,
    AnalyzeResponse,
    CropInfo,
    EconomicsResponse,
    EnvironmentResponse,
    FarmPlanRequest,
    FarmPlanResponse,
    FieldProfile,
    FrostRiskResponse,
    GeocodeResponse,
    Location,
    RotationResponse,
    SoilHealthResponse,
    WaterPlanResponse,
)

router = APIRouter(prefix="/api/v1", tags=["agronomy"])


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Rank crops for a location and a farmer profile",
)
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Run the full pipeline: NASA POWER -> rule engine -> AI -> ranked advice."""

    service = request.app.state.recommender
    return await service.analyze(payload)


@router.get(
    "/environment",
    response_model=EnvironmentResponse,
    summary="Get the NASA POWER climate and soil summary without advice",
)
async def environment(
    request: Request,
    latitude: Annotated[float, Query(ge=-90, le=90, description="WGS84 latitude")],
    longitude: Annotated[float, Query(ge=-180, le=180, description="WGS84 longitude")],
    region_name: Annotated[str | None, Query(max_length=120)] = None,
    recent_days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> EnvironmentResponse:
    service = request.app.state.recommender
    location = Location(latitude=latitude, longitude=longitude, region_name=region_name)
    return await service.environment(location, FieldProfile(), recent_days=recent_days)


@router.post(
    "/advice",
    response_model=AdviceResponse,
    summary="Plain-language answer to the farmer's 'what should I plant?' question",
)
async def advice(payload: AdviceRequest, request: Request) -> AdviceResponse:
    """Farmer text + NASA data + rule engine + optional AI explanation."""

    service = request.app.state.advice
    return await service.advise(payload)


@router.get(
    "/reverse-geocode",
    response_model=GeocodeResponse,
    summary="Turn coordinates into a place name (OpenStreetMap Nominatim)",
)
async def reverse_geocode(
    request: Request,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
) -> GeocodeResponse:
    geocoder = getattr(request.app.state, "geocoder", None)
    if geocoder is None:
        return GeocodeResponse(
            found=False,
            latitude=latitude,
            longitude=longitude,
            error="Reverse geocoding is disabled on this server.",
        )
    return await geocoder.reverse(latitude, longitude)


@router.get(
    "/crops", response_model=list[CropInfo], summary="Supported crop catalogue"
)
async def crops() -> list[CropInfo]:
    output: list[CropInfo] = []
    for crop in CROP_CATALOG.values():
        traits = traits_for(crop.key)
        output.append(
            CropInfo(
                key=crop.key,
                name=crop.name,
                local_name=crop.local_name,
                category=crop.category,
                growing_days=crop.growing_days,
                water_need_mm=crop.water_need_mm,
                planting_months=list(crop.planting_months),
                planting_window=crop.planting_window("en"),
                nitrogen_need=crop.nitrogen_need,
                notes=crop.notes,
                icon=traits.icon,
                family=traits.family,
                family_label=traits.family_label,
                rotation_role=traits.role,
                rotation_benefit=traits.benefit,
            )
        )
    return output


@router.post(
    "/farm-plan",
    response_model=FarmPlanResponse,
    summary="One call for the full farm plan: this year, rotation, soil, water, money and risk",
)
async def farm_plan(payload: FarmPlanRequest, request: Request) -> FarmPlanResponse:
    service = request.app.state.farm_plan
    return await service.plan(payload)


@router.post(
    "/rotation",
    response_model=RotationResponse,
    summary="Multi-year crop rotation plan",
)
async def rotation(payload: FarmPlanRequest, request: Request) -> RotationResponse:
    service = request.app.state.farm_plan
    return await service.rotation(payload)


@router.post(
    "/soil-health",
    response_model=SoilHealthResponse,
    summary="Soil-health report card and improvement steps",
)
async def soil_health(payload: FarmPlanRequest, request: Request) -> SoilHealthResponse:
    service = request.app.state.farm_plan
    return await service.soil_health(payload)


@router.post(
    "/water-plan",
    response_model=WaterPlanResponse,
    summary="Monthly water balance, irrigation need and water-saving tips",
)
async def water_plan(payload: FarmPlanRequest, request: Request) -> WaterPlanResponse:
    service = request.app.state.farm_plan
    return await service.water_plan(payload)


@router.post(
    "/economics",
    response_model=EconomicsResponse,
    summary="Profit and cost analysis in USD per hectare and per decare",
)
async def economics(payload: FarmPlanRequest, request: Request) -> EconomicsResponse:
    service = request.app.state.farm_plan
    return await service.economics(payload)


@router.get(
    "/frost-risk",
    response_model=FrostRiskResponse,
    summary="Frost, heat and drought risk from long-term climate normals",
)
async def frost_risk(
    request: Request,
    latitude: Annotated[float, Query(ge=-90, le=90, description="WGS84 latitude")],
    longitude: Annotated[float, Query(ge=-180, le=180, description="WGS84 longitude")],
    region_name: Annotated[str | None, Query(max_length=120)] = None,
    crop: Annotated[str | None, Query(max_length=80, description="Optional crop key")] = None,
    irrigation: Annotated[str, Query(pattern="^(rainfed|limited|full)$")] = "rainfed",
    planting_month: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> FrostRiskResponse:
    service = request.app.state.farm_plan
    payload = FarmPlanRequest(
        location=Location(latitude=latitude, longitude=longitude, region_name=region_name),
        start_crop=crop,
        irrigation=irrigation,  # type: ignore[arg-type]
        planting_month=planting_month,
    )
    return await service.frost_risk(payload)


@router.get(
    "/ai-providers",
    response_model=list[AIProviderInfo],
    summary="Supported AI providers and their trade-offs",
)
async def ai_providers() -> list[AIProviderInfo]:
    return list(AI_PROVIDER_INFO)
