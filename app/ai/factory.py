"""Build the configured AI provider with graceful fallback."""

from __future__ import annotations

import logging

from app.ai.anthropic import AnthropicProvider
from app.ai.base import AIProvider, AIProviderError
from app.ai.gemini import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from app.ai.gemini import GeminiProvider
from app.ai.heuristic import HeuristicProvider
from app.ai.openai_compatible import OpenAICompatibleProvider
from app.config import Settings

logger = logging.getLogger(__name__)

OPENAI_COMPATIBLE_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "xai": ("https://api.x.ai/v1", "grok-3-mini"),
    "together": ("https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "openrouter": ("https://openrouter.ai/api/v1", "google/gemini-2.5-flash"),
    "ollama": ("http://localhost:11434/v1", "llama3.2"),
}

NO_KEY_PROVIDERS = {"ollama"}


def ai_is_configured(settings: Settings) -> bool:
    provider = settings.normalized_ai_provider
    if provider in {"heuristic", "none", "off", ""}:
        return True
    if provider in NO_KEY_PROVIDERS:
        return True
    return bool(settings.ai_api_key)


def build_ai_provider(settings: Settings) -> AIProvider:
    provider = settings.normalized_ai_provider

    if provider in {"heuristic", "none", "off", ""}:
        return HeuristicProvider()

    missing_key = provider not in NO_KEY_PROVIDERS and not settings.ai_api_key
    if missing_key:
        message = f"AI_API_KEY is not set for {provider}; the deterministic engine will be used."
        if not settings.ai_fallback_to_heuristic:
            raise AIProviderError(message)
        logger.warning(message)
        return HeuristicProvider(reason=message)

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        default_url, default_model = OPENAI_COMPATIBLE_PROVIDERS[provider]
        return OpenAICompatibleProvider(
            name=provider,
            base_url=settings.ai_base_url or default_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model or default_model,
            timeout_seconds=settings.ai_timeout_seconds,
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_output_tokens,
            json_mode=settings.ai_json_mode,
        )

    if provider == "custom":
        if not settings.ai_base_url:
            message = "AI_BASE_URL is required for the custom provider; the deterministic engine will be used."
            if not settings.ai_fallback_to_heuristic:
                raise AIProviderError(message)
            logger.warning(message)
            return HeuristicProvider(reason=message)
        return OpenAICompatibleProvider(
            name="custom",
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model or "default",
            timeout_seconds=settings.ai_timeout_seconds,
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_output_tokens,
            json_mode=settings.ai_json_mode,
        )

    if provider == "gemini":
        return GeminiProvider(
            api_key=settings.ai_api_key or "",
            model=settings.ai_model or GEMINI_DEFAULT_MODEL,
            base_url=settings.ai_base_url or "https://generativelanguage.googleapis.com/v1beta",
            timeout_seconds=settings.ai_timeout_seconds,
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_output_tokens,
        )

    if provider == "anthropic":
        return AnthropicProvider(
            api_key=settings.ai_api_key or "",
            model=settings.ai_model or "claude-sonnet-4-5",
            base_url=settings.ai_base_url or "https://api.anthropic.com/v1",
            timeout_seconds=settings.ai_timeout_seconds,
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_output_tokens,
        )

    message = f"Unknown AI_PROVIDER '{provider}'; the deterministic engine will be used."
    if not settings.ai_fallback_to_heuristic:
        raise AIProviderError(message)
    logger.warning(message)
    return HeuristicProvider(reason=message)
