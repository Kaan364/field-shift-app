"""Project Alphecca - farmer-first test interface.

Design principles:
1. **Simple flow first.** The farmer picks the field on the map, answers 3-4
   questions and can describe the problem in their own words. The result is
   shown in short, plain sentences.
2. **Details are optional.** Advanced information such as climate, soil and
   score breakdown opens only when "Show details" is ticked.
3. **No business logic here.** Everything lives in the FastAPI backend; this
   file only sends HTTP requests and renders the answer.
4. **Expert mode is preserved.** The "Expert / test mode" section at the bottom
   lets you try every endpoint by hand.

Run::

    python run_ui.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
import streamlit as st

DEFAULT_API_URL = os.getenv("ALPHECCA_API_URL", "http://127.0.0.1:8000")
DEFAULT_UI_URL = os.getenv("ALPHECCA_UI_URL", "http://127.0.0.1:8501")

# ---------------------------------------------------------------------------
# Dictionaries (label -> API value)
# ---------------------------------------------------------------------------
SOIL_TEXTURES = [
    ("unknown", "I don't know"),
    ("sand", "Sand"),
    ("loamy_sand", "Loamy sand"),
    ("sandy_loam", "Sandy loam"),
    ("loam", "Loam"),
    ("silt_loam", "Silt loam"),
    ("silt", "Silt"),
    ("clay_loam", "Clay loam"),
    ("sandy_clay_loam", "Sandy clay loam"),
    ("clay", "Clay"),
]
DRAINAGE = [("poor", "Poor"), ("medium", "Medium"), ("good", "Good")]
IRRIGATION = [("rainfed", "Rainfed only"), ("limited", "Limited irrigation"), ("full", "Full irrigation")]
SIMPLE_IRRIGATION = [
    ("rainfed", "No, rainfed only"),
    ("limited", "Sometimes / partially"),
    ("full", "Yes, I can irrigate fully"),
]
WATER = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
LABOR = [("family", "Family labour"), ("hired", "Hired"), ("mixed", "Mixed"), ("scarce", "Scarce")]
MECHANIZATION = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
MARKET = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
GOALS = [
    ("max_profit", "Maximum profit"),
    ("max_yield", "Maximum yield"),
    ("low_water", "Low water use"),
    ("low_input", "Low input"),
    ("organic", "Organic production"),
    ("soil_health", "Soil health"),
    ("risk_averse", "Risk-averse"),
]
SIMPLE_GOALS = [
    ("max_profit", "I want to earn more money"),
    ("max_yield", "I want a bigger harvest"),
    ("low_input", "I want to spend less"),
    ("low_water", "I have little water, so something that needs little water"),
    ("risk_averse", "I don't want to take risks, I want something safe"),
]
MONTHS = [
    "I don't know", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
CLIMATE_LABELS = {
    "hyper_arid": "hyper-arid",
    "arid": "arid",
    "semi_arid": "semi-arid",
    "dry_sub_humid": "dry sub-humid",
    "humid": "humid",
    "per_humid": "per-humid",
    "unknown": "unknown",
}
COMPONENT_LABELS = {
    "temperature": "Temperature fit",
    "water": "Water balance",
    "ph": "pH fit",
    "texture": "Soil texture",
    "salinity": "Salinity",
    "climate_risk": "Climate risk (frost/heat)",
    "goal_fit": "Goal fit",
    "market": "Market access",
    "calendar": "Planting calendar",
}
PRESETS: dict[str, tuple[float, float, str]] = {
    "Edirne (Thrace)": (41.6771, 26.5557, "Edirne"),
    "Tekirdağ (Thrace)": (40.9781, 27.5117, "Tekirdağ"),
    "Kırklareli (Thrace)": (41.7333, 27.2167, "Kırklareli"),
    "Ankara": (39.9334, 32.8597, "Ankara"),
    "İzmir": (38.4237, 27.1428, "İzmir"),
    "Konya": (37.8746, 32.4932, "Konya"),
    "Şanlıurfa": (37.1591, 38.7969, "Şanlıurfa"),
    "Antalya": (36.8969, 30.7133, "Antalya"),
}
FALLBACK_CROPS = [
    ("wheat", "Winter wheat"),
    ("barley", "Barley"),
    ("maize", "Maize"),
    ("sunflower", "Sunflower"),
    ("chickpea", "Chickpea"),
    ("lentil", "Lentil"),
    ("potato", "Potato"),
    ("tomato", "Tomato (field)"),
    ("cotton", "Cotton"),
    ("soybean", "Soybean"),
    ("canola", "Canola"),
    ("sugar_beet", "Sugar beet"),
    ("alfalfa", "Alfalfa"),
    ("olive", "Olive"),
    ("grape", "Grape (vineyard)"),
    ("apple", "Apple"),
]
EXAMPLE_TEXT = (
    "My field is in Edirne. I do not know what to plant. "
    "I also do not know how to grow, feed or care for a crop. "
    "Can you explain it to me simply?"
)

DEFAULTS: dict[str, Any] = {
    # Simple flow
    "s_lat": 41.6771,
    "s_lon": 26.5557,
    "s_place": "Edirne",
    "s_area_donum": 20.0,
    "s_irrigation": "limited",
    "s_goal": "max_profit",
    "s_month": 10,
    "s_texture": "clay_loam",
    "s_ph": 7.0,
    "s_om": 2.2,
    "s_text": "",
    "s_detail": False,
    # Expert flow
    "in_lat": 41.6771,
    "in_lon": 26.5557,
    "in_region": "Edirne",
    "f_area": 20.0,
    "f_texture": "clay_loam",
    "f_ph": 7.0,
    "f_om": 2.2,
    "f_salinity": 0.0,
    "f_depth": 0.0,
    "f_drainage": "medium",
    "f_slope": 0.0,
    "f_prev": "",
    "r_irrigation": "limited",
    "r_water": "medium",
    "r_budget": 10000.0,
    "r_labor": "family",
    "r_mech": "medium",
    "r_organic": False,
    "p_goal": "max_profit",
    "p_interest": [],
    "p_excluded": [],
    "p_month": 10,
    "p_market": "medium",
    "p_maxdays": 0,
    "o_top_n": 5,
    "o_lang": "en",
    "e_lat": 39.9334,
    "e_lon": 32.8597,
    "e_region": "Ankara",
    "e_days": 30,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _init_state() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)
    st.session_state.setdefault("api_base", DEFAULT_API_URL)


def api_call(
    method: str,
    base_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: Any | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Call the backend; always return the result as a dictionary."""

    url = f"{base_url.rstrip('/')}{path}"
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, params=params, json=payload)
        elapsed = int((time.perf_counter() - started) * 1000)
        try:
            data = response.json()
        except ValueError:
            data = {"raw_text": response.text[:4000]}
        return {
            "ok": response.is_success,
            "status": response.status_code,
            "data": data,
            "ms": elapsed,
            "error": None if response.is_success else _error_message(response.status_code, data),
            "url": url,
        }
    except httpx.HTTPError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "status": None,
            "data": None,
            "ms": elapsed,
            "error": f"{type(exc).__name__}: {exc}",
            "url": url,
        }


