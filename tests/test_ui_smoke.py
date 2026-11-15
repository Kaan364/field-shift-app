"""Arayüz dosyalarının varlığını ve çökmeden render edildiğini doğrular."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_SCRIPT = PROJECT_ROOT / "ui" / "app.py"

pytest.importorskip("streamlit")


def test_ui_files_exist() -> None:
    assert UI_SCRIPT.exists(), "ui/app.py bulunamadı"
    assert (PROJECT_ROOT / "run_ui.py").exists(), "run_ui.py bulunamadı"


def test_ui_renders_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend kapalıyken arayüz hata ekranı göstermeli, çökmemeli."""

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("ALPHECCA_API_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(str(UI_SCRIPT), default_timeout=120)
    app.run()

    assert not list(app.exception)
    assert len(app.tabs) == 5
    assert any("Cannot reach the API" in error.value for error in app.error)


def test_ui_shows_farmer_first_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Çiftçi akışı: harita, basit sorular, serbest metin ve tek büyük düğme."""

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("ALPHECCA_API_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(str(UI_SCRIPT), default_timeout=120)
    app.run()

    assert not list(app.exception)
    headings = [item.value for item in app.markdown]
    assert any("Where is your field?" in value for value in headings)
    assert any("Tell us in your own words" in value for value in headings)

    labels = [button.label for button in app.button]
    assert any("Tell me what to plant" in label for label in labels)
    assert any("Find my location automatically" in item.label for item in app.get("link_button"))
    # Serbest metin alanı mevcut olmalı.
    assert any(field.label == "Describe your situation" for field in app.text_area)


def test_ui_detail_checkbox_hidden_until_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ayrıntılı bilgi kutusu, sonuç gelmeden görünmemeli (arayüz sade kalsın)."""

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("ALPHECCA_API_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(str(UI_SCRIPT), default_timeout=120)
    app.run()

    labels = [checkbox.label for checkbox in app.checkbox]
    assert not any("Show details" in label for label in labels)


def test_ui_example_text_button_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """'Örnek yazıyı doldur' düğmesi çökmemeli ve kutuyu doldurmalı.

    Bu düğme bir zamanlar ``StreamlitWidgetAlreadyInstantiatedError`` veriyordu;
    bu test o hatanın geri gelmesini engeller.
    """

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("ALPHECCA_API_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(str(UI_SCRIPT), default_timeout=120)
    app.run()

    button = next(b for b in app.button if "Fill in the example text" in b.label)
    button.click().run()

    assert not list(app.exception)
    field = next(item for item in app.text_area if item.label == "Describe your situation")
    assert "I do not know what to plant" in field.value


def test_ui_reset_location_button_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """'Merkeze dön' ve 'Bu bölgeyi kullan' düğmeleri de çökmemeli."""

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("ALPHECCA_API_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(str(UI_SCRIPT), default_timeout=120)
    app.run()

    next(b for b in app.button if "Return to centre" in b.label).click().run()
    assert not list(app.exception)

    next(b for b in app.button if "Use this region" in b.label).click().run()
    assert not list(app.exception)


def test_farmer_flow_builds_valid_advice_payload() -> None:
    """Arayüzün gönderdiği basit akış gövdesi API sözleşmesine uymalı."""

    from app.schemas import AdviceRequest

    payload = {
        "location": {"latitude": 41.6771, "longitude": 26.5557, "region_name": "Edirne"},
        "area_hectares": 2.0,  # 20 dönüm / 10
        "irrigation": "limited",
        "water_availability": "medium",
        "goal": "max_profit",
        "soil_texture": "clay_loam",
        "planting_month": 10,
        "free_text": "Ne ekeceğimi bilmiyorum, bana basitçe anlat.",
        "top_n": 3,
        "language": "en",
    }
    request = AdviceRequest.model_validate(payload)
    assert request.location.region_name == "Edirne"
    assert request.area_hectares == 2.0
    assert request.free_text


def test_ui_builds_valid_default_payload() -> None:
    """Varsayılan form değerleri API sözleşmesine uygun bir istek üretmeli."""

    from app.schemas import AnalyzeRequest

    payload = {
        "location": {"latitude": 41.6771, "longitude": 26.5557, "region_name": "Edirne"},
        "field": {
            "area_hectares": 20.0,
            "soil_texture": "clay_loam",
            "soil_ph": 7.0,
            "organic_matter_pct": 2.2,
            "drainage": "medium",
        },
        "resources": {
            "irrigation": "limited",
            "water_availability": "medium",
            "budget_usd": 10000.0,
            "labor": "family",
            "mechanization": "medium",
            "organic_certified": False,
        },
        "preferences": {
            "goal": "max_profit",
            "crops_of_interest": ["wheat"],
            "excluded_crops": [],
            "market_access": "medium",
            "planting_month": 10,
        },
        "top_n": 5,
        "language": "en",
    }
    request = AnalyzeRequest.model_validate(payload)
    assert request.location.latitude == 41.6771
    assert request.top_n == 5
