"""AI provider parsing, prompt and fallback tests (no real API keys)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.anthropic import AnthropicProvider
from app.ai.base import (
    AIAnalysis,
    AIContext,
    AIProviderError,
    AdviceContext,
    extract_json_object,
    parse_advice,
    parse_analysis,
)
from app.ai.gemini import GeminiProvider
from app.ai.heuristic import HeuristicProvider
from app.ai.openai_compatible import OpenAICompatibleProvider
from tests.helpers import ai_json_response, completion_response


def make_context(language: str = "tr") -> AIContext:
    return AIContext(
        language=language,
        location={"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
        farmer={
            "field": {"soil_ph": 7.4},
            "resources": {"irrigation": "limited", "water_availability": "medium"},
            "preferences": {"goal": "max_profit"},
        },
        environment={
            "climate": {
                "annual_mean_temp_c": 10.35,
                "annual_precip_mm": 418.2,
                "climate_class": "semi_arid",
            }
        },
        candidates=[
            {
                "crop_key": "wheat",
                "crop_name": "Winter wheat",
                "crop_name_local": "Kışlık Buğday",
                "category": "cereal",
                "rule_score": 80,
                "component_scores": {
                    "temperature": 90,
                    "water": 60,
                    "market": 85,
                    "calendar": 100,
                },
                "strengths": ["Sıcaklık uygun"],
                "limiting_factors": ["Su açığı var"],
                "planting_window": "Ekim–Kasım",
                "water_need_mm": 450,
                "growing_days": 240,
            }
        ],
        data_quality=["NASA POWER grid tabanlıdır."],
    )


async def test_heuristic_provider_produces_structured_advice():
    result = await HeuristicProvider().analyze(make_context())
    assert isinstance(result, AIAnalysis)
    assert "Kışlık Buğday" in result.summary
    assert result.crops[0].crop_key == "wheat"
    assert result.crops[0].actions
    assert result.crops[0].risks
    assert result.confidence in {"low", "medium", "high"}


def test_extract_json_handles_fenced_output():
    text = '```json\n{"summary": "ok", "crops": []}\n```'
    payload = extract_json_object(text)
    assert payload["summary"] == "ok"


def test_extract_json_rejects_garbage():
    with pytest.raises(AIProviderError):
        extract_json_object("sorry, I cannot do that")


def test_parse_analysis_filters_unknown_crops_and_normalizes_confidence():
    payload = ai_json_response(
        crops=[
            {"crop_key": "wheat", "ai_score": 88, "rationale": "ok"},
            {"crop_key": "invented", "ai_score": 99, "rationale": "nope"},
        ],
        confidence="HIGH",
    )
    analysis = parse_analysis(json.dumps(payload, ensure_ascii=False), allowed_crop_keys={"wheat"})
    assert len(analysis.crops) == 1
    assert analysis.crops[0].crop_key == "wheat"
    assert analysis.confidence == "high"


def test_parse_analysis_clamps_scores_and_coerces_string_lists():
    payload = ai_json_response(
        crops=[
            {
                "crop_key": "wheat",
                "ai_score": 150,
                "rationale": "ok",
                "risks": "Kuraklık\nDon",
                "actions": "Sulama planı",
            }
        ]
    )
    analysis = parse_analysis(json.dumps(payload, ensure_ascii=False), allowed_crop_keys={"wheat"})
    assert analysis.crops[0].ai_score == 100
    assert analysis.crops[0].risks == ["Kuraklık", "Don"]
    assert analysis.crops[0].actions == ["Sulama planı"]


async def test_openai_compatible_provider_roundtrip():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_response(ai_json_response()))

    provider = OpenAICompatibleProvider(
        name="openai",
        base_url="https://example.test/v1",
        api_key="secret",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.analyze(make_context())
    await provider.aclose()

    assert result.summary == "Test summary."
    assert captured[0].headers["Authorization"] == "Bearer secret"
    body = json.loads(captured[0].content)
    assert body["model"] == "test-model"
    assert body["response_format"] == {"type": "json_object"}
    assert "sadece output_schema" in body["messages"][1]["content"].lower()


async def test_openai_compatible_retries_without_json_mode_on_400():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, text="response_format is not supported")
        return httpx.Response(200, json=completion_response(ai_json_response()))

    provider = OpenAICompatibleProvider(
        name="custom",
        base_url="https://example.test/v1",
        api_key="secret",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.analyze(make_context())
    await provider.aclose()

    assert result.summary
    assert len(bodies) == 2
    assert "response_format" in bodies[0]
    assert "response_format" not in bodies[1]


async def test_openai_compatible_http_error_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api key")

    provider = OpenAICompatibleProvider(
        name="openai",
        base_url="https://example.test/v1",
        api_key="bad",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AIProviderError):
        await provider.analyze(make_context())
    await provider.aclose()


async def test_gemini_advice_request_shape():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        plan = {
            "headline": "Kışlık Buğday ek.",
            "why": "Yağış yeterli.",
            "steps": ["Toprak analizi yaptır."],
            "grow": ["Tohum yatağını düzle."],
            "feed": ["Gübreyi analize göre ver."],
            "care": ["Tarlayı gez."],
            "risks": ["Kuraklık"],
            "ask_farmer": ["Sulama var mı?"],
            "confidence": "medium",
        }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": json.dumps(plan, ensure_ascii=False)}]
                        }
                    }
                ]
            },
        )

    provider = GeminiProvider(
        api_key="gem-key",
        model="gemini-3.5-flash-lite",
        transport=httpx.MockTransport(handler),
    )
    context = AdviceContext(
        language="tr",
        location={"latitude": 41.6771, "longitude": 26.5557, "region_name": "Edirne"},
        farmer={"field": {"soil_ph": 7.0}, "resources": {"irrigation": "limited"}},
        environment={"climate": {"annual_precip_mm": 613.0}},
        candidates=[
            {
                "crop_key": "wheat",
                "crop_name_local": "Kışlık Buğday",
                "rule_score": 92.0,
                "water_need_mm": 450,
                "nitrogen_need": "medium",
                "strengths": ["soğuğa dayanıklı"],
                "limiting_factors": [],
            }
        ],
        free_text="Ne ekeceğimi bilmiyorum.",
    )
    plan = await provider.advise(context)
    await provider.aclose()

    assert plan.headline == "Kışlık Buğday ek."
    request = captured[0]
    assert request.headers["x-goog-api-key"] == "gem-key"
    payload = json.loads(request.content)
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert "temperature" not in payload["generationConfig"], "Gemini 3.x sıcaklık kabul etmiyor"
    user_text = payload["contents"][0]["parts"][0]["text"]
    assert "Ne ekeceğimi bilmiyorum" in user_text


def test_parse_advice_flags_unknown_crop():
    payload = {
        "headline": "Muz ek.",
        "recommended_crop_key": "banana",
        "why": "Test",
        "confidence": "high",
    }
    plan = parse_advice(json.dumps(payload), allowed_crop_keys={"wheat"})
    assert any("Unverified crop" in risk for risk in plan.risks)


async def test_gemini_provider_roundtrip_and_request_shape():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": json.dumps(ai_json_response(), ensure_ascii=False)}]
                        }
                    }
                ]
            },
        )

    provider = GeminiProvider(
        api_key="gem-key",
        model="gemini-test",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.analyze(make_context())
    await provider.aclose()

    assert result.summary == "Test summary."
    request = captured[0]
    assert "models/gemini-test:generateContent" in str(request.url)
    assert request.headers["x-goog-api-key"] == "gem-key"
    body = json.loads(request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "systemInstruction" in body


async def test_anthropic_provider_roundtrip():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": json.dumps(ai_json_response(), ensure_ascii=False)}
                ]
            },
        )

    provider = AnthropicProvider(
        api_key="anthropic-key",
        model="claude-test",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.analyze(make_context())
    await provider.aclose()

    assert result.summary == "Test summary."
    request = captured[0]
    assert request.headers["x-api-key"] == "anthropic-key"
    body = json.loads(request.content)
    assert body["model"] == "claude-test"
    assert body["system"]
