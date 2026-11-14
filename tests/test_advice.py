"""Serbest metinli öneri akışı (`/api/v1/advice`) ve coğrafi kodlama testleri."""

from __future__ import annotations

import httpx
import pytest

from app.ai.base import AIContext, AIProvider, AdviceContext
from app.clients.geocoding import NominatimClient
from app.schemas import AdvicePlan, GeocodeResponse
from tests.helpers import ai_json_response  # noqa: F401  (fixture benzeri yardımcı)


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
            "Edirne'de 20 dönüm tarlam var. Ne ekeceğimi bilmiyorum. "
            "Bitkiyi nasıl büyüteceğimi, nasıl besleyeceğimi bilmiyorum."
        ),
        "top_n": 3,
        "language": "tr",
    }
    payload.update(overrides)
    return payload


def test_advice_plan_coerces_list_text_fields():
    """Modeller `headline`/`why` alanlarını bazen liste döndürüyor; plan reddedilmemeli."""

    plan = AdvicePlan.model_validate(
        {
            "headline": ["Kışlık Buğday ekin.", "Arpa alternatif."],
            "why": ["Yağış uygun.", "Kış soğuk geçer."],
            "steps": "Toprağı işle.\nEkim yap.",
            "confidence": "HIGH",
        }
    )

    assert plan.headline == "Kışlık Buğday ekin. Arpa alternatif."
    assert plan.why == "Yağış uygun. Kış soğuk geçer."
    assert plan.steps == ["Toprağı işle.", "Ekim yap."]
    assert plan.confidence == "high"


def test_advice_with_heuristic_provider(client):
    response = client.post("/api/v1/advice", json=advice_payload())
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["ai"]["kind"] == "deterministic"
    assert data["advice"]["headline"]
    assert len(data["recommendations"]) == 3
    assert data["advice"]["steps"], "basit adımlar boş olmamalı"
    assert data["advice"]["grow"]
    assert data["advice"]["feed"]
    assert data["advice"]["care"]

    # Sıralama kural motorundan gelir: final == rule
    for rec in data["recommendations"]:
        assert rec["scores"]["final_score"] == rec["scores"]["rule_score"]
        assert rec["scores"]["ai_score"] is None


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

    async def analyze(self, context: AIContext):  # pragma: no cover - kullanılmaz
        raise AssertionError("advice akışı analyze() çağırmamalı")

    async def advise(self, context: AdviceContext) -> AdvicePlan:
        self.contexts.append(context)
        return AdvicePlan(
            headline="Kışlık Buğday ek. Bu bölgede en uygun seçenek.",
            why="Yağış ve sıcaklık buğdaya uygun.",
            steps=["Toprak analizi yaptır.", "Ekim zamanını kaçırma."],
            grow=["Tohum yatağını düzle."],
            feed=["Gübreyi analize göre ver."],
            care=["Tarlayı haftada bir gez."],
            risks=["Kuraklık riski var."],
            ask_farmer=["Tarlanı sulayabiliyor musun?"],
            confidence="medium",
        )


def test_advice_passes_free_text_to_ai(make_client):
    provider = RecordingProvider()
    client = make_client(ai=provider)

    response = client.post("/api/v1/advice", json=advice_payload())
    assert response.status_code == 200, response.text

    assert provider.contexts, "AI sağlayıcısı çağrılmalı"
    context = provider.contexts[0]
    assert "Ne ekeceğimi bilmiyorum" in context.free_text
    assert context.candidates, "kural motoru adayları AI'a aktarılmalı"

    data = response.json()
    assert data["ai"]["kind"] == "llm"
    assert data["ai"]["used"] is True
    assert data["advice"]["headline"].startswith("Kışlık Buğday")


class FailingProvider(AIProvider):
    name = "failing"
    model = "failing-1"
    kind = "llm"

    async def analyze(self, context: AIContext):  # pragma: no cover
        raise AssertionError("kullanılmaz")

    async def advise(self, context: AdviceContext) -> AdvicePlan:
        raise RuntimeError("kotu aşıldı")


def test_advice_falls_back_when_ai_fails(make_client):
    client = make_client(ai=FailingProvider())
    response = client.post("/api/v1/advice", json=advice_payload())
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["ai"]["fallback_used"] is True
    assert data["ai"]["error"]
    assert data["advice"]["headline"]
    assert any("Yapay zekâya ulaşılamadı" in warning for warning in data["warnings"])


def test_advice_without_free_text_still_works(client):
    response = client.post("/api/v1/advice", json=advice_payload(free_text=""))
    assert response.status_code == 200
    data = response.json()
    assert data["advice"]["ask_farmer"], "eksik bilgi için soru sorulmalı"


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
# Nominatim istemcisi
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
    assert len(calls) == 1, "aynı koordinat önbellekten dönmeli"
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
