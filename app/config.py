"""Application configuration.

All settings are read from environment variables (and an optional ``.env``
file). The defaults are deliberately safe: the app runs without any API key,
using the deterministic agronomy engine.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ------------------------------------------------------
    app_name: str = "Project Alphecca API"
    app_version: str = "0.2.0"
    environment: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    ui_base_url: str = "/app/"
    log_level: str = "INFO"
    cors_origins: str = "*"

    # --- NASA POWER -------------------------------------------------------
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api/temporal"
    nasa_power_community: str = "AG"
    nasa_power_timeout_seconds: float = Field(30.0, gt=0)
    nasa_power_cache_ttl_seconds: int = Field(3600, ge=0)
    nasa_power_daily_cache_ttl_seconds: int = Field(1800, ge=0)
    nasa_power_max_retries: int = Field(2, ge=0, le=5)
    nasa_power_retry_backoff_seconds: float = Field(0.75, ge=0)

    # --- Coğrafi kodlama (harita / yer adı) -------------------------------
    geocoding_enabled: bool = True
    geocoding_base_url: str = "https://nominatim.openstreetmap.org"
    geocoding_timeout_seconds: float = Field(8.0, gt=0)
    geocoding_cache_ttl_seconds: int = Field(86_400, ge=0)
    geocoding_user_agent: str = "ProjectAlphecca/0.1 (agricultural decision support)"
    geocoding_language: str = "en"

    # --- AI ---------------------------------------------------------------
    ai_provider: str = "heuristic"
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_base_url: str | None = None
    ai_timeout_seconds: float = Field(45.0, gt=0)
    ai_temperature: float = Field(0.2, ge=0, le=2)
    ai_max_output_tokens: int = Field(1600, ge=256, le=8192)
    ai_weight: float = Field(0.35, ge=0, le=1)
    ai_blend_with_heuristic: bool = True
    ai_fallback_to_heuristic: bool = True
    ai_json_mode: bool = True
    max_ai_candidates: int = Field(8, ge=1, le=16)

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw in {"", "*"}:
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def normalized_ai_provider(self) -> str:
        return (self.ai_provider or "heuristic").strip().lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
