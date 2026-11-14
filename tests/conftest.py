"""Pytest fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.heuristic import HeuristicProvider
from app.config import Settings
from app.main import create_app
from tests.helpers import FakeNASA


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        ai_provider="heuristic",
        geocoding_enabled=False,  # testlerde dış servise çıkılmasın
        nasa_power_max_retries=0,
        nasa_power_retry_backoff_seconds=0,
        log_level="WARNING",
    )


@pytest.fixture
def fake_nasa() -> FakeNASA:
    return FakeNASA()


@pytest.fixture
def client(settings: Settings, fake_nasa: FakeNASA):
    app = create_app(settings, nasa_client=fake_nasa, ai_provider=HeuristicProvider())
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_client(settings: Settings):
    clients: list[TestClient] = []

    def factory(*, nasa=None, ai=None, geocoder=None):
        app = create_app(
            settings,
            nasa_client=nasa or FakeNASA(),
            ai_provider=ai or HeuristicProvider(),
            geocoder=geocoder,
        )
        test_client = TestClient(app)
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield factory

    for test_client in clients:
        test_client.__exit__(None, None, None)
