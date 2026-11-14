"""NASA POWER client tests using httpx MockTransport (no real network)."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.clients.nasa_power import NASAAPIError, NASAPowerClient, parse_nasa_payload
from tests.helpers import climatology_payload, daily_payload


def _client(handler, **kwargs) -> NASAPowerClient:
    defaults = {
        "max_retries": 0,
        "retry_backoff_seconds": 0,
        "cache_ttl_seconds": 60,
        "daily_cache_ttl_seconds": 60,
        "timeout_seconds": 5,
    }
    defaults.update(kwargs)
    return NASAPowerClient(transport=httpx.MockTransport(handler), **defaults)


async def test_parse_replaces_fill_values_and_reads_elevation():
    payload = climatology_payload()
    payload["properties"]["parameter"]["T2M"]["JAN"] = -999.0
    result = parse_nasa_payload(payload)
    assert result.elevation_m == 1128.1
    assert result.parameters["T2M"]["JAN"] is None
    assert result.parameters["T2M"]["FEB"] == 0.31
    assert result.api_version == "v2.10.1"


async def test_climatology_request_and_cache():
    payload = climatology_payload()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload)

    client = _client(handler)
    first = await client.get_climatology(39.93, 32.85)
    second = await client.get_climatology(39.93, 32.85)
    await client.aclose()

    assert len(calls) == 1
    assert first.parameters["T2M"]["ANN"] == 10.35
    assert second is first
    query = parse_qs(urlparse(str(calls[0].url)).query)
    assert query["community"] == ["AG"]
    assert query["latitude"] == ["39.93"]
    assert query["longitude"] == ["32.85"]
    assert "T2M" in query["parameters"][0]
    assert query["format"] == ["JSON"]


async def test_daily_request_builds_expected_date_window():
    payload = daily_payload()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload)

    client = _client(handler)
    await client.get_daily(39.93, 32.85, days=7, end_date=date(2026, 11, 14))
    await client.aclose()

    query = parse_qs(urlparse(str(calls[0].url)).query)
    assert query["start"] == ["20261108"]
    assert query["end"] == ["20261114"]


async def test_transient_errors_are_retried_then_succeed():
    payload = climatology_payload()
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json=payload)

    client = _client(handler, max_retries=2)
    result = await client.get_climatology(39.93, 32.85)
    await client.aclose()

    assert state["count"] == 3
    assert result.parameters["PRECTOTCORR"]["ANN"] == 1.15


async def test_http_error_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    client = _client(handler, max_retries=0)
    with pytest.raises(NASAAPIError):
        await client.get_climatology(39.93, 32.85)
    await client.aclose()


async def test_network_error_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = _client(handler)
    with pytest.raises(NASAAPIError):
        await client.get_climatology(39.93, 32.85)
    await client.aclose()


async def test_non_json_response_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = _client(handler)
    with pytest.raises(NASAAPIError):
        await client.get_climatology(39.93, 32.85)
    await client.aclose()
