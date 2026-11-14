"""HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.ai.provider_info import AI_PROVIDER_INFO
from app.domain.crops import CROP_CATALOG
from app.schemas import (
    AdviceRequest,
    AdviceResponse,
    AIProviderInfo,
    AnalyzeRequest,
    AnalyzeResponse,
    CropInfo,
    EnvironmentResponse,
    FieldProfile,
    GeocodeResponse,
    Location,
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
    return [
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
        )
        for crop in CROP_CATALOG.values()
    ]


@router.get(
    "/ai-providers",
    response_model=list[AIProviderInfo],
    summary="Desteklenen AI sağlayıcıları ve karşılaştırmaları",
)
async def ai_providers() -> list[AIProviderInfo]:
    return list(AI_PROVIDER_INFO)
