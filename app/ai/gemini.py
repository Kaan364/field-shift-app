"""Google Gemini (Generative Language API) provider.

Güncel API bilgisi (Kasım 2026):
- Uç nokta: ``POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent``
- Kimlik doğrulama: ``x-goog-api-key`` başlığı (eski ``?key=`` yöntemi yerine)
- Varsayılan model: ``gemini-3.5-flash-lite`` (hızlı + ucuz, yapılandırılmış JSON için yeterli)
- ``gemini-2.5-flash`` 1 Aralık 2026'dan itibaren ``gemini-3.5-flash-lite``'a yönlendiriliyor,
  bu yüzden varsayılan olarak kullanılmıyor.
- Gemini 3.x ailesinde bazı örnekleme parametreleri (temperature gibi) kaldırıldığı için
  sıcaklık yalnızca 2.x modellerinde gönderilir.
"""

from __future__ import annotations

import httpx

from app.ai.base import (
    AIAnalysis,
    AIContext,
    AIProvider,
    AIProviderError,
    AdviceContext,
    build_advice_messages,
    build_messages,
    parse_advice,
    parse_analysis,
)
from app.schemas import AdvicePlan

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProvider):
    name = "gemini"
    kind = "llm"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 45.0,
        temperature: float = 0.2,
        max_tokens: int = 1600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={"Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    @property
    def _supports_temperature(self) -> bool:
        return self.model.startswith("gemini-2")

    def _generation_config(self) -> dict[str, object]:
        config: dict[str, object] = {
            "maxOutputTokens": self.max_tokens,
            "responseMimeType": "application/json",
        }
        if self._supports_temperature:
            config["temperature"] = self.temperature
        return config

    async def _generate(self, system: str, user: str) -> str:
        if not self.api_key:
            raise AIProviderError("Gemini için API anahtarı tanımlı değil.")

        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": self._generation_config(),
        }
        response = await self._client.post(
            f"{self.base_url}/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json=payload,
        )
        if response.status_code >= 400:
            detail = response.text[:400].replace("\n", " ")
            raise AIProviderError(f"Gemini API hatası (HTTP {response.status_code}): {detail}")

        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("Gemini yanıtı beklenen biçimde değil.") from exc

    # ------------------------------------------------------------------
    async def analyze(self, context: AIContext) -> AIAnalysis:
        system, user = build_messages(context)
        content = await self._generate(system, user)
        allowed = {candidate["crop_key"] for candidate in context.candidates}
        return parse_analysis(content, allowed_crop_keys=allowed)

    async def advise(self, context: AdviceContext) -> AdvicePlan:
        system, user = build_advice_messages(context)
        content = await self._generate(system, user)
        allowed = {candidate["crop_key"] for candidate in context.candidates}
        return parse_advice(content, allowed_crop_keys=allowed)
