"""AI abstraction layer.

The product treats the LLM as an *advisor on top of* a deterministic agronomy
engine, never as the only source of truth. This module defines the common
contract, prompt construction and robust JSON parsing.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.scoring import CropEvaluation
from app.schemas import AdvicePlan, AnalyzeRequest, EnvironmentSnapshot


class AIProviderError(RuntimeError):
    """Raised when an AI provider cannot return a usable analysis."""


class AICropAssessment(BaseModel):
    crop_key: str
    ai_score: float = Field(70.0, ge=0, le=100)
    rationale: str = ""
    risks: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    planting_window: str | None = None

    @field_validator("ai_score", mode="before")
    @classmethod
    def _clamp_score(cls, value: Any) -> float:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return 70.0

    @field_validator("risks", "actions", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return value


class AIAnalysis(BaseModel):
    summary: str = ""
    crops: list[AICropAssessment] = Field(default_factory=list)
    general_risks: list[str] = Field(default_factory=list)
    general_actions: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    notes: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> str:
        text = str(value or "medium").strip().lower()
        return text if text in {"low", "medium", "high"} else "medium"

    @field_validator("general_risks", "general_actions", mode="before")
    @classmethod
    def _coerce_general_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return value


class AIContext(BaseModel):
    """Compact, JSON-safe payload sent to the LLM."""

    language: str
    location: dict[str, Any]
    farmer: dict[str, Any]
    environment: dict[str, Any]
    candidates: list[dict[str, Any]]
    data_quality: list[str] = Field(default_factory=list)


class AIProvider(ABC):
    name: str = "base"
    model: str | None = None
    kind: Literal["llm", "deterministic"] = "llm"

    @abstractmethod
    async def analyze(self, context: AIContext) -> AIAnalysis:
        raise NotImplementedError

    async def advise(self, context: "AdviceContext") -> AdvicePlan:
        """Serbest metinli çiftçi sorusuna sade dille cevap.

        Varsayılan olarak desteklenmez; destekleyen sağlayıcılar ezer.
        """

        raise AIProviderError(
            f"Provider {self.name} does not support the free-text advice flow."
        )

    async def aclose(self) -> None:  # pragma: no cover - trivial default
        return None


# ---------------------------------------------------------------------------
# Context / prompt builders
# ---------------------------------------------------------------------------
def build_ai_context(
    request: AnalyzeRequest,
    environment: EnvironmentSnapshot,
    evaluations: list[CropEvaluation],
    *,
    max_candidates: int = 8,
) -> AIContext:
    environment_payload = {
        "elevation_m": environment.nasa_elevation_m,
        "climate": environment.climate.model_dump(mode="json"),
        "soil": environment.soil.model_dump(mode="json"),
        "recent_weather": (
            environment.recent_weather.model_dump(mode="json")
            if environment.recent_weather
            else None
        ),
        "notes": environment.notes,
    }
    candidates = []
    for evaluation in evaluations[:max_candidates]:
        candidates.append(
            {
                "crop_key": evaluation.crop.key,
                "crop_name": evaluation.crop.name,
                "crop_name_local": evaluation.crop.local_name,
                "category": evaluation.crop.category,
                "rule_score": evaluation.rule_score,
                "component_scores": evaluation.components,
                "strengths": evaluation.strengths,
                "limiting_factors": evaluation.limiting_factors,
                "season": (
                    {
                        "window": evaluation.season.window_label,
                        "mean_temp_c": evaluation.season.mean_temp_c,
                        "total_precip_mm": evaluation.season.total_precip_mm,
                        "frost_months": evaluation.season.frost_months,
                        "heat_months": evaluation.season.heat_months,
                    }
                    if evaluation.season
                    else None
                ),
                "water_need_mm": evaluation.crop.water_need_mm,
                "growing_days": evaluation.crop.growing_days,
                "nitrogen_need": evaluation.crop.nitrogen_need,
                "planting_window": evaluation.crop.planting_window(request.language.value),
            }
        )

    return AIContext(
        language=request.language.value,
        location=request.location.model_dump(mode="json"),
        farmer={
            "field": request.field.model_dump(mode="json"),
            "resources": request.resources.model_dump(mode="json"),
            "preferences": request.preferences.model_dump(mode="json"),
        },
        environment=environment_payload,
        candidates=candidates,
        data_quality=environment.notes,
    )


SYSTEM_PROMPT_TR = """Sen deneyimli bir tarım agronomisti ve çiftçi karar destek asistanısın.
Sana NASA POWER verilerinden türetilmiş iklim/toprak özeti, çiftçi profili ve deterministik
bir kural motorunun puanladığı aday ekinler veriliyor.

