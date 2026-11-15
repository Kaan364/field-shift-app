"""FastAPI application factory and system endpoints."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from json import dumps as json_dumps
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.ai.base import AIProviderError
from app.ai.factory import ai_is_configured, build_ai_provider
from app.api.routes import router
from app.clients.geocoding import NominatimClient
from app.clients.nasa_power import NASAAPIError, NASAPowerClient
from app.config import Settings, get_settings
from app.logging_conf import configure_logging
from app.schemas import AnalyzeRequest, ApiInfo, HealthResponse
from app.services.advice import AdviceService
from app.services.farm_plan import FarmPlanService
from app.services.recommendation import AnalysisError, RecommendationService

logger = logging.getLogger(__name__)

_UNSET = object()

GEO_PAGE = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Konumumu bul</title>
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0;
         min-height: 100vh; display: flex; align-items: center; justify-content: center;
         background: #f3f7f1; color: #1c2b1a; }
  main { background: #fff; padding: 28px 22px; border-radius: 16px; max-width: 420px;
         width: 92%; box-shadow: 0 10px 30px rgba(0,0,0,.08); text-align: center; }
  h1 { font-size: 1.35rem; margin: 0 0 10px; }
  p { font-size: 1rem; line-height: 1.5; color: #44503f; }
  button { width: 100%; padding: 16px; font-size: 1.1rem; font-weight: 600;
           border: 0; border-radius: 12px; background: #2f7d32; color: #fff; cursor: pointer; }
  button:active { transform: translateY(1px); }
  #msg { min-height: 1.4em; margin-top: 14px; font-size: .95rem; color: #8a5a00; }
  .hint { font-size: .85rem; color: #6b7565; margin-top: 16px; }
</style>
</head>
<body>
<main>
  <h1>📍 Tarlanın konumunu bul</h1>
  <p>Aşağıdaki düğmeye bas. Tarayıcı izin isterse <strong>İzin ver</strong> seç.</p>
  <button id="go" type="button">Konumumu kullan</button>
  <div id="msg"></div>
  <p class="hint">Konumun yalnızca bu cihazda, öneri hesaplamak için kullanılır. Sunucuda saklanmaz.</p>
</main>
<script>
  const target = __TARGET__;
  const msg = document.getElementById('msg');
  const go = document.getElementById('go');
  go.addEventListener('click', function () {
    if (!navigator.geolocation) {
      msg.textContent = 'Tarayıcın konum özelliğini desteklemiyor. Enlem/boylamı elle girebilirsin.';
      return;
    }
    msg.textContent = 'Konum isteniyor...';
    navigator.geolocation.getCurrentPosition(function (pos) {
      const lat = pos.coords.latitude.toFixed(5);
      const lon = pos.coords.longitude.toFixed(5);
      const sep = target.indexOf('?') === -1 ? '?' : '&';
      window.location.replace(target + sep + 'lat=' + lat + '&lon=' + lon);
    }, function (err) {
      msg.textContent = 'Konum alınamadı (' + err.message + '). Tarayıcı ayarlarından konum iznini aç.';
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  });
</script>
</body>
</html>
"""


def _example_request() -> dict:
    extra = AnalyzeRequest.model_config.get("json_schema_extra") or {}
    return extra.get("example", {})