def _error_message(status: int, data: Any) -> str:
    if isinstance(data, dict):
        detail = data.get("message") or data.get("detail") or data.get("error")
        if detail:
            return f"HTTP {status}: {detail}"
    return f"HTTP {status}"


def _fill_example_text() -> None:
    """Fill the example text.

    The ``on_click`` callback runs *before* widgets are created, so the
    ``s_text`` key can safely be changed here.
    """

    st.session_state["s_text"] = EXAMPLE_TEXT


def _reset_coordinates() -> None:
    latitude, longitude, region = PRESETS["Edirne (Thrace)"]
    sync_all_coordinates(latitude, longitude, region)


def _use_preset(name: str) -> None:
    latitude, longitude, region = PRESETS[name]
    sync_all_coordinates(latitude, longitude, region)
    st.session_state["s_place"] = region


@st.cache_data(ttl=600, show_spinner=False)
def load_crops(base_url: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=25.0) as client:
        response = client.get(f"{base_url.rstrip('/')}/api/v1/crops")
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=600, show_spinner=False)
def load_providers(base_url: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=25.0) as client:
        response = client.get(f"{base_url.rstrip('/')}/api/v1/ai-providers")
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=3600, show_spinner=False)
def lookup_place(base_url: str, latitude: float, longitude: float) -> str:
    """Turn coordinates into a readable place name; return "" on failure."""

    result = api_call(
        "GET",
        base_url,
        "/api/v1/reverse-geocode",
        params={"latitude": latitude, "longitude": longitude},
        timeout=12.0,
    )
    if not result["ok"]:
        return ""
    data = result["data"] or {}
    if not data.get("found"):
        return ""
    parts = [
        data.get("district"),
        data.get("city") or data.get("region"),
        data.get("country"),
    ]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen[:3])


