r"""Canlı AI sağlayıcı kontrolü (sunucu ve NASA çağrısı gerekmez).

``.env`` içindeki ``AI_*`` ayarlarıyla sağlayıcıyı kurar, temsili bir
"ne ekeyim?" bağlamı üretir ve gerçek bir istek atar. Amaç: API anahtarının,
model adının ve JSON doğrulama zincirinin uçtan uca çalıştığını 5 saniyede
görmek.

Kullanım::

    .\.venv\Scripts\python.exe scripts\ai_check.py
    .\.venv\Scripts\python.exe scripts\ai_check.py --model gemini-3.5-flash-lite
    .\.venv\Scripts\python.exe scripts\ai_check.py --provider heuristic

Çıkış kodu: 0 = gerçek AI cevabı alındı, 1 = anahtar yok / çağrı başarısız /
deterministik geri dönüş kullanıldı.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Betik "scripts/" içinden çalıştırıldığı için proje kökünü import yoluna ekle.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.base import AdviceContext  # noqa: E402
from app.ai.factory import build_ai_provider  # noqa: E402
from app.ai.heuristic import HeuristicProvider  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402

SAMPLE_FREE_TEXT = (
    "Edirne'de 20 dönüm tarlam var, 2 dönümü sulanabiliyor. Ne ekeceğimi bilmiyorum. "
    "Bitkiyi nasıl büyüteceğimi, nasıl besleyeceğimi ve nasıl bakacağımı da bilmiyorum."
)


def build_context(language: str = "tr") -> AdviceContext:
    """Kural motorunun gerçek çıktısına benzeyen küçük, sabit bir bağlam."""

    return AdviceContext(
        language=language,
        location={
            "latitude": 41.6771,
            "longitude": 26.5557,
            "region_name": "Edirne",
        },
        farmer={
            "field": {
                "area_hectares": 2.0,
                "soil_texture": "clay_loam",
                "soil_ph": 6.8,
                "organic_matter_pct": 1.6,
            },
            "resources": {"irrigation": "limited", "water_availability": "medium"},
            "preferences": {"goal": "max_profit", "planting_month": 10},
        },
        environment={
            "climate": {
                "annual_mean_temp_c": 13.65,
                "annual_precip_mm": 613.0,
                "climate_class": "semi_arid",
                "aridity_index": 0.42,
                "growing_season_days": 275,
            },
            "frost_months": [1, 2, 3, 11, 12],
            "heat_months": [7, 8],
            "soil_moisture": {"root_zone_mean": 0.31, "top_layer_mean": 0.28},
        },
        candidates=[
            {
                "crop_key": "winter_wheat",
                "local_name": "Kışlık Buğday",
                "rule_score": 92.0,
                "why": "Kışı soğuk geçen, 600 mm civarı yağış alan tarlaya uyar.",
                "limiting_factors": ["Kurak ilkbaharda sulama gerekebilir."],
            },
            {
                "crop_key": "barley",
                "local_name": "Arpa",
                "rule_score": 91.2,
                "why": "Buğdaya göre kuraklığa daha dayanıklı.",
                "limiting_factors": ["Verim buğdaydan düşük olabilir."],
            },
            {
                "crop_key": "sunflower",
                "local_name": "Ayçiçeği",
                "rule_score": 78.4,
                "why": "İlkbahar ekimine ve sınırlı sulamaya uyar.",
                "limiting_factors": ["Çiçeklenmede su stresi verimi düşürür."],
            },
        ],
        free_text=SAMPLE_FREE_TEXT,
        data_quality=[
            "NASA POWER verisi 0.5-1 derece ızgaradır; tarla ölçeğinde değildir.",
            "Toprak pH ve organik madde çiftçi beyanıdır, ölçülmemiştir.",
        ],
    )


def _print_plan(plan) -> None:
    print(f"\nBaşlık: {plan.headline}")
    print(f"Gerekçe: {plan.why}")
    for title, items in (
        ("İlk adımlar", plan.steps),
        ("Nasıl büyütülür", plan.grow),
        ("Nasıl beslenir", plan.feed),
        ("Nasıl bakılır", plan.care),
        ("Riskler", plan.risks),
        ("Çiftçiye sorulacaklar", plan.ask_farmer),
    ):
        if not items:
            continue
        print(f"\n{title}:")
        for item in items:
            print(f"  - {item}")
    print(f"\nGüven: {plan.confidence}")


async def _run(settings: Settings, language: str) -> int:
    provider = build_ai_provider(settings)
    name = getattr(provider, "name", "unknown")
    model = getattr(provider, "model", None)
    print(f"Sağlayıcı : {name}")
    print(f"Model     : {model or '-'}")
    print(f"Anahtar   : {'tanımlı' if settings.ai_api_key else 'YOK'}")

    if isinstance(provider, HeuristicProvider):
        print("\nAI devrede değil; deterministik motor kullanılıyor.")
        if provider.reason:
            print(f"Sebep: {provider.reason}")
        print("İpucu: .env içinde AI_PROVIDER=gemini ve AI_API_KEY=... olmalı.")
        return 1

    context = build_context(language)
    started = time.perf_counter()
    try:
        plan = await provider.advise(context)
    except Exception as exc:  # noqa: BLE001 - CLI diagnostics
        elapsed = time.perf_counter() - started
        print(f"\nHATA ({elapsed:.1f} sn): {exc}")
        return 1
    finally:
        close = getattr(provider, "aclose", None)
        if callable(close):
            await close()

    elapsed = time.perf_counter() - started
    print(f"Gecikme   : {elapsed:.2f} sn")
    _print_plan(plan)

    if not plan.headline:
        print("\nUYARI: başlık boş döndü; model JSON şemasına tam uymamış olabilir.")
        return 1
    print("\nOK: gerçek AI cevabı alındı ve doğrulamadan geçti.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Project Alphecca canlı AI kontrolü")
    parser.add_argument("--provider", help="AI_PROVIDER değerini geçici olarak değiştir")
    parser.add_argument("--model", help="AI_MODEL değerini geçici olarak değiştir")
    parser.add_argument("--language", default="tr", choices=["tr", "en"])
    args = parser.parse_args()

    settings = get_settings()
    if args.provider:
        settings.ai_provider = args.provider
    if args.model:
        settings.ai_model = args.model

    return asyncio.run(_run(settings, args.language))


if __name__ == "__main__":
    sys.exit(main())
