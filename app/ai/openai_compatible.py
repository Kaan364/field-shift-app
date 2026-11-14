"""OpenAI-compatible chat completion provider.

Works with OpenAI, Groq, Mistral, DeepSeek, xAI, Together, OpenRouter and a
local Ollama server (all expose ``POST /chat/completions``).
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIProvider):
    kind = "llm"

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 45.0,
        temperature: float = 0.2,
        max_tokens: int = 1600,
        json_mode: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={"Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(self, system: str, user: str) -> str:
        if not self.api_key and self.name not in {"ollama"}:
            raise AIProviderError(f"{self.name} için API anahtarı tanımlı değil.")

        base_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = dict(base_payload)
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = await self._client.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers
        )

        # Some OpenAI-compatible servers reject response_format. Retry once
        # without it instead of failing the whole request.
        if response.status_code == 400 and self.json_mode:
            logger.info("%s response_format desteklemedi; json_mode olmadan yeniden denenecek.", self.name)
            payload = dict(base_payload)
            response = await self._client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )

        if response.status_code >= 400:
            detail = response.text[:400].replace("\n", " ")
            raise AIProviderError(
                f"{self.name} API hatası (HTTP {response.status_code}): {detail}"
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(f"{self.name} yanıtı beklenen biçimde değil.") from exc

        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

        return str(content)

    async def analyze(self, context: AIContext) -> AIAnalysis:
        system, user = build_messages(context)
        content = await self._complete(system, user)
        allowed = {candidate["crop_key"] for candidate in context.candidates}
        return parse_analysis(content, allowed_crop_keys=allowed)

    async def advise(self, context: AdviceContext) -> AdvicePlan:
        system, user = build_advice_messages(context)
        content = await self._complete(system, user)
        allowed = {candidate["crop_key"] for candidate in context.candidates}
        return parse_advice(content, allowed_crop_keys=allowed)
