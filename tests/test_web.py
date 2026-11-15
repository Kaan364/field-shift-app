"""Tests for the farmer-facing web UI served by FastAPI."""

from __future__ import annotations

import re


def test_root_serves_html_to_browsers(client):
    response = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "FieldWise" in response.text
    assert "/app/styles.css" in response.text
    assert "/app/app.js" in response.text


def test_root_keeps_json_for_api_clients(client):
    response = client.get("/", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["endpoints"]["farm_plan"]


def test_farmer_app_is_served_under_app(client):
    response = client.get("/app/")
    assert response.status_code == 200
    assert "FieldWise" in response.text
    assert "<html" in response.text.lower()


def test_static_assets_are_served(client):
    assets = {
        "/app/styles.css": "text/css",
        "/app/app.js": "javascript",
        "/app/manifest.webmanifest": "json",
        "/app/sw.js": "javascript",
    }
    for path, expected in assets.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert expected in response.headers["content-type"], (path, response.headers["content-type"])


def test_icons_are_served(client):
    for path in (
        "/app/icons/favicon.svg",
        "/app/icons/icon-192.png",
        "/app/icons/icon-512.png",
        "/app/icons/icon-maskable-512.png",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(response.content) > 100, path


def test_manifest_is_installable(client):
    manifest = client.get("/app/manifest.webmanifest").json()

    assert manifest["start_url"] == "/app/"
    assert manifest["scope"] == "/app/"
    assert manifest["display"] == "standalone"
    assert manifest["lang"] == "en"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])


def test_service_worker_never_caches_the_api(client):
    script = client.get("/app/sw.js").text
    assert "/api/" in script
    assert "caches.open" in script


def test_html_has_required_wizard_controls(client):
    html = client.get("/app/").text
    for element_id in (
        "startBtn",
        "citySelect",
        "areaInput",
        "geoBtn",
        "submitBtn",
        "screen-result",
        "rotationTimeline",
        "soilGrade",
        "waterStats",
        "climateTrends",
        "listenBtn",
        "printBtn",
        "shareBtn",
        "disclaimer",
    ):
        assert re.search(rf'id="{element_id}"', html), element_id


def test_html_states_the_decision_support_limit(client):
    html = client.get("/app/").text.lower()
    assert "decision support" in html
    assert "guarantee" in html


def test_app_js_references_real_endpoints(client):
    script = client.get("/app/app.js").text
    assert "/api/v1/farm-plan" in script
    assert "/api/v1/reverse-geocode" in script
    assert "/app/sw.js" in script