def create_app(
    settings: Settings | None = None,
    *,
    nasa_client: NASAPowerClient | None = None,
    ai_provider=None,
    geocoder=_UNSET,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    nasa = nasa_client or NASAPowerClient(
        base_url=settings.nasa_power_base_url,
        community=settings.nasa_power_community,
        timeout_seconds=settings.nasa_power_timeout_seconds,
        cache_ttl_seconds=settings.nasa_power_cache_ttl_seconds,
        daily_cache_ttl_seconds=settings.nasa_power_daily_cache_ttl_seconds,
        max_retries=settings.nasa_power_max_retries,
        retry_backoff_seconds=settings.nasa_power_retry_backoff_seconds,
    )
    ai = ai_provider or build_ai_provider(settings)
    recommender = RecommendationService(nasa, ai, settings)
    advice_service = AdviceService(recommender, nasa, ai, settings)
    farm_plan_service = FarmPlanService(recommender, advice_service, nasa, settings)
    if geocoder is not _UNSET:
        geocoder_client = geocoder
    elif settings.geocoding_enabled:
        geocoder_client = NominatimClient(
            base_url=settings.geocoding_base_url,
            timeout_seconds=settings.geocoding_timeout_seconds,
            cache_ttl_seconds=settings.geocoding_cache_ttl_seconds,
            user_agent=settings.geocoding_user_agent,
            language=settings.geocoding_language,
        )
    else:
        geocoder_client = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        for client in (nasa, ai, geocoder_client):
            close = getattr(client, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 - shutdown must not fail
                    logger.warning("İstemci kapatılırken hata oluştu.", exc_info=True)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "NASA POWER verileri + açıklanabilir agronomi kuralları + değiştirilebilir LLM "
            "katmanı ile çiftçiler için karar destek API'si. Telefon uyumlu çiftçi arayüzü "
            "`/app/` altında, Swagger bu adreste: `/docs`."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    web_dir = Path(__file__).resolve().parent.parent / "web"
    index_file = web_dir / "index.html"

    app.state.settings = settings
    app.state.nasa = nasa
    app.state.ai = ai
    app.state.recommender = recommender
    app.state.advice = advice_service
    app.state.farm_plan = farm_plan_service
    app.state.geocoder = geocoder_client

    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = (request.headers.get("X-Request-ID") or uuid4().hex)[:64]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        logger.info(
            "%s %s -> %s (%s ms, request_id=%s)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response

    @app.exception_handler(NASAAPIError)
    async def nasa_error_handler(request: Request, exc: NASAAPIError):
        logger.warning("NASA POWER hatası: %s", exc)
        return JSONResponse(
            status_code=502,
            content={
                "error": "nasa_power_unavailable",
                "message": str(exc),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(AnalysisError)
    async def analysis_error_handler(request: Request, exc: AnalysisError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": str(exc),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(AIProviderError)
    async def ai_error_handler(request: Request, exc: AIProviderError):
        return JSONResponse(
            status_code=503,
            content={
                "error": "ai_unavailable",
                "message": str(exc),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.get("/", response_model=ApiInfo, tags=["system"])
    async def root(request: Request):
        """Serve the mobile farmer app to browsers, JSON to API clients.

        Opening the deployed URL on a phone shows the farmer interface; API
        clients that send ``Accept: application/json`` keep getting the
        machine-readable service description (and the test suite relies on it).
        """

        accept = request.headers.get("accept", "")
        if index_file.exists() and "text/html" in accept.lower():
            return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
        return ApiInfo(
            name=settings.app_name,
            version=settings.app_version,
            description=(
                "Çiftçiler için NASA POWER destekli, AI ile zenginleştirilmiş karar destek API'si."
            ),
            docs_url="/docs",
            openapi_url="/openapi.json",
            endpoints={
                "farmer_app": "GET /app/",
                "farm_plan": "POST /api/v1/farm-plan",
                "rotation": "POST /api/v1/rotation",
                "soil_health": "POST /api/v1/soil-health",
                "water_plan": "POST /api/v1/water-plan",
                "analyze": "POST /api/v1/analyze",
                "advice": "POST /api/v1/advice",
                "environment": "GET /api/v1/environment",
                "reverse_geocode": "GET /api/v1/reverse-geocode",
                "crops": "GET /api/v1/crops",
                "ai_providers": "GET /api/v1/ai-providers",
                "health": "GET /health",
                "geolocation_page": "GET /geo?next=/app/",
            },
            example_request=_example_request(),
        )

    @app.get("/geo", response_class=HTMLResponse, include_in_schema=False)
    async def geo(next: str = "") -> HTMLResponse:
        """Tarayıcıdan konum izni isteyen küçük sayfa.

        İzin verilirse ``?lat=..&lon=..`` ile arayüze geri döner. Arayüz bu iki
        parametreyi okuyup haritayı ve formu otomatik doldurur.
        """

        target = (next or settings.ui_base_url).strip()
        parsed = urlparse(target)
        absolute = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        if not absolute and not target.startswith("/"):
            target = settings.ui_base_url
            if not target.startswith("/"):
                parsed = urlparse(target)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    target = "/app/"
        return HTMLResponse(GEO_PAGE.replace("__TARGET__", json_dumps(target)))

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    @app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        cache = getattr(nasa, "cache", None)
        return HealthResponse(
            status="ok",
            version=settings.app_version,
            environment=settings.environment,
            ai_provider=getattr(ai, "name", "unknown"),
            ai_configured=ai_is_configured(settings),
            geocoding_enabled=geocoder_client is not None,
            nasa_power_base_url=settings.nasa_power_base_url,
            cache_entries=len(cache) if cache is not None and hasattr(cache, "__len__") else None,
            timestamp=datetime.now(timezone.utc),
        )

    app.include_router(router)

    if web_dir.exists():
        app.mount("/app", StaticFiles(directory=str(web_dir), html=True), name="farmer-web")

    return app


app = create_app()
