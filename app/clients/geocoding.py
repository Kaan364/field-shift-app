"""Reverse geocoding (koordinat -> yer adı) via OpenStreetMap Nominatim.

Harita API'si olarak Nominatim seçildi çünkü:
- API anahtarı gerektirmez (öğrenci/demo projesi için uygun),
- OpenStreetMap verisi küresel kapsama sahiptir,
- Türkçe yer adları ``accept-language=tr`` ile alınabilir.

Kullanım koşulları: istek başına tanımlayıcı bir User-Agent zorunludur ve
saniyede 1 isteği geçmemek gerekir. Bu yüzden sonuçlar TTL'li önbelleğe alınır.
"""

from __future__ import annotations

import time

import httpx

from app.schemas import GeocodeResponse


class NominatimClient:
    def __init__(
        self,
        *,
        base_url: str = "https://nominatim.openstreetmap.org",
        timeout_seconds: float = 8.0,
        cache_ttl_seconds: int = 86_400,
        user_agent: str = "ProjectAlphecca/0.1 (agricultural decision support)",
        language: str = "tr",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.language = language
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
        )
        self._cache: dict[tuple[float, float], tuple[float, GeocodeResponse]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def reverse(self, latitude: float, longitude: float) -> GeocodeResponse:
        key = (round(latitude, 3), round(longitude, 3))
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        params = {
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "format": "jsonv2",
            "zoom": 12,
            "addressdetails": 1,
            "accept-language": self.language,
        }
        try:
            response = await self._client.get(f"{self.base_url}/reverse", params=params)
        except httpx.HTTPError as exc:
            return GeocodeResponse(
                found=False,
                latitude=latitude,
                longitude=longitude,
                error=f"Could not reach the address service: {type(exc).__name__}",
            )

        if response.status_code >= 400:
            return GeocodeResponse(
                found=False,
                latitude=latitude,
                longitude=longitude,
                error=f"The address service returned HTTP {response.status_code}.",
            )

        try:
            data = response.json()
        except ValueError:
            return GeocodeResponse(
                found=False,
                latitude=latitude,
                longitude=longitude,
                error="The address service returned invalid JSON.",
            )

        address = data.get("address") or {}
        result = GeocodeResponse(
            found=bool(data.get("display_name") or address),
            latitude=latitude,
            longitude=longitude,
            display_name=_short_display_name(data.get("display_name")),
            city=address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("province"),
            district=address.get("suburb")
            or address.get("district")
            or address.get("county")
            or address.get("village"),
            region=address.get("state") or address.get("region"),
            country=address.get("country"),
        )
        self._cache[key] = (now, result)
        return result

    def cache_size(self) -> int:
        return len(self._cache)


def _short_display_name(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return ", ".join(parts[:3])
