"""Shared fixtures and NASA-shaped payload builders for tests."""

from __future__ import annotations

import json
from datetime import date, timedelta

from app.clients.nasa_power import NASAAPIError, NASAResult, parse_nasa_payload, TTLCache

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

# Approximate Ankara climatology, close to the real NASA POWER response.
T2M = {
    "JAN": -2.08, "FEB": 0.31, "MAR": 4.18, "APR": 8.86, "MAY": 14.17, "JUN": 18.58,
    "JUL": 22.23, "AUG": 22.52, "SEP": 17.96, "OCT": 11.88, "NOV": 5.11, "DEC": -0.05,
    "ANN": 10.35,
}
T2M_MAX = {
    "JAN": 13.76, "FEB": 18.49, "MAR": 23.16, "APR": 26.35, "MAY": 32.01, "JUN": 35.69,
    "JUL": 39.35, "AUG": 38.22, "SEP": 37.04, "OCT": 30.13, "NOV": 23.73, "DEC": 16.67,
    "ANN": 39.35,
}
T2M_MIN = {
    "JAN": -22.45, "FEB": -20.24, "MAR": -13.89, "APR": -7.23, "MAY": -2.6, "JUN": 4.04,
    "JUL": 7.3, "AUG": 7.16, "SEP": 1.77, "OCT": -5.62, "NOV": -10.97, "DEC": -16.78,
    "ANN": -22.45,
}
PRECIP = {
    "JAN": 1.6, "FEB": 1.28, "MAR": 1.34, "APR": 1.3, "MAY": 1.66, "JUN": 1.48,
    "JUL": 0.42, "AUG": 0.44, "SEP": 0.64, "OCT": 1.05, "NOV": 1.05, "DEC": 1.5, "ANN": 1.15,
}
RH = {
    "JAN": 87.49, "FEB": 80.55, "MAR": 73.21, "APR": 67.17, "MAY": 64.2, "JUN": 59.12,
    "JUL": 49.25, "AUG": 46.73, "SEP": 51.27, "OCT": 62.81, "NOV": 72.81, "DEC": 83.8, "ANN": 66.47,
}
SOLAR = {
    "JAN": 6.98, "FEB": 10.43, "MAR": 14.93, "APR": 19.6, "MAY": 23.27, "JUN": 26.46,
    "JUL": 27.57, "AUG": 24.55, "SEP": 19.53, "OCT": 13.38, "NOV": 9.14, "DEC": 6.21, "ANN": 16.87,
}
WIND = {
    "JAN": 2.19, "FEB": 2.45, "MAR": 2.51, "APR": 2.18, "MAY": 1.95, "JUN": 2.01,
    "JUL": 2.34, "AUG": 2.35, "SEP": 2.11, "OCT": 2.02, "NOV": 1.91, "DEC": 1.95, "ANN": 2.16,
}
SOIL_MOISTURE = {
    "JAN": 0.61, "FEB": 0.65, "MAR": 0.66, "APR": 0.63, "MAY": 0.58, "JUN": 0.53,
    "JUL": 0.48, "AUG": 0.46, "SEP": 0.47, "OCT": 0.48, "NOV": 0.51, "DEC": 0.55, "ANN": 0.55,
}
TOPSOIL = {
    "JAN": 0.62, "FEB": 0.67, "MAR": 0.68, "APR": 0.64, "MAY": 0.58, "JUN": 0.51,
    "JUL": 0.36, "AUG": 0.27, "SEP": 0.29, "OCT": 0.4, "NOV": 0.49, "DEC": 0.55, "ANN": 0.51,
}
SOIL_TEMP = {
    "JAN": -2.78, "FEB": -0.06, "MAR": 4.3, "APR": 9.25, "MAY": 14.95, "JUN": 19.96,
    "JUL": 24.41, "AUG": 24.8, "SEP": 19.4, "OCT": 12.05, "NOV": 4.24, "DEC": -0.82, "ANN": 10.86,
}