Görevin:
1. Adayları çiftçinin hedefi, kaynakları ve bölge koşullarına göre yeniden değerlendirmek.
2. Her aday için kısa, somut gerekçe; riskler ve uygulanabilir aksiyonlar yazmak.
3. Verilmeyen bir veriyi ASLA uydurmamak. Eksik veriyi açıkça belirtmek.
4. Kesin verim, gelir veya kâr garantisi vermemek; bunun yerine olasılık ve risk dili kullanmak.
5. Yalnızca geçerli JSON döndürmek. Markdown, kod bloğu veya JSON dışında metin yazmamak.

Önemli sınırlar:
- NASA POWER grid tabanlıdır ve tarla ölçeğinde değildir.
- NASA POWER toprak besin içeriği (N-P-K), pH veya organik madde sağlamaz.
- Yerel çeşit, pazar fiyatı, yasal kısıt ve uzman görüşü verilmediyse bunları varsayma.
- Türkçe yanıt ver (language="tr" ise). Teknik terimleri çiftçinin anlayacağı dille açıkla.
- Aday listesinde olmayan bir crop_key üretme.
"""

SYSTEM_PROMPT_EN = """You are an experienced agronomist and farmer decision-support assistant.
You receive a climate/soil summary derived from NASA POWER data, a farmer profile and
candidate crops scored by a deterministic rule engine.

Your job:
1. Re-evaluate candidates against the farmer's goal, resources and local conditions.
2. For each candidate, provide a concise rationale, risks and actionable steps.
3. NEVER invent data that was not provided. State gaps explicitly.
4. Do not guarantee yield, income or profit; use probabilistic and risk-aware language.
5. Return valid JSON only. No markdown, code fences or text outside the JSON.

Hard limits:
- NASA POWER is gridded, not field-scale.
- NASA POWER does not provide soil nutrients (N-P-K), pH or organic matter.
- Do not assume local varieties, market prices, regulations or expert advice unless provided.
- Respond in English when language="en".
- Do not emit a crop_key that is not in the candidate list.
"""

OUTPUT_SCHEMA = {
    "summary": "2-4 sentence overall recommendation in the requested language",
    "crops": [
        {
            "crop_key": "one of the candidate crop_key values",
            "ai_score": "0-100 number; your agronomic confidence-adjusted score",
            "rationale": "2-4 sentences, specific to the provided data",
            "risks": ["2-4 concrete risks"],
            "actions": ["2-5 concrete, executable actions"],
            "planting_window": "short text",
        }
    ],
    "general_risks": ["cross-cutting risks"],
    "general_actions": ["cross-cutting next steps"],
    "confidence": "low | medium | high",
    "notes": "data gaps or caveats, optional",
}


def build_messages(context: AIContext) -> tuple[str, str]:
    system = SYSTEM_PROMPT_TR if context.language == "tr" else SYSTEM_PROMPT_EN
    user_payload = {
        "task": "Rank the candidate crops and explain the recommendation.",
        "output_schema": OUTPUT_SCHEMA,
        "context": context.model_dump(mode="json"),
    }
    user = (
        "Aşağıdaki JSON bağlamını kullan. Sadece output_schema'ya uygun JSON döndür.\n\n"
        if context.language == "tr"
        else "Use the JSON context below. Return only JSON matching output_schema.\n\n"
    )
    user += json.dumps(user_payload, ensure_ascii=False, indent=2)
    return system, user


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response."""

    if not text or not text.strip():
        raise AIProviderError("The AI provider returned an empty response.")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AIProviderError("No JSON object was found in the AI response.")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"The AI response is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AIProviderError("The AI response is not a JSON object.")
    return payload


def parse_analysis(text: str, allowed_crop_keys: set[str] | None = None) -> AIAnalysis:
    analysis = AIAnalysis.model_validate(extract_json_object(text))
    if allowed_crop_keys is not None:
        analysis.crops = [crop for crop in analysis.crops if crop.crop_key in allowed_crop_keys]
    return analysis


# ---------------------------------------------------------------------------
# Free-text advice ("ne ekeyim?") context, prompt and parser
# ---------------------------------------------------------------------------
class AdviceContext(BaseModel):
    """Farmer free text + NASA summary + rule-engine candidates."""

    language: str
    location: dict[str, Any]
    farmer: dict[str, Any]
    environment: dict[str, Any]
    candidates: list[dict[str, Any]]
    free_text: str = ""
    data_quality: list[str] = Field(default_factory=list)
    economics: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)


