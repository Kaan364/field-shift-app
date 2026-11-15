"""Free-text advice flow (`/api/v1/advice`) and reverse-geocoding tests."""

from __future__ import annotations

import httpx
import pytest

from app.ai.base import AIContext, AIProvider, AdviceContext
from app.clients.geocoding import NominatimClient
from app.schemas import AdvicePlan, GeocodeResponse
from tests.helpers import ai_json_response  # noqa: F401  (fixture-like helper)


def advice_payload(**overrides) -> dict:
    payload = {
        "location": {"latitude": 41.6771, "longitude": 26.5557, "region_name": "Edirne"},
        "area_hectares": 2.0,
        "soil_texture": "clay_loam",
        "soil_ph": 7.0,
        "organic_matter_pct": 2.2,
        "irrigation": "limited",
        "water_availability": "medium",
        "goal": "max_profit",
        "planting_month": 10,
        "free_text": (
            "I have 20 decare in Edirne and I do not know what to plant. "
            "I do not know how to grow or feed the crop either."
        ),
        "top_n": 3,
        "language": "en",
    }
    payload.update(overrides)
    return payload


def test_advice_plan_coerces_list_text_fields():
    """Models sometimes return `headline`/`why` as lists; the plan must not be rejected."""

    plan = AdvicePlan.model_validate(
        {
            "headline": ["Plant winter wheat.", "Barley is an alternative."],
            "why": ["Rainfall is suitable.", "Winter is cold."],
            "steps": "Till the soil.\nSow the seed.",
            "confidence": "HIGH",
        }
    )

    assert plan.headline == "Plant winter wheat. Barley is an alternative."
    assert plan.why == "Rainfall is suitable. Winter is cold."
    assert plan.steps == ["Till the soil.", "Sow the seed."]
    assert plan.confidence == "high"


def test_advice_with_heuristic_provider(client):
    response = client.post("/api/v1/advice", json=advice_payload())
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["ai"]["kind"] == "deterministic"
    assert data["advice"]["headline"]
    assert len(data["recommendations"]) == 3
    assert data["advice"]["steps"], "simple steps must not be empty"
    assert data["advice"]["grow"]
    assert data["advice"]["feed"]
    assert data["advice"]["care"]

    # Ranking comes from the rule engine: final == rule
    for rec in data["recommendations"]:
        assert rec["scores"]["final_score"] == rec["scores"]["rule_score"]
        assert rec["scores"]["ai_score"] is None


def test_advice_includes_economics_and_risk(client):
    response = client.post("/api/v1/advice", json=advice_payload())
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["economics"]["available"] is True
    assert data["economics"]["crops"]
    assert data["economics"]["total_gross_margin_usd"] is not None
    assert data["risk"]["frost"]
    assert data["risk"]["heat"]
    assert data["risk"]["drought"]
    assert data["risk"]["months"]
    assert data["advice"]["commentary"]


def test_advice_rejects_invalid_location(client):
    payload = advice_payload(location={"latitude": 120, "longitude": 26.5})
    response = client.post("/api/v1/advice", json=payload)
    assert response.status_code == 422


class RecordingProvider(AIProvider):
    name = "recording"
    model = "recording-1"
    kind = "llm"

    def __init__(self) -> None:
        self.contexts: list[AdviceContext] = []

    async def analyze(self, context: AIContext):  # pragma: no cover - unused
        raise AssertionError("advice flow must not call analyze()")

    async def advise(self, context: AdviceContext) -> AdvicePlan:
        self.contexts.append(context)
        return AdvicePlan(
            headline="Plant winter wheat. It is the best option here.",
            why="Rainfall and temperature suit wheat.",
            steps=["Get a soil test.", "Do not miss the sowing window."],
            grow=["Level the seed bed."],
            feed=["Apply fertiliser according to the soil test."],
            care=["Walk the field once a week."],
            risks=["There is a drought risk."],
            ask_farmer=["Can you irrigate your field?"],
            confidence="medium",
        )


