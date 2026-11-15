"""Free-text ("what should I plant?") farmer advice orchestration.

Flow:
1. The farmer's free text, location and a few simple answers are collected.
2. NASA POWER climate/soil data is fetched.
3. The deterministic rule engine scores the candidates (it owns the ranking).
4. The AI writes the plain-language explanation; when blending is enabled the
   deterministic narrative, risks and action lists are merged with it.
5. If the AI is unavailable, the deterministic template takes over.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from app.ai.base import AdviceContext, build_ai_context
from app.ai.blending import blend_advice
from app.ai.heuristic import HeuristicProvider
from app.clients.nasa_power import NASAPowerClient
from app.config import Settings
from app.domain.economics import build_economics
from app.domain.frost import assess_risk
from app.domain.scoring import CropEvaluation
from app.schemas import (
    AIMetadata,
    AdvicePlan,
    AdviceRequest,
    AdviceResponse,
    AnalyzeRequest,
    CropRecommendation,
    DataSource,
    FieldProfile,
    Language,
    Preferences,
    Resources,
    ScoreBreakdown,
)
from app.services.agronomy import irrigation_supply_mm, season_metrics
from app.services.recommendation import (
    DISCLAIMER_EN,
    DISCLAIMER_TR,
    AnalysisError,
    RecommendationService,
)
from app.services.sections import economics_payload, risk_payload

logger = logging.getLogger(__name__)


class AdviceService:
    def __init__(
        self,
        recommender: RecommendationService,
        nasa_client: NASAPowerClient,
        ai_provider,
        settings: Settings,
    ) -> None:
        self.recommender = recommender
        self.nasa = nasa_client
        self.ai = ai_provider
        self.settings = settings

    async def advise(self, payload: AdviceRequest) -> AdviceResponse:
        request = self._to_analyze_request(payload)
        environment, evaluations, warnings, _has_daily = await self.recommender.prepare(request)
        if not evaluations:
            raise AnalysisError(
                "No crop could be evaluated for this location and preferences.",
                status_code=422,
                code="no_candidates",
            )

        top_crop = evaluations[0].crop
        season = season_metrics(environment, top_crop, payload.planting_month)
        water_deficit = max(
            0.0,
            float(top_crop.water_need_mm)
            - ((season.total_precip_mm or 0.0) + irrigation_supply_mm(request.resources)),
        )
        economics = build_economics(
            environment,
            request.field,
            request.resources,
            [top_crop],
            area_hectares=request.field.area_hectares,
            water_deficit_mm=water_deficit,
        )
        risk = assess_risk(
            environment,
            crop=top_crop,
            water_deficit_mm=water_deficit,
            irrigation=request.resources.irrigation,
        )

        analyze_context = build_ai_context(
            request,
            environment,
            evaluations,
            max_candidates=self.settings.max_ai_candidates,
        )
        heuristic_result = await self.recommender.heuristic.analyze(analyze_context)

        candidate_limit = max(payload.top_n, 3)
        advice_context = AdviceContext(
            language=payload.language.value,
            location=request.location.model_dump(mode="json"),
            farmer={
                "field": request.field.model_dump(mode="json"),
                "resources": request.resources.model_dump(mode="json"),
                "preferences": request.preferences.model_dump(mode="json"),
            },
            environment=analyze_context.environment,
            candidates=analyze_context.candidates[:candidate_limit],
            free_text=payload.free_text.strip(),
            data_quality=environment.notes,
            economics={
                "headline": economics.headline,
                "summary": economics.summary,
                "gross_margin_usd": economics.total_gross_margin_usd,
                "margin_per_decare_usd": economics.margin_per_decare_usd,
                "total_cost_usd": economics.total_cost_usd,
                "break_even_price_usd_per_t": economics.break_even_price_usd_per_t,
                "low_profit_usd": economics.low_profit_usd,
                "high_profit_usd": economics.high_profit_usd,
            },
            risk={
                "overall": risk.overall_label,
                "summary": risk.summary,
                "frost": risk.frost.risk_label,
                "heat": risk.heat.risk_label,
                "drought": risk.drought.risk_label,
                "last_frost_month": risk.frost.last_frost_month,
                "first_frost_month": risk.frost.first_frost_month,
                "actions": risk.actions,
            },
        )

        plan, ai_meta = await self._run_ai(advice_context, warnings)
        recommendations = self._recommendations(payload, evaluations, heuristic_result)

        if ai_meta.kind == "llm" and ai_meta.used and not ai_meta.fallback_used:
            warnings.append(
                "The explanation was written by AI; the ranking comes from the rule engine. "
                "Ask an expert before critical decisions such as pesticide or fertiliser doses."
            )
            if ai_meta.blended:
                warnings.append(
                    "The AI explanation was blended with the deterministic rule engine: "
                    "narrative, risks and action lists combine both views."
                )

        summary = plan.headline or recommendations[0].rationale

        return AdviceResponse(
            advice_id=uuid4().hex,
            generated_at=datetime.now(timezone.utc),
            language=payload.language,
            location=request.location,
            environment=environment,
            recommendations=recommendations,
            advice=plan,
            economics=economics_payload(economics),
            risk=risk_payload(risk),
            summary=summary,
            warnings=self._dedupe(warnings),
            ai=ai_meta,
            data_sources=self._data_sources(request, ai_meta),
            disclaimer=DISCLAIMER_TR if payload.language == Language.TR else DISCLAIMER_EN,
        )

    # ------------------------------------------------------------------
    def _to_analyze_request(self, payload: AdviceRequest) -> AnalyzeRequest:
        planting_month = payload.planting_month
        return AnalyzeRequest(
            location=payload.location,
            field=FieldProfile(
                area_hectares=payload.area_hectares or 1.0,
                soil_texture=payload.soil_texture,
                soil_ph=payload.soil_ph,
                organic_matter_pct=payload.organic_matter_pct,
                salinity_ds_m=payload.salinity_ds_m,
                drainage=payload.drainage,
                slope_pct=payload.slope_pct,
                previous_crop=payload.previous_crop,
            ),
            resources=Resources(
                irrigation=payload.irrigation,
                water_availability=payload.water_availability,
            ),
            preferences=Preferences(
                goal=payload.goal,
                planting_month=planting_month,
                market_access=payload.market_access,
            ),
            top_n=payload.top_n,
            language=payload.language,
        )

    async def _run_ai(
        self, context: AdviceContext, warnings: list[str]
    ) -> tuple[AdvicePlan, AIMetadata]:
        started = time.perf_counter()
        provider = self.ai
        meta = AIMetadata(
            provider=getattr(provider, "name", "unknown"),
            model=getattr(provider, "model", None),
            kind=getattr(provider, "kind", "llm"),
            used=False,
            fallback_used=False,
        )

        if isinstance(provider, HeuristicProvider):
            plan = await provider.advise(context)
            meta.used = True
            meta.kind = "deterministic"
            meta.latency_ms = int((time.perf_counter() - started) * 1000)
            meta.notes = "Explanation generated deterministically by the rule engine."
            if provider.reason:
                meta.notes = f"{meta.notes} {provider.reason}"
            return plan, meta

        # Always keep the deterministic plan: it is both the fallback and the
        # second half of the blended answer.
        heuristic_plan = await self.recommender.heuristic.advise(context)

        try:
            plan = await provider.advise(context)  # type: ignore[attr-defined]
            meta.used = True
            if self.settings.ai_blend_with_heuristic:
                plan = blend_advice(plan, heuristic_plan, self.settings.ai_weight)
                meta.blended = True
                meta.blend_weight = self.settings.ai_weight
                meta.notes = (
                    "AI explanation was blended with the deterministic advice plan "
                    f"(AI weight {self.settings.ai_weight:.2f})."
                )
            meta.latency_ms = int((time.perf_counter() - started) * 1000)
            return plan, meta
        except Exception as exc:  # noqa: BLE001 - provider failures are isolated
            logger.warning("AI free-text advice failed: %s", exc)
            if not self.settings.ai_fallback_to_heuristic:
                raise AnalysisError(
                    f"The AI provider did not respond: {exc}",
                    status_code=503,
                    code="ai_unavailable",
                ) from exc

            plan = heuristic_plan
            meta.used = False
            meta.fallback_used = True
            meta.error = str(exc)[:500]
            meta.latency_ms = int((time.perf_counter() - started) * 1000)
            meta.notes = (
                "AI çağrısı başarısız oldu; deterministik açıklama kullanıldı."
                if context.language == "tr"
                else "The AI call failed; the deterministic explanation was used."
            )
            warnings.append(
                "AI servisine ulaşılamadı; açıklamalar deterministik kural motorundan geliyor."
                if context.language == "tr"
                else (
                    "The AI service could not be reached; explanations come from the "
                    "deterministic rule engine."
                )
            )
            return plan, meta

    # ------------------------------------------------------------------
    def _recommendations(
        self,
        payload: AdviceRequest,
        evaluations: list[CropEvaluation],
        heuristic_result,
    ) -> list[CropRecommendation]:
        assessments = {item.crop_key: item for item in heuristic_result.crops}
        output: list[CropRecommendation] = []
        for rank, evaluation in enumerate(evaluations[: payload.top_n], start=1):
            crop = evaluation.crop
            assessment = assessments.get(crop.key)
            output.append(
                CropRecommendation(
                    rank=rank,
                    crop_key=crop.key,
                    crop_name=crop.name,
                    crop_name_local=crop.local_name,
                    category=crop.category,
                    scores=ScoreBreakdown(
                        rule_score=evaluation.rule_score,
                        ai_score=None,
                        final_score=evaluation.rule_score,
                        components=evaluation.components,
                    ),
                    rationale=(
                        assessment.rationale
                        if assessment and assessment.rationale
                        else RecommendationService._fallback_rationale(evaluation, payload.language)
                    ),
                    risks=self._dedupe(
                        (assessment.risks if assessment else []) or evaluation.limiting_factors
                    )[:5],
                    actions=self._dedupe(assessment.actions if assessment else [])[:6],
                    planting_window=crop.planting_window(payload.language.value),
                    growing_days=crop.growing_days,
                    water_need_mm=crop.water_need_mm,
                    confidence=evaluation.confidence,
                )
            )
        return output

    def _data_sources(self, request: AnalyzeRequest, ai_meta: AIMetadata) -> list[DataSource]:
        lat = f"{request.location.latitude:.4f}"
        lon = f"{request.location.longitude:.4f}"
        turkish = request.language == Language.TR
        sources = [
            DataSource(
                name="NASA POWER - Climatology",
                url=(
                    f"{self.settings.nasa_power_base_url}/climatology/point"
                    f"?parameters=T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,ALLSKY_SFC_SW_DWN,WS2M,"
                    f"GWETROOT,GWETTOP,TS,EVLAND,EVPTRNS&community=AG"
                    f"&latitude={lat}&longitude={lon}&format=JSON"
                ),
                description=(
                    "25 yıllık (2001-2025) aylık iklim ve toprak nemi/sıcaklığı ortalamaları."
                    if turkish
                    else "25-year (2001-2025) monthly climate and soil-moisture/temperature averages."
                ),
            ),
            DataSource(
                name="Deterministic rule engine",
                url=None,
                description=(
                    "Sıralama ve puanlar kural tabanlıdır; AI açıklamayı yazar."
                    if turkish
                    else "Ranking and scores come from explainable rules; the AI writes the explanation."
                ),
            ),
        ]
        if ai_meta.kind == "llm" and not ai_meta.fallback_used:
            sources.append(
                DataSource(
                    name=f"AI provider: {ai_meta.provider}",
                    url=None,
                    description=(
                        f"Model: {ai_meta.model or 'not specified'}. The explanation is unverified; "
                        "expert review is required."
                    ),
                )
            )
            if ai_meta.blended:
                sources.append(
                    DataSource(
                        name="Deterministic rule engine (blended)",
                        url=None,
                        description=(
                            "The deterministic advice plan is merged with the AI explanation "
                            f"(AI weight {ai_meta.blend_weight or 0.0:.2f}); ranking is unchanged."
                        ),
                    )
                )
        elif ai_meta.kind == "llm" and ai_meta.fallback_used:
            sources.append(
                DataSource(
                    name="Deterministic rule engine",
                    url=None,
                    description=(
                        "The AI provider did not respond; the deterministic advice plan "
                        "produced this explanation."
                    ),
                )
            )
        return sources

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for item in items:
            text = (item or "").strip()
            if text and text not in seen:
                seen.add(text)
                output.append(text)
        return output
