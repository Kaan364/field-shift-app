r"""Live smoke check against a running Project Alphecca API.

Usage (server already running on port 8000):

    .\.venv\Scripts\python.exe scripts\live_check.py --lat 39.93 --lon 32.85 --region Ankara

The script makes one real NASA POWER call through the API.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Project Alphecca canlı API kontrolü")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--lat", type=float, default=39.93)
    parser.add_argument("--lon", type=float, default=32.85)
    parser.add_argument("--region", default="Ankara")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()

    payload = {
        "location": {
            "latitude": args.lat,
            "longitude": args.lon,
            "region_name": args.region,
        },
        "field": {
            "area_hectares": 10,
            "soil_texture": "clay_loam",
            "soil_ph": 7.4,
            "organic_matter_pct": 1.8,
        },
        "resources": {
            "irrigation": "limited",
            "water_availability": "medium",
            "budget_usd": 5000,
        },
        "preferences": {
            "goal": "max_profit",
            "planting_month": 10,
            "market_access": "medium",
        },
        "top_n": args.top_n,
        "language": "tr",
    }

    base = args.base_url.rstrip("/")
    try:
        with httpx.Client(timeout=120) as client:
            health = client.get(f"{base}/health")
            health.raise_for_status()
            print("Health:", json.dumps(health.json(), ensure_ascii=False, indent=2))

            response = client.post(f"{base}/api/v1/analyze", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        print(f"API isteği başarısız: {exc}", file=sys.stderr)
        return 1

    climate = data["environment"]["climate"]
    print("\n--- İklim ---")
    print(
        f"{args.region}: {climate['annual_mean_temp_c']} °C, "
        f"{climate['annual_precip_mm']} mm/yıl, "
        f"sınıf={climate['climate_class']}, "
        f"aridity={climate['aridity_index']}"
    )
    print("\n--- Öneriler ---")
    for item in data["recommendations"]:
        print(
            f"{item['rank']}. {item['crop_name_local']} "
            f"(kural={item['scores']['rule_score']}, "
            f"AI={item['scores']['ai_score']}, "
            f"final={item['scores']['final_score']}, "
            f"güven={item['confidence']})"
        )
    print("\n--- Özet ---")
    print(data["summary"])
    if data["warnings"]:
        print("\n--- Uyarılar ---")
        for warning in data["warnings"]:
            print("-", warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