def fmt(value: Any, suffix: str = "", digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def label_of(options: list[tuple[str, str]], value: str) -> str:
    for key, label in options:
        if key == value:
            return label
    return value


def crop_label_map() -> dict[str, str]:
    try:
        crops = load_crops(st.session_state["api_base"])
        return {crop["key"]: crop.get("name") or crop["local_name"] for crop in crops}
    except Exception:  # noqa: BLE001 - the interface must not crash
        return dict(FALLBACK_CROPS)


def sync_all_coordinates(latitude: float, longitude: float, place: str | None = None) -> None:
    st.session_state.update(
        {
            "s_lat": latitude,
            "s_lon": longitude,
            "in_lat": latitude,
            "in_lon": longitude,
            "e_lat": latitude,
            "e_lon": longitude,
        }
    )
    if place:
        st.session_state["s_place"] = place
        st.session_state["in_region"] = place
        st.session_state["e_region"] = place


def ui_origin() -> str:
    """Browser address of the interface (used to return from the location page)."""

    try:
        host = st.context.headers.get("host")
    except Exception:  # noqa: BLE001 - may be missing in test/headless environments
        host = None
    if host:
        return f"http://{host}"
    return DEFAULT_UI_URL


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def render_parcel_map(base_url: str) -> None:
    latitude = float(st.session_state["s_lat"])
    longitude = float(st.session_state["s_lon"])

    try:
        import folium
        from streamlit_folium import st_folium
    except ImportError:
        st.info(
            "The map component is not installed. To install it: "
            "`pip install -r requirements-ui.txt` · You can also enter latitude/longitude manually below."
        )
        return

    map_object = folium.Map(
        location=[latitude, longitude],
        zoom_start=9,
        control_scale=True,
        tiles="OpenStreetMap",
    )
    folium.Marker(
        [latitude, longitude],
        tooltip="Your selected point",
        popup="Your field is here",
    ).add_to(map_object)
    folium.Circle(
        [latitude, longitude],
        radius=1200,
        color="#2f7d32",
        weight=2,
        fill=True,
        fill_opacity=0.12,
    ).add_to(map_object)

    clicked = st_folium(
        map_object,
        height=340,
        use_container_width=True,
        returned_objects=["last_clicked"],
        key="parcel_map",
        # If not set explicitly, Streamlit rebinds the component on every rerun
        # and the map jumps back to the world view (zoom 3).
        center=(latitude, longitude),
        zoom=9,
    )

    last_clicked = (clicked or {}).get("last_clicked") if isinstance(clicked, dict) else None
    if last_clicked and last_clicked.get("lat") is not None:
        new_lat = round(float(last_clicked["lat"]), 5)
        new_lon = round(float(last_clicked["lng"]), 5)
        if abs(new_lat - latitude) > 1e-9 or abs(new_lon - longitude) > 1e-9:
            sync_all_coordinates(new_lat, new_lon)
            st.session_state["s_place"] = ""
            st.rerun()

    place = lookup_place(base_url, latitude, longitude)
    if place:
        if place != st.session_state.get("s_place"):
            st.session_state["s_place"] = place
        st.caption(f"📍 Selected place: **{place}** · {latitude:.4f}, {longitude:.4f}")
    else:
        st.caption(f"📍 Selected point: **{latitude:.4f}, {longitude:.4f}**")
    st.caption("Tap your field on the map; the point moves there.")


# ---------------------------------------------------------------------------
# Shared detail blocks
# ---------------------------------------------------------------------------
def render_environment(environment: dict[str, Any]) -> None:
    climate = environment.get("climate") or {}
    soil = environment.get("soil") or {}
    recent = environment.get("recent_weather") or {}

    st.markdown("##### 🌦️ Climate summary (NASA POWER, 2001-2025 average)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Annual rainfall", fmt(climate.get("annual_precip_mm"), " mm", 1))
    c2.metric("Mean temperature", fmt(climate.get("annual_mean_temp_c"), " °C", 2))
    c3.metric(
        "Climate class",
        CLIMATE_LABELS.get(climate.get("climate_class") or "", climate.get("climate_class") or "—"),
    )
    c4.metric("Growing season", fmt(climate.get("growing_season_days"), " days", 0))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Annual ET0", fmt(climate.get("annual_evapotranspiration_mm"), " mm", 0))
    c6.metric("Aridity index", fmt(climate.get("aridity_index"), "", 2))
    c7.metric("Frost months", str(len(climate.get("frost_months") or [])))
    c8.metric("Heat-stress months", str(len(climate.get("heat_stress_months") or [])))

    if climate.get("frost_months"):
        st.caption("🧊 Months with frost: " + ", ".join(climate["frost_months"]))
    if climate.get("heat_stress_months"):
        st.caption("🔥 Heat-stress months: " + ", ".join(climate["heat_stress_months"]))
    if climate.get("growing_season_mean_temp_c") is not None:
        st.caption(
            f"Growing-season mean temperature: {fmt(climate.get('growing_season_mean_temp_c'), ' °C')}"
        )

    st.markdown("##### 🧱 Soil")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("NASA root-zone moisture", fmt(soil.get("root_zone_moisture_mean"), "", 3))
    s2.metric("Surface moisture", fmt(soil.get("topsoil_moisture_mean"), "", 3))
    s3.metric("Soil temperature", fmt(soil.get("mean_soil_temp_c"), " °C", 1))
    s4.metric(
        "Soil condition",
        f"{fmt(soil.get('soil_condition_score'), '', 0)} / 100",
        help=soil.get("soil_condition_label") or None,
    )
    st.caption(
        "Farmer input → texture: "
        f"{label_of(SOIL_TEXTURES, soil.get('soil_texture') or 'unknown')}, "
        f"pH: {fmt(soil.get('soil_ph'), '', 1)}, "
        f"organic matter: {fmt(soil.get('organic_matter_pct'), ' %', 1)}, "
        f"salinity: {fmt(soil.get('salinity_ds_m'), ' dS/m', 2)}, "
        f"drainage: {label_of(DRAINAGE, soil.get('drainage') or 'medium')}"
    )
    if soil.get("data_gaps"):
        st.warning("Data gaps: " + " · ".join(soil["data_gaps"]))

    if recent:
        st.markdown("##### 🌡️ Observed weather of recent days (not a forecast)")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric(
            "Window",
            fmt(recent.get("window_days"), " days", 0),
            help=f"Available days: {recent.get('available_days')}",
        )
        r2.metric("Total rainfall", fmt(recent.get("total_precip_mm"), " mm", 1))
        r3.metric("Mean temperature", fmt(recent.get("mean_temp_c"), " °C", 2))
        r4.metric("Longest dry spell", fmt(recent.get("longest_dry_spell_days"), " days", 0))

    monthly = environment.get("monthly") or []
    if monthly:
        st.markdown("##### 📅 Monthly distribution")
        rows = []
        for item in monthly:
            rows.append(
                {
                    "Month": item.get("month"),
                    "Mean °C": item.get("mean_temp_c"),
                    "Min °C": item.get("min_temp_c"),
                    "Max °C": item.get("max_temp_c"),
                    "Rainfall (mm)": item.get("precip_month_mm"),
                    "Humidity (%)": item.get("relative_humidity_pct"),
                    "Solar (kWh/m²/day)": item.get("solar_kwh_m2_day"),
                    "ET0 (mm/day)": item.get("evapotranspiration_mm_per_day"),
                    "Root moisture": item.get("root_zone_moisture"),
                    "Soil °C": item.get("soil_temp_c"),
                    "Frost": "🧊" if item.get("frost_risk") else "",
                    "Heat stress": "🔥" if item.get("heat_stress") else "",
                }
            )
        frame = pd.DataFrame(rows)
        st.dataframe(frame, width="stretch", hide_index=True)

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.caption("Temperature curve (°C)")
            st.line_chart(frame.set_index("Month")[["Mean °C", "Min °C", "Max °C"]], height=260)
        with chart_col2:
            st.caption("Monthly rainfall (mm)")
            st.bar_chart(frame.set_index("Month")[["Rainfall (mm)"]], height=260)

    if environment.get("notes"):
        with st.expander("ℹ️ Data notes"):
            for note in environment["notes"]:
                st.markdown(f"- {note}")


def render_score_table(recommendations: list[dict[str, Any]]) -> None:
    if not recommendations:
        return
    table = pd.DataFrame(
        [
            {
                "#": item.get("rank"),
                "Crop": item.get("crop_name") or item.get("crop_name_local"),
                "Score": item.get("scores", {}).get("final_score"),
                "Rule": item.get("scores", {}).get("rule_score"),
                "AI": item.get("scores", {}).get("ai_score"),
                "Confidence": item.get("confidence"),
                "Planting window": item.get("planting_window"),
                "Days": item.get("growing_days"),
                "Water (mm)": item.get("water_need_mm"),
            }
            for item in recommendations
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)

    for item in recommendations:
        components = item.get("scores", {}).get("components") or {}
        with st.expander(
            f"{item.get('rank')}. {item.get('crop_name') or item.get('crop_name_local')} — "
            f"score {fmt(item.get('scores', {}).get('rule_score'), '', 1)}"
        ):
            st.markdown(f"**Rationale:** {item.get('rationale') or '—'}")
            if item.get("risks"):
                st.markdown("**Risks**")
                for risk in item["risks"]:
                    st.markdown(f"- ⚠️ {risk}")
            if item.get("actions"):
                st.markdown("**Actions**")
                for action in item["actions"]:
                    st.markdown(f"- ✅ {action}")
            if components:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Component": COMPONENT_LABELS.get(key, key), "Score": value}
                            for key, value in components.items()
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )


def bullets(title: str, items: list[str], icon: str = "•") -> None:
    if not items:
        return
    st.markdown(f"#### {title}")
    for item in items:
        st.markdown(f"{icon} {item}")


# ---------------------------------------------------------------------------
# Simple result screen
# ---------------------------------------------------------------------------
def render_simple_result(result: dict[str, Any], base_url: str) -> None:
    if not result["ok"]:
        st.error("Could not get a recommendation. Check your internet connection and location, then try again.")
        with st.expander("Technical detail"):
            st.code(result.get("error") or "unknown error")
            st.json(result.get("data") or {})
        return

    data = result["data"]
    advice = data.get("advice") or {}
    recommendations = data.get("recommendations") or []
    ai = data.get("ai") or {}

    st.success(f"Recommendation ready · {result['ms']} ms")

    st.markdown(f"## 🌾 {advice.get('headline') or data.get('summary')}")
    if advice.get("why"):
        st.markdown(advice["why"])

    if recommendations:
        columns = st.columns(len(recommendations))
        for column, rec in zip(columns, recommendations):
            column.metric(
                rec.get("crop_name") or rec.get("crop_name_local"),
                f"{fmt(rec.get('scores', {}).get('rule_score'), '', 0)} / 100",
                help="This score was calculated from the regional climate, your soil and your preferences.",
            )

    if ai.get("kind") == "llm" and ai.get("used") and not ai.get("fallback_used"):
        if ai.get("blended"):
            st.caption(
                f"This explanation blends AI ({ai.get('provider')} / {ai.get('model') or '—'}) "
                "with the deterministic rule engine. The ranking is set by the rule engine."
            )
        else:
            st.caption(
                f"This explanation was written by AI ({ai.get('provider')} / {ai.get('model') or '—'}). "
                "The ranking was set by the rule engine."
            )
    else:
        st.caption(
            "This explanation was written by the rule engine (no AI key configured). "
            "Results still rely on NASA data and agronomic rules."
        )

    bullets("✅ First things to do", advice.get("steps") or [], "**•**")
    bullets("🌱 How do I grow it?", advice.get("grow") or [], "•")
    bullets("🧪 How do I feed it?", advice.get("feed") or [], "•")
    bullets("💧 How do I care for it?", advice.get("care") or [], "•")
    bullets("⚠️ Watch out", advice.get("risks") or [], "•")

    if advice.get("ask_farmer"):
        st.info(
            "To give you better advice, it would help me to know:\n\n"
            + "\n".join(f"- {question}" for question in advice["ask_farmer"])
        )

    detail = st.checkbox(
        "🔍 Show details (climate, soil, scores)",
        key="s_detail",
        help="Shows the region's rainfall, temperature, soil moisture and the score breakdown if you want.",
    )
    if detail:
        environment = data.get("environment") or {}
        if environment:
            render_environment(environment)
        st.markdown("### 📊 Score table and rationales")
        render_score_table(recommendations)
        if data.get("warnings"):
            st.markdown("### ⚠️ Warnings")
            for warning in data["warnings"]:
                st.markdown(f"- {warning}")
        if data.get("data_sources"):
            with st.expander("📚 Data sources"):
                for source in data["data_sources"]:
                    st.markdown(f"- **{source.get('name')}**: {source.get('description')}")
        with st.expander("🧾 Raw API response (developer)"):
            st.json(data)

    if data.get("disclaimer"):
        st.caption(data["disclaimer"])


# ---------------------------------------------------------------------------
# Legacy (detailed) analysis view — used in expert mode
# ---------------------------------------------------------------------------
def render_analysis(result: dict[str, Any]) -> None:
    ai = result.get("ai") or {}
    st.markdown("### 📊 Analysis result")
    st.info(result.get("summary") or "No summary.")

    if ai.get("kind") == "deterministic":
        st.warning(
            "The AI layer is **not active**: recommendations come only from the deterministic rule engine. "
            f"(Provider: `{ai.get('provider')}`"
            + (f" · note: {ai.get('notes')}" if ai.get("notes") else "")
            + ")"
        )
    else:
        detail = (
            f"Provider: `{ai.get('provider')}`"
            f" · model: `{ai.get('model') or '—'}`"
            f" · used: {'yes' if ai.get('used') else 'no'}"
            f" · fallback: {'yes' if ai.get('fallback_used') else 'no'}"
            f" · blended: {'yes' if ai.get('blended') else 'no'}"
            f" · latency: {fmt(ai.get('latency_ms'), ' ms', 0)}"
        )
        if ai.get("error"):
            st.warning(f"The AI response could not be obtained; the deterministic result was used. {detail}\n\nError: {ai['error']}")
        else:
            st.success(detail)

    st.caption(
        "Final score = rule-engine weight + AI weight (default 65% / 35%). "
        "The AI score only balances the rule score; it cannot decide on its own."
    )

    recommendations = result.get("recommendations") or []
    top = recommendations[0] if recommendations else None
    if top:
        st.markdown("#### 🏆 Top recommendation")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Crop", top.get("crop_name") or top.get("crop_name_local"))
        t2.metric("Final score", fmt(top.get("scores", {}).get("final_score"), " / 100", 1))
        t3.metric(
            "Rule / AI",
            f"{fmt(top.get('scores', {}).get('rule_score'), '', 1)} / "
            f"{fmt(top.get('scores', {}).get('ai_score'), '', 1)}",
        )
        t4.metric("Confidence", str(top.get("confidence") or "—"))

    render_score_table(recommendations)

    environment = result.get("environment") or {}
    if environment:
        with st.expander("🌦️ Environment data used (NASA POWER)", expanded=False):
            render_environment(environment)

    if result.get("warnings"):
        st.markdown("#### ⚠️ Warnings")
        for warning in result["warnings"]:
            st.markdown(f"- {warning}")
    if result.get("general_risks"):
        st.markdown("#### 🚧 General risks")
        for risk in result["general_risks"]:
            st.markdown(f"- {risk}")
    if result.get("general_actions"):
        st.markdown("#### 🗺️ General action plan")
        for action in result["general_actions"]:
            st.markdown(f"- {action}")
    if result.get("data_sources"):
        with st.expander("📚 Data sources"):
            for source in result["data_sources"]:
                st.markdown(f"- **{source.get('name')}**: {source.get('description')}")
    if result.get("disclaimer"):
        st.caption(result["disclaimer"])
    st.caption(
        f"Analysis ID: `{result.get('analysis_id')}` · generated: {result.get('generated_at')}"
    )


def json_download(data: dict[str, Any], name: str) -> None:
    st.download_button(
        "⬇️ Download raw JSON",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name=name,
        mime="application/json",
        width="stretch",
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.set_page_config(page_title="What should I plant? · Project Alphecca", page_icon="🌱", layout="wide")
_init_state()

# Read the ?lat=..&lon=.. parameters returned by the browser location prompt once.
incoming = st.query_params
if "lat" in incoming and "lon" in incoming:
    try:
        incoming_lat = float(incoming["lat"])
        incoming_lon = float(incoming["lon"])
    except (TypeError, ValueError):
        incoming_lat = incoming_lon = None
    if incoming_lat is not None and incoming_lon is not None:
        sync_all_coordinates(round(incoming_lat, 5), round(incoming_lon, 5))
        st.session_state["s_place"] = ""
        st.session_state["geo_received"] = True
    st.query_params.clear()

st.title("🌱 What should I plant?")
st.caption(
    "Pick your field on the map and answer a few questions. We prepare a simple recommendation "
    "for you based on NASA satellite data and agronomic rules."
)

# --- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Connection")
    base_url = st.text_input("API address", key="api_base").rstrip("/")

    health = api_call("GET", base_url, "/health", timeout=10.0)
    if health["ok"]:
        info = health["data"]
        st.success(f"Connected · v{info.get('version')}")
        provider_label = str(info.get("ai_provider") or "unknown")
        if provider_label == "heuristic":
            ai_state = "none — the rule engine writes the explanation"
        elif info.get("ai_configured"):
            ai_state = "available"
        else:
            ai_state = "none (no key configured)"
        st.caption(f"AI: **{provider_label}** · key: {ai_state}")
        st.caption(f"Cache: {info.get('cache_entries')} · latency: {health['ms']} ms")
    else:
        st.error("Cannot reach the API")
        st.caption(health["error"] or "Unknown error")
        st.code("python run_ui.py", language="powershell")
        st.caption("Run this command in the project folder to start the backend.")

    st.divider()
    st.header("📍 Preset locations")
    preset_name = st.selectbox("Choose a region", list(PRESETS), key="preset_pick")
    st.button(
        "Use this region",
        width="stretch",
        on_click=_use_preset,
        args=(preset_name,),
    )

    st.divider()
    st.header("🔗 Links")
    st.markdown(f"- [Swagger /docs]({base_url}/docs)")
    st.markdown(f"- [Health check]({base_url}/health)")
    with st.expander("ℹ️ What does this interface test?"):
        st.markdown(
            "- `POST /api/v1/advice` — free text + plain-language advice\n"
            "- `POST /api/v1/analyze` — full scoring pipeline\n"
            "- `GET /api/v1/environment` — NASA environment data\n"
            "- `GET /api/v1/reverse-geocode` — coordinates → place name\n"
            "- `GET /api/v1/crops`, `/api/v1/ai-providers`\n"
            "- `GET /health`, `GET /` and the free-form console"
        )

# ---------------------------------------------------------------------------
# 1) FARMER FLOW
# ---------------------------------------------------------------------------
st.markdown("### 1️⃣ Where is your field?")
render_parcel_map(base_url)

location_col1, location_col2 = st.columns([2, 1])
with location_col1:
    st.link_button(
        "📍 Find my location automatically (browser permission)",
        f"{base_url}/geo?next={ui_origin()}",
        width="stretch",
        help="Asks for browser location permission. If you allow it, the map moves to your location.",
    )
with location_col2:
    st.button(
        "🧭 Return to centre",
        width="stretch",
        help="Return the map to the default region",
        on_click=_reset_coordinates,
    )

with st.expander("⌨️ I want to enter the location manually"):
    manual_col1, manual_col2, manual_col3 = st.columns(3)
    with manual_col1:
        st.number_input(
            "Latitude", min_value=-90.0, max_value=90.0, step=0.0001,
            format="%.4f", key="s_lat",
        )
    with manual_col2:
        st.number_input(
            "Longitude", min_value=-180.0, max_value=180.0, step=0.0001,
            format="%.4f", key="s_lon",
        )
    with manual_col3:
        st.text_input("Place name (optional)", key="s_place", max_chars=120)

st.markdown("### 2️⃣ A few questions about your field")
q1, q2 = st.columns(2)
with q1:
    st.number_input(
        "How many decares is your field? (1 decare ≈ 0.1 hectare)",
        min_value=0.0,
        max_value=1_000_000.0,
        step=1.0,
        key="s_area_donum",
        help="You can leave it at 0 if you don't know.",
    )
with q2:
    st.selectbox(
        "Can you irrigate?",
        [key for key, _ in SIMPLE_IRRIGATION],
        format_func=lambda value: label_of(SIMPLE_IRRIGATION, value),
        key="s_irrigation",
    )

q3, q4 = st.columns(2)
with q3:
    st.selectbox(
        "What do you want?",
        [key for key, _ in SIMPLE_GOALS],
        format_func=lambda value: label_of(SIMPLE_GOALS, value),
        key="s_goal",
    )
with q4:
    st.selectbox(
        "When are you thinking of planting?",
        list(range(0, 13)),
        format_func=lambda value: MONTHS[value],
        key="s_month",
    )

with st.expander("🪴 Do you know your soil? (leave blank if you don't)"):
    soil_col1, soil_col2, soil_col3 = st.columns(3)
    with soil_col1:
        st.selectbox(
            "Soil texture",
            [key for key, _ in SOIL_TEXTURES],
            format_func=lambda value: label_of(SOIL_TEXTURES, value),
            key="s_texture",
        )
    with soil_col2:
        st.number_input(
            "Soil pH (0 = don't know)", min_value=0.0, max_value=10.0, step=0.1, key="s_ph"
        )
    with soil_col3:
        st.number_input(
            "Organic matter % (0 = don't know)", min_value=0.0, max_value=30.0, step=0.1, key="s_om"
        )

st.markdown("### 3️⃣ Tell us in your own words (optional)")
st.caption(
    "Write it however you like. You don't have to write anything; the questions above are enough."
)
text_col1, text_col2 = st.columns([3, 1])
with text_col1:
    free_text = st.text_area(
        "Describe your situation",
        key="s_text",
        height=110,
        placeholder=(
            "Example: My field is in Edirne. I don't know what to plant. "
            "I don't know how to grow or feed the crop."
        ),
        label_visibility="collapsed",
    )
with text_col2:
    st.button(
        "📝 Fill in the example text",
        width="stretch",
        on_click=_fill_example_text,
        help="Writes the example sentence into the box; you can then edit it.",
    )

st.markdown("")
submit_col, clear_col = st.columns([3, 1])
with submit_col:
    run_advice = st.button(
        "🌾 Tell me what to plant",
        type="primary",
        width="stretch",
    )
with clear_col:
    if st.button("🧹 Clear", width="stretch"):
        st.session_state.pop("s_result", None)
        st.session_state.pop("analysis", None)
        st.rerun()

if run_advice:
    if not health["ok"]:
        st.error("Cannot reach the server. Run `python run_ui.py` first.")
    else:
        area_hectares = (
            float(st.session_state["s_area_donum"]) / 10.0
            if float(st.session_state["s_area_donum"]) > 0
            else None
        )
        payload: dict[str, Any] = {
            "location": {
                "latitude": float(st.session_state["s_lat"]),
                "longitude": float(st.session_state["s_lon"]),
                "region_name": (st.session_state.get("s_place") or "").strip() or None,
            },
            "irrigation": st.session_state["s_irrigation"],
            "water_availability": (
                "low" if st.session_state["s_irrigation"] == "rainfed"
                else "high" if st.session_state["s_irrigation"] == "full"
                else "medium"
            ),
            "goal": st.session_state["s_goal"],
            "soil_texture": st.session_state["s_texture"],
            "free_text": free_text.strip(),
            "top_n": 3,
            "language": "en",
        }
        if area_hectares:
            payload["area_hectares"] = area_hectares
        if float(st.session_state["s_ph"]) > 0:
            payload["soil_ph"] = float(st.session_state["s_ph"])
        if float(st.session_state["s_om"]) > 0:
            payload["organic_matter_pct"] = float(st.session_state["s_om"])
        if int(st.session_state["s_month"]) > 0:
            payload["planting_month"] = int(st.session_state["s_month"])

        with st.spinner("Fetching your field's weather and soil data... (3-10 seconds the first time)"):
            response = api_call("POST", base_url, "/api/v1/advice", payload=payload, timeout=240.0)
        st.session_state["s_result"] = response
        st.session_state["s_payload"] = payload

simple_result = st.session_state.get("s_result")
if simple_result:
    st.divider()
    render_simple_result(simple_result, base_url)
    if simple_result.get("ok"):
        with st.expander("🧾 Submitted information"):
            st.json(st.session_state.get("s_payload", {}))

# ---------------------------------------------------------------------------
# 2) EXPERT / TEST MODE
# ---------------------------------------------------------------------------
st.divider()
with st.expander("🧑‍🌾 Expert / test mode — all API functions", expanded=False):
    st.caption(
        "This section is for developers and agronomists. Raw scores, every parameter and "
        "the free-form API console are here."
    )
    crops_map = crop_label_map()
    tab_analyze, tab_env, tab_crops, tab_ai, tab_system = st.tabs(
        [
            "🌱 Analysis",
            "🌦️ Environment data",
            "🌾 Crop catalogue",
            "🤖 AI providers",
            "🩺 System & console",
        ]
    )

    # =====================================================================
    # Analysis
    # =====================================================================
    with tab_analyze:
        with st.form("analyze_form"):
            st.markdown("#### 1️⃣ Location")
            loc1, loc2, loc3 = st.columns(3)
            with loc1:
                st.number_input(
                    "Latitude", min_value=-90.0, max_value=90.0,
                    step=0.0001, format="%.4f", key="in_lat",
                )
            with loc2:
                st.number_input(
                    "Longitude", min_value=-180.0, max_value=180.0,
                    step=0.0001, format="%.4f", key="in_lon",
                )
            with loc3:
                st.text_input("Region name (label)", key="in_region", max_chars=120)

            st.markdown("#### 2️⃣ Field / soil")
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                st.number_input(
                    "Area (hectares)", min_value=0.1, max_value=1_000_000.0,
                    step=1.0, key="f_area",
                )
            with f2:
                st.selectbox(
                    "Soil texture", [key for key, _ in SOIL_TEXTURES],
                    format_func=lambda value: label_of(SOIL_TEXTURES, value), key="f_texture",
                )
            with f3:
                st.number_input(
                    "Soil pH (0 = unknown)", min_value=0.0, max_value=10.0,
                    step=0.1, key="f_ph",
                )
            with f4:
                st.number_input(
                    "Organic matter % (0 = unknown)", min_value=0.0, max_value=30.0,
                    step=0.1, key="f_om",
                )

            f5, f6, f7, f8 = st.columns(4)
            with f5:
                st.number_input(
                    "Salinity dS/m (0 = unknown)", min_value=0.0, max_value=40.0,
                    step=0.1, key="f_salinity",
                )
            with f6:
                st.number_input(
                    "Soil depth cm (0 = unknown)", min_value=0.0, max_value=300.0,
                    step=5.0, key="f_depth",
                )
            with f7:
                st.selectbox(
                    "Drainage", [key for key, _ in DRAINAGE],
                    format_func=lambda value: label_of(DRAINAGE, value), key="f_drainage",
                )
            with f8:
                st.number_input(
                    "Slope % (0 = unknown)", min_value=0.0, max_value=80.0,
                    step=1.0, key="f_slope",
                )

            st.text_input(
                "Previous crop (optional)", key="f_prev", max_chars=80, placeholder="e.g. wheat"
            )

            st.markdown("#### 3️⃣ Resources")
            r1, r2, r3 = st.columns(3)
            with r1:
                st.selectbox(
                    "Irrigation", [key for key, _ in IRRIGATION],
                    format_func=lambda value: label_of(IRRIGATION, value), key="r_irrigation",
                )
            with r2:
                st.selectbox(
                    "Water availability", [key for key, _ in WATER],
                    format_func=lambda value: label_of(WATER, value), key="r_water",
                )
            with r3:
                st.number_input(
                    "Budget USD (0 = unknown)", min_value=0.0, max_value=100_000_000.0,
                    step=500.0, key="r_budget",
                )

            r4, r5, r6 = st.columns(3)
            with r4:
                st.selectbox(
                    "Labour", [key for key, _ in LABOR],
                    format_func=lambda value: label_of(LABOR, value), key="r_labor",
                )
            with r5:
                st.selectbox(
                    "Mechanisation", [key for key, _ in MECHANIZATION],
                    format_func=lambda value: label_of(MECHANIZATION, value), key="r_mech",
                )
            with r6:
                st.checkbox("Organically certified", key="r_organic")

            st.markdown("#### 4️⃣ Preferences")
            p1, p2, p3 = st.columns(3)
            with p1:
                st.selectbox(
                    "Goal", [key for key, _ in GOALS],
                    format_func=lambda value: label_of(GOALS, value), key="p_goal",
                )
            with p2:
                st.selectbox(
                    "Planting month", list(range(0, 13)),
                    format_func=lambda value: MONTHS[value], key="p_month",
                )
            with p3:
                st.selectbox(
                    "Market access", [key for key, _ in MARKET],
                    format_func=lambda value: label_of(MARKET, value), key="p_market",
                )

            p4, p5 = st.columns(2)
            with p4:
                st.multiselect(
                    "Crops of interest", options=list(crops_map),
                    format_func=lambda key: crops_map.get(key, key), key="p_interest",
                )
            with p5:
                st.multiselect(
                    "Excluded crops", options=list(crops_map),
                    format_func=lambda key: crops_map.get(key, key), key="p_excluded",
                )

            o1, o2, o3 = st.columns(3)
            with o1:
                st.slider("How many recommendations to show", min_value=1, max_value=8, key="o_top_n")
            with o2:
                st.radio("Language", options=["en", "tr"], horizontal=True, key="o_lang")
            with o3:
                st.number_input(
                    "Max. growing period (days, 0 = unlimited)",
                    min_value=0, max_value=400, step=10, key="p_maxdays",
                )

            submitted = st.form_submit_button("🚀 Analyse", type="primary", width="stretch")

        if submitted:
            field: dict[str, Any] = {
                "area_hectares": float(st.session_state["f_area"]),
                "soil_texture": st.session_state["f_texture"],
                "drainage": st.session_state["f_drainage"],
            }
            optional_field = {
                "soil_ph": st.session_state["f_ph"],
                "organic_matter_pct": st.session_state["f_om"],
                "salinity_ds_m": st.session_state["f_salinity"],
                "soil_depth_cm": st.session_state["f_depth"],
                "slope_pct": st.session_state["f_slope"],
            }
            for key, value in optional_field.items():
                if value and float(value) > 0:
                    field[key] = float(value)
            if st.session_state["f_prev"].strip():
                field["previous_crop"] = st.session_state["f_prev"].strip()

            resources: dict[str, Any] = {
                "irrigation": st.session_state["r_irrigation"],
                "water_availability": st.session_state["r_water"],
                "labor": st.session_state["r_labor"],
                "mechanization": st.session_state["r_mech"],
                "organic_certified": bool(st.session_state["r_organic"]),
            }
            if st.session_state["r_budget"] and float(st.session_state["r_budget"]) > 0:
                resources["budget_usd"] = float(st.session_state["r_budget"])

            preferences: dict[str, Any] = {
                "goal": st.session_state["p_goal"],
                "crops_of_interest": list(st.session_state["p_interest"]),
                "excluded_crops": list(st.session_state["p_excluded"]),
                "market_access": st.session_state["p_market"],
            }
            if int(st.session_state["p_month"]) > 0:
                preferences["planting_month"] = int(st.session_state["p_month"])
            if int(st.session_state["p_maxdays"]) >= 60:
                preferences["max_growing_days"] = int(st.session_state["p_maxdays"])

            payload = {
                "location": {
                    "latitude": float(st.session_state["in_lat"]),
                    "longitude": float(st.session_state["in_lon"]),
                    "region_name": st.session_state["in_region"].strip() or None,
                },
                "field": field,
                "resources": resources,
                "preferences": preferences,
                "top_n": int(st.session_state["o_top_n"]),
                "language": st.session_state["o_lang"],
            }

            with st.spinner("Fetching NASA POWER data; rules and AI are running..."):
                response = api_call("POST", base_url, "/api/v1/analyze", payload=payload)
            st.session_state["analysis"] = response
            st.session_state["analysis_payload"] = payload

        analysis = st.session_state.get("analysis")
        if analysis:
            if analysis["ok"]:
                st.success(f"Analysis complete · {analysis['ms']} ms · HTTP {analysis['status']}")
                render_analysis(analysis["data"])
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                json_download(analysis["data"], f"alphecca_analysis_{stamp}.json")
                with st.expander("🧾 Submitted request body"):
                    st.json(st.session_state.get("analysis_payload", {}))
                with st.expander("🧾 Raw API response"):
                    st.json(analysis["data"])
            else:
                st.error(f"Analysis failed · {analysis['error']}")
                with st.expander("Error detail"):
                    st.json(analysis["data"] if analysis["data"] is not None else {})

    # =====================================================================
    # Environment data
    # =====================================================================
    with tab_env:
        with st.form("env_form"):
            e1, e2, e3, e4 = st.columns(4)
            with e1:
                st.number_input(
                    "Latitude", min_value=-90.0, max_value=90.0, step=0.0001,
                    format="%.4f", key="e_lat",
                )
            with e2:
                st.number_input(
                    "Longitude", min_value=-180.0, max_value=180.0, step=0.0001,
                    format="%.4f", key="e_lon",
                )
            with e3:
                st.text_input("Region name", key="e_region", max_chars=120)
            with e4:
                st.number_input(
                    "Weather for how many recent days", min_value=7, max_value=90, step=1, key="e_days"
                )
            env_submitted = st.form_submit_button(
                "🌦️ Fetch environment data", type="primary", width="stretch"
            )

        if env_submitted:
            params = {
                "latitude": float(st.session_state["e_lat"]),
                "longitude": float(st.session_state["e_lon"]),
                "recent_days": int(st.session_state["e_days"]),
            }
            if st.session_state["e_region"].strip():
                params["region_name"] = st.session_state["e_region"].strip()
            with st.spinner("Calling NASA POWER..."):
                env_response = api_call("GET", base_url, "/api/v1/environment", params=params)
            st.session_state["environment"] = env_response

        env_result = st.session_state.get("environment")
        if env_result:
            if env_result["ok"]:
                data = env_result["data"]
                st.success(
                    f"{data.get('location', {}).get('region_name') or 'Location'} · {env_result['ms']} ms"
                )
                render_environment(data.get("environment") or {})
                if data.get("warnings"):
                    st.markdown("#### ⚠️ Warnings")
                    for warning in data["warnings"]:
                        st.markdown(f"- {warning}")
                json_download(data, "alphecca_environment.json")
                with st.expander("🧾 Raw API response"):
                    st.json(data)
            else:
                st.error(f"Could not fetch environment data · {env_result['error']}")
                with st.expander("Error detail"):
                    st.json(env_result["data"] if env_result["data"] is not None else {})

    # =====================================================================
    # Crop catalogue
    # =====================================================================
    with tab_crops:
        try:
            crops = load_crops(base_url)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load the crop catalogue: {exc}")
            crops = []

        if crops:
            crop_frame = pd.DataFrame(
                [
                    {
                        "Key": crop.get("key"),
                        "Crop (EN)": crop.get("name"),
                        "Crop (local)": crop.get("local_name"),
                        "Category": crop.get("category"),
                        "Growing days": crop.get("growing_days"),
                        "Water need (mm)": crop.get("water_need_mm"),
                        "Planting window": crop.get("planting_window"),
                        "Nitrogen need": crop.get("nitrogen_need"),
                    }
                    for crop in crops
                ]
            )
            filter1, filter2 = st.columns([2, 1])
            with filter1:
                search = st.text_input("Search", placeholder="wheat, barley, olive...")
            with filter2:
                categories = sorted({crop.get("category") or "—" for crop in crops})
                picked = st.multiselect("Category", categories, default=categories)
            filtered = crop_frame[crop_frame["Category"].isin(picked)]
            if search.strip():
                needle = search.strip().lower()
                mask = (
                    filtered["Crop (EN)"].str.lower().str.contains(needle, na=False)
                    | filtered["Crop (local)"].str.lower().str.contains(needle, na=False)
                    | filtered["Key"].str.lower().str.contains(needle, na=False)
                )
                filtered = filtered[mask]
            st.caption(f"Showing {len(filtered)} crops (total {len(crops)})")
            st.dataframe(filtered, width="stretch", hide_index=True)

            picked_key = st.selectbox(
                "View details",
                options=[crop.get("key") for crop in crops],
                format_func=lambda key: next(
                    (crop.get("name") for crop in crops if crop.get("key") == key), key
                ),
            )
            detail = next((crop for crop in crops if crop.get("key") == picked_key), None)
            if detail:
                st.markdown(f"**{detail.get('name')} / {detail.get('local_name')}**")
                st.markdown(detail.get("notes") or "—")
                st.caption(
                    f"Planting window: {detail.get('planting_window')} · "
                    f"growing: {detail.get('growing_days')} days · "
                    f"water: {detail.get('water_need_mm')} mm · "
                    f"nitrogen: {detail.get('nitrogen_need')}"
                )
            with st.expander("🧾 Raw API response"):
                st.json(crops)

    # =====================================================================
    # AI providers
    # =====================================================================
    with tab_ai:
        try:
            providers = load_providers(base_url)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load the AI provider list: {exc}")
            providers = []

        if providers:
            provider_frame = pd.DataFrame(
                [
                    {
                        "Key": provider.get("key"),
                        "Name": provider.get("label"),
                        "Type": provider.get("kind"),
                        "Recommended": "✅" if provider.get("recommended") else "",
                        "Cost": provider.get("cost_tier"),
                        "Latency": provider.get("latency"),
                        "JSON reliability": provider.get("json_reliability"),
                        "Privacy": provider.get("privacy"),
                        "Example models": ", ".join(provider.get("model_examples") or [])[:80],
                    }
                    for provider in providers
                ]
            )
            st.dataframe(provider_frame, width="stretch", hide_index=True)

            for provider in providers:
                with st.expander(
                    f"{'⭐ ' if provider.get('recommended') else ''}{provider.get('label')} "
                    f"(`{provider.get('key')}`)"
                ):
                    st.markdown(f"**Best used for:** {provider.get('best_for')}")
                    col_good, col_bad = st.columns(2)
                    with col_good:
                        st.markdown("**Strengths**")
                        for strength in provider.get("strengths") or []:
                            st.markdown(f"- ✅ {strength}")
                    with col_bad:
                        st.markdown("**Weaknesses**")
                        for weakness in provider.get("weaknesses") or []:
                            st.markdown(f"- ⚠️ {weakness}")
            with st.expander("🧾 Raw API response"):
                st.json(providers)

    # =====================================================================
    # System and console
    # =====================================================================
    with tab_system:
        st.markdown("### 🩺 System status")
        if health["ok"]:
            info = health["data"]
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Status", info.get("status", "—"))
            h2.metric("Version", info.get("version", "—"))
            h3.metric("Environment", info.get("environment", "—"))
            h4.metric("AI provider", info.get("ai_provider", "—"))
            h5, h6, h7, h8 = st.columns(4)
            h5.metric("AI key", "available" if info.get("ai_configured") else "missing")
            h6.metric("Cache", fmt(info.get("cache_entries"), "", 0))
            h7.metric("Response time", f"{health['ms']} ms")
            h8.metric("Geocoding", "on" if info.get("geocoding_enabled") else "off")
            st.caption(f"NASA POWER: {info.get('nasa_power_base_url')} · server time: {info.get('timestamp')}")
            with st.expander("🧾 Raw /health response"):
                st.json(info)
        else:
            st.error(f"Health check failed · {health['error']}")
            st.code("python run_ui.py", language="powershell")

        st.markdown("### 🏠 Root endpoint")
        root = api_call("GET", base_url, "/", timeout=10.0)
        if root["ok"]:
            root_data = root["data"]
            st.markdown(f"**{root_data.get('name')}** · v{root_data.get('version')}")
            st.markdown(root_data.get("description") or "")
            st.json(root_data.get("endpoints") or {})
            with st.expander("🧾 Raw response"):
                st.json(root_data)
        else:
            st.warning(f"Root endpoint error · {root['error']}")

        st.divider()
        st.markdown("### 🧪 Free-form API console")
        st.caption("Test any endpoint by hand. The body is only used for POST/PUT.")
        console1, console2 = st.columns([1, 3])
        with console1:
            method = st.selectbox("Method", ["GET", "POST", "PUT", "DELETE"], key="console_method")
        with console2:
            path = st.text_input("Path", value="/api/v1/health", key="console_path")
        body_text = st.text_area(
            "JSON body (optional)",
            value="",
            height=160,
            key="console_body",
            placeholder='{"location": {"latitude": 41.6771, "longitude": 26.5557}}',
        )
        if st.button("📨 Send request", type="primary"):
            parsed_body: Any = None
            if body_text.strip():
                try:
                    parsed_body = json.loads(body_text)
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
                    st.stop()
            console_response = api_call(
                method,
                base_url,
                path if path.startswith("/") else f"/{path}",
                payload=parsed_body if method in {"POST", "PUT"} else None,
            )
            if console_response["ok"]:
                st.success(f"HTTP {console_response['status']} · {console_response['ms']} ms")
            else:
                st.error(f"{console_response['error']} · {console_response['ms']} ms")
            st.json(console_response["data"] if console_response["data"] is not None else {})

        st.divider()
        st.caption(
            "Project Alphecca test interface · Data comes from NASA POWER; local measurement and "
            "agronomist approval are required before production."
        )
