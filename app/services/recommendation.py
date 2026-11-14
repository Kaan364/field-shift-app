"""End-to-end recommendation orchestration."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from app.ai.base import AIAnalysis, AICropAssessment, build_ai_context
from app.ai.heuristic import HeuristicProvider
from app.clients.nasa_power import NASAAPIError, NASAPowerClient
from app.config import Settings
from app.domain.crops import CropProfile
from app.domain.scoring import CropEvaluation, evaluate_candidates
from app.schemas import (
    AIMetadata,
    AnalyzeRequest,
    AnalyzeResponse,
    CropRecommendation,
    DataSource,
    EnvironmentResponse,
    EnvironmentSnapshot,
    Language,
    Location,
    ScoreBreakdown,
)
from app.services.agronomy import build_environment

logger = logging.getLogger(__name__)


class AnalysisError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 422, code: str = "analysis_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


DISCLAIMER_TR = (
    "Bu çıktı bir karar destek aracıdır; verim, gelir veya kâr garantisi değildir. "
    "NASA POWER verileri grid tabanlı ve geçmişe dönük ortalamalardır, tarla ölçeğinde değildir. "
    "Ekim, gübreleme, ilaçlama ve sulama kararlarından önce toprak analizi yaptırın ve "
    "yetkili bir tarım uzmanına / il-ilçe tarım müdürlüğüne danışın."
)

DISCLAIMER_EN = (
    "This output is decision support, not a guarantee of yield, income or profit. "
    "NASA POWER data is gridded and climatological, not field-scale. "
    "Before planting, fertilising, spraying or irrigating, obtain a soil test and consult "
    "a qualified agronomist or the local extension service."
)


class RecommendationService:
    def __init__(self, nasa_client: NASAPowerClient, ai_provider, settings: Settings) -> None:
        self.nasa = nasa_client
        self.ai = ai_provider
        self.settings = settings
        self.heuristic = HeuristicProvider()

    async def environment(
        self,
        location: Location,
        field,
        *,
        recent_days: int = 30,
    ) -> EnvironmentResponse:
        warnings: list[str] = []
        climatology = await self.nasa.get_climatology(location.latitude, location.longitude)
        daily = None
        try:
            daily = await self.nasa.get_daily(
                location.latitude, location.longitude, days=recent_days
            )
        except NASAAPIError as exc:
            warnings.append(f"Son günlük hava verisi alınamadı: {exc}")

        environment, _ = build_environment(
            climatology, daily, field, recent_days=recent_days
        )
        return EnvironmentResponse(
            generated_at=datetime.now(timezone.utc),
            location=location,
            environment=environment,
            warnings=warnings,
        )

    async def prepare(
        self, request: AnalyzeRequest
    ) -> tuple[EnvironmentSnapshot, list[CropEvaluation], list[str], bool]:
        """NASA verisini çeker, ortamı ve kural motoru adaylarını hazırlar.

        Hem ``analyze`` hem de serbest metinli öneri akışı bu adımı paylaşır.
        Dönen dörtlü: (ortam, adaylar, uyarılar, günlük veri alındı mı).
        """

        warnings: list[str] = []
        climatology = await self.nasa.get_climatology(
            request.location.latitude, request.location.longitude
        )
        daily = None
        try:
            daily = await self.nasa.get_daily(
                request.location.latitude, request.location.longitude, days=30
            )
        except NASAAPIError as exc:
            warnings.append(
                f"Son 30 günlük hava verisi alınamadı; analiz iklim ortalamalarıyla yapıldı ({exc})."
            )

        environment, _ = build_environment(climatology, daily, request.field, recent_days=30)
        evaluations, scoring_warnings = evaluate_candidates(request, environment)
        warnings.extend(scoring_warnings)
        return environment, evaluations, warnings, daily is not None

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        environment, evaluations, warnings, has_daily = await self.prepare(request)
        if not evaluations:
            raise AnalysisError(
                "Seçilen filtrelerle değerlendirilebilecek ekin kalmadı. Hariç listesini veya sezon süresi sınırını gevşetin.",
                status_code=422,
                code="no_candidates",
            )

        context = build_ai_context(
            request,
            environment,
            evaluations,
            max_candidates=self.settings.max_ai_candidates,
        )

        ai_result, ai_meta = await self._run_ai(context, warnings)

        heuristic_result = await self.heuristic.analyze(context)
        recommendations = self._merge(
            request, environment, evaluations, ai_result, heuristic_result, ai_meta
        )

        used_ai = ai_meta.kind == "llm" and ai_meta.used and not ai_meta.fallback_used
        if used_ai:
            warnings.append(
                "AI tarafından üretilen gerekçe ve aksiyonlar doğrulanmamış olabilir; "
                "saha kararından önce agronomist kontrolü yapın."
            )

        summary = (ai_result.summary or heuristic_result.summary).strip()
        if not summary:
            summary = heuristic_result.summary

        general_risks = ai_result.general_risks or heuristic_result.general_risks
        general_actions = ai_result.general_actions or heuristic_result.general_actions

        if ai_meta.kind == "deterministic" and isinstance(self.ai, HeuristicProvider) and self.ai.reason:
            warnings.append(self.ai.reason)

        return AnalyzeResponse(
            analysis_id=uuid4().hex,
            generated_at=datetime.now(timezone.utc),
            language=request.language,
            location=request.location,
            environment=environment,
            recommendations=recommendations,
            summary=summary,
            general_risks=self._dedupe(general_risks)[:6],
            general_actions=self._dedupe(general_actions)[:8],
            warnings=self._dedupe(warnings),
            data_sources=self._data_sources(request, has_daily, ai_meta),
            ai=ai_meta,
            disclaimer=DISCLAIMER_TR if request.language == Language.TR else DISCLAIMER_EN,
        )

    # ------------------------------------------------------------------
    # AI execution
    # ------------------------------------------------------------------
    async def _run_ai(self, context, warnings: list[str]) -> tuple[AIAnalysis, AIMetadata]:
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
            result = await provider.analyze(context)
            meta.used = True
            meta.kind = "deterministic"
            meta.latency_ms = int((time.perf_counter() - started) * 1000)
            meta.notes = (
                "Deterministik kural motoru kullanıldı."
                if context.language == "tr"
                else "Deterministic rule engine was used."
            )
            if provider.reason:
                meta.notes = f"{meta.notes} {provider.reason}"
            return result, meta

        try:
            result = await provider.analyze(context)
            meta.used = True
            meta.latency_ms = int((time.perf_counter() - started) * 1000)
            return result, meta
        except Exception as exc:  # noqa: BLE001 - we deliberately isolate provider failures
            logger.warning("AI sağlayıcısı başarısız oldu: %s", exc)
            if not self.settings.ai_fallback_to_heuristic:
                raise AnalysisError(
                    f"AI sağlayıcısı yanıt veremedi: {exc}",
                    status_code=503,
                    code="ai_unavailable",
                ) from exc

            result = await self.heuristic.analyze(context)
            meta.used = False
            meta.fallback_used = True
            meta.error = str(exc)[:500]
            meta.latency_ms = int((time.perf_counter() - started) * 1000)
            meta.notes = (
                "LLM çağrısı başarısız oldu; deterministik motor devreye alındı."
                if context.language == "tr"
                else "LLM call failed; the deterministic engine was used."
            )
            warnings.append(
                "AI sağlayıcısına ulaşılamadı; sonuçlar deterministik agronomi motoruyla üretildi. "
                "AI anahtarını, kotayı ve ağ bağlantısını kontrol edin."
            )
            return result, meta

    # ------------------------------------------------------------------
    # Result merging
    # ------------------------------------------------------------------
    def _merge(
        self,
        request: AnalyzeRequest,
        environment: EnvironmentSnapshot,
        evaluations: list[CropEvaluation],
        ai_result: AIAnalysis,
        heuristic_result: AIAnalysis,
        ai_meta: AIMetadata,
    ) -> list[CropRecommendation]:
        assessments = {item.crop_key: item for item in ai_result.crops}
        fallback_assessments = {item.crop_key: item for item in heuristic_result.crops}
        weight = self.settings.ai_weight

        merged: list[tuple[float, CropEvaluation, AICropAssessment]] = []
        for evaluation in evaluations:
            assessment = assessments.get(evaluation.crop.key) or fallback_assessments.get(evaluation.crop.key)
            if assessment is None:
                assessment = AICropAssessment(
                    crop_key=evaluation.crop.key,
                    ai_score=evaluation.rule_score,
                    rationale="",
                    risks=evaluation.limiting_factors,
                    actions=[],
                )
            ai_score = max(0.0, min(100.0, float(assessment.ai_score)))
            final_score = (1.0 - weight) * evaluation.rule_score + weight * ai_score
            merged.append((round(final_score, 1), evaluation, assessment))

        merged.sort(key=lambda item: (item[0], item[1].crop.market_demand), reverse=True)
        final_scores = [item[0] for item in merged]

        recommendations: list[CropRecommendation] = []
        for rank, (final_score, evaluation, assessment) in enumerate(merged[: request.top_n], start=1):
            crop: CropProfile = evaluation.crop
            if rank < len(final_scores):
                gap_to_next = final_scores[rank - 1] - final_scores[rank]
            else:
                gap_to_next = 10.0
            confidence = self._confidence(
                evaluation, ai_result, rank=rank, gap_to_next=gap_to_next
            )
            recommendations.append(
                CropRecommendation(
                    rank=rank,
                    crop_key=crop.key,
                    crop_name=crop.name,
                    crop_name_local=crop.local_name,
                    category=crop.category,
                    scores=ScoreBreakdown(
                        rule_score=evaluation.rule_score,
                        ai_score=round(float(assessment.ai_score), 1),
                        final_score=final_score,
                        components=evaluation.components,
                    ),
                    rationale=assessment.rationale
                    or self._fallback_rationale(evaluation, request.language),
                    risks=self._dedupe(assessment.risks or evaluation.limiting_factors)[:5],
                    actions=self._dedupe(assessment.actions)[:6],
                    planting_window=assessment.planting_window
                    or crop.planting_window(request.language.value),
                    growing_days=crop.growing_days,
                    water_need_mm=crop.water_need_mm,
                    confidence=confidence,
                )
            )
        return recommendations

    @staticmethod
    def _confidence(
        evaluation: CropEvaluation,
        ai_result: AIAnalysis,
        *,
        rank: int,
        gap_to_next: float,
    ) -> str:
        if ai_result.confidence == "low" or evaluation.confidence == "low":
            return "low"
        if rank == 1 and gap_to_next < 4:
            return "low"
        if ai_result.confidence == "high" and evaluation.confidence == "high" and gap_to_next >= 8:
            return "high"
        return "medium"

    @staticmethod
    def _fallback_rationale(evaluation: CropEvaluation, language: Language) -> str:
        if language == Language.TR:
            parts = [f"{evaluation.crop.local_name} kural motorunda {evaluation.rule_score}/100 aldı."]
            if evaluation.strengths:
                parts.append("Güçlü yönler: " + "; ".join(evaluation.strengths[:3]) + ".")
            if evaluation.limiting_factors:
                parts.append("Sınırlar: " + "; ".join(evaluation.limiting_factors[:3]) + ".")
            return " ".join(parts)
        parts = [f"{evaluation.crop.name} scored {evaluation.rule_score}/100 in the rule engine."]
        if evaluation.strengths:
            parts.append("Strengths: " + "; ".join(evaluation.strengths[:3]) + ".")
        if evaluation.limiting_factors:
            parts.append("Constraints: " + "; ".join(evaluation.limiting_factors[:3]) + ".")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
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

    def _data_sources(
        self,
        request: AnalyzeRequest,
        has_daily: bool,
        ai_meta: AIMetadata,
    ) -> list[DataSource]:
        lat = f"{request.location.latitude:.4f}"
        lon = f"{request.location.longitude:.4f}"
        climatology_url = (
            f"{self.settings.nasa_power_base_url}/climatology/point"
            f"?parameters=T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,ALLSKY_SFC_SW_DWN,WS2M,"
            f"GWETROOT,GWETTOP,TS,EVLAND,EVPTRNS&community=AG"
            f"&latitude={lat}&longitude={lon}&format=JSON"
        )
        sources = [
            DataSource(
                name="NASA POWER - Climatology",
                url=climatology_url,
                description="25 yıllık (2001-2025) aylık iklim ve toprak nemi/sıcaklığı ortalamaları.",
            ),
            DataSource(
                name="Çiftçi girdileri",
                url=None,
                description="Tarla profili, kaynaklar ve tercihler; doğrulanmamış beyan niteliğindedir.",
            ),
        ]
        if has_daily:
            daily_url = (
                f"{self.settings.nasa_power_base_url}/daily/point"
                f"?parameters=T2M,T2M_MIN,T2M_MAX,PRECTOTCORR,RH2M,GWETROOT,GWETTOP"
                f"&community=AG&latitude={lat}&longitude={lon}&format=JSON"
            )
            sources.append(
                DataSource(
                    name="NASA POWER - Daily (recent)",
                    url=daily_url,
                    description="Son 30 günün günlük sıcaklık, yağış ve toprak nemi verileri.",
                )
            )
        if ai_meta.kind == "llm":
            sources.append(
                DataSource(
                    name=f"AI sağlayıcı: {ai_meta.provider}",
                    url=None,
                    description=(
                        f"Model: {ai_meta.model or 'belirtilmedi'}. AI çıktısı doğrulanmamıştır; "
                        "agronomist kontrolü gerekir."
                    ),
                )
            )
        else:
            sources.append(
                DataSource(
                    name="Deterministik agronomi motoru",
                    url=None,
                    description="Açıklanabilir kural tabanlı puanlama; harici AI çağrısı yapılmadı.",
                )
            )
        return sources
