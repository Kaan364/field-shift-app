"""Project Alphecca - çiftçi odaklı test arayüzü.

Tasarım ilkeleri:
1. **Önce basit akış.** Çiftçi haritadan tarlasını seçer, 3-4 soruya cevap verir,
   isterse kendi cümleleriyle derdini yazar. Sonuç kısa ve sade cümlelerle gösterilir.
2. **Detay isteğe bağlı.** İklim, toprak, puan kırılımı gibi ileri bilgiler
   "Detaylı bilgi" kutusu işaretlenince açılır.
3. **İş mantığı burada yok.** Her şey FastAPI backend'inde; bu dosya yalnızca
   HTTP isteği atar ve cevabı gösterir.
4. **Uzman modu korunur.** Tüm uçları elle denemek için alttaki "Uzman / test modu".

Çalıştırma::

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
# Sözlükler (etiket -> API değeri)
# ---------------------------------------------------------------------------
SOIL_TEXTURES = [
    ("unknown", "Bilmiyorum"),
    ("sand", "Kum"),
    ("loamy_sand", "Tınlı kum"),
    ("sandy_loam", "Kumlu tın"),
    ("loam", "Tın"),
    ("silt_loam", "Siltli tın"),
    ("silt", "Silt"),
    ("clay_loam", "Killi tın"),
    ("sandy_clay_loam", "Kumlu killi tın"),
    ("clay", "Kil"),
]
DRAINAGE = [("poor", "Zayıf"), ("medium", "Orta"), ("good", "İyi")]
IRRIGATION = [("rainfed", "Sadece yağmur"), ("limited", "Kısıtlı sulama"), ("full", "Tam sulama")]
SIMPLE_IRRIGATION = [
    ("rainfed", "Hayır, sadece yağmur"),
    ("limited", "Bazen / kısmen"),
    ("full", "Evet, tam sulayabilirim"),
]
WATER = [("low", "Düşük"), ("medium", "Orta"), ("high", "Yüksek")]
LABOR = [("family", "Aile işgücü"), ("hired", "Ücretli"), ("mixed", "Karma"), ("scarce", "Kıt")]
MECHANIZATION = [("low", "Düşük"), ("medium", "Orta"), ("high", "Yüksek")]
MARKET = [("low", "Düşük"), ("medium", "Orta"), ("high", "Yüksek")]
GOALS = [
    ("max_profit", "Maksimum kâr"),
    ("max_yield", "Maksimum verim"),
    ("low_water", "Az su kullanımı"),
    ("low_input", "Az girdi"),
    ("organic", "Organik üretim"),
    ("soil_health", "Toprak sağlığı"),
    ("risk_averse", "Riski sevmeyen"),
]
SIMPLE_GOALS = [
    ("max_profit", "Daha çok para kazanmak istiyorum"),
    ("max_yield", "Daha çok ürün almak istiyorum"),
    ("low_input", "Az masraf yapmak istiyorum"),
    ("low_water", "Suyum az, az su isteyen bir şey olsun"),
    ("risk_averse", "Risk almak istemiyorum, garanti olsun"),
]
MONTHS = [
    "Bilmiyorum", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
CLIMATE_LABELS = {
    "hyper_arid": "hiper-kurak",
    "arid": "kurak",
    "semi_arid": "yarı kurak",
    "dry_sub_humid": "kuru-yarı nemli",
    "humid": "nemli",
    "per_humid": "çok nemli",
    "unknown": "bilinmiyor",
}
COMPONENT_LABELS = {
    "temperature": "Sıcaklık uyumu",
    "water": "Su dengesi",
    "ph": "pH uyumu",
    "texture": "Toprak dokusu",
    "salinity": "Tuzluluk",
    "climate_risk": "İklim riski (don/sıcak)",
    "goal_fit": "Hedefe uygunluk",
    "market": "Pazar erişimi",
    "calendar": "Ekim takvimi",
}
PRESETS: dict[str, tuple[float, float, str]] = {
    "Edirne (Trakya)": (41.6771, 26.5557, "Edirne"),
    "Tekirdağ (Trakya)": (40.9781, 27.5117, "Tekirdağ"),
    "Kırklareli (Trakya)": (41.7333, 27.2167, "Kırklareli"),
    "Ankara": (39.9334, 32.8597, "Ankara"),
    "İzmir": (38.4237, 27.1428, "İzmir"),
    "Konya": (37.8746, 32.4932, "Konya"),
    "Şanlıurfa": (37.1591, 38.7969, "Şanlıurfa"),
    "Antalya": (36.8969, 30.7133, "Antalya"),
}
FALLBACK_CROPS = [
    ("wheat", "Kışlık Buğday"),
    ("barley", "Arpa"),
    ("maize", "Mısır"),
    ("sunflower", "Ayçiçeği"),
    ("chickpea", "Nohut"),
    ("lentil", "Mercimek"),
    ("potato", "Patates"),
    ("tomato", "Domates (tarla)"),
    ("cotton", "Pamuk"),
    ("soybean", "Soya"),
    ("canola", "Kanola"),
    ("sugar_beet", "Şeker Pancarı"),
    ("alfalfa", "Yonca"),
    ("olive", "Zeytin"),
    ("grape", "Üzüm (Bağ)"),
    ("apple", "Elma"),
]
EXAMPLE_TEXT = (
    "Tarlam Edirne'de. Ne ekeceğimi bilmiyorum. "
    "Bitkiyi nasıl büyüteceğimi, nasıl besleyeceğimi, nasıl bakacağımı da bilmiyorum. "
    "Bana basit bir şekilde anlatır mısın?"
)

DEFAULTS: dict[str, Any] = {
    # Basit akış
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
    # Uzman akışı
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
    "o_lang": "tr",
    "e_lat": 39.9334,
    "e_lon": 32.8597,
    "e_region": "Ankara",
    "e_days": 30,
}


# ---------------------------------------------------------------------------
# Yardımcılar
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
    """Backend'e istek atar; sonucu her durumda sözlük olarak döndürür."""

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
    """Örnek metni doldurur.

    ``on_click`` geri çağrısı, widget'lar oluşturulmadan *önce* çalıştığı için
    ``s_text`` anahtarını burada güvenle değiştirebiliyoruz.
    """

    st.session_state["s_text"] = EXAMPLE_TEXT


