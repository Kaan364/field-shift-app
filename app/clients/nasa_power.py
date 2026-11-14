"""NASA POWER API client.

Documentation: https://power.larc.nasa.gov/docs/services/api/

The client fetches:
* monthly climatology (25-year baseline) for climate and soil-moisture proxies;
* recent daily values (last N days) for a short-term context.

NASA returns ``-999.0`` for missing values; those are normalised to ``None``.
A small in-process TTL cache avoids hammering the public API.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CLIMATOLOGY_PARAMETERS = (
    "T2M",
    "T2M_MAX",
    "T2M_MIN",
    "PRECTOTCORR",
    "RH2M",
    "ALLSKY_SFC_SW_DWN",
    "WS2M",
    "GWETROOT",
    "GWETTOP",
    "TS",
    "EVLAND",
    "EVPTRNS",
)

DAILY_PARAMETERS = (
    "T2M",
    "T2M_MIN",
    "T2M_MAX",
    "PRECTOTCORR",
    "RH2M",
    "GWETROOT",
    "GWETTOP",
)


class NASAAPIError(RuntimeError):
    """Raised when NASA POWER cannot provide usable data."""


class _TransientNASAError(RuntimeError):
    pass


@dataclass(frozen=True)
class NASAResult:
    latitude: float
    longitude: float
    elevation_m: float | None
    parameters: dict[str, dict[str, float | None]]
    fill_value: float = -999.0
    source_title: str = ""
    api_version: str | None = None
    sources: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    start: str | None = None
    end: str | None = None


class TTLCache:
    """Tiny thread-safe-enough TTL cache for a single process."""

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = max(0, ttl_seconds)
        self._store: dict[str, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            self.misses += 1
            return None
        expires_at, value = item
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = self.ttl_seconds if ttl_seconds is None else max(0, ttl_seconds)
        if ttl == 0:
            return
        self._store[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        self._purge_expired()
        return len(self._store)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires_at, _) in self._store.items() if now >= expires_at]
        for key in expired:
            self._store.pop(key, None)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def parse_nasa_payload(
    payload: dict[str, Any],
    *,
    start: str | None = None,
    end: str | None = None,
) -> NASAResult:
    """Convert a raw NASA POWER JSON response into a typed result."""

    try:
        coordinates = payload["geometry"]["coordinates"]
        parameters_raw = payload["properties"]["parameter"]
    except (KeyError, TypeError) as exc:  # pragma: no cover - defensive
        raise NASAAPIError("NASA POWER yanıtı beklenen biçimde değil.") from exc

    header = payload.get("header", {}) or {}
    fill_value = _to_float(header.get("fill_value"))
    if fill_value is None:
        fill_value = -999.0

    parameters: dict[str, dict[str, float | None]] = {}
    for parameter, series in parameters_raw.items():
        if not isinstance(series, dict):
            continue
        cleaned: dict[str, float | None] = {}
        for key, value in series.items():
            number = _to_float(value)
            cleaned[key] = None if number is None or number == fill_value else number
        parameters[parameter] = cleaned

    elevation = None
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 3:
        elevation = _to_float(coordinates[2])
        if elevation is not None and elevation <= -999:
            elevation = None

    api_meta = header.get("api", {}) or {}
    return NASAResult(
        latitude=float(coordinates[1]),
        longitude=float(coordinates[0]),
        elevation_m=elevation,
        parameters=parameters,
        fill_value=fill_value,
        source_title=str(header.get("title", "")),
        api_version=api_meta.get("version"),
        sources=list(header.get("sources", []) or []),
        messages=list(payload.get("messages", []) or []),
        start=start,
        end=end,
    )


class NASAPowerClient:
    def __init__(
        self,
        base_url: str = "https://power.larc.nasa.gov/api/temporal",
        *,
        community: str = "AG",
        timeout_seconds: float = 30.0,
        cache_ttl_seconds: int = 3600,
        daily_cache_ttl_seconds: int = 1800,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.75,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.community = community
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.cache = TTLCache(cache_ttl_seconds)
        self.daily_cache_ttl_seconds = daily_cache_ttl_seconds
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={
                "User-Agent": "Project-Alphecca/0.1 (agricultural decision support)",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_climatology(
        self,
        latitude: float,
        longitude: float,
        *,
        parameters: tuple[str, ...] = CLIMATOLOGY_PARAMETERS,
    ) -> NASAResult:
        key = f"clim:{latitude:.3f}:{longitude:.3f}:{self.community}:{','.join(parameters)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        result = await self._request(
            "climatology/point",
            latitude=latitude,
            longitude=longitude,
            parameters=parameters,
        )
        self.cache.set(key, result)
        return result

    async def get_daily(
        self,
        latitude: float,
        longitude: float,
        *,
        days: int = 30,
        parameters: tuple[str, ...] = DAILY_PARAMETERS,
        end_date: date | None = None,
    ) -> NASAResult:
        days = max(1, min(days, 366))
        end = end_date or date.today()
        start = end - timedelta(days=days - 1)
        start_text = start.strftime("%Y%m%d")
        end_text = end.strftime("%Y%m%d")
        key = (
            f"daily:{latitude:.3f}:{longitude:.3f}:{start_text}:{end_text}:"
            f"{self.community}:{','.join(parameters)}"
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        result = await self._request(
            "daily/point",
            latitude=latitude,
            longitude=longitude,
            parameters=parameters,
            start=start_text,
            end=end_text,
        )
        result = NASAResult(
            latitude=result.latitude,
            longitude=result.longitude,
            elevation_m=result.elevation_m,
            parameters=result.parameters,
            fill_value=result.fill_value,
            source_title=result.source_title,
            api_version=result.api_version,
            sources=result.sources,
            messages=result.messages,
            start=start_text,
            end=end_text,
        )
        self.cache.set(key, result, ttl_seconds=self.daily_cache_ttl_seconds)
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _request(self, path: str, **params: Any) -> NASAResult:
        url = f"{self.base_url}/{path.lstrip('/')}"
        query: dict[str, Any] = {
            "parameters": ",".join(params.pop("parameters")),
            "community": self.community,
            "latitude": round(float(params.pop("latitude")), 4),
            "longitude": round(float(params.pop("longitude")), 4),
            "format": "JSON",
        }
        query.update(params)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(url, params=query)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise _TransientNASAError(
                        f"NASA POWER geçici hata döndürdü (HTTP {response.status_code})."
                    )
                if response.status_code >= 400:
                    detail = response.text[:300].replace("\n", " ")
                    raise NASAAPIError(
                        f"NASA POWER isteği başarısız (HTTP {response.status_code}): {detail}"
                    )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise NASAAPIError("NASA POWER geçerli JSON döndürmedi.") from exc
                return parse_nasa_payload(payload)
            except (_TransientNASAError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self.retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "NASA POWER isteği yeniden denenecek (%s/%s): %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                if delay > 0:
                    await asyncio.sleep(delay)

        raise NASAAPIError(
            "NASA POWER servisine ulaşılamadı. İnternet bağlantısını kontrol edip "
            "birkaç dakika sonra tekrar deneyin."
        ) from last_error
