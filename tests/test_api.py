"""API-level tests (FastAPI + TestClient, external services faked)."""

from __future__ import annotations

from app.ai.base import AIAnalysis, AICropAssessment, AIProvider, AIProviderError
from tests.helpers import FakeNASA, request_payload


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ai_provider"] == "heuristic"
    assert data["ai_configured"] is True
    assert data["geocoding_enabled"] is False  # test istemcisinde dış servis kapalı
    assert isinstance(data["cache_entries"], int)
    assert response.headers["X-Request-ID"]


def test_geo_page_embeds_safe_redirect_target(client):
    ok = client.get("/geo", params={"next": "http://127.0.0.1:8501"})
    assert ok.status_code == 200
    assert "Use my location" in ok.text
    assert "http://127.0.0.1:8501" in ok.text

    # javascript: gibi tehlikeli hedefler yok sayılır, varsayılan arayüz adresine düşer.
    hostile = client.get("/geo", params={"next": "javascript:alert(1)"})
    assert hostile.status_code == 200
    assert "javascript:alert" not in hostile.text


def test_root_describes_api(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["docs_url"] == "/docs"
    assert "analyze" in data["endpoints"]
    assert data["example_request"]["location"]["region_name"] == "Ankara"


def test_catalog_and_provider_metadata(client):
    crops = client.get("/api/v1/crops")
    assert crops.status_code == 200
    keys = [item["key"] for item in crops.json()]
    assert len(keys) == len(set(keys))
    assert "wheat" in keys

    providers = client.get("/api/v1/ai-providers")
    assert providers.status_code == 200
    provider_keys = {item["key"] for item in providers.json()}
    assert {"gemini", "openai", "heuristic", "ollama"} <= provider_keys
    recommended = [item for item in providers.json() if item["recommended"]]
    assert len(recommended) == 1


def test_analyze_success(client):
    response = client.post("/api/v1/analyze", json=request_payload(top_n=3))
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["analysis_id"]
    assert data["location"]["region_name"] == "Ankara"
    assert len(data["environment"]["monthly"]) == 12
    assert len(data["recommendations"]) == 3

    scores = [item["scores"]["final_score"] for item in data["recommendations"]]
    assert scores == sorted(scores, reverse=True)
    assert [item["rank"] for item in data["recommendations"]] == [1, 2, 3]
    assert data["recommendations"][0]["crop_key"] == "wheat"
    assert data["ai"]["kind"] == "deterministic"
    assert data["ai"]["used"] is True
    assert data["summary"]
    assert data["disclaimer"]
    assert data["data_sources"]
    assert "detay" not in data["recommendations"][0]


def test_analyze_validation_error(client):
    payload = request_payload()
    payload["location"]["latitude"] = 120
    response = client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 422


def test_analyze_nasa_failure_returns_502(make_client):
    client = make_client(nasa=FakeNASA(error="NASA down for maintenance"))
    response = client.post("/api/v1/analyze", json=request_payload())
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "nasa_power_unavailable"
    assert "maintenance" in body["message"]
    assert body["request_id"]


def test_analyze_no_candidates(make_client):
    client = make_client()
    payload = request_payload()
    payload["preferences"]["max_growing_days"] = 60
    response = client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "no_candidates"


def test_analyze_ai_failure_falls_back(make_client):
    class FailingAI(AIProvider):
        name = "failing"
        model = "failing-1"

        async def analyze(self, context):
            raise AIProviderError("quota exceeded")

    client = make_client(ai=FailingAI())
    response = client.post("/api/v1/analyze", json=request_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["ai"]["fallback_used"] is True
    assert data["ai"]["used"] is False
    assert data["ai"]["error"] == "quota exceeded"
    assert any("deterministic" in warning.lower() for warning in data["warnings"])


def test_ai_weight_blend(make_client):
    class StubAI(AIProvider):
        name = "stub"
        model = "stub-1"

        async def analyze(self, context):
            return AIAnalysis(
                summary="Stub özet.",
                crops=[
                    AICropAssessment(
                        crop_key="wheat",
                        ai_score=100,
                        rationale="Stub gerekçe.",
                        risks=["Stub risk"],
                        actions=["Stub aksiyon"],
                    )
                ],
                confidence="high",
            )

    client = make_client(ai=StubAI())
    response = client.post("/api/v1/analyze", json=request_payload(top_n=8))
    assert response.status_code == 200
    data = response.json()
    wheat = next(item for item in data["recommendations"] if item["crop_key"] == "wheat")
    expected = round(0.65 * wheat["scores"]["rule_score"] + 0.35 * 100, 1)
    assert abs(wheat["scores"]["final_score"] - expected) <= 0.11
    assert data["ai"]["kind"] == "llm"
    assert data["ai"]["used"] is True
    assert data["ai"]["blended"] is True
    assert data["ai"]["blend_weight"] == 0.35
    # The AI rationale and the deterministic check are both kept.
    assert "Stub gerekçe." in wheat["rationale"]
    assert "Rule-engine check:" in wheat["rationale"]
    assert any("blended" in warning.lower() for warning in data["warnings"])
    assert any("blended" in source["name"].lower() for source in data["data_sources"])
    assert data["recommendations"][0]["crop_key"] == "wheat"


def test_blending_can_be_disabled(make_client, settings):
    class StubAI(AIProvider):
        name = "stub"
        model = "stub-1"

        async def analyze(self, context):
            return AIAnalysis(
                summary="Stub summary.",
                crops=[
                    AICropAssessment(
                        crop_key="wheat",
                        ai_score=100,
                        rationale="Stub rationale.",
                    )
                ],
                confidence="high",
            )

    settings.ai_blend_with_heuristic = False
    client = make_client(ai=StubAI())
    response = client.post("/api/v1/analyze", json=request_payload())
    assert response.status_code == 200
    data = response.json()
    wheat = next(item for item in data["recommendations"] if item["crop_key"] == "wheat")
    assert data["ai"]["blended"] is False
    assert "Rule-engine check:" not in wheat["rationale"]
    assert not any("blended" in source["name"].lower() for source in data["data_sources"])


def test_environment_endpoint(client):
    response = client.get(
        "/api/v1/environment",
        params={"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["environment"]["climate"]["annual_precip_mm"] == 418.2
    assert data["environment"]["climate"]["climate_class"] == "semi_arid"
    assert data["environment"]["recent_weather"]["available_days"] == 27


def test_environment_endpoint_validates_coordinates(client):
    response = client.get("/api/v1/environment", params={"latitude": -95, "longitude": 32.85})
    assert response.status_code == 422


def test_ai_disabled_without_fallback_returns_503(make_client, settings):
    settings.ai_fallback_to_heuristic = False

    class FailingAI(AIProvider):
        name = "failing"
        model = "failing-1"

        async def analyze(self, context):
            raise AIProviderError("provider down")

    client = make_client(ai=FailingAI())
    response = client.post("/api/v1/analyze", json=request_payload())
    assert response.status_code == 503
    assert response.json()["error"] == "ai_unavailable"