def climatology_payload() -> dict:
    parameters = {
        "T2M": T2M,
        "T2M_MAX": T2M_MAX,
        "T2M_MIN": T2M_MIN,
        "PRECTOTCORR": PRECIP,
        "RH2M": RH,
        "ALLSKY_SFC_SW_DWN": SOLAR,
        "WS2M": WIND,
        "GWETROOT": SOIL_MOISTURE,
        "GWETTOP": TOPSOIL,
        "TS": SOIL_TEMP,
        "EVLAND": {**{m: 1.07 for m in MONTHS}, "ANN": 1.07},
        "EVPTRNS": {**{m: 0.38 for m in MONTHS}, "ANN": 0.38},
    }
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [32.85, 39.93, 1128.1]},
        "properties": {"parameter": parameters},
        "header": {
            "title": "NASA/POWER Source Native Resolution Climatology",
            "api": {"version": "v2.10.1", "name": "POWER Climatology API"},
            "sources": ["MERRA2", "POWER"],
            "fill_value": -999.0,
        },
        "messages": ["test fixture"],
    }


def daily_payload(end: date | None = None) -> dict:
    end = end or date(2026, 11, 14)
    dates = [end - timedelta(days=offset) for offset in range(29, -1, -1)]
    t2m = {}
    tmax = {}
    tmin = {}
    precip = {}
    moisture = {}
    for index, day in enumerate(dates):
        key = day.strftime("%Y%m%d")
        if index >= 27:
            t2m[key] = -999.0
            tmax[key] = -999.0
            tmin[key] = -999.0
            precip[key] = -999.0
            moisture[key] = -999.0
            continue
        value = 8.0 + (index % 10) * 0.8
        t2m[key] = round(value, 2)
        tmax[key] = round(value + 8.0, 2)
        tmin[key] = round(value - 6.0, 2)
        precip[key] = 5.0 if index in {2, 3, 4, 15} else 0.0
        moisture[key] = round(0.4 + (index % 5) * 0.03, 3)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [32.85, 39.93, 1128.1]},
        "properties": {
            "parameter": {
                "T2M": t2m,
                "T2M_MAX": tmax,
                "T2M_MIN": tmin,
                "PRECTOTCORR": precip,
                "RH2M": {key: 60.0 for key in t2m},
                "GWETROOT": moisture,
                "GWETTOP": {key: min(1.0, value + 0.05) if value >= 0 else -999.0 for key, value in moisture.items()},
            }
        },
        "header": {"fill_value": -999.0, "title": "POWER Daily", "api": {"version": "v2.10.1"}},
    }


class FakeNASA:
    """Drop-in stand-in for NASAPowerClient used by API tests."""

    def __init__(self, climatology: dict | None = None, daily: dict | None = None, error: str | None = None):
        self.climatology = climatology or climatology_payload()
        self.daily = daily or daily_payload()
        self.error = error
        self.cache = TTLCache(0)
        self.calls = 0

    async def get_climatology(self, latitude: float, longitude: float, **kwargs) -> NASAResult:
        self.calls += 1
        if self.error:
            raise NASAAPIError(self.error)
        return parse_nasa_payload(self.climatology)

    async def get_daily(self, latitude: float, longitude: float, **kwargs) -> NASAResult:
        if self.error:
            raise NASAAPIError(self.error)
        return parse_nasa_payload(self.daily)

    async def aclose(self) -> None:
        return None


def request_payload(**overrides) -> dict:
    payload = {
        "location": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
        "field": {
            "area_hectares": 12.5,
            "soil_texture": "clay_loam",
            "soil_ph": 7.4,
            "organic_matter_pct": 1.8,
        },
        "resources": {"irrigation": "limited", "water_availability": "medium", "budget_usd": 6000},
        "preferences": {
            "goal": "max_profit",
            "crops_of_interest": ["wheat", "chickpea"],
            "planting_month": 10,
            "market_access": "medium",
        },
        "top_n": 3,
        "language": "tr",
    }
    payload.update(overrides)
    return payload


def ai_json_response(**overrides) -> dict:
    payload = {
        "summary": "Test özeti.",
        "crops": [
            {
                "crop_key": "wheat",
                "ai_score": 90,
                "rationale": "Buğday uygundur.",
                "risks": ["Kuraklık"],
                "actions": ["Sulama planı"],
                "planting_window": "Ekim–Kasım",
            }
        ],
        "general_risks": ["Fiyat dalgalanması"],
        "general_actions": ["Toprak analizi"],
        "confidence": "medium",
        "notes": "Test",
    }
    payload.update(overrides)
    return payload


def completion_response(content: dict | str) -> dict:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}
