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
    EnvironmentResponse,
    FarmPlanRequest,
    FarmPlanResponse,
    FieldProfile,
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
    summary="Bölge ve çiftçi girdilerine göre ekin önerisi üret",
)
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Run the full pipeline: NASA POWER -> rule engine -> AI -> ranked advice."""

    service = request.app.state.recommender
    return await service.analyze(payload)


@router.get(
    "/environment",
    response_model=EnvironmentResponse,
    summary="NASA POWER iklim/toprak özetini ham öneri olmadan getir",
)
async def environment(
    request: Request,
    latitude: Annotated[float, Query(ge=-90, le=90, description="WGS84 enlem")],
    longitude: Annotated[float, Query(ge=-180, le=180, description="WGS84 boylam")],
    region_name: Annotated[str | None, Query(max_length=120)] = None,
    recent_days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> EnvironmentResponse:
    service = request.app.state.recommender
    location = Location(latitude=latitude, longitude=longitude, region_name=region_name)
    return await service.environment(location, FieldProfile(), recent_days=recent_days)


@router.post(
    "/advice",
    response_model=AdviceResponse,
    summary="Serbest metinle sorulan 'ne ekeyim?' sorusuna sade dilli öneri",
)
async def advice(payload: AdviceRequest, request: Request) -> AdviceResponse:
    """Çiftçinin kendi cümleleri + NASA verisi + kural motoru + (varsa) AI açıklaması."""

    service = request.app.state.advice
    return await service.advise(payload)


@router.get(
    "/reverse-geocode",
    response_model=GeocodeResponse,
    summary="Koordinatı yer adına çevir (OpenStreetMap Nominatim)",
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
            error="Coğrafi kodlama bu sunucuda kapalı.",
        )
    return await geocoder.reverse(latitude, longitude)


@router.get(
    "/crops", response_model=list[CropInfo], summary="Desteklenen ekin kataloğu"
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
                planting_window=crop.planting_window("tr"),
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
    summary="Tek çağrıda tam çiftlik planı: bu yıl + 3 yıllık rotasyon + toprak + su + iklim",
)
async def farm_plan(payload: FarmPlanRequest, request: Request) -> FarmPlanResponse:
    service = request.app.state.farm_plan
    return await service.plan(payload)


@router.post(
    "/rotation",
    response_model=RotationResponse,
    summary="Çok yıllık ekim nöbeti (rotasyon) planı",
)
async def rotation(payload: FarmPlanRequest, request: Request) -> RotationResponse:
    service = request.app.state.farm_plan
    return await service.rotation(payload)


@router.post(
    "/soil-health",
    response_model=SoilHealthResponse,
    summary="Toprak sağlığı karnesi ve iyileştirme adımları",
)
async def soil_health(payload: FarmPlanRequest, request: Request) -> SoilHealthResponse:
    service = request.app.state.farm_plan
    return await service.soil_health(payload)


@router.post(
    "/water-plan",
    response_model=WaterPlanResponse,
    summary="Aylık su dengesi, sulama ihtiyacı ve su tasarrufu önerileri",
)
async def water_plan(payload: FarmPlanRequest, request: Request) -> WaterPlanResponse:
    service = request.app.state.farm_plan
    return await service.water_plan(payload)


@router.get(
    "/ai-providers",
    response_model=list[AIProviderInfo],
    summary="Desteklenen AI sağlayıcıları ve karşılaştırmaları",
)
async def ai_providers() -> list[AIProviderInfo]:
    return list(AI_PROVIDER_INFO)