def test_advice_passes_free_text_to_ai(make_client):
    provider = RecordingProvider()
    client = make_client(ai=provider)

    response = client.post("/api/v1/advice", json=advice_payload())
    assert response.status_code == 200, response.text

    assert provider.contexts, "the AI provider must be called"
    context = provider.contexts[0]
    assert "I do not know what to plant" in context.free_text
    assert context.candidates, "rule-engine candidates must be passed to the AI"

    data = response.json()
    assert data["ai"]["kind"] == "llm"
    assert data["ai"]["used"] is True
    assert data["ai"]["blended"] is True
    assert data["advice"]["headline"].startswith("Plant winter wheat")
    # Both the AI explanation and the deterministic check survive the merge.
    assert "Rule-engine check:" in data["advice"]["why"]
    assert any("blended" in warning.lower() for warning in data["warnings"])


class FailingProvider(AIProvider):
    name = "failing"
    model = "failing-1"
    kind = "llm"

    async def analyze(self, context: AIContext):  # pragma: no cover
        raise AssertionError("unused")

    async def advise(self, context: AdviceContext) -> AdvicePlan:
        raise RuntimeError("quota exceeded")


def test_advice_falls_back_when_ai_fails(make_client):
    client = make_client(ai=FailingProvider())
    response = client.post("/api/v1/advice", json=advice_payload())
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["ai"]["fallback_used"] is True
    assert data["ai"]["error"]
    assert data["advice"]["headline"]
    assert any("AI service could not be reached" in warning for warning in data["warnings"])


def test_advice_without_free_text_still_works(client):
    response = client.post("/api/v1/advice", json=advice_payload(free_text=""))
    assert response.status_code == 200
    data = response.json()
    assert data["advice"]["ask_farmer"], "missing information should trigger a question"


class FakeGeocoder:
    def __init__(self, found: bool = True) -> None:
        self.found = found
        self.calls = 0

    async def reverse(self, latitude: float, longitude: float) -> GeocodeResponse:
        self.calls += 1
        return GeocodeResponse(
            found=self.found,
            latitude=latitude,
            longitude=longitude,
            city="Edirne",
            district="Merkez",
            country="Türkiye",
            display_name="Edirne, Merkez, Türkiye",
        )


def test_reverse_geocode_endpoint(make_client):
    client = make_client(geocoder=FakeGeocoder())
    response = client.get(
        "/api/v1/reverse-geocode", params={"latitude": 41.6771, "longitude": 26.5557}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert data["city"] == "Edirne"


def test_reverse_geocode_validation(client):
    response = client.get(
        "/api/v1/reverse-geocode", params={"latitude": 91, "longitude": 26.5}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Nominatim client
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nominatim_client_parses_and_caches():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "display_name": "Edirne, Merkez, Edirne, Türkiye",
                "address": {
                    "city": "Edirne",
                    "suburb": "Merkez",
                    "state": "Edirne",
                    "country": "Türkiye",
                },
            },
        )

    geocoder = NominatimClient(transport=httpx.MockTransport(handler))
    first = await geocoder.reverse(41.6771, 26.5557)
    second = await geocoder.reverse(41.6771, 26.5557)
    await geocoder.aclose()

    assert first.found is True
    assert first.city == "Edirne"
    assert first.display_name == "Edirne, Merkez, Edirne"
    assert second.city == "Edirne"
    assert len(calls) == 1, "the same coordinate must be served from cache"
    assert calls[0].headers["User-Agent"].startswith("ProjectAlphecca")


@pytest.mark.asyncio
async def test_nominatim_client_handles_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    geocoder = NominatimClient(transport=httpx.MockTransport(handler))
    result = await geocoder.reverse(41.0, 26.0)
    await geocoder.aclose()

    assert result.found is False
    assert result.error and "503" in result.error