ADVICE_SYSTEM_PROMPT_TR = """Sen deneyimli bir tarım danışmanısın. Karşındaki kişi çiftçi ve
tarım bilgisi çok az olabilir. Ona yardımcı olacaksın.

Sana şunlar veriliyor:
- Çiftçinin kendi cümleleriyle anlattığı durum,
- NASA POWER verisinden üretilmiş iklim/toprak özeti,
- Deterministik kural motorunun puanladığı aday bitkiler.

Kurallar (kesinlikle uy):
1. Yalnızca sana verilen verilere dayan. Verilmeyen sayı, fiyat, verim veya yerel bilgi UYDURMA.
2. "Kesin kazanırsın", "bu kadar ürün alırsın" gibi garanti verme. Olasılık dili kullan.
3. ÇOK BASİT Türkçe yaz. Kısa cümleler kur. Teknik terim kullanma; kullanırsan hemen parantez içinde açıkla.
4. Çiftçinin sorularını yanıtla: ne ekmeli, nasıl büyütmeli, nasıl beslemeli, nasıl bakmalı.
5. Aday listesinde olmayan bitki önerme. Yeni bir crop_key üretme.
6. Emin olmadığın yerde "bilmiyorum, bunu tarım müdürlüğüne sor" de. Bu bir zayıflık değildir.
7. Sadece geçerli JSON döndür. Markdown, kod bloğu veya JSON dışı metin yazma.
8. Kısa yaz: her liste en fazla 5 madde, her madde en fazla 2 cümle.

Önemli: NASA POWER tarla ölçeğinde değildir, toprak besinini (N-P-K) vermez.
Bunu gerektiğinde sade bir dille hatırlat."""

ADVICE_SYSTEM_PROMPT_EN = """You are an experienced agricultural advisor speaking to a farmer who may
have very limited farming or reading experience.

You receive: the farmer's own words, a NASA POWER climate/soil summary, and candidate crops
scored by a deterministic rule engine.

Hard rules:
1. Use only the provided data. Never invent numbers, prices, yields or local facts.
2. Never promise results. Use probability and risk language.
3. Write VERY simple language, short sentences, explain any technical term.
4. Answer: what to plant, how to grow it, how to feed it, how to care for it.
5. Only recommend crops from the candidate list; never invent a crop_key.
6. Say "ask your local extension service" when unsure.
7. Return valid JSON only. No markdown or code fences.
8. Be brief: max 5 items per list, max 2 sentences per item.
9. The context includes `economics` and `risk` with pre-calculated numbers. Use them in
   `commentary`; explain profit, cost, break-even and frost/heat/drought risk in very
   simple words. Never invent a different price, yield or probability."""

ADVICE_OUTPUT_SCHEMA = {
    "headline": "one short sentence: what to plant and why (max 15 words)",
    "why": "2-3 short sentences using only the provided data",
    "commentary": (
        "3-5 short sentences that combine the money outlook (profit, cost, break-even) "
        "and the frost/heat/drought risk into one plain-English advisor note"
    ),
    "steps": ["4-5 first actions, one short sentence each"],
    "grow": ["how to establish the crop: soil prep, sowing, timing"],
    "feed": ["fertilisation in plain language; say a soil test is needed"],
    "care": ["irrigation, weeding, pest/disease monitoring, harvest care"],
    "risks": ["3-4 concrete risks in plain language"],
    "ask_farmer": ["1-3 questions whose answers would improve the advice"],
    "confidence": "low | medium | high",
}


def build_advice_messages(context: AdviceContext) -> tuple[str, str]:
    system = ADVICE_SYSTEM_PROMPT_TR if context.language == "tr" else ADVICE_SYSTEM_PROMPT_EN
    payload = {
        "task": "Answer the farmer's question in very simple language.",
        "output_schema": ADVICE_OUTPUT_SCHEMA,
        "context": context.model_dump(mode="json"),
    }
    user = (
        "Aşağıdaki JSON bağlamını kullan. Sadece output_schema'ya uygun JSON döndür.\n\n"
        if context.language == "tr"
        else "Use the JSON context below. Return only JSON matching output_schema.\n\n"
    )
    user += json.dumps(payload, ensure_ascii=False, indent=2)
    return system, user


def parse_advice(text: str, allowed_crop_keys: set[str] | None = None) -> AdvicePlan:
    """Validate the AI answer and remove crop names that were not offered."""

    raw = extract_json_object(text)
    plan = AdvicePlan.model_validate(raw)

    if allowed_crop_keys:
        allowed_names = {key.lower() for key in allowed_crop_keys}
        banned = _find_forbidden_crop(raw, allowed_names)
        if banned:
            plan.risks = [
                *plan.risks,
                f"Unverified crop name removed: {', '.join(banned)}",
            ]
    return plan


def _find_forbidden_crop(raw: dict[str, Any], allowed: set[str]) -> list[str]:
    """Serbest metinde aday listesi dışında geçen crop_key var mı (hafif kontrol)."""

    found: list[str] = []
    recommended = raw.get("recommended_crop_key") or raw.get("crop_key")
    if isinstance(recommended, str) and recommended.strip().lower() not in allowed:
        found.append(recommended.strip())
    return found