def _reset_coordinates() -> None:
    latitude, longitude, region = PRESETS["Edirne (Trakya)"]
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
    """Koordinatı okunur yer adına çevirir; başarısızsa boş döner."""

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
        return {crop["key"]: crop["local_name"] for crop in crops}
    except Exception:  # noqa: BLE001 - arayüz çökmemeli
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
    """Arayüzün tarayıcıdaki adresi (konum izni sayfasına geri dönüş için)."""

    try:
        host = st.context.headers.get("host")
    except Exception:  # noqa: BLE001 - test/headless ortamında olmayabilir
        host = None
    if host:
        return f"http://{host}"
    return DEFAULT_UI_URL


# ---------------------------------------------------------------------------
# Harita
# ---------------------------------------------------------------------------
def render_parcel_map(base_url: str) -> None:
    latitude = float(st.session_state["s_lat"])
    longitude = float(st.session_state["s_lon"])

    try:
        import folium
        from streamlit_folium import st_folium
    except ImportError:
        st.info(
            "Harita bileşeni kurulu değil. Kurmak için: "
            "`pip install -r requirements-ui.txt` · Enlem/boylamı aşağıdan elle girebilirsin."
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
        tooltip="Seçtiğin nokta",
        popup="Tarlan burada",
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
        # Açıkça verilmezse Streamlit her yeniden çalışmada bileşeni yeniden
        # bağlıyor ve harita dünya görünümüne (zoom 3) sıçrıyor.
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
        st.caption(f"📍 Seçilen yer: **{place}** · {latitude:.4f}, {longitude:.4f}")
    else:
        st.caption(f"📍 Seçilen nokta: **{latitude:.4f}, {longitude:.4f}**")
    st.caption("Haritada tarlanın üstüne dokun; nokta oraya taşınır.")


# ---------------------------------------------------------------------------
# Ortak detay blokları
# ---------------------------------------------------------------------------
def render_environment(environment: dict[str, Any]) -> None:
    climate = environment.get("climate") or {}
    soil = environment.get("soil") or {}
    recent = environment.get("recent_weather") or {}

    st.markdown("##### 🌦️ İklim özeti (NASA POWER, 2001-2025 ortalaması)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Yıllık yağış", fmt(climate.get("annual_precip_mm"), " mm", 1))
    c2.metric("Ortalama sıcaklık", fmt(climate.get("annual_mean_temp_c"), " °C", 2))
    c3.metric(
        "İklim sınıfı",
        CLIMATE_LABELS.get(climate.get("climate_class") or "", climate.get("climate_class") or "—"),
    )
    c4.metric("Büyüme sezonu", fmt(climate.get("growing_season_days"), " gün", 0))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Yıllık ET0", fmt(climate.get("annual_evapotranspiration_mm"), " mm", 0))
    c6.metric("Kuraklık indeksi", fmt(climate.get("aridity_index"), "", 2))
    c7.metric("Don ayları", str(len(climate.get("frost_months") or [])))
    c8.metric("Sıcak stres ayları", str(len(climate.get("heat_stress_months") or [])))

    if climate.get("frost_months"):
        st.caption("🧊 Don görülen aylar: " + ", ".join(climate["frost_months"]))
    if climate.get("heat_stress_months"):
        st.caption("🔥 Sıcak stresi ayları: " + ", ".join(climate["heat_stress_months"]))
    if climate.get("growing_season_mean_temp_c") is not None:
        st.caption(
            f"Büyüme sezonu ortalama sıcaklığı: {fmt(climate.get('growing_season_mean_temp_c'), ' °C')}"
        )

    st.markdown("##### 🧱 Toprak")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("NASA kök bölgesi nemi", fmt(soil.get("root_zone_moisture_mean"), "", 3))
    s2.metric("Yüzey nemi", fmt(soil.get("topsoil_moisture_mean"), "", 3))
    s3.metric("Toprak sıcaklığı", fmt(soil.get("mean_soil_temp_c"), " °C", 1))
    s4.metric(
        "Toprak durumu",
        f"{fmt(soil.get('soil_condition_score'), '', 0)} / 100",
        help=soil.get("soil_condition_label") or None,
    )
    st.caption(
        "Çiftçi bildirimi → doku: "
        f"{label_of(SOIL_TEXTURES, soil.get('soil_texture') or 'unknown')}, "
        f"pH: {fmt(soil.get('soil_ph'), '', 1)}, "
        f"organik madde: {fmt(soil.get('organic_matter_pct'), ' %', 1)}, "
        f"tuzluluk: {fmt(soil.get('salinity_ds_m'), ' dS/m', 2)}, "
        f"drenaj: {label_of(DRAINAGE, soil.get('drainage') or 'medium')}"
    )
    if soil.get("data_gaps"):
        st.warning("Veri boşlukları: " + " · ".join(soil["data_gaps"]))

    if recent:
        st.markdown("##### 🌡️ Son günlerdeki gerçek hava durumu (tahmin değil)")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric(
            "Pencere",
            fmt(recent.get("window_days"), " gün", 0),
            help=f"Erişilebilen gün: {recent.get('available_days')}",
        )
        r2.metric("Toplam yağış", fmt(recent.get("total_precip_mm"), " mm", 1))
        r3.metric("Ortalama sıcaklık", fmt(recent.get("mean_temp_c"), " °C", 2))
        r4.metric("En uzun kurak dönem", fmt(recent.get("longest_dry_spell_days"), " gün", 0))

    monthly = environment.get("monthly") or []
    if monthly:
        st.markdown("##### 📅 Aylık dağılım")
        rows = []
        for item in monthly:
            rows.append(
                {
                    "Ay": item.get("month"),
                    "Ort °C": item.get("mean_temp_c"),
                    "Min °C": item.get("min_temp_c"),
                    "Maks °C": item.get("max_temp_c"),
                    "Yağış (mm)": item.get("precip_month_mm"),
                    "Nem (%)": item.get("relative_humidity_pct"),
                    "Güneş (kWh/m²/gün)": item.get("solar_kwh_m2_day"),
                    "ET0 (mm/gün)": item.get("evapotranspiration_mm_per_day"),
                    "Kök nemi": item.get("root_zone_moisture"),
                    "Toprak °C": item.get("soil_temp_c"),
                    "Don": "🧊" if item.get("frost_risk") else "",
                    "Sıcak stresi": "🔥" if item.get("heat_stress") else "",
                }
            )
        frame = pd.DataFrame(rows)
        st.dataframe(frame, width="stretch", hide_index=True)

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.caption("Sıcaklık eğrisi (°C)")
            st.line_chart(frame.set_index("Ay")[["Ort °C", "Min °C", "Maks °C"]], height=260)
        with chart_col2:
            st.caption("Aylık yağış (mm)")
            st.bar_chart(frame.set_index("Ay")[["Yağış (mm)"]], height=260)

    if environment.get("notes"):
        with st.expander("ℹ️ Veri notları"):
            for note in environment["notes"]:
                st.markdown(f"- {note}")


def render_score_table(recommendations: list[dict[str, Any]]) -> None:
    if not recommendations:
        return
    table = pd.DataFrame(
        [
            {
                "#": item.get("rank"),
                "Ürün": item.get("crop_name_local") or item.get("crop_name"),
                "Puan": item.get("scores", {}).get("final_score"),
                "Kural": item.get("scores", {}).get("rule_score"),
                "AI": item.get("scores", {}).get("ai_score"),
                "Güven": item.get("confidence"),
                "Ekim penceresi": item.get("planting_window"),
                "Gün": item.get("growing_days"),
                "Su (mm)": item.get("water_need_mm"),
            }
            for item in recommendations
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)

    for item in recommendations:
        components = item.get("scores", {}).get("components") or {}
        with st.expander(
            f"{item.get('rank')}. {item.get('crop_name_local')} — "
            f"puan {fmt(item.get('scores', {}).get('rule_score'), '', 1)}"
        ):
            st.markdown(f"**Gerekçe:** {item.get('rationale') or '—'}")
            if item.get("risks"):
                st.markdown("**Riskler**")
                for risk in item["risks"]:
                    st.markdown(f"- ⚠️ {risk}")
            if item.get("actions"):
                st.markdown("**Aksiyonlar**")
                for action in item["actions"]:
                    st.markdown(f"- ✅ {action}")
            if components:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Bileşen": COMPONENT_LABELS.get(key, key), "Puan": value}
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
# Basit sonuç ekranı
# ---------------------------------------------------------------------------
def render_simple_result(result: dict[str, Any], base_url: str) -> None:
    if not result["ok"]:
        st.error("Öneri alınamadı. İnternetini ve konumu kontrol edip tekrar dene.")
        with st.expander("Teknik ayrıntı"):
            st.code(result.get("error") or "bilinmeyen hata")
            st.json(result.get("data") or {})
        return

    data = result["data"]
    advice = data.get("advice") or {}
    recommendations = data.get("recommendations") or []
    ai = data.get("ai") or {}

    st.success(f"Öneri hazır · {result['ms']} ms")

    st.markdown(f"## 🌾 {advice.get('headline') or data.get('summary')}")
    if advice.get("why"):
        st.markdown(advice["why"])

    if recommendations:
        columns = st.columns(len(recommendations))
        for column, rec in zip(columns, recommendations):
            column.metric(
                rec.get("crop_name_local") or rec.get("crop_name"),
                f"{fmt(rec.get('scores', {}).get('rule_score'), '', 0)} / 100",
                help="Bu puan bölge iklimi, toprağın ve tercihlerine göre hesaplandı.",
            )

    if ai.get("kind") == "llm" and ai.get("used") and not ai.get("fallback_used"):
        st.caption(
            f"Bu açıklamayı yapay zekâ yazdı ({ai.get('provider')} / {ai.get('model') or '—'}). "
            "Sıralamayı ise kural motoru belirledi."
        )
    else:
        st.caption(
            "Bu açıklama kural motoru tarafından yazıldı (yapay zekâ anahtarı tanımlı değil). "
            "Sonuçlar yine de NASA verisi ve tarım kurallarına dayanır."
        )

    bullets("✅ İlk yapman gerekenler", advice.get("steps") or [], "**•**")
    bullets("🌱 Nasıl büyütürüm?", advice.get("grow") or [], "•")
    bullets("🧪 Nasıl beslerim?", advice.get("feed") or [], "•")
    bullets("💧 Nasıl bakarım?", advice.get("care") or [], "•")
    bullets("⚠️ Dikkat et", advice.get("risks") or [], "•")

    if advice.get("ask_farmer"):
        st.info(
            "Daha iyi öneri verebilmem için şunları bilmem iyi olur:\n\n"
            + "\n".join(f"- {question}" for question in advice["ask_farmer"])
        )

    detail = st.checkbox(
        "🔍 Detaylı bilgi göster (iklim, toprak, puanlar)",
        key="s_detail",
        help="İstersen bölgenin yağışı, sıcaklığı, toprak nemi ve puan kırılımını gösterir.",
    )
    if detail:
        environment = data.get("environment") or {}
        if environment:
            render_environment(environment)
        st.markdown("### 📊 Puan tablosu ve gerekçeler")
        render_score_table(recommendations)
        if data.get("warnings"):
            st.markdown("### ⚠️ Uyarılar")
            for warning in data["warnings"]:
                st.markdown(f"- {warning}")
        if data.get("data_sources"):
            with st.expander("📚 Veri kaynakları"):
                for source in data["data_sources"]:
                    st.markdown(f"- **{source.get('name')}**: {source.get('description')}")
        with st.expander("🧾 Ham API cevabı (geliştirici)"):
            st.json(data)

    if data.get("disclaimer"):
        st.caption(data["disclaimer"])


# ---------------------------------------------------------------------------
# Eski (ayrıntılı) analiz görünümü — uzman modunda kullanılır
# ---------------------------------------------------------------------------
def render_analysis(result: dict[str, Any]) -> None:
    ai = result.get("ai") or {}
    st.markdown("### 📊 Analiz sonucu")
    st.info(result.get("summary") or "Özet yok.")

    if ai.get("kind") == "deterministic":
        st.warning(
            "Yapay zekâ katmanı **devrede değil**: öneriler yalnızca deterministik kural motorundan geliyor. "
            f"(Sağlayıcı: `{ai.get('provider')}`"
            + (f" · not: {ai.get('notes')}" if ai.get("notes") else "")
            + ")"
        )
    else:
        detail = (
            f"Sağlayıcı: `{ai.get('provider')}`"
            f" · model: `{ai.get('model') or '—'}`"
            f" · kullanıldı: {'evet' if ai.get('used') else 'hayır'}"
            f" · yedek: {'evet' if ai.get('fallback_used') else 'hayır'}"
            f" · gecikme: {fmt(ai.get('latency_ms'), ' ms', 0)}"
        )
        if ai.get("error"):
            st.warning(f"AI cevabı alınamadı, deterministik sonuç kullanıldı. {detail}\n\nHata: {ai['error']}")
        else:
            st.success(detail)

    st.caption(
        "Nihai puan = kural motoru ağırlığı + AI ağırlığı (varsayılan %65 / %35). "
        "AI puanı yalnızca kural puanını dengeler, tek başına karar veremez."
    )

    recommendations = result.get("recommendations") or []
    top = recommendations[0] if recommendations else None
    if top:
        st.markdown("#### 🏆 Öne çıkan öneri")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Ürün", top.get("crop_name_local") or top.get("crop_name"))
        t2.metric("Nihai puan", fmt(top.get("scores", {}).get("final_score"), " / 100", 1))
        t3.metric(
            "Kural / AI",
            f"{fmt(top.get('scores', {}).get('rule_score'), '', 1)} / "
            f"{fmt(top.get('scores', {}).get('ai_score'), '', 1)}",
        )
        t4.metric("Güven", str(top.get("confidence") or "—"))

    render_score_table(recommendations)

    environment = result.get("environment") or {}
    if environment:
        with st.expander("🌦️ Kullanılan çevre verisi (NASA POWER)", expanded=False):
            render_environment(environment)

    if result.get("warnings"):
        st.markdown("#### ⚠️ Uyarılar")
        for warning in result["warnings"]:
            st.markdown(f"- {warning}")
    if result.get("general_risks"):
        st.markdown("#### 🚧 Genel riskler")
        for risk in result["general_risks"]:
            st.markdown(f"- {risk}")
    if result.get("general_actions"):
        st.markdown("#### 🗺️ Genel aksiyon planı")
        for action in result["general_actions"]:
            st.markdown(f"- {action}")
    if result.get("data_sources"):
        with st.expander("📚 Veri kaynakları"):
            for source in result["data_sources"]:
                st.markdown(f"- **{source.get('name')}**: {source.get('description')}")
    if result.get("disclaimer"):
        st.caption(result["disclaimer"])
    st.caption(
        f"Analiz kimliği: `{result.get('analysis_id')}` · oluşturulma: {result.get('generated_at')}"
    )


def json_download(data: dict[str, Any], name: str) -> None:
    st.download_button(
        "⬇️ Ham JSON indir",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name=name,
        mime="application/json",
        width="stretch",
    )


# ---------------------------------------------------------------------------
# Sayfa
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Ne ekeyim? · Project Alphecca", page_icon="🌱", layout="wide")
_init_state()

# Tarayıcı konum izninden dönen ?lat=..&lon=.. parametrelerini bir kez oku.
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

st.title("🌱 Ne ekeyim?")
st.caption(
    "Tarlanı haritadan seç, birkaç soruya cevap ver. NASA'nın uydu verilerine ve tarım "
    "kurallarına göre sana basit bir öneri hazırlayalım."
)

# --- Kenar çubuğu ----------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Bağlantı")
    base_url = st.text_input("API adresi", key="api_base").rstrip("/")

    health = api_call("GET", base_url, "/health", timeout=10.0)
    if health["ok"]:
        info = health["data"]
        st.success(f"Bağlı · v{info.get('version')}")
        provider_label = str(info.get("ai_provider") or "unknown")
        if provider_label == "heuristic":
            ai_state = "yok — açıklamayı kural motoru yazıyor"
        elif info.get("ai_configured"):
            ai_state = "var"
        else:
            ai_state = "yok (anahtar tanımlı değil)"
        st.caption(f"Yapay zekâ: **{provider_label}** · anahtar: {ai_state}")
        st.caption(f"Önbellek: {info.get('cache_entries')} · gecikme: {health['ms']} ms")
    else:
        st.error("API'ye ulaşılamıyor")
        st.caption(health["error"] or "Bilinmeyen hata")
        st.code("python run_ui.py", language="powershell")
        st.caption("Backend'i başlatmak için proje klasöründe bu komutu çalıştır.")

    st.divider()
    st.header("📍 Hazır konum")
    preset_name = st.selectbox("Bölge seç", list(PRESETS), key="preset_pick")
    st.button(
        "Bu bölgeyi kullan",
        width="stretch",
        on_click=_use_preset,
        args=(preset_name,),
    )

    st.divider()
    st.header("🔗 Bağlantılar")
    st.markdown(f"- [Swagger /docs]({base_url}/docs)")
    st.markdown(f"- [Sağlık kontrolü]({base_url}/health)")
    with st.expander("ℹ️ Arayüz ne test eder?"):
        st.markdown(
            "- `POST /api/v1/advice` — serbest metin + sade öneri\n"
            "- `POST /api/v1/analyze` — tam puanlama hattı\n"
            "- `GET /api/v1/environment` — NASA çevre verisi\n"
            "- `GET /api/v1/reverse-geocode` — koordinat → yer adı\n"
            "- `GET /api/v1/crops`, `/api/v1/ai-providers`\n"
            "- `GET /health`, `GET /` ve serbest konsol"
        )

# ---------------------------------------------------------------------------
# 1) ÇİFTÇİ AKIŞI
# ---------------------------------------------------------------------------
st.markdown("### 1️⃣ Tarlan nerede?")
render_parcel_map(base_url)

location_col1, location_col2 = st.columns([2, 1])
with location_col1:
    st.link_button(
        "📍 Konumumu otomatik bul (tarayıcı izni)",
        f"{base_url}/geo?next={ui_origin()}",
        width="stretch",
        help="Tarayıcı konum izni ister. İzin verirsen harita senin konumuna taşınır.",
    )
with location_col2:
    st.button(
        "🧭 Merkeze dön",
        width="stretch",
        help="Haritayı varsayılan bölgeye döndür",
        on_click=_reset_coordinates,
    )

with st.expander("⌨️ Konumu elle yazmak istiyorum"):
    manual_col1, manual_col2, manual_col3 = st.columns(3)
    with manual_col1:
        st.number_input(
            "Enlem (latitude)", min_value=-90.0, max_value=90.0, step=0.0001,
            format="%.4f", key="s_lat",
        )
    with manual_col2:
        st.number_input(
            "Boylam (longitude)", min_value=-180.0, max_value=180.0, step=0.0001,
            format="%.4f", key="s_lon",
        )
    with manual_col3:
        st.text_input("Yer adı (isteğe bağlı)", key="s_place", max_chars=120)

st.markdown("### 2️⃣ Tarlan hakkında birkaç soru")
q1, q2 = st.columns(2)
with q1:
    st.number_input(
        "Tarlan kaç dönüm? (1 dönüm ≈ 0.1 hektar)",
        min_value=0.0,
        max_value=1_000_000.0,
        step=1.0,
        key="s_area_donum",
        help="Bilmiyorsan 0 bırakabilirsin.",
    )
with q2:
    st.selectbox(
        "Sulayabiliyor musun?",
        [key for key, _ in SIMPLE_IRRIGATION],
        format_func=lambda value: label_of(SIMPLE_IRRIGATION, value),
        key="s_irrigation",
    )

q3, q4 = st.columns(2)
with q3:
    st.selectbox(
        "Ne istiyorsun?",
        [key for key, _ in SIMPLE_GOALS],
        format_func=lambda value: label_of(SIMPLE_GOALS, value),
        key="s_goal",
    )
with q4:
    st.selectbox(
        "Ne zaman ekmeyi düşünüyorsun?",
        list(range(0, 13)),
        format_func=lambda value: MONTHS[value],
        key="s_month",
    )

with st.expander("🪴 Toprağını tanıyor musun? (bilmiyorsan boş bırak)"):
    soil_col1, soil_col2, soil_col3 = st.columns(3)
    with soil_col1:
        st.selectbox(
            "Toprak yapısı",
            [key for key, _ in SOIL_TEXTURES],
            format_func=lambda value: label_of(SOIL_TEXTURES, value),
            key="s_texture",
        )
    with soil_col2:
        st.number_input(
            "Toprak pH (0 = bilmiyorum)", min_value=0.0, max_value=10.0, step=0.1, key="s_ph"
        )
    with soil_col3:
        st.number_input(
            "Organik madde % (0 = bilmiyorum)", min_value=0.0, max_value=30.0, step=0.1, key="s_om"
        )

st.markdown("### 3️⃣ Kendi cümlelerinle anlat (isteğe bağlı)")
st.caption(
    "Nasıl anlatmak istersen öyle yaz. Yazmak zorunda değilsin; yukarıdaki sorular da yeterli."
)
text_col1, text_col2 = st.columns([3, 1])
with text_col1:
    free_text = st.text_area(
        "Durumunu anlat",
        key="s_text",
        height=110,
        placeholder=(
            "Örnek: Tarlam Edirne'de. Ne ekeceğimi bilmiyorum. "
            "Bitkiyi nasıl büyüteceğimi, nasıl besleyeceğimi bilmiyorum."
        ),
        label_visibility="collapsed",
    )
with text_col2:
    st.button(
        "📝 Örnek yazıyı doldur",
        width="stretch",
        on_click=_fill_example_text,
        help="Örnek cümleyi kutuya yazar; sonra üzerinde değiştirebilirsin.",
    )

st.markdown("")
submit_col, clear_col = st.columns([3, 1])
with submit_col:
    run_advice = st.button(
        "🌾 Bana ne ekeceğimi söyle",
        type="primary",
        width="stretch",
    )
with clear_col:
    if st.button("🧹 Temizle", width="stretch"):
        st.session_state.pop("s_result", None)
        st.session_state.pop("analysis", None)
        st.rerun()

if run_advice:
    if not health["ok"]:
        st.error("Sunucuya ulaşılamıyor. Önce `python run_ui.py` komutunu çalıştır.")
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
            "language": "tr",
        }
        if area_hectares:
            payload["area_hectares"] = area_hectares
        if float(st.session_state["s_ph"]) > 0:
            payload["soil_ph"] = float(st.session_state["s_ph"])
        if float(st.session_state["s_om"]) > 0:
            payload["organic_matter_pct"] = float(st.session_state["s_om"])
        if int(st.session_state["s_month"]) > 0:
            payload["planting_month"] = int(st.session_state["s_month"])

        with st.spinner("Tarlanın hava ve toprak verisi alınıyor... (ilk seferde 3-10 saniye)"):
            response = api_call("POST", base_url, "/api/v1/advice", payload=payload, timeout=240.0)
        st.session_state["s_result"] = response
        st.session_state["s_payload"] = payload

simple_result = st.session_state.get("s_result")
if simple_result:
    st.divider()
    render_simple_result(simple_result, base_url)
    if simple_result.get("ok"):
        with st.expander("🧾 Gönderilen bilgiler"):
            st.json(st.session_state.get("s_payload", {}))

# ---------------------------------------------------------------------------
# 2) UZMAN / TEST MODU
# ---------------------------------------------------------------------------
st.divider()
with st.expander("🧑‍🌾 Uzman / test modu — tüm API işlevleri", expanded=False):
    st.caption(
        "Bu bölüm geliştirici ve ziraat uzmanı içindir. Ham puanlar, tüm parametreler ve "
        "serbest API konsolu burada."
    )
    crops_map = crop_label_map()
    tab_analyze, tab_env, tab_crops, tab_ai, tab_system = st.tabs(
        [
            "🌱 Analiz",
            "🌦️ Çevre Verisi",
            "🌾 Ürün Kataloğu",
            "🤖 AI Sağlayıcıları",
            "🩺 Sistem & Konsol",
        ]
    )

    # =====================================================================
    # Analiz
    # =====================================================================
    with tab_analyze:
        with st.form("analyze_form"):
            st.markdown("#### 1️⃣ Konum")
            loc1, loc2, loc3 = st.columns(3)
            with loc1:
                st.number_input(
                    "Enlem (latitude)", min_value=-90.0, max_value=90.0,
                    step=0.0001, format="%.4f", key="in_lat",
                )
            with loc2:
                st.number_input(
                    "Boylam (longitude)", min_value=-180.0, max_value=180.0,
                    step=0.0001, format="%.4f", key="in_lon",
                )
            with loc3:
                st.text_input("Bölge adı (etiket)", key="in_region", max_chars=120)

            st.markdown("#### 2️⃣ Tarla / toprak")
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                st.number_input(
                    "Alan (hektar)", min_value=0.1, max_value=1_000_000.0,
                    step=1.0, key="f_area",
                )
            with f2:
                st.selectbox(
                    "Toprak dokusu", [key for key, _ in SOIL_TEXTURES],
                    format_func=lambda value: label_of(SOIL_TEXTURES, value), key="f_texture",
                )
            with f3:
                st.number_input(
                    "Toprak pH (0 = bilinmiyor)", min_value=0.0, max_value=10.0,
                    step=0.1, key="f_ph",
                )
            with f4:
                st.number_input(
                    "Organik madde % (0 = bilinmiyor)", min_value=0.0, max_value=30.0,
                    step=0.1, key="f_om",
                )

            f5, f6, f7, f8 = st.columns(4)
            with f5:
                st.number_input(
                    "Tuzluluk dS/m (0 = bilinmiyor)", min_value=0.0, max_value=40.0,
                    step=0.1, key="f_salinity",
                )
            with f6:
                st.number_input(
                    "Toprak derinliği cm (0 = bilinmiyor)", min_value=0.0, max_value=300.0,
                    step=5.0, key="f_depth",
                )
            with f7:
                st.selectbox(
                    "Drenaj", [key for key, _ in DRAINAGE],
                    format_func=lambda value: label_of(DRAINAGE, value), key="f_drainage",
                )
            with f8:
                st.number_input(
                    "Eğim % (0 = bilinmiyor)", min_value=0.0, max_value=80.0,
                    step=1.0, key="f_slope",
                )

            st.text_input(
                "Önceki ürün (isteğe bağlı)", key="f_prev", max_chars=80, placeholder="Örn. buğday"
            )

            st.markdown("#### 3️⃣ Kaynaklar")
            r1, r2, r3 = st.columns(3)
            with r1:
                st.selectbox(
                    "Sulama", [key for key, _ in IRRIGATION],
                    format_func=lambda value: label_of(IRRIGATION, value), key="r_irrigation",
                )
            with r2:
                st.selectbox(
                    "Su bulunabilirliği", [key for key, _ in WATER],
                    format_func=lambda value: label_of(WATER, value), key="r_water",
                )
            with r3:
                st.number_input(
                    "Bütçe USD (0 = bilinmiyor)", min_value=0.0, max_value=100_000_000.0,
                    step=500.0, key="r_budget",
                )

            r4, r5, r6 = st.columns(3)
            with r4:
                st.selectbox(
                    "İşgücü", [key for key, _ in LABOR],
                    format_func=lambda value: label_of(LABOR, value), key="r_labor",
                )
            with r5:
                st.selectbox(
                    "Mekanizasyon", [key for key, _ in MECHANIZATION],
                    format_func=lambda value: label_of(MECHANIZATION, value), key="r_mech",
                )
            with r6:
                st.checkbox("Organik sertifikalı", key="r_organic")

            st.markdown("#### 4️⃣ Tercihler")
            p1, p2, p3 = st.columns(3)
            with p1:
                st.selectbox(
                    "Hedef", [key for key, _ in GOALS],
                    format_func=lambda value: label_of(GOALS, value), key="p_goal",
                )
            with p2:
                st.selectbox(
                    "Ekim ayı", list(range(0, 13)),
                    format_func=lambda value: MONTHS[value], key="p_month",
                )
            with p3:
                st.selectbox(
                    "Pazar erişimi", [key for key, _ in MARKET],
                    format_func=lambda value: label_of(MARKET, value), key="p_market",
                )

            p4, p5 = st.columns(2)
            with p4:
                st.multiselect(
                    "İlgilenilen ürünler", options=list(crops_map),
                    format_func=lambda key: crops_map.get(key, key), key="p_interest",
                )
            with p5:
                st.multiselect(
                    "Hariç tutulan ürünler", options=list(crops_map),
                    format_func=lambda key: crops_map.get(key, key), key="p_excluded",
                )

            o1, o2, o3 = st.columns(3)
            with o1:
                st.slider("Kaç öneri gösterilsin", min_value=1, max_value=8, key="o_top_n")
            with o2:
                st.radio("Dil", options=["tr", "en"], horizontal=True, key="o_lang")
            with o3:
                st.number_input(
                    "Maks. yetişme süresi (gün, 0 = sınırsız)",
                    min_value=0, max_value=400, step=10, key="p_maxdays",
                )

            submitted = st.form_submit_button("🚀 Analiz et", type="primary", width="stretch")

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

            with st.spinner("NASA POWER verisi çekiliyor, kurallar ve AI çalışıyor..."):
                response = api_call("POST", base_url, "/api/v1/analyze", payload=payload)
            st.session_state["analysis"] = response
            st.session_state["analysis_payload"] = payload

        analysis = st.session_state.get("analysis")
        if analysis:
            if analysis["ok"]:
                st.success(f"Analiz tamamlandı · {analysis['ms']} ms · HTTP {analysis['status']}")
                render_analysis(analysis["data"])
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                json_download(analysis["data"], f"alphecca_analiz_{stamp}.json")
                with st.expander("🧾 Gönderilen istek gövdesi"):
                    st.json(st.session_state.get("analysis_payload", {}))
                with st.expander("🧾 Ham API cevabı"):
                    st.json(analysis["data"])
            else:
                st.error(f"Analiz başarısız · {analysis['error']}")
                with st.expander("Hata ayrıntısı"):
                    st.json(analysis["data"] if analysis["data"] is not None else {})

    # =====================================================================
    # Çevre verisi
    # =====================================================================
    with tab_env:
        with st.form("env_form"):
            e1, e2, e3, e4 = st.columns(4)
            with e1:
                st.number_input(
                    "Enlem", min_value=-90.0, max_value=90.0, step=0.0001,
                    format="%.4f", key="e_lat",
                )
            with e2:
                st.number_input(
                    "Boylam", min_value=-180.0, max_value=180.0, step=0.0001,
                    format="%.4f", key="e_lon",
                )
            with e3:
                st.text_input("Bölge adı", key="e_region", max_chars=120)
            with e4:
                st.number_input(
                    "Son kaç günün hava durumu", min_value=7, max_value=90, step=1, key="e_days"
                )
            env_submitted = st.form_submit_button(
                "🌦️ Çevre verisini getir", type="primary", width="stretch"
            )

        if env_submitted:
            params = {
                "latitude": float(st.session_state["e_lat"]),
                "longitude": float(st.session_state["e_lon"]),
                "recent_days": int(st.session_state["e_days"]),
            }
            if st.session_state["e_region"].strip():
                params["region_name"] = st.session_state["e_region"].strip()
            with st.spinner("NASA POWER çağrılıyor..."):
                env_response = api_call("GET", base_url, "/api/v1/environment", params=params)
            st.session_state["environment"] = env_response

        env_result = st.session_state.get("environment")
        if env_result:
            if env_result["ok"]:
                data = env_result["data"]
                st.success(
                    f"{data.get('location', {}).get('region_name') or 'Konum'} · {env_result['ms']} ms"
                )
                render_environment(data.get("environment") or {})
                if data.get("warnings"):
                    st.markdown("#### ⚠️ Uyarılar")
                    for warning in data["warnings"]:
                        st.markdown(f"- {warning}")
                json_download(data, "alphecca_cevre.json")
                with st.expander("🧾 Ham API cevabı"):
                    st.json(data)
            else:
                st.error(f"Çevre verisi alınamadı · {env_result['error']}")
                with st.expander("Hata ayrıntısı"):
                    st.json(env_result["data"] if env_result["data"] is not None else {})

    # =====================================================================
    # Ürün kataloğu
    # =====================================================================
    with tab_crops:
        try:
            crops = load_crops(base_url)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Ürün kataloğu alınamadı: {exc}")
            crops = []

        if crops:
            crop_frame = pd.DataFrame(
                [
                    {
                        "Anahtar": crop.get("key"),
                        "Ürün (TR)": crop.get("local_name"),
                        "Ürün (EN)": crop.get("name"),
                        "Kategori": crop.get("category"),
                        "Yetişme (gün)": crop.get("growing_days"),
                        "Su ihtiyacı (mm)": crop.get("water_need_mm"),
                        "Ekim penceresi": crop.get("planting_window"),
                        "Azot ihtiyacı": crop.get("nitrogen_need"),
                    }
                    for crop in crops
                ]
            )
            filter1, filter2 = st.columns([2, 1])
            with filter1:
                search = st.text_input("Ara", placeholder="buğday, arpa, zeytin...")
            with filter2:
                categories = sorted({crop.get("category") or "—" for crop in crops})
                picked = st.multiselect("Kategori", categories, default=categories)
            filtered = crop_frame[crop_frame["Kategori"].isin(picked)]
            if search.strip():
                needle = search.strip().lower()
                mask = (
                    filtered["Ürün (TR)"].str.lower().str.contains(needle, na=False)
                    | filtered["Ürün (EN)"].str.lower().str.contains(needle, na=False)
                    | filtered["Anahtar"].str.lower().str.contains(needle, na=False)
                )
                filtered = filtered[mask]
            st.caption(f"{len(filtered)} ürün gösteriliyor (toplam {len(crops)})")
            st.dataframe(filtered, width="stretch", hide_index=True)

            picked_key = st.selectbox(
                "Detayını gör",
                options=[crop.get("key") for crop in crops],
                format_func=lambda key: next(
                    (crop.get("local_name") for crop in crops if crop.get("key") == key), key
                ),
            )
            detail = next((crop for crop in crops if crop.get("key") == picked_key), None)
            if detail:
                st.markdown(f"**{detail.get('local_name')} / {detail.get('name')}**")
                st.markdown(detail.get("notes") or "—")
                st.caption(
                    f"Ekim penceresi: {detail.get('planting_window')} · "
                    f"yetişme: {detail.get('growing_days')} gün · "
                    f"su: {detail.get('water_need_mm')} mm · "
                    f"azot: {detail.get('nitrogen_need')}"
                )
            with st.expander("🧾 Ham API cevabı"):
                st.json(crops)

    # =====================================================================
    # AI sağlayıcıları
    # =====================================================================
    with tab_ai:
        try:
            providers = load_providers(base_url)
        except Exception as exc:  # noqa: BLE001
            st.error(f"AI sağlayıcı listesi alınamadı: {exc}")
            providers = []

        if providers:
            provider_frame = pd.DataFrame(
                [
                    {
                        "Anahtar": provider.get("key"),
                        "Ad": provider.get("label"),
                        "Tür": provider.get("kind"),
                        "Önerilen": "✅" if provider.get("recommended") else "",
                        "Maliyet": provider.get("cost_tier"),
                        "Gecikme": provider.get("latency"),
                        "JSON güvenilirliği": provider.get("json_reliability"),
                        "Gizlilik": provider.get("privacy"),
                        "Örnek modeller": ", ".join(provider.get("model_examples") or [])[:80],
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
                    st.markdown(f"**En uygun kullanım:** {provider.get('best_for')}")
                    col_good, col_bad = st.columns(2)
                    with col_good:
                        st.markdown("**Güçlü yönler**")
                        for strength in provider.get("strengths") or []:
                            st.markdown(f"- ✅ {strength}")
                    with col_bad:
                        st.markdown("**Zayıf yönler**")
                        for weakness in provider.get("weaknesses") or []:
                            st.markdown(f"- ⚠️ {weakness}")
            with st.expander("🧾 Ham API cevabı"):
                st.json(providers)

    # =====================================================================
    # Sistem ve konsol
    # =====================================================================
    with tab_system:
        st.markdown("### 🩺 Sistem durumu")
        if health["ok"]:
            info = health["data"]
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Durum", info.get("status", "—"))
            h2.metric("Sürüm", info.get("version", "—"))
            h3.metric("Ortam", info.get("environment", "—"))
            h4.metric("AI sağlayıcı", info.get("ai_provider", "—"))
            h5, h6, h7, h8 = st.columns(4)
            h5.metric("AI anahtarı", "var" if info.get("ai_configured") else "yok")
            h6.metric("Önbellek", fmt(info.get("cache_entries"), "", 0))
            h7.metric("Yanıt süresi", f"{health['ms']} ms")
            h8.metric("Coğrafi kodlama", "açık" if info.get("geocoding_enabled") else "kapalı")
            st.caption(f"NASA POWER: {info.get('nasa_power_base_url')} · sunucu saati: {info.get('timestamp')}")
            with st.expander("🧾 Ham /health cevabı"):
                st.json(info)
        else:
            st.error(f"Sağlık kontrolü başarısız · {health['error']}")
            st.code("python run_ui.py", language="powershell")

        st.markdown("### 🏠 Kök endpoint")
        root = api_call("GET", base_url, "/", timeout=10.0)
        if root["ok"]:
            root_data = root["data"]
            st.markdown(f"**{root_data.get('name')}** · v{root_data.get('version')}")
            st.markdown(root_data.get("description") or "")
            st.json(root_data.get("endpoints") or {})
            with st.expander("🧾 Ham cevap"):
                st.json(root_data)
        else:
            st.warning(f"Kök endpoint hatası · {root['error']}")

        st.divider()
        st.markdown("### 🧪 Serbest API konsolu")
        st.caption("Herhangi bir endpoint'i elle test etmek için. Gövde yalnızca POST/PUT içindir.")
        console1, console2 = st.columns([1, 3])
        with console1:
            method = st.selectbox("Metot", ["GET", "POST", "PUT", "DELETE"], key="console_method")
        with console2:
            path = st.text_input("Yol", value="/api/v1/health", key="console_path")
        body_text = st.text_area(
            "JSON gövde (isteğe bağlı)",
            value="",
            height=160,
            key="console_body",
            placeholder='{"location": {"latitude": 41.6771, "longitude": 26.5557}}',
        )
        if st.button("📨 İsteği gönder", type="primary"):
            parsed_body: Any = None
            if body_text.strip():
                try:
                    parsed_body = json.loads(body_text)
                except json.JSONDecodeError as exc:
                    st.error(f"Geçersiz JSON: {exc}")
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
            "Project Alphecca test arayüzü · Veriler NASA POWER'dan gelir, üretim öncesi yerel ölçüm ve "
            "ziraat mühendisi onayı gerekir."
        )
