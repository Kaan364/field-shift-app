"""Anthropic Claude (Messages API) provider."""

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


class AnthropicProvider(AIProvider):
    name = "anthropic"
    kind = "llm"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: str = "https://api.anthropic.com/v1",
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
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise AIProviderError("No API key is configured for Anthropic.")

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        response = await self._client.post(f"{self.base_url}/messages", json=payload)
        if response.status_code >= 400:
            detail = response.text[:400].replace("\n", " ")
            raise AIProviderError(f"Anthropic API error (HTTP {response.status_code}): {detail}")

        try:
            data = response.json()
            return "".join(
                block.get("text", "")
                for block in data["content"]
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise AIProviderError("The Anthropic response was not in the expected format.") from exc

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
